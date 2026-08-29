"""Testes do armazenamento de rascunhos de anúncio (src/safety/draft_log.py) — o único
arquivo mutável do sistema (todo o resto é append-only), então precisa de cobertura
extra para create/update/leitura por status não silenciosamente perder dados."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.safety.draft_log import append_drafts, get_draft, read_drafts, update_draft, write_dashboard_snapshot


def test_append_and_read_by_status(tmp_path):
    path = tmp_path / "ad_drafts.json"
    saved = append_drafts([
        {"batch_id": "b1", "property": {"title": "Casa A"}},
        {"batch_id": "b1", "property": {"title": "Casa B"}},
    ], path=path)

    assert len(saved) == 2
    assert all(d["status"] == "rascunho" for d in saved)
    assert all(d["draft_id"] for d in saved)

    drafts = read_drafts(status="rascunho", path=path)
    assert len(drafts) == 2
    assert {d["property"]["title"] for d in drafts} == {"Casa A", "Casa B"}


def test_append_preserves_existing_drafts(tmp_path):
    path = tmp_path / "ad_drafts.json"
    append_drafts([{"batch_id": "b1", "property": {"title": "Casa A"}}], path=path)
    append_drafts([{"batch_id": "b2", "property": {"title": "Casa B"}}], path=path)

    drafts = read_drafts(path=path)
    assert len(drafts) == 2


def test_update_draft_changes_status(tmp_path):
    path = tmp_path / "ad_drafts.json"
    [draft] = append_drafts([{"batch_id": "b1", "property": {"title": "Casa A"}}], path=path)

    updated = update_draft(draft["draft_id"], status="criado", meta_campaign_id="123", path=path)

    assert updated["status"] == "criado"
    assert updated["meta_campaign_id"] == "123"
    assert "updated_at" in updated

    # não deve mais aparecer como pendente
    assert read_drafts(status="rascunho", path=path) == []
    assert read_drafts(status="criado", path=path)[0]["draft_id"] == draft["draft_id"]


def test_update_unknown_draft_returns_none(tmp_path):
    path = tmp_path / "ad_drafts.json"
    append_drafts([{"batch_id": "b1", "property": {"title": "Casa A"}}], path=path)
    assert update_draft("id-que-nao-existe", status="criado", path=path) is None


def test_get_draft_by_id(tmp_path):
    path = tmp_path / "ad_drafts.json"
    [draft] = append_drafts([{"batch_id": "b1", "property": {"title": "Casa A"}}], path=path)
    found = get_draft(draft["draft_id"], path=path)
    assert found is not None
    assert found["property"]["title"] == "Casa A"


def test_get_draft_missing_returns_none(tmp_path):
    path = tmp_path / "ad_drafts.json"
    assert get_draft("nao-existe", path=path) is None


def test_filter_by_batch_id(tmp_path):
    path = tmp_path / "ad_drafts.json"
    append_drafts([{"batch_id": "b1", "property": {"title": "Casa A"}}], path=path)
    append_drafts([{"batch_id": "b2", "property": {"title": "Casa B"}}], path=path)

    b1_drafts = read_drafts(batch_id="b1", path=path)
    assert len(b1_drafts) == 1
    assert b1_drafts[0]["property"]["title"] == "Casa A"


def test_read_drafts_on_missing_file_returns_empty(tmp_path):
    path = tmp_path / "does_not_exist.json"
    assert read_drafts(path=path) == []


def test_dashboard_snapshot_includes_leilao_and_preview_image(tmp_path):
    source_path = tmp_path / "ad_drafts.json"
    out_path = tmp_path / "drafts_data.json"
    append_drafts([{
        "batch_id": "b1", "leilao": "Leilão 15498 - Imóveis Setembro",
        "preview_image_url": "./creative_previews/abc.jpg",
        "account_id": "act_1", "page_id": "p1", "link_url": "https://x", "picture_url": "https://x/foto.jpg",
        "property": {"title": "Casa A", "headline": "Casa A"},
    }], path=source_path)

    write_dashboard_snapshot(source_path=source_path, out_path=out_path)

    import json
    snapshot = json.loads(out_path.read_text(encoding="utf-8"))
    [pending] = snapshot["pending"]
    assert pending["leilao"] == "Leilão 15498 - Imóveis Setembro"
    assert pending["preview_image_url"] == "./creative_previews/abc.jpg"
    assert pending["missing_fields"] == []
