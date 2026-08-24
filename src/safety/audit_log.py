"""Trilha de auditoria (append-only) de toda DECISÃO da IA — aplicada, simulada (dry-run)
ou rejeitada pelas guardrails. Persistida em logs/audit_log.jsonl e versionada no próprio
repositório git (o workflow do GitHub Actions faz commit do arquivo a cada execução).
Alimenta o rollback manual (src/safety) e o dashboard web (docs/index.html)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

DEFAULT_LOG_PATH = Path("logs/audit_log.jsonl")

Status = Literal["applied", "simulated", "rejected"]


def log_action(*, action_type: str, target_type: str, target_id: str, target_name: str,
               before_value: str | None, after_value: str | None, reasoning: str,
               confidence: float, status: Status, dry_run: bool,
               rejection_reason: str | None = None, adjusted: bool = False,
               log_path: Path = DEFAULT_LOG_PATH) -> dict[str, Any]:
    """status: "applied" (mudança real feita no Facebook), "simulated" (aprovada pelas
    guardrails mas não aplicada porque safety.dry_run está ativo) ou "rejected" (barrada
    pelas guardrails antes de chegar perto do Facebook — rejection_reason explica por quê)."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action_type": action_type,
        "target_type": target_type,
        "target_id": target_id,
        "target_name": target_name,
        "before_value": before_value,
        "after_value": after_value,
        "reasoning": reasoning,
        "confidence": confidence,
        "status": status,
        "dry_run": dry_run,
        "rejection_reason": rejection_reason,
        "adjusted": adjusted,
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def read_log(log_path: Path = DEFAULT_LOG_PATH) -> list[dict[str, Any]]:
    if not log_path.exists():
        return []
    with log_path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def last_change_timestamps(log_path: Path = DEFAULT_LOG_PATH) -> dict[str, str]:
    """Por target_id, o timestamp da última mudança REAL (status="applied") — usado
    pelas guardrails para calcular o cooldown entre mudanças. Ações simuladas ou
    rejeitadas nunca contam para o cooldown."""
    last: dict[str, str] = {}
    for entry in read_log(log_path):
        if entry.get("status") != "applied":
            continue
        last[entry["target_id"]] = entry["timestamp"]
    return last
