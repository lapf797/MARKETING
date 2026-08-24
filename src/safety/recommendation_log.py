"""Registro (append-only) das recomendações de público-alvo geradas pela IA para novos
ativos. Persistido em logs/audience_recommendations.jsonl e versionado no repositório git.
Alimenta o dashboard web (docs/index.html) e complementa o envio ao Power BI."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.ai.schemas import AudienceRecommendation

DEFAULT_LOG_PATH = Path("logs/audience_recommendations.jsonl")


def log_recommendation(*, asset_category: str, asset_description: str, target_location: str,
                        recommendation: AudienceRecommendation, source_url: str | None = None,
                        log_path: Path = DEFAULT_LOG_PATH) -> dict[str, Any]:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "asset_category": asset_category,
        "asset_description": asset_description,
        "target_location": target_location,
        "source_url": source_url,
        **recommendation.model_dump(),
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def read_recommendations(log_path: Path = DEFAULT_LOG_PATH) -> list[dict[str, Any]]:
    if not log_path.exists():
        return []
    with log_path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
