"""Testes do registro de públicos personalizados/semelhantes — precisa manter só a versão
mais recente por nome e nunca devolver um público sem lookalike como se fosse usável."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.safety.audience_registry import get_latest_lookalike, list_audiences, record_sync


def test_record_and_get_latest_lookalike(tmp_path):
    path = tmp_path / "custom_audiences.json"
    record_sync(name="Compradores", custom_audience_id="ca_1", lookalike_audience_id="la_1",
                members_sent=100, path=path)

    latest = get_latest_lookalike(path=path)
    assert latest["lookalike_audience_id"] == "la_1"
    assert latest["custom_audience_id"] == "ca_1"


def test_resync_same_name_replaces_previous_entry(tmp_path):
    path = tmp_path / "custom_audiences.json"
    record_sync(name="Compradores", custom_audience_id="ca_1", lookalike_audience_id="la_1",
                members_sent=100, path=path)
    record_sync(name="Compradores", custom_audience_id="ca_1", lookalike_audience_id="la_2",
                members_sent=150, path=path)

    audiences = list_audiences(path=path)
    assert len(audiences) == 1
    assert audiences[0]["lookalike_audience_id"] == "la_2"
    assert audiences[0]["members_sent"] == 150


def test_entries_without_lookalike_are_ignored(tmp_path):
    path = tmp_path / "custom_audiences.json"
    record_sync(name="Sem lookalike", custom_audience_id="ca_2", lookalike_audience_id=None,
                members_sent=50, path=path)

    assert get_latest_lookalike(path=path) is None
    assert len(list_audiences(path=path)) == 1  # ainda aparece na listagem geral


def test_get_latest_lookalike_filters_by_name(tmp_path):
    path = tmp_path / "custom_audiences.json"
    record_sync(name="A", custom_audience_id="ca_a", lookalike_audience_id="la_a",
                members_sent=10, path=path)
    record_sync(name="B", custom_audience_id="ca_b", lookalike_audience_id="la_b",
                members_sent=20, path=path)

    assert get_latest_lookalike(name="B", path=path)["custom_audience_id"] == "ca_b"


def test_no_audiences_returns_none(tmp_path):
    path = tmp_path / "does_not_exist.json"
    assert get_latest_lookalike(path=path) is None
    assert list_audiences(path=path) == []
