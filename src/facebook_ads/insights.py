"""Coleta e normalização de métricas de performance do Facebook Ads em DataFrames
prontos para alimentar tanto o otimizador diário quanto o consultor de público-alvo."""
from __future__ import annotations

import pandas as pd

from .client import FacebookAdsClient


def _extract_action_value(actions: list[dict] | None, action_type: str) -> float:
    if not actions:
        return 0.0
    for action in actions:
        if action.get("action_type") == action_type:
            return float(action.get("value", 0) or 0)
    return 0.0


def fetch_daily_performance(client: FacebookAdsClient, *, lookback_days: int,
                             conversion_action_type: str) -> pd.DataFrame:
    """Performance diária por campanha/adset dos últimos N dias, com CPA calculado
    a partir do tipo de conversão configurado em config/settings.yaml."""
    date_preset = {
        1: "yesterday", 7: "last_7d", 14: "last_14d", 28: "last_28d", 30: "last_30d",
    }.get(lookback_days, "last_14d")

    raw = client.get_insights(client.ad_account_id, date_preset=date_preset, level="adset", time_increment=1)
    if not raw:
        return pd.DataFrame()

    rows = []
    for entry in raw:
        conversions = _extract_action_value(entry.get("actions"), conversion_action_type)
        spend = float(entry.get("spend", 0) or 0)
        rows.append({
            "date": entry.get("date_start"),
            "campaign_id": entry.get("campaign_id"),
            "campaign_name": entry.get("campaign_name"),
            "adset_id": entry.get("adset_id"),
            "adset_name": entry.get("adset_name"),
            "spend": spend,
            "impressions": int(entry.get("impressions", 0) or 0),
            "clicks": int(entry.get("clicks", 0) or 0),
            "ctr": float(entry.get("ctr", 0) or 0),
            "cpm": float(entry.get("cpm", 0) or 0),
            "frequency": float(entry.get("frequency", 0) or 0),
            "reach": int(entry.get("reach", 0) or 0),
            "conversions": conversions,
            "cpa": (spend / conversions) if conversions else None,
        })
    return pd.DataFrame(rows)


def fetch_audience_breakdown(client: FacebookAdsClient, *, conversion_action_type: str = "lead",
                              breakdowns: list[str] | None = None) -> pd.DataFrame:
    """Performance histórica agregada por faixa etária/gênero (ou outras quebras),
    usada como base de dados reais para as recomendações de público-alvo da IA."""
    breakdowns = breakdowns or ["age", "gender"]
    raw = client.get_insights(client.ad_account_id, date_preset="last_90d", level="campaign",
                               time_increment="all_days", breakdowns=breakdowns)
    rows = []
    for entry in raw:
        spend = float(entry.get("spend", 0) or 0)
        conversions = _extract_action_value(entry.get("actions"), conversion_action_type)
        row = {
            "campaign_id": entry.get("campaign_id"),
            "campaign_name": entry.get("campaign_name"),
            "spend": spend,
            "impressions": int(entry.get("impressions", 0) or 0),
            "clicks": int(entry.get("clicks", 0) or 0),
            "conversions": conversions,
            "cpa": (spend / conversions) if conversions else None,
        }
        for breakdown in breakdowns:
            row[breakdown] = entry.get(breakdown)
        rows.append(row)
    return pd.DataFrame(rows)
