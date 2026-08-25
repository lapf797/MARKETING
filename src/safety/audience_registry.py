"""Registro dos públicos personalizados e semelhantes (lookalike) já sincronizados com o
Facebook — para que novas campanhas usem automaticamente o público semelhante mais
recente como uma camada a mais de segmentação (junto com os interesses), sem precisar
recriar nada a cada vez. Mesmo padrão mutável de src/safety/draft_log.py."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_PATH = Path("logs/custom_audiences.json")


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"audiences": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _save(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def record_sync(*, name: str, custom_audience_id: str, lookalike_audience_id: str | None,
                 members_sent: int, path: Path = DEFAULT_PATH) -> dict:
    """Grava (ou substitui, se já existir um público com o mesmo nome) o resultado de uma
    sincronização — só a versão mais recente de cada público nomeado é mantida."""
    data = _load(path)
    entry = {
        "name": name,
        "custom_audience_id": custom_audience_id,
        "lookalike_audience_id": lookalike_audience_id,
        "members_sent": members_sent,
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }
    data["audiences"] = [a for a in data["audiences"] if a.get("name") != name] + [entry]
    _save(data, path)
    return entry


def get_latest_lookalike(*, name: str | None = None, path: Path = DEFAULT_PATH) -> dict | None:
    """O público semelhante mais recente já sincronizado (o único usado automaticamente em
    novas campanhas) — opcionalmente filtrado por nome, se você mantém mais de um público."""
    audiences = _load(path)["audiences"]
    if name:
        audiences = [a for a in audiences if a.get("name") == name]
    audiences = [a for a in audiences if a.get("lookalike_audience_id")]
    if not audiences:
        return None
    return sorted(audiences, key=lambda a: a["synced_at"])[-1]


def list_audiences(*, path: Path = DEFAULT_PATH) -> list[dict]:
    return _load(path)["audiences"]
