"""Testes das guardrails de segurança — a parte mais crítica do sistema, já que decide
quais ações da IA são de fato aplicadas em dinheiro real no Facebook Ads."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ai.schemas import OptimizationAction
from src.config import SafetyConfig
from src.safety.guardrails import apply_guardrails


def make_config(**overrides) -> SafetyConfig:
    defaults = dict(
        dry_run=True,
        max_budget_change_pct_per_day=20,
        min_budget_change_pct_to_act=5,
        min_spend_before_action_cents=5000,
        cooldown_hours_between_changes=20,
        max_actions_per_run=15,
        max_pauses_per_run=5,
        account_daily_budget_cap_cents=1_000_000,
        max_cpa_cents=15000,
        min_conversions_for_reliable_cpa=3,
        max_frequency=4.0,
        require_ai_confidence=0.6,
        currency_minor_unit_factor=100,
        min_impressions_before_placement_action=500,
    )
    defaults.update(overrides)
    return SafetyConfig(**defaults)


def make_action(**overrides) -> OptimizationAction:
    defaults = dict(
        action_type="increase_budget", target_type="adset", target_id="123",
        target_name="Adset teste", current_value="10000", proposed_value="12000",
        reasoning="teste", confidence=0.9,
    )
    defaults.update(overrides)
    return OptimizationAction(**defaults)


def test_approves_valid_budget_increase_within_limits():
    action = make_action(proposed_value="11000")  # +10%, dentro do limite de 20%
    result = apply_guardrails(
        [action], config=make_config(),
        current_budgets_cents={"123": 10000}, last_change_at={},
        spend_last_period_cents={"123": 8000},
        current_total_daily_budget_cents=10000,
    )
    assert len(result.approved) == 1
    assert result.approved[0].proposed_value == "11000"


def test_clips_budget_change_exceeding_max_pct():
    action = make_action(proposed_value="20000")  # +100%, acima do limite de 20%
    result = apply_guardrails(
        [action], config=make_config(),
        current_budgets_cents={"123": 10000}, last_change_at={},
        spend_last_period_cents={"123": 8000},
        current_total_daily_budget_cents=10000,
    )
    assert len(result.approved) == 1
    assert result.approved[0].proposed_value == "12000"  # 10000 + 20%
    assert len(result.adjusted) == 1


def test_rejects_action_with_low_confidence():
    action = make_action(confidence=0.3)
    result = apply_guardrails(
        [action], config=make_config(),
        current_budgets_cents={"123": 10000}, last_change_at={},
        spend_last_period_cents={"123": 8000},
        current_total_daily_budget_cents=10000,
    )
    assert len(result.approved) == 0
    assert len(result.rejected) == 1


def test_rejects_action_in_cooldown():
    recent = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    action = make_action()
    result = apply_guardrails(
        [action], config=make_config(),
        current_budgets_cents={"123": 10000}, last_change_at={"123": recent},
        spend_last_period_cents={"123": 8000},
        current_total_daily_budget_cents=10000,
    )
    assert len(result.approved) == 0
    assert "cooldown" in result.rejected[0][1]


def test_rejects_action_with_insufficient_spend_data():
    action = make_action()
    result = apply_guardrails(
        [action], config=make_config(),
        current_budgets_cents={"123": 10000}, last_change_at={},
        spend_last_period_cents={"123": 1000},  # abaixo do mínimo de 5000
        current_total_daily_budget_cents=10000,
    )
    assert len(result.approved) == 0


def test_rejects_when_account_cap_would_be_exceeded():
    action = make_action(current_value="90000", proposed_value="95000")
    result = apply_guardrails(
        [action], config=make_config(account_daily_budget_cap_cents=90000),
        current_budgets_cents={"123": 90000}, last_change_at={},
        spend_last_period_cents={"123": 50000},
        current_total_daily_budget_cents=90000,
    )
    assert len(result.approved) == 0
    assert "teto" in result.rejected[0][1]


def test_ignores_tiny_budget_changes():
    action = make_action(proposed_value="10200")  # +2%, abaixo do mínimo de 5%
    result = apply_guardrails(
        [action], config=make_config(),
        current_budgets_cents={"123": 10000}, last_change_at={},
        spend_last_period_cents={"123": 8000},
        current_total_daily_budget_cents=10000,
    )
    assert len(result.approved) == 0


def test_respects_max_pauses_per_run():
    actions = [
        make_action(action_type="pause", target_id=str(i), current_value="10000", proposed_value=None)
        for i in range(3)
    ]
    result = apply_guardrails(
        actions, config=make_config(max_pauses_per_run=2),
        current_budgets_cents={str(i): 10000 for i in range(3)}, last_change_at={},
        spend_last_period_cents={str(i): 8000 for i in range(3)},
        current_total_daily_budget_cents=30000,
    )
    assert len(result.approved) == 2


def test_no_action_is_ignored():
    action = make_action(action_type="no_action", current_value=None, proposed_value=None)
    result = apply_guardrails(
        [action], config=make_config(),
        current_budgets_cents={"123": 10000}, last_change_at={},
        spend_last_period_cents={"123": 8000},
        current_total_daily_budget_cents=10000,
    )
    assert len(result.approved) == 0
    assert len(result.rejected) == 0
