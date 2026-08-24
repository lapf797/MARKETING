"""Armazena os rascunhos de anúncio gerados a partir de um catálogo de leilão. Ao
contrário da trilha de auditoria (append-only), este arquivo é mutável: cada rascunho
nasce com status "rascunho" e muda para "criado", "rejeitado" ou "erro" conforme o humano
revisa e o script scripts/create_campaigns_from_drafts.py processa cada um."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

DEFAULT_PATH = Path("logs/ad_drafts.json")

Status = Literal["rascunho", "criado", "rejeitado", "erro"]


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"drafts": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _save(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def append_drafts(entries: list[dict[str, Any]], *, path: Path = DEFAULT_PATH) -> list[dict]:
    """Cada entry já deve trazer os campos de conteúdo prontos (ver
    scripts/analyze_catalog.py); esta função só atribui draft_id/created_at/status e persiste."""
    data = _load(path)
    now = datetime.now(timezone.utc).isoformat()
    saved = []
    for entry in entries:
        record = {"draft_id": str(uuid.uuid4()), "created_at": now, "status": "rascunho", **entry}
        data["drafts"].append(record)
        saved.append(record)
    _save(data, path)
    return saved


def read_drafts(*, status: Status | None = None, batch_id: str | None = None,
                 path: Path = DEFAULT_PATH) -> list[dict]:
    drafts = _load(path)["drafts"]
    if status:
        drafts = [d for d in drafts if d.get("status") == status]
    if batch_id:
        drafts = [d for d in drafts if d.get("batch_id") == batch_id]
    return drafts


def get_draft(draft_id: str, *, path: Path = DEFAULT_PATH) -> dict | None:
    for draft in _load(path)["drafts"]:
        if draft.get("draft_id") == draft_id:
            return draft
    return None


def update_draft(draft_id: str, *, path: Path = DEFAULT_PATH, **fields: Any) -> dict | None:
    data = _load(path)
    updated = None
    for draft in data["drafts"]:
        if draft.get("draft_id") == draft_id:
            draft.update(fields)
            draft["updated_at"] = datetime.now(timezone.utc).isoformat()
            updated = draft
            break
    if updated is not None:
        _save(data, path)
    return updated


DASHBOARD_SNAPSHOT_PATH = Path("docs/drafts_data.json")


def write_dashboard_snapshot(*, source_path: Path = DEFAULT_PATH,
                              out_path: Path = DASHBOARD_SNAPSHOT_PATH) -> None:
    """Grava um resumo dos rascunhos para o dashboard web (docs/index.html) — chamado ao
    final de scripts/analyze_catalog.py e scripts/create_campaigns_from_drafts.py."""
    drafts = read_drafts(path=source_path)

    def _missing_fields(draft: dict) -> list[str]:
        return [name for name in ("account_id", "page_id", "link_url", "picture_url") if not draft.get(name)]

    pending = []
    for draft in drafts:
        if draft.get("status") != "rascunho":
            continue
        prop = draft.get("property", {})
        pending.append({
            "draft_id": draft["draft_id"],
            "title": prop.get("title"),
            "category": prop.get("category"),
            "city": prop.get("city"),
            "state": prop.get("state"),
            "headline": prop.get("headline"),
            "total_budget_cents": draft.get("total_budget_cents"),
            "pause_date": draft.get("pause_date"),
            "missing_fields": _missing_fields(draft),
        })

    recent_created = [
        {"draft_id": d["draft_id"], "title": d.get("property", {}).get("title"),
         "meta_campaign_id": d.get("meta_campaign_id"), "updated_at": d.get("updated_at")}
        for d in drafts if d.get("status") == "criado"
    ]
    recent_errors = [
        {"draft_id": d["draft_id"], "title": d.get("property", {}).get("title"),
         "error_message": d.get("error_message"), "updated_at": d.get("updated_at")}
        for d in drafts if d.get("status") == "erro"
    ]

    snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pending_count": len(pending),
        "pending": pending,
        "recent_created": list(reversed(recent_created))[:20],
        "recent_errors": list(reversed(recent_errors))[:20],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
