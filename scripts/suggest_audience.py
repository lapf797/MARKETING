"""CLI para pedir à IA uma recomendação de público-alvo para um novo ativo de leilão.

Uso:
    python scripts/suggest_audience.py --category "Imoveis" \\
        --description "Apartamento 3 quartos, Zona Sul, 90m2" \\
        --location "Sao Paulo, SP" --value 450000 --budget 100

Por padrão, cria uma campanha e um adset PAUSADOS no Facebook Ads com o público sugerido,
para você revisar e ativar manualmente. Use --no-create para apenas ver a recomendação sem
tocar no Facebook.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import anthropic

from src.ai.audience_advisor import recommend_audience
from src.config import load_config
from src.facebook_ads.client import FacebookAdsClient
from src.facebook_ads.insights import fetch_audience_breakdown
from src.reporting.powerbi_push import PowerBIClient
from src.safety.recommendation_log import log_recommendation

_GENDER_CODES = {"male": [1], "female": [2], "all": [1, 2]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Sugere público-alvo para um novo ativo de leilão.")
    parser.add_argument("--category", required=True, help='Ex: "Imoveis", "Veiculos", "Maquinas"')
    parser.add_argument("--description", required=True)
    parser.add_argument("--location", required=True, help='Ex: "Sao Paulo, SP"')
    parser.add_argument("--value", type=float, default=None, help="Valor estimado do ativo")
    parser.add_argument("--budget", type=float, required=True, help="Orçamento diário máximo (na moeda da conta)")
    parser.add_argument("--no-create", action="store_true",
                         help="Apenas mostra a recomendação, sem criar campanha pausada no Facebook")
    args = parser.parse_args()

    config = load_config()
    fb_client = FacebookAdsClient(config.facebook.access_token, config.facebook.ad_account_id,
                                   config.facebook.api_version)
    ai_client = anthropic.Anthropic(api_key=config.ai.api_key)

    print("Buscando histórico de performance por segmento...")
    history = fetch_audience_breakdown(fb_client, conversion_action_type=config.facebook.conversion_action_type)

    print("Consultando a IA...")
    recommendation = recommend_audience(
        ai_client, model=config.ai.model, effort=config.ai.audience_advisor_effort,
        asset_description=args.description, asset_category=args.category, asset_value=args.value,
        target_location=args.location,
        max_daily_budget_cents=int(round(args.budget * config.safety.currency_minor_unit_factor)),
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
        asset_category=args.category, asset_description=args.description,
        target_location=args.location, recommendation=recommendation,
    )

    if config.powerbi.push_enabled:
        pbi = PowerBIClient(config.powerbi.tenant_id, config.powerbi.client_id,
                             config.powerbi.client_secret, config.powerbi.workspace_id,
                             config.powerbi.dataset_id)
        pbi.push_rows(config.powerbi.table_audience, [{
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "asset_category": args.category,
            "asset_description": args.description,
            "age_min": recommendation.age_min,
            "age_max": recommendation.age_max,
            "gender_targeting": recommendation.gender_targeting,
            "interests": ", ".join(recommendation.interests),
            "geo_locations": ", ".join(recommendation.geo_locations),
            "placements": ", ".join(recommendation.placements),
            "suggested_daily_budget": recommendation.suggested_daily_budget_cents / 100,
            "confidence": recommendation.confidence,
        }])

    if args.no_create:
        return

    print("\nCriando campanha e adset PAUSADOS no Facebook Ads para revisão...")
    campaign = fb_client.create_campaign(
        name=f"[IA] {args.category} - {args.description[:60]}",
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
        campaign_id=campaign["id"], name=f"[IA] Publico sugerido - {args.description[:40]}",
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


if __name__ == "__main__":
    main()
