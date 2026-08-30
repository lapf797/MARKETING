"""Analisa o catálogo de leilão em PDF (todos os lotes de uma vez, até 60) e gera rascunhos
de anúncio prontos para revisão — não toca no Facebook Ads em nenhum momento; é seguro
rodar quantas vezes quiser.

Uso:
    python scripts/analyze_catalog.py --pdf caminho/ou/url/do/catalogo.pdf \\
        --leilao "Leilão 15498 - Imóveis Setembro" \\
        --link-url "https://milanleiloes.com.br/leilao/imoveis" \\
        --account-id act_123456 --page-id 987654

Depois de revisar os rascunhos (impressos aqui e salvos em logs/ad_drafts.json — também
visíveis no dashboard web, com pré-visualização por lote e um filtro por leilão), use
scripts/create_campaigns_from_drafts.py (ou o botão "Aprovar" no dashboard) para
efetivamente criar as campanhas aprovadas no Facebook Ads. Cada rascunho ainda precisa de
uma foto anexada manualmente antes de aprovar — ver README.md, seção "Limitações
conhecidas".

Também pode ser disparado sem instalar nada localmente, direto pelo dashboard (card
"Analisar catálogo do leilão") ou pela aba Actions do GitHub
(.github/workflows/analyze-catalog.yml, que chama run_analysis() abaixo)."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import anthropic

from src.ai.budget_rules import days_until, suggested_total_budget_cents
from src.ai.catalog_extractor import analyze_catalog
from src.config import load_config
from src.safety.draft_log import append_drafts, write_dashboard_snapshot


def run_analysis(*, pdf: str, leilao: str | None = None, link_url: str | None = None,
                  account_id: str | None = None, page_id: str | None = None) -> None:
    """Lógica completa do comando — usada tanto pelo CLI (main, abaixo) quanto pelo
    workflow do GitHub Actions (scripts/run_analyze_catalog_from_env.py)."""
    config = load_config()
    ai_client = anthropic.Anthropic(api_key=config.ai.api_key)

    print(f"Lendo catálogo: {pdf}")
    analysis = analyze_catalog(
        ai_client, model=config.ai.model, effort=config.ai.catalog_extractor_effort,
        pdf_source=pdf, landing_page_url=link_url,
    )
    print(f"\n{analysis.total_properties} ativo(s) identificado(s). {analysis.summary}\n")

    if not analysis.properties:
        print("Nenhum ativo extraído — nada para salvar como rascunho.")
        return

    batch_id = str(int(time.time()))
    leilao = leilao or f"Leilão {batch_id}"
    account_id = account_id or config.facebook.ad_account_id
    entries = []
    for prop in analysis.properties:
        total_budget_cents = suggested_total_budget_cents(
            prop.price_value, tiers_cents=config.ads.budget_tiers_cents,
            above_max_tier_cents=config.ads.budget_above_max_tier_cents,
        )
        entries.append({
            "batch_id": batch_id,
            "leilao": leilao,
            "link_url": link_url,
            "account_id": account_id,
            "page_id": page_id,
            "picture_url": None,
            "property": prop.model_dump(),
            "campaign_name": f"[Leilão] {prop.title}"[:100],
            "total_budget_cents": total_budget_cents,
            "pause_date": prop.auction_date,
        })

    saved = append_drafts(entries)
    write_dashboard_snapshot()

    print(f"{len(saved)} rascunho(s) salvo(s) em logs/ad_drafts.json:\n")
    for draft in saved:
        prop = draft["property"]
        days = days_until(draft["pause_date"])
        daily_cents = draft["total_budget_cents"] / days
        print(f"  [{draft['draft_id'][:8]}] {prop['title']} ({prop.get('city') or '—'}/{prop.get('state') or '—'})")
        print(f"      Headline: {prop['headline']}")
        print(f"      Orçamento total: R$ {draft['total_budget_cents'] / 100:.2f} "
              f"(~R$ {daily_cents / 100:.2f}/dia até {draft['pause_date'] or 'data não definida'})")
        print(f"      Público: {prop['age_min']}-{prop['age_max']}, {prop['gender_targeting']}, "
              f"interesses: {', '.join(prop['interests'])}")
        print(f"      Foto no catálogo: {prop.get('photo_page_reference') or 'não identificada'}")
        print()

    print("IMPORTANTE: cada rascunho ainda precisa de uma foto pronta (picture_url, uma URL "
          "pública da imagem) antes de poder ser aprovado — use:\n"
          "  python scripts/create_campaigns_from_drafts.py --draft-id <id> --picture-url <url>\n"
          "Se --page-id não foi informado agora, também precisa ser definido antes da "
          "aprovação (edite logs/ad_drafts.json diretamente, ou rode este comando de novo "
          "com a flag preenchida).")
    print("\nPróximo passo: revise os rascunhos no dashboard (ou aqui) e aprove com o botão "
          "\"Aprovar e criar campanha\" (ou scripts/create_campaigns_from_drafts.py --confirm) "
          "para criar de verdade as campanhas aprovadas no Facebook Ads.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extrai todos os ativos de um catálogo de leilão em PDF e gera rascunhos de anúncio."
    )
    parser.add_argument("--pdf", required=True, help="Caminho local do PDF, ou uma URL http(s) para baixá-lo")
    parser.add_argument("--leilao", default=None,
                         help='Nome do leilão (ex: "Leilão 15498 - Imóveis Setembro") — agrupa todos os lotes '
                              "deste envio no dashboard. Se não informado, usa o número do lote (batch_id).")
    parser.add_argument("--link-url", default=None, help="URL de destino (landing page) que os anúncios vão usar")
    parser.add_argument("--account-id", default=None, help="ID da conta de anúncios Meta (padrão: FB_AD_ACCOUNT_ID do .env)")
    parser.add_argument("--page-id", default=None, help="ID da página do Facebook (pode ser definido depois, na aprovação)")
    args = parser.parse_args()

    run_analysis(pdf=args.pdf, leilao=args.leilao, link_url=args.link_url,
                 account_id=args.account_id, page_id=args.page_id)


if __name__ == "__main__":
    main()
