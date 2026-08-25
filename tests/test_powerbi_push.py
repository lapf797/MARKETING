"""Teste de to_action_row (src/reporting/powerbi_push.py): garante que um entry da trilha
de auditoria (src.safety.audit_log.log_action) é filtrado para exatamente as colunas da
tabela OptimizerActions antes de ir pro Power BI — a Push Dataset API rejeita a linha
inteira se ela tiver qualquer propriedade fora do schema da tabela, e log_action() sempre
inclui campos extras (status/rejection_reason/adjusted) usados só localmente."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.reporting.powerbi_push import ACTION_ROW_FIELDS, to_action_row


def test_to_action_row_keeps_only_schema_columns():
    entry = {
        "timestamp": "2026-08-25T12:00:00+00:00",
        "action_type": "optimize_placements",
        "target_type": "adset",
        "target_id": "123",
        "target_name": "Campanha X",
        "before_value": "a",
        "after_value": "b",
        "reasoning": "motivo",
        "confidence": 0.9,
        "status": "applied",
        "dry_run": False,
        "rejection_reason": None,
        "adjusted": False,
    }
    row = to_action_row(entry)
    assert set(row.keys()) == set(ACTION_ROW_FIELDS)
    assert "status" not in row
    assert "rejection_reason" not in row
    assert "adjusted" not in row
    assert row["target_name"] == "Campanha X"


def test_to_action_row_raises_if_entry_missing_a_schema_field():
    incomplete_entry = {"timestamp": "2026-08-25T12:00:00+00:00", "action_type": "x"}
    try:
        to_action_row(incomplete_entry)
        assert False, "deveria ter levantado KeyError"
    except KeyError:
        pass
