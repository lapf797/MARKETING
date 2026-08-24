"""Script de configuração ÚNICA: cria o dataset de push no Power BI com o schema usado
pelo sistema (CampaignPerformance, OptimizerActions, AudienceRecommendations).

Rode uma vez, na configuração inicial:
    python scripts/setup_powerbi_dataset.py

O script imprime o dataset_id criado — copie esse valor para POWERBI_DATASET_ID no seu
.env (local) e nos Secrets do GitHub Actions (produção). Não precisa rodar de novo depois,
a menos que queira recriar o dataset do zero.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests

from src.config import AppConfig, load_config
from src.reporting.powerbi_push import AAD_TOKEN_URL, POWERBI_BASE_URL, POWERBI_SCOPE


def build_dataset_schema(config: AppConfig) -> dict:
    return {
        "name": "Marketing Leiloes - Facebook Ads",
        "defaultMode": "PushStreaming",
        "tables": [
            {
                "name": config.powerbi.table_campaign_metrics,
                "columns": [
                    {"name": "date", "dataType": "DateTime"},
                    {"name": "campaign_id", "dataType": "String"},
                    {"name": "campaign_name", "dataType": "String"},
                    {"name": "adset_id", "dataType": "String"},
                    {"name": "adset_name", "dataType": "String"},
                    {"name": "spend", "dataType": "Double"},
                    {"name": "impressions", "dataType": "Int64"},
                    {"name": "clicks", "dataType": "Int64"},
                    {"name": "ctr", "dataType": "Double"},
                    {"name": "cpm", "dataType": "Double"},
                    {"name": "frequency", "dataType": "Double"},
                    {"name": "reach", "dataType": "Int64"},
                    {"name": "conversions", "dataType": "Double"},
                    {"name": "cpa", "dataType": "Double"},
                ],
            },
            {
                "name": config.powerbi.table_actions,
                "columns": [
                    {"name": "timestamp", "dataType": "DateTime"},
                    {"name": "action_type", "dataType": "String"},
                    {"name": "target_type", "dataType": "String"},
                    {"name": "target_id", "dataType": "String"},
                    {"name": "target_name", "dataType": "String"},
                    {"name": "before_value", "dataType": "String"},
                    {"name": "after_value", "dataType": "String"},
                    {"name": "reasoning", "dataType": "String"},
                    {"name": "confidence", "dataType": "Double"},
                    {"name": "dry_run", "dataType": "Boolean"},
                ],
            },
            {
                "name": config.powerbi.table_audience,
                "columns": [
                    {"name": "timestamp", "dataType": "DateTime"},
                    {"name": "asset_category", "dataType": "String"},
                    {"name": "asset_description", "dataType": "String"},
                    {"name": "age_min", "dataType": "Int64"},
                    {"name": "age_max", "dataType": "Int64"},
                    {"name": "gender_targeting", "dataType": "String"},
                    {"name": "interests", "dataType": "String"},
                    {"name": "geo_locations", "dataType": "String"},
                    {"name": "placements", "dataType": "String"},
                    {"name": "suggested_daily_budget", "dataType": "Double"},
                    {"name": "confidence", "dataType": "Double"},
                ],
            },
        ],
    }


def main() -> None:
    config = load_config()
    pbi = config.powerbi
    token_response = requests.post(
        AAD_TOKEN_URL.format(tenant_id=pbi.tenant_id),
        data={
            "grant_type": "client_credentials",
            "client_id": pbi.client_id,
            "client_secret": pbi.client_secret,
            "scope": POWERBI_SCOPE,
        },
        timeout=30,
    )
    token_response.raise_for_status()
    token = token_response.json()["access_token"]

    response = requests.post(
        f"{POWERBI_BASE_URL}/groups/{pbi.workspace_id}/datasets",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=build_dataset_schema(config),
        timeout=30,
    )
    response.raise_for_status()
    dataset = response.json()
    print("Dataset criado com sucesso!")
    print(f"dataset_id: {dataset['id']}")
    print("Copie esse valor para o secret/variável POWERBI_DATASET_ID.")


if __name__ == "__main__":
    main()
