"""Regras determinísticas de orçamento e prazo para anúncios criados a partir de um
catálogo de leilão. Mantidas como código (não pedidas à IA) pela mesma razão das
guardrails em src/safety/guardrails.py: decisão sobre dinheiro real deve ser previsível e
fácil de auditar, não uma sugestão de modelo de linguagem que pode variar a cada chamada."""
from __future__ import annotations

from datetime import date, datetime


def suggested_total_budget_cents(price_value: float | None, *,
                                  tiers_cents: list[tuple[float, int]],
                                  above_max_tier_cents: int) -> int:
    """tiers_cents: lista de (teto_de_valor_do_ativo, orçamento_total_cents), em ordem
    crescente. O ativo cai na primeira faixa cujo teto ele não ultrapassa; acima de todas
    as faixas, usa above_max_tier_cents. Sem price_value conhecido, usa a primeira faixa
    (mais conservadora)."""
    if not tiers_cents:
        return above_max_tier_cents
    if price_value is None:
        return tiers_cents[0][1]
    for threshold, budget_cents in tiers_cents:
        if price_value < threshold:
            return budget_cents
    return above_max_tier_cents


def days_until(target_date: str | None, *, minimum_days: int = 1, default_days: int = 30) -> int:
    """Dias entre hoje e a data do leilão (YYYY-MM-DD). Sem data reconhecível, usa um
    prazo padrão conservador. Nunca retorna menos que minimum_days — evita orçamento
    diário artificialmente alto quando a data do leilão já passou ou é hoje."""
    if not target_date:
        return default_days
    try:
        parsed = datetime.strptime(target_date, "%Y-%m-%d").date()
    except ValueError:
        return default_days
    delta = (parsed - date.today()).days
    return max(delta, minimum_days)
