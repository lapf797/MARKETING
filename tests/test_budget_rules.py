"""Testes das regras determinísticas de orçamento/prazo para anúncios de catálogo —
mantidas como código (não pedidas à IA) para ficarem previsíveis; ver src/ai/budget_rules.py."""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ai.budget_rules import days_until, suggested_total_budget_cents

TIERS = [(300_000.0, 75_000), (1_000_000.0, 200_000)]
ABOVE_MAX = 450_000


def test_budget_first_tier():
    assert suggested_total_budget_cents(150_000, tiers_cents=TIERS, above_max_tier_cents=ABOVE_MAX) == 75_000


def test_budget_second_tier():
    assert suggested_total_budget_cents(500_000, tiers_cents=TIERS, above_max_tier_cents=ABOVE_MAX) == 200_000


def test_budget_above_max_tier():
    assert suggested_total_budget_cents(2_000_000, tiers_cents=TIERS, above_max_tier_cents=ABOVE_MAX) == 450_000


def test_budget_unknown_price_uses_first_tier():
    assert suggested_total_budget_cents(None, tiers_cents=TIERS, above_max_tier_cents=ABOVE_MAX) == 75_000


def test_budget_tier_boundary_is_exclusive():
    # exatamente no teto de uma faixa cai na faixa seguinte (< strict, não <=)
    assert suggested_total_budget_cents(300_000, tiers_cents=TIERS, above_max_tier_cents=ABOVE_MAX) == 200_000


def test_days_until_future_date():
    target = (date.today() + timedelta(days=10)).isoformat()
    assert days_until(target) == 10


def test_days_until_past_date_clamps_to_minimum():
    target = (date.today() - timedelta(days=5)).isoformat()
    assert days_until(target, minimum_days=1) == 1


def test_days_until_missing_date_uses_default():
    assert days_until(None, default_days=30) == 30


def test_days_until_malformed_date_uses_default():
    assert days_until("não é uma data", default_days=30) == 30
