"""Pede à IA uma recomendação de público-alvo para um novo ativo de leilão.

Modo recomendado — a partir do link do leilão, a IA lê a página e extrai os dados sozinha:
    python scripts/suggest_audience.py --url "https://milanleiloes.com.br/leilao/imoveis/15498" --budget 100

Modo manual — quando não há link, ou para complementar/corrigir o que foi extraído:
    python scripts/suggest_audience.py --category "Imoveis" \\
        --description "Apartamento 3 quartos, Zona Sul, 90m2" \\
        --location "Sao Paulo, SP" --value 450000 --budget 100

Os dois podem ser combinados: --url extrai os dados automaticamente, e qualquer uma das
outras flags (--category/--description/--location/--value) informada junto SOBRESCREVE
o valor extraído só naquele campo específico.

Por padrão, cria uma campanha e um adset PAUSADOS no Facebook Ads com o público sugerido,
para você revisar e ativar manualmente. Use --no-create para apenas ver a recomendação sem
tocar no Facebook.

Também pode ser disparado sem instalar nada localmente, direto pela aba Actions do GitHub
(.github/workflows/suggest-audience.yml, que chama run_suggestion() abaixo)."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import anthropic

from src.ai.audience_advisor import recommend_audience
from src.ai.listing_extractor import extract_listing
from src.config import load_config
from src.facebook_ads.client import FacebookAdsClient
from src.facebook_ads.insights import fetch_audience_breakdown
from src.reporting.powerbi_push import PowerBIClient
from src.safety.recommendation_log import log_recommendation

_GENDER_CODES = {"male": [1], "female": [2], "all": [1, 2]}


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
                    no_create: bool) -> None:
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

    print("Consultando a IA para a recomendação de público...")
    recommendation = recommend_audience(
        ai_client, model=config.ai.model, effort=config.ai.audience_advisor_effort,
        asset_description=description, asset_category=category, asset_value=value,
        target_location=location,
        max_daily_budget_cents=int(round(budget * config.safety.currency_minor_unit_factor)),
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

    print("\nCriando campanha e adset PAUSADOS no Facebook Ads para revisão...")
    campaign = fb_client.create_campaign(
        name=f"[IA] {category} - {description[:60]}",
        objective="OUTCOME_LEADS",
    )
    targeting = {
        "age_min": recommendation.age_min,
        "age_max": recommendation.age_max,
        "genders": _GENDER_CODES[recommendation.gender_targeting],
        # geo_locations e interesses aqui são placeholders — o Meta exige IDs específicos
        # (via GET /search?type=adgeolocation e type=adinterest), não nomes livres.
        # Resolva-os no Gerenciador de Anúncios antes de ativar (veja docs/SETUP_FACEBOOK.md).
        "geo_locations": {"custom_locations": []},
    }
    adset = fb_client.create_adset(
        campaign_id=campaign["id"], name=f"[IA] Publico sugerido - {description[:40]}",
        daily_budget_cents=recommendation.suggested_daily_budget_cents,
        targeting=targeting, optimization_goal="OFFSITE_CONVERSIONS", billing_event="IMPRESSIONS",
    )
    print(f"Campanha criada (PAUSADA): {campaign['id']}")
    print(f"Adset criado (PAUSADO): {adset['id']}")
    print(f"Interesses sugeridos pela IA (ainda não aplicados — precisam de IDs reais): "
          f"{', '.join(recommendation.interests)}")
    print("\nIMPORTANTE: revise a segmentação geográfica e os interesses no Gerenciador de "
          "Anúncios antes de ativar — a IA sugere por nome, mas o Meta exige IDs específicos "
          "de interesse/localização (ver docs/SETUP_FACEBOOK.md).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sugere público-alvo para um novo ativo de leilão.")
    parser.add_argument("--url", default=None, help="Link da página do lote no site do leilão — a IA extrai os dados automaticamente")
    parser.add_argument("--category", default=None, help='Ex: "Imoveis", "Veiculos", "Maquinas" (sobrescreve o que veio de --url)')
    parser.add_argument("--description", default=None, help="Sobrescreve o que veio de --url")
    parser.add_argument("--location", default=None, help='Ex: "Sao Paulo, SP" (sobrescreve o que veio de --url)')
    parser.add_argument("--value", type=float, default=None, help="Valor estimado do ativo (sobrescreve o que veio de --url)")
    parser.add_argument("--budget", type=float, required=True, help="Orçamento diário máximo (na moeda da conta)")
    parser.add_argument("--no-create", action="store_true",
                         help="Apenas mostra a recomendação, sem criar campanha pausada no Facebook")
    args = parser.parse_args()

    try:
        run_suggestion(url=args.url, category=args.category, description=args.description,
                        location=args.location, value=args.value, budget=args.budget,
                        no_create=args.no_create)
    except SuggestionError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
