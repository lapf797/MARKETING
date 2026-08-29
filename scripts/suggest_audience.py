"""Pede à IA uma recomendação de público-alvo para um novo ativo de leilão e monta um
rascunho de anúncio pronto para revisão — o mesmo sistema de rascunhos usado pelo catálogo
em PDF (src/safety/draft_log.py). Nunca cria nada ao vivo no Facebook diretamente: a
criação real da campanha só acontece depois de aprovado, via
scripts/create_campaigns_from_drafts.py --confirm (ou pelo botão "Aprovar" no dashboard).

Modo recomendado — a partir do link do leilão, a IA lê a página e extrai os dados sozinha:
    python scripts/suggest_audience.py --url "https://milanleiloes.com.br/leilao/imoveis/15498" \\
        --leilao "Leilão 15498 - Imóveis Setembro" --budget 100

Modo manual — quando não há link, ou para complementar/corrigir o que foi extraído:
    python scripts/suggest_audience.py --category "Imoveis" \\
        --description "Apartamento 3 quartos, Zona Sul, 90m2" \\
        --location "Sao Paulo, SP" --value 450000 --leilao "Leilão 15498" --budget 100

Os dois podem ser combinados: --url extrai os dados automaticamente, e qualquer uma das
outras flags (--category/--description/--location/--value) informada junto SOBRESCREVE
o valor extraído só naquele campo específico.

--leilao agrupa este e os demais lotes do mesmo envio no dashboard ("por leilão") — use o
mesmo nome para lotes do mesmo leilão. --picture-url é opcional mas recomendada: com ela, o
rascunho já sai com a pré-visualização do criativo pronta (foto + marca + selos), a mesma
composição final que vai pro Facebook quando aprovado.

Use --no-create para só ver a recomendação e a copy, sem salvar rascunho nenhum.

Também pode ser disparado sem instalar nada localmente, direto pelo dashboard (card
"Sugerir público-alvo") ou pela aba Actions do GitHub
(.github/workflows/suggest-audience.yml, que chama run_suggestion() abaixo)."""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import anthropic

from src.ai.ad_copywriter import write_single_ad_copy
from src.ai.audience_advisor import recommend_audience
from src.ai.listing_extractor import extract_listing
from src.config import load_config
from src.creative.pipeline import generate_ad_image_bytes
from src.facebook_ads.client import FacebookAdsClient
from src.facebook_ads.insights import fetch_audience_breakdown
from src.reporting.powerbi_push import PowerBIClient
from src.safety.draft_log import append_drafts, update_draft, write_dashboard_snapshot
from src.safety.recommendation_log import log_recommendation

PREVIEW_DIR = Path(__file__).resolve().parents[1] / "docs" / "creative_previews"


class SuggestionError(ValueError):
    """Entrada inválida ou insuficiente para gerar uma recomendação."""


def _print_listing(listing) -> None:
    print("\n=== Dados extraídos da página do leilão ===")
    print(f"Título: {listing.title or '—'}")
    print(f"Categoria: {listing.category or '—'}")
    print(f"Localização: {listing.location or '—'}")
    print(f"Valor de avaliação: {listing.estimated_value if listing.estimated_value is not None else '—'}")
    print(f"Lance mínimo: {listing.starting_bid if listing.starting_bid is not None else '—'}")
    print(f"Encerramento do leilão: {listing.auction_end_at or '—'}")
    if listing.key_details:
        print(f"Detalhes: {', '.join(listing.key_details)}")
    if listing.extraction_notes:
        print(f"Notas da extração: {listing.extraction_notes}")


def run_suggestion(*, url: str | None, category: str | None, description: str | None,
                    location: str | None, value: float | None, budget: float,
                    leilao: str | None = None, picture_url: str | None = None,
                    link_url: str | None = None, account_id: str | None = None,
                    page_id: str | None = None, no_create: bool = False) -> None:
    """Lógica completa do comando — usada tanto pelo CLI (main, abaixo) quanto pelo
    workflow do GitHub Actions (scripts/run_suggest_audience_from_env.py)."""
    if not url and not (category and description and location):
        raise SuggestionError(
            "informe --url (para extrair os dados automaticamente da página do leilão) "
            "ou --category, --description e --location manualmente."
        )

    config = load_config()
    fb_client = FacebookAdsClient(config.facebook.access_token, config.facebook.ad_account_id,
                                   config.facebook.api_version)
    ai_client = anthropic.Anthropic(api_key=config.ai.api_key)

    listing = None
    if url:
        print(f"Lendo a página do leilão: {url}")
        listing = extract_listing(ai_client, model=config.ai.model, effort=config.ai.audience_advisor_effort, url=url)
        if not listing.success:
            print(f"\nNão foi possível extrair os dados automaticamente: {listing.error_message}")
            if not (category and description and location):
                raise SuggestionError(
                    "a extração falhou e faltam --category/--description/--location para prosseguir manualmente."
                )
            print("Prosseguindo com os dados informados manualmente.")
            listing = None
        else:
            _print_listing(listing)

    category = category or (listing.category if listing else None)
    location = location or (listing.location if listing else None)
    value = value if value is not None else (
        (listing.estimated_value or listing.starting_bid) if listing else None
    )
    if description:
        pass
    elif listing:
        parts = [listing.description or listing.title or ""]
        if listing.key_details:
            parts.append("Detalhes: " + "; ".join(listing.key_details))
        description = "\n".join(p for p in parts if p)

    if not category or not description or not location:
        raise SuggestionError(
            "não foi possível determinar categoria, descrição ou localização do ativo — "
            "complemente com --category/--description/--location."
        )

    print("\nBuscando histórico de performance por segmento...")
    history = fetch_audience_breakdown(fb_client, conversion_action_type=config.facebook.conversion_action_type)

    daily_budget_cents = int(round(budget * config.safety.currency_minor_unit_factor))

    print("Consultando a IA para a recomendação de público...")
    recommendation = recommend_audience(
        ai_client, model=config.ai.model, effort=config.ai.audience_advisor_effort,
        asset_description=description, asset_category=category, asset_value=value,
        target_location=location, max_daily_budget_cents=daily_budget_cents,
        historical_breakdown=history,
    )

    print("\n=== Recomendação de público-alvo ===")
    print(f"Idade: {recommendation.age_min}-{recommendation.age_max}")
    print(f"Gênero: {recommendation.gender_targeting}")
    print(f"Interesses: {', '.join(recommendation.interests)}")
    print(f"Localização: {', '.join(recommendation.geo_locations)}")
    print(f"Posicionamentos: {', '.join(recommendation.placements)}")
    print(f"Orçamento diário sugerido: {recommendation.suggested_daily_budget_cents / 100:.2f}")
    print(f"Confiança: {recommendation.confidence:.2f}")
    print(f"Raciocínio: {recommendation.reasoning}")

    log_recommendation(
        asset_category=category, asset_description=description, target_location=location,
        recommendation=recommendation, source_url=url,
    )

    if config.powerbi.push_enabled:
        pbi = PowerBIClient(config.powerbi.tenant_id, config.powerbi.client_id,
                             config.powerbi.client_secret, config.powerbi.workspace_id,
                             config.powerbi.dataset_id)
        pbi.push_rows(config.powerbi.table_audience, [{
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "asset_category": category,
            "asset_description": description,
            "source_url": url or "",
            "age_min": recommendation.age_min,
            "age_max": recommendation.age_max,
            "gender_targeting": recommendation.gender_targeting,
            "interests": ", ".join(recommendation.interests),
            "geo_locations": ", ".join(recommendation.geo_locations),
            "placements": ", ".join(recommendation.placements),
            "suggested_daily_budget": recommendation.suggested_daily_budget_cents / 100,
            "confidence": recommendation.confidence,
        }])

    if no_create:
        return

    if not leilao:
        raise SuggestionError(
            "informe --leilao (nome do leilão) para salvar o rascunho — agrupa este lote "
            "com os demais do mesmo envio no dashboard."
        )

    print("\nGerando a copy do anúncio...")
    copy = write_single_ad_copy(
        ai_client, model=config.ai.model, effort=config.ai.audience_advisor_effort,
        category=category, description=description, location=location, value=value,
        key_details=listing.key_details if listing else None,
    )
    print(f"Manchete: {copy.headline}")
    print(f"Texto principal: {copy.primary_text}")
    print(f"Descrição: {copy.ad_description}")

    title = (listing.title if listing else None) or f"{category} - {location}"
    pause_date = None
    if listing and listing.auction_end_at and re.fullmatch(r"\d{4}-\d{2}-\d{2}", listing.auction_end_at):
        pause_date = listing.auction_end_at

    [draft] = append_drafts([{
        "leilao": leilao,
        "link_url": link_url or url,
        "account_id": account_id or config.facebook.ad_account_id,
        "page_id": page_id,
        "picture_url": picture_url,
        "campaign_name": f"[Leilão] {title}"[:100],
        "daily_budget_cents": daily_budget_cents,
        "pause_date": pause_date,
        "property": {
            "title": title,
            "category": category,
            "city": location,
            "state": None,
            "headline": copy.headline,
            "primary_text": copy.primary_text,
            "ad_description": copy.ad_description,
            "age_min": recommendation.age_min,
            "age_max": recommendation.age_max,
            "gender_targeting": recommendation.gender_targeting,
            "interests": recommendation.interests,
            "audience_reasoning": recommendation.reasoning,
            "geo_locations_suggested": recommendation.geo_locations,
            "placements_suggested": recommendation.placements,
            "confidence": min(recommendation.confidence, copy.confidence),
        },
    }])
    print(f"\nRascunho salvo: {draft['draft_id']}")

    if picture_url:
        print("Gerando a pré-visualização do criativo...")
        try:
            image_bytes = generate_ad_image_bytes(
                picture_url=picture_url, prop=draft["property"], pause_date=pause_date, config=config,
            )
            PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
            preview_path = PREVIEW_DIR / f"{draft['draft_id']}.jpg"
            preview_path.write_bytes(image_bytes)
            update_draft(draft["draft_id"], preview_image_url=f"./creative_previews/{draft['draft_id']}.jpg")
            print(f"Pré-visualização salva em {preview_path}")
        except Exception as exc:
            print(f"Não foi possível gerar a pré-visualização do criativo: {exc}")

    write_dashboard_snapshot()
    print("\nRevise a recomendação e a pré-visualização no dashboard antes de aprovar. Ao "
          "aprovar (botão no dashboard, ou "
          f"scripts/create_campaigns_from_drafts.py --draft-id {draft['draft_id']} --confirm), "
          "a campanha PAUSADA é criada de verdade no Facebook Ads para você ativar manualmente.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sugere público-alvo para um novo ativo de leilão.")
    parser.add_argument("--url", default=None, help="Link da página do lote no site do leilão — a IA extrai os dados automaticamente")
    parser.add_argument("--category", default=None, help='Ex: "Imoveis", "Veiculos", "Maquinas" (sobrescreve o que veio de --url)')
    parser.add_argument("--description", default=None, help="Sobrescreve o que veio de --url")
    parser.add_argument("--location", default=None, help='Ex: "Sao Paulo, SP" (sobrescreve o que veio de --url)')
    parser.add_argument("--value", type=float, default=None, help="Valor estimado do ativo (sobrescreve o que veio de --url)")
    parser.add_argument("--budget", type=float, required=True, help="Orçamento diário máximo (na moeda da conta)")
    parser.add_argument("--leilao", default=None,
                         help='Nome do leilão (ex: "Leilão 15498 - Imóveis Setembro") — agrupa este lote com os '
                              "demais do mesmo envio no dashboard. Obrigatório, a menos que use --no-create.")
    parser.add_argument("--picture-url", default=None,
                         help="URL pública da foto do lote — com ela, o rascunho já sai com a pré-visualização do criativo pronta")
    parser.add_argument("--link-url", default=None, help="URL de destino do anúncio (padrão: o mesmo valor de --url)")
    parser.add_argument("--account-id", default=None, help="ID da conta de anúncios Meta (padrão: FB_AD_ACCOUNT_ID do .env)")
    parser.add_argument("--page-id", default=None, help="ID da página do Facebook (pode ser definido depois, na aprovação)")
    parser.add_argument("--no-create", action="store_true",
                         help="Apenas mostra a recomendação e a copy, sem salvar rascunho nenhum")
    args = parser.parse_args()

    try:
        run_suggestion(url=args.url, category=args.category, description=args.description,
                        location=args.location, value=args.value, budget=args.budget,
                        leilao=args.leilao, picture_url=args.picture_url, link_url=args.link_url,
                        account_id=args.account_id, page_id=args.page_id, no_create=args.no_create)
    except SuggestionError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
