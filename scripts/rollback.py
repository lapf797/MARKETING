"""Reverte a última ação automática REAL aplicada a um adset/campanha específico,
usando o valor anterior registrado na trilha de auditoria (logs/audit_log.jsonl).

Uso:
    python scripts/rollback.py <id_do_objeto_no_facebook>
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import load_config
from src.facebook_ads.client import FacebookAdsClient
from src.safety.audit_log import log_action, read_log


def main() -> None:
    parser = argparse.ArgumentParser(description="Reverte a última ação automática aplicada a um adset/campanha.")
    parser.add_argument("target_id", help="ID do objeto no Facebook Ads (campanha ou adset)")
    args = parser.parse_args()

    config = load_config()
    fb_client = FacebookAdsClient(config.facebook.access_token, config.facebook.ad_account_id,
                                   config.facebook.api_version)

    entries = [e for e in read_log() if e["target_id"] == args.target_id and not e.get("dry_run")]
    if not entries:
        print(f"Nenhuma ação real registrada para {args.target_id}. Nada para reverter.")
        return

    last = entries[-1]
    print(f"Última ação em {args.target_id}: {last['action_type']} "
          f"({last['before_value']} -> {last['after_value']}) às {last['timestamp']}")

    if last["action_type"] in ("increase_budget", "decrease_budget"):
        before = int(last["before_value"])
        if last["target_type"] == "campaign":
            fb_client.update_campaign_budget(args.target_id, daily_budget_cents=before)
        else:
            fb_client.update_adset_budget(args.target_id, daily_budget_cents=before)
    elif last["action_type"] == "pause":
        fb_client.set_status(args.target_id, "ACTIVE")
    elif last["action_type"] == "resume":
        fb_client.set_status(args.target_id, "PAUSED")
    else:
        print(f"Tipo de ação '{last['action_type']}' não possui rollback automático.")
        return

    log_action(
        action_type=f"rollback_{last['action_type']}", target_type=last["target_type"],
        target_id=args.target_id, target_name=last["target_name"],
        before_value=last["after_value"], after_value=last["before_value"],
        reasoning="Rollback manual solicitado via scripts/rollback.py", confidence=1.0, dry_run=False,
    )
    print("Rollback aplicado e registrado na trilha de auditoria.")


if __name__ == "__main__":
    main()
