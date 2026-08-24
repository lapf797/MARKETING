"""Configuração central do sistema: carrega .env + config/settings.yaml e valida
as variáveis de ambiente obrigatórias antes de qualquer chamada de API."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

load_dotenv()


@dataclass
class SafetyConfig:
    dry_run: bool
    max_budget_change_pct_per_day: float
    min_budget_change_pct_to_act: float
    min_spend_before_action_cents: int
    cooldown_hours_between_changes: float
    max_actions_per_run: int
    max_pauses_per_run: int
    account_daily_budget_cap_cents: int
    max_cpa_cents: int
    min_conversions_for_reliable_cpa: int
    max_frequency: float
    require_ai_confidence: float
    currency_minor_unit_factor: int


@dataclass
class FacebookConfig:
    api_version: str
    insights_lookback_days: int
    conversion_action_type: str
    access_token: str
    ad_account_id: str
    app_id: str | None
    app_secret: str | None


@dataclass
class AIConfig:
    model: str
    optimizer_effort: str
    audience_advisor_effort: str
    api_key: str


@dataclass
class PowerBIConfig:
    push_enabled: bool
    table_campaign_metrics: str
    table_actions: str
    table_audience: str
    tenant_id: str | None
    client_id: str | None
    client_secret: str | None
    workspace_id: str | None
    dataset_id: str | None


@dataclass
class AppConfig:
    safety: SafetyConfig
    facebook: FacebookConfig
    ai: AIConfig
    powerbi: PowerBIConfig


def _require_env(name: str, *, required: bool = True) -> str | None:
    value = (os.environ.get(name) or "").strip() or None
    if required and not value:
        raise RuntimeError(
            f"Variável de ambiente obrigatória não definida: {name}. "
            "Configure-a no .env (local) ou nos Secrets do GitHub Actions (produção)."
        )
    return value


def load_config(path: str | Path | None = None) -> AppConfig:
    config_path = Path(path or os.environ.get("CONFIG_PATH", "config/settings.yaml"))
    if not config_path.exists():
        raise FileNotFoundError(
            f"Arquivo de configuração não encontrado: {config_path}. "
            "Veja config/settings.yaml no repositório e ajuste os limites de segurança."
        )
    raw: dict[str, Any] = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    safety_raw = raw["safety"]
    pause_raw = safety_raw["pause_thresholds"]
    safety = SafetyConfig(
        dry_run=bool(safety_raw["dry_run"]),
        max_budget_change_pct_per_day=float(safety_raw["max_budget_change_pct_per_day"]),
        min_budget_change_pct_to_act=float(safety_raw["min_budget_change_pct_to_act"]),
        min_spend_before_action_cents=int(safety_raw["min_spend_before_action_cents"]),
        cooldown_hours_between_changes=float(safety_raw["cooldown_hours_between_changes"]),
        max_actions_per_run=int(safety_raw["max_actions_per_run"]),
        max_pauses_per_run=int(safety_raw["max_pauses_per_run"]),
        account_daily_budget_cap_cents=int(safety_raw["account_daily_budget_cap_cents"]),
        max_cpa_cents=int(pause_raw["max_cpa_cents"]),
        min_conversions_for_reliable_cpa=int(pause_raw["min_conversions_for_reliable_cpa"]),
        max_frequency=float(pause_raw["max_frequency"]),
        require_ai_confidence=float(safety_raw["require_ai_confidence"]),
        currency_minor_unit_factor=int(safety_raw["currency_minor_unit_factor"]),
    )

    fb_raw = raw["facebook"]
    facebook = FacebookConfig(
        api_version=str(fb_raw["api_version"]),
        insights_lookback_days=int(fb_raw["insights_lookback_days"]),
        conversion_action_type=str(fb_raw["conversion_action_type"]),
        access_token=_require_env("FB_ACCESS_TOKEN"),
        ad_account_id=_require_env("FB_AD_ACCOUNT_ID"),
        app_id=_require_env("FB_APP_ID", required=False),
        app_secret=_require_env("FB_APP_SECRET", required=False),
    )

    ai_raw = raw["ai"]
    ai = AIConfig(
        model=str(ai_raw["model"]),
        optimizer_effort=str(ai_raw["optimizer_effort"]),
        audience_advisor_effort=str(ai_raw["audience_advisor_effort"]),
        api_key=_require_env("ANTHROPIC_API_KEY"),
    )

    pbi_raw = raw["powerbi"]
    push_enabled = bool(pbi_raw["push_enabled"])
    powerbi = PowerBIConfig(
        push_enabled=push_enabled,
        table_campaign_metrics=str(pbi_raw["table_campaign_metrics"]),
        table_actions=str(pbi_raw["table_actions"]),
        table_audience=str(pbi_raw["table_audience"]),
        tenant_id=_require_env("POWERBI_TENANT_ID", required=push_enabled),
        client_id=_require_env("POWERBI_CLIENT_ID", required=push_enabled),
        client_secret=_require_env("POWERBI_CLIENT_SECRET", required=push_enabled),
        workspace_id=_require_env("POWERBI_WORKSPACE_ID", required=push_enabled),
        dataset_id=_require_env("POWERBI_DATASET_ID", required=push_enabled),
    )

    return AppConfig(safety=safety, facebook=facebook, ai=ai, powerbi=powerbi)
