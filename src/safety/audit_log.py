"""Trilha de auditoria (append-only) de toda ação aplicada — permite rastrear o que mudou
e reverter manualmente se necessário. Persistida em logs/audit_log.jsonl e versionada no
próprio repositório git (o workflow do GitHub Actions faz commit do arquivo a cada execução)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_LOG_PATH = Path("logs/audit_log.jsonl")


def log_action(action_type: str, target_type: str, target_id: str, target_name: str,
               before_value: str | None, after_value: str | None, reasoning: str,
               confidence: float, dry_run: bool, log_path: Path = DEFAULT_LOG_PATH) -> dict[str, Any]:
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
        "dry_run": dry_run,
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
    """Por target_id, o timestamp da última ação REAL (não dry-run) aplicada — usado
    pelas guardrails para calcular o cooldown entre mudanças."""
    last: dict[str, str] = {}
    for entry in read_log(log_path):
        if entry.get("dry_run"):
            continue
        last[entry["target_id"]] = entry["timestamp"]
    return last
