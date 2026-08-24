"""Guardrails de segurança: toda ação sugerida pela IA passa por aqui antes de ser aplicada
no Facebook Ads de verdade. Esta camada é 100% determinística (sem IA envolvida) — nenhuma
ação escapa destes limites, independentemente do que o modelo proponha."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from src.ai.schemas import OptimizationAction
from src.config import SafetyConfig


@dataclass
class GuardrailResult:
    approved: list[OptimizationAction]
    rejected: list[tuple[OptimizationAction, str]]  # (ação, motivo da rejeição)
    adjusted: list[tuple[OptimizationAction, str]]   # ações cujo valor foi ajustado (clipado)


def _hours_since(timestamp_iso: str | None) -> float:
    if not timestamp_iso:
        return float("inf")
    last = datetime.fromisoformat(timestamp_iso)
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - last).total_seconds() / 3600


def _clip_budget_change(current_cents: int, proposed_cents: int, max_pct: float) -> tuple[int, bool]:
    max_delta = int(current_cents * (max_pct / 100))
    min_allowed = max(0, current_cents - max_delta)
    max_allowed = current_cents + max_delta
    clipped = min(max(proposed_cents, min_allowed), max_allowed)
    return clipped, clipped != proposed_cents


def apply_guardrails(
    actions: list[OptimizationAction],
    *,
    config: SafetyConfig,
    current_budgets_cents: dict[str, int],
    last_change_at: dict[str, str],
    spend_last_period_cents: dict[str, int],
    current_total_daily_budget_cents: int,
) -> GuardrailResult:
    approved: list[OptimizationAction] = []
    rejected: list[tuple[OptimizationAction, str]] = []
    adjusted: list[tuple[OptimizationAction, str]] = []

    pause_count = 0
    projected_total_budget = current_total_daily_budget_cents

    for action in actions:
        if action.action_type == "no_action":
            continue

        if action.confidence < config.require_ai_confidence:
            rejected.append((
                action,
                f"confiança {action.confidence:.2f} abaixo do mínimo {config.require_ai_confidence:.2f}",
            ))
            continue

        hours_since_change = _hours_since(last_change_at.get(action.target_id))
        if hours_since_change < config.cooldown_hours_between_changes:
            rejected.append((
                action,
                f"em cooldown — última mudança há {hours_since_change:.1f}h "
                f"(mínimo {config.cooldown_hours_between_changes}h)",
            ))
            continue

        spend = spend_last_period_cents.get(action.target_id, 0)
        if action.action_type in ("increase_budget", "decrease_budget", "pause") \
                and spend < config.min_spend_before_action_cents:
            rejected.append((
                action,
                f"gasto insuficiente para decidir com segurança "
                f"({spend / 100:.2f} < {config.min_spend_before_action_cents / 100:.2f})",
            ))
            continue

        if len(approved) >= config.max_actions_per_run:
            rejected.append((action, f"limite de ações por execução atingido ({config.max_actions_per_run})"))
            continue

        if action.action_type in ("increase_budget", "decrease_budget"):
            current = current_budgets_cents.get(action.target_id)
            if current is None:
                rejected.append((action, "orçamento atual desconhecido — não é seguro calcular o ajuste"))
                continue
            try:
                proposed = int(float(action.proposed_value))
            except (TypeError, ValueError):
                rejected.append((action, "valor proposto inválido"))
                continue

            pct_change = abs(proposed - current) / current * 100 if current else 0
            if pct_change < config.min_budget_change_pct_to_act:
                rejected.append((
                    action,
                    f"variação de {pct_change:.1f}% abaixo do mínimo para agir "
                    f"({config.min_budget_change_pct_to_act}%)",
                ))
                continue

            clipped, was_clipped = _clip_budget_change(current, proposed, config.max_budget_change_pct_per_day)
            delta = clipped - current
            if projected_total_budget + delta > config.account_daily_budget_cap_cents:
                rejected.append((
                    action,
                    f"aplicar esta mudança estouraria o teto diário de conta "
                    f"({config.account_daily_budget_cap_cents / 100:.2f})",
                ))
                continue

            projected_total_budget += delta
            action = action.model_copy(update={"proposed_value": str(clipped)})
            if was_clipped:
                adjusted.append((
                    action,
                    f"orçamento ajustado para respeitar variação máxima de "
                    f"{config.max_budget_change_pct_per_day}%/dia",
                ))

        if action.action_type == "pause":
            if pause_count >= config.max_pauses_per_run:
                rejected.append((action, f"limite de pausas por execução atingido ({config.max_pauses_per_run})"))
                continue
            pause_count += 1

        approved.append(action)

    return GuardrailResult(approved=approved, rejected=rejected, adjusted=adjusted)
