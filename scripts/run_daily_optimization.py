"""Orquestrador da otimização diária:

1. Busca a performance recente de todos os adsets ativos no Facebook Ads.
2. Pede à IA (Claude) um plano de otimização.
3. Passa o plano pelas guardrails de segurança (limites de orçamento, cooldown, teto de conta).
4. Aplica as ações aprovadas no Facebook Ads (ou simula, se safety.dry_run estiver ativo).
5. Registra tudo na trilha de auditoria e envia métricas + ações para o Power BI.

Rodado automaticamente todo dia pelo GitHub Actions
(.github/workflows/daily-optimization.yml), mas pode ser rodado manualmente também.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import anthropic
import pandas as pd

from src.ai.optimizer import build_optimization_plan
from src.ai.schemas import OptimizationAction
from src.config import AppConfig, load_config
from src.facebook_ads.client import FacebookAdsClient
from src.facebook_ads.insights import fetch_daily_performance
from src.reporting.powerbi_push import PowerBIClient
from src.safety.audit_log import last_change_timestamps, log_action
from src.safety.guardrails import apply_guardrails


def _current_budgets_and_metadata(fb_client: FacebookAdsClient) -> tuple[pd.DataFrame, dict[str, int]]:
    """Retorna metadados dos adsets ativos e um dict {id: orçamento_em_centavos} cobrindo
    tanto campanhas com Orçamento de Campanha Otimizado (CBO) quanto adsets com orçamento
    próprio — o que o Facebook realmente controla varia por campanha."""
    campaigns = fb_client.list_campaigns(status_filter=["ACTIVE"])
    rows = []
    budgets: dict[str, int] = {}
    for campaign in campaigns:
        campaign_budget = campaign.get("daily_budget")
        uses_cbo = campaign_budget is not None
        if uses_cbo:
            budgets[campaign["id"]] = int(campaign_budget)

        adsets = fb_client.list_adsets(campaign["id"])
        for adset in adsets:
            if adset.get("effective_status") not in ("ACTIVE", "PAUSED"):
                continue
            adset_budget = adset.get("daily_budget")
            if adset_budget is not None:
                budgets[adset["id"]] = int(adset_budget)
            rows.append({
                "adset_id": adset["id"],
                "adset_name": adset.get("name"),
                "campaign_id": campaign["id"],
                "campaign_name": campaign.get("name"),
                "status": adset.get("effective_status"),
                "adset_daily_budget": adset_budget,
                "campaign_daily_budget": campaign_budget,
                "budget_control_level": "campaign" if uses_cbo else "adset",
            })
    return pd.DataFrame(rows), budgets


def _apply_action(fb_client: FacebookAdsClient, action: OptimizationAction, *, dry_run: bool) -> None:
    if dry_run:
        return
    if action.action_type in ("increase_budget", "decrease_budget"):
        cents = int(float(action.proposed_value))
        if action.target_type == "campaign":
            fb_client.update_campaign_budget(action.target_id, daily_budget_cents=cents)
        else:
            fb_client.update_adset_budget(action.target_id, daily_budget_cents=cents)
    elif action.action_type == "pause":
        fb_client.set_status(action.target_id, "PAUSED")
    elif action.action_type == "resume":
        fb_client.set_status(action.target_id, "ACTIVE")
    # flag_for_audience_refresh não altera nada no Facebook — é só um sinal para o time humano.


def main() -> None:
    config: AppConfig = load_config()
    fb_client = FacebookAdsClient(config.facebook.access_token, config.facebook.ad_account_id,
                                   config.facebook.api_version)
    ai_client = anthropic.Anthropic(api_key=config.ai.api_key)

    print(f"[{datetime.now(timezone.utc).isoformat()}] Buscando performance dos últimos "
          f"{config.facebook.insights_lookback_days} dias...")
    performance_df = fetch_daily_performance(
        fb_client, lookback_days=config.facebook.insights_lookback_days,
        conversion_action_type=config.facebook.conversion_action_type,
    )
    adset_meta_df, current_budgets = _current_budgets_and_metadata(fb_client)

    if performance_df.empty:
        print("Nenhum dado de performance retornado — encerrando sem ações.")
        return

    print("Consultando a IA para gerar o plano de otimização de hoje...")
    plan = build_optimization_plan(ai_client, model=config.ai.model, effort=config.ai.optimizer_effort,
                                    performance_df=performance_df, adset_meta=adset_meta_df)
    print(f"Resumo da IA: {plan.summary}")
    print(f"{len(plan.actions)} ações propostas.")

    spend_per_target = (
        performance_df.groupby("adset_id")["spend"].sum().mul(100).round().astype(int).to_dict()
    )
    last_changes = last_change_timestamps()
    current_total_budget = sum(v for v in current_budgets.values() if v)

    result = apply_guardrails(
        plan.actions,
        config=config.safety,
        current_budgets_cents=current_budgets,
        last_change_at=last_changes,
        spend_last_period_cents=spend_per_target,
        current_total_daily_budget_cents=current_total_budget,
    )

    print(f"Aprovadas: {len(result.approved)} | Rejeitadas: {len(result.rejected)} | "
          f"Ajustadas: {len(result.adjusted)}")
    for action, reason in result.rejected:
        print(f"  REJEITADA [{action.target_name}] {action.action_type}: {reason}")

    action_log_rows = []
    for action in result.approved:
        before = str(current_budgets.get(action.target_id, action.current_value))
        print(f"  APLICANDO [{action.target_name}] {action.action_type}: "
              f"{action.current_value} -> {action.proposed_value} ({action.reasoning})")
        try:
            _apply_action(fb_client, action, dry_run=config.safety.dry_run)
        except Exception as exc:  # noqa: BLE001 — precisa registrar qualquer falha de API real, não interromper o resto
            print(f"  ERRO ao aplicar ação em {action.target_id}: {exc}")
            continue

        entry = log_action(
            action_type=action.action_type, target_type=action.target_type,
            target_id=action.target_id, target_name=action.target_name,
            before_value=before, after_value=action.proposed_value,
            reasoning=action.reasoning, confidence=action.confidence,
            dry_run=config.safety.dry_run,
        )
        action_log_rows.append(entry)

    if config.powerbi.push_enabled:
        print("Enviando dados para o Power BI...")
        pbi = PowerBIClient(config.powerbi.tenant_id, config.powerbi.client_id,
                             config.powerbi.client_secret, config.powerbi.workspace_id,
                             config.powerbi.dataset_id)
        pbi.push_rows(config.powerbi.table_campaign_metrics, performance_df.to_dict(orient="records"))
        pbi.push_rows(config.powerbi.table_actions, action_log_rows)

    suffix = " (modo dry-run — nenhuma mudança real foi aplicada)" if config.safety.dry_run else ""
    print(f"Execução concluída.{suffix}")


if __name__ == "__main__":
    main()
