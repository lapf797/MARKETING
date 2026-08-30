"""Testa só a flag --budget de scripts/create_campaigns_from_drafts.py — o resto do script
(criação de verdade no Facebook) já depende de credenciais reais e não é coberto aqui."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.create_campaigns_from_drafts import main
from src.safety.draft_log import append_drafts


def test_budget_flag_sets_daily_budget_cents(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    [draft] = append_drafts([{"batch_id": "b1", "property": {"title": "Casa A"}}])

    monkeypatch.setattr(sys, "argv", ["create_campaigns_from_drafts.py", "--draft-id", draft["draft_id"], "--budget", "120"])
    main()

    data = json.loads((tmp_path / "logs" / "ad_drafts.json").read_text(encoding="utf-8"))
    updated = next(d for d in data["drafts"] if d["draft_id"] == draft["draft_id"])
    assert updated["daily_budget_cents"] == 12000
    assert updated["status"] == "rascunho"  # não muda o status, só o orçamento

    snapshot = json.loads((tmp_path / "docs" / "drafts_data.json").read_text(encoding="utf-8"))
    assert snapshot["pending"][0]["daily_budget_cents"] == 12000

    assert "R$ 120.00/dia" in capsys.readouterr().out


def test_budget_flag_requires_draft_id(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["create_campaigns_from_drafts.py", "--budget", "120"])
    try:
        main()
        assert False, "deveria ter chamado parser.error / sys.exit"
    except SystemExit as exc:
        assert exc.code != 0


def test_budget_flag_rejects_non_positive_value(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    [draft] = append_drafts([{"batch_id": "b1", "property": {"title": "Casa A"}}])
    monkeypatch.setattr(sys, "argv", ["create_campaigns_from_drafts.py", "--draft-id", draft["draft_id"], "--budget", "0"])
    try:
        main()
        assert False, "deveria ter chamado parser.error / sys.exit"
    except SystemExit as exc:
        assert exc.code != 0
