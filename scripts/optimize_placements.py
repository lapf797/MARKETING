"""Otimização diária de posicionamento e demografia — NUNCA mexe em orçamento. Complementa
scripts/run_daily_optimization.py (que decide QUANTO gastar); este decide ONDE e PARA QUEM
o orçamento já definido é exibido, concentrando a verba nos posicionamentos e faixas de
público que já provaram clique mais barato. Roda sobre todas as campanhas ativas por
padrão; use --campaign-id para uma só.

Uso:
    python scripts/optimize_placements.py                  # todas as campanhas ativas
    python scripts/optimize_placements.py --campaign-id 123456789
    python scripts/optimize_placements.py --dry-run          # mostra o plano, não aplica

Rodado automaticamente todo dia pelo GitHub Actions, antes da otimização de orçamento
(.github/workflows/daily-optimization.yml), mas pode ser rodado manualmente também.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import anthropic

from src.ai.placement_optimizer import build_placement_plan
from src.config import AppConfig, load_config
from src.facebook_ads.client import FacebookAdsClient, FacebookAdsError
from src.facebook_ads.placement_targeting import (
    build_age_gender_only_targeting,
    build_placement_targeting,
)
from src.safety.audit_log import last_change_timestamps, log_action

ACTION_TYPE = "optimize_placements"


def _hours_since(timestamp_iso: str | None) -> float:
    if not timestamp_iso:
        return float("inf")
    from datetime import datetime, timezone
    last = datetime.fromisoformat(timestamp_iso)
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - last).total_seconds() / 3600


def _optimize_one(ai_client: anthropic.Anthropic, fb_client: FacebookAdsClient, *,
                   config: AppConfig, campaign: dict, adset: dict,
                   last_changes: dict[str, str], dry_run: bool) -> None:
    campaign_id = campaign["id"]
    campaign_name = campaign.get("name", campaign_id)
    adset_id = adset["id"]

    hours_since = _hours_since(last_changes.get(adset_id))
    if hours_since < config.safety.cooldown_hours_between_changes:
        print(f"  [{campaign_name}] em cooldown — última mudança há {hours_since:.1f}h, "
              f"pulando.")
        return

    overall_rows = fb_client.get_insights(
        campaign_id, date_preset="maximum", level="campaign",
        fields=["impressions", "clicks", "ctr", "cpc", "spend", "reach"],
    )
    overall = overall_rows[0] if overall_rows else {}
    impressions = int(float(overall.get("impressions", 0) or 0))
    if impressions < config.safety.min_impressions_before_placement_action:
        print(f"  [{campaign_name}] pouco volume ({impressions} impressões, mínimo "
              f"{config.safety.min_impressions_before_placement_action}) — pulando.")
        log_action(
            action_type=ACTION_TYPE, target_type="adset", target_id=adset_id, target_name=campaign_name,
            before_value=None, after_value=None,
            reasoning="volume insuficiente para decidir posicionamento/demografia com segurança",
            confidence=1.0, status="rejected", dry_run=dry_run,
            rejection_reason=f"{impressions} impressões, mínimo {config.safety.min_impressions_before_placement_action}",
        )
        return

    by_platform_placement = fb_client.get_insights(
        campaign_id, date_preset="maximum", level="campaign",
        breakdowns=["publisher_platform", "platform_position"],
        fields=["impressions", "clicks", "ctr", "cpc", "spend"],
    )
    by_age_gender = fb_client.get_insights(
        campaign_id, date_preset="maximum", level="campaign",
        breakdowns=["age", "gender"], fields=["impressions", "clicks", "ctr", "cpc"],
    )
    current_targeting = adset.get("targeting") or {}

    plan = build_placement_plan(
        ai_client, model=config.ai.model, effort=config.ai.optimizer_effort,
        campaign_name=campaign_name, overall=overall,
        by_platform_placement=by_platform_placement, by_age_gender=by_age_gender,
        current_targeting=current_targeting,
    )

    if not plan.should_apply:
        print(f"  [{campaign_name}] IA não propôs mudança: {plan.reason_if_not_applying}")
        log_action(
            action_type=ACTION_TYPE, target_type="adset", target_id=adset_id, target_name=campaign_name,
            before_value=None, after_value=None,
            reasoning=plan.reason_if_not_applying or plan.explanation,
            confidence=plan.confidence, status="rejected", dry_run=dry_run,
            rejection_reason="a IA concluiu que não havia ajuste seguro a propor agora",
        )
        return

    if plan.confidence < config.safety.require_ai_confidence:
        print(f"  [{campaign_name}] confiança {plan.confidence:.2f} abaixo do mínimo "
              f"{config.safety.require_ai_confidence:.2f} — pulando.")
        log_action(
            action_type=ACTION_TYPE, target_type="adset", target_id=adset_id, target_name=campaign_name,
            before_value=None, after_value=None, reasoning=plan.explanation, confidence=plan.confidence,
            status="rejected", dry_run=dry_run,
            rejection_reason=f"confiança abaixo do mínimo ({config.safety.require_ai_confidence})",
        )
        return

    new_targeting = build_placement_targeting(current_targeting, plan)
    summary = (f"posicionamentos: {plan.platforms_to_keep or 'sem alterar'}; "
               f"idade: {new_targeting.get('age_min')}-{new_targeting.get('age_max')}; "
               f"gênero: {plan.gender_targeting}")
    print(f"  [{campaign_name}] {'(dry-run) ' if dry_run else ''}aplicando: {summary}")
    print(f"      {plan.explanation}")

    if dry_run:
        log_action(
            action_type=ACTION_TYPE, target_type="adset", target_id=adset_id, target_name=campaign_name,
            before_value=str(current_targeting), after_value=str(new_targeting),
            reasoning=plan.explanation, confidence=plan.confidence, status="simulated", dry_run=True,
        )
        return

    warning = None
    try:
        fb_client.update_adset_targeting(adset_id, new_targeting)
    except FacebookAdsError as exc:
        warning = f"a Meta recusou o recorte de posicionamentos, aplicando só idade/gênero: {exc}"
        print(f"      Aviso: {warning}")
        fallback_targeting = build_age_gender_only_targeting(current_targeting, plan)
        fb_client.update_adset_targeting(adset_id, fallback_targeting)
        new_targeting = fallback_targeting

    log_action(
        action_type=ACTION_TYPE, target_type="adset", target_id=adset_id, target_name=campaign_name,
        before_value=str(current_targeting), after_value=str(new_targeting),
        reasoning=plan.explanation + (f" ({warning})" if warning else ""),
        confidence=plan.confidence, status="applied", dry_run=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Otimiza posicionamento e demografia das campanhas ativas, sem mexer em orçamento.")
    parser.add_argument("--campaign-id", default=None, help="Processa só esta campanha (por padrão, processa todas as ativas)")
    parser.add_argument("--dry-run", action="store_true", help="Mostra o plano de cada campanha sem aplicar nada no Facebook")
    args = parser.parse_args()

    config = load_config()
    fb_client = FacebookAdsClient(config.facebook.access_token, config.facebook.ad_account_id,
                                   config.facebook.api_version)
    ai_client = anthropic.Anthropic(api_key=config.ai.api_key)

    if args.campaign_id:
        campaigns = [{"id": args.campaign_id, "name": args.campaign_id}]
    else:
        campaigns = fb_client.list_campaigns(status_filter=["ACTIVE"])

    if not campaigns:
        print("Nenhuma campanha ativa encontrada.")
        return

    last_changes = last_change_timestamps()
    print(f"{len(campaigns)} campanha(s) para avaliar.")

    for campaign in campaigns:
        adsets = fb_client.list_adsets(campaign["id"])
        active_adsets = [a for a in adsets if a.get("effective_status") == "ACTIVE"]
        if not active_adsets:
            print(f"  [{campaign.get('name', campaign['id'])}] sem adset ativo — pulando.")
            continue
        _optimize_one(ai_client, fb_client, config=config, campaign=campaign,
                       adset=active_adsets[0], last_changes=last_changes, dry_run=args.dry_run)

    if args.dry_run:
        print("\nModo de revisão (--dry-run) — nenhuma mudança real foi aplicada no Facebook.")


if __name__ == "__main__":
    main()
