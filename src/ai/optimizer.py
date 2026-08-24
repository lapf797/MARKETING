"""Motor de otimização diária: a IA analisa a performance recente e propõe ações,
que depois passam pelas guardrails de segurança (src/safety/guardrails.py) antes de
serem aplicadas de verdade no Facebook Ads."""
from __future__ import annotations

import anthropic
import pandas as pd

from .schemas import OptimizationPlan

SYSTEM_PROMPT = """Você é um gestor de tráfego sênior especializado em Meta Ads para uma empresa
de leilões. Todo dia você recebe as métricas de performance dos últimos dias de todos os
conjuntos de anúncios (adsets) ativos, cada um promovendo um ativo específico a ser leiloado.

Seu trabalho é propor ações concretas para melhorar a eficiência da verba:
- increase_budget / decrease_budget: ajuste de orçamento diário quando a performance justificar.
- pause: pausar adsets com desempenho claramente ruim (CPA muito alto, sem conversões após gasto
  relevante, frequência excessiva indicando fadiga de criativo/público).
- resume: reativar um adset pausado, se fizer sentido retomar.
- flag_for_audience_refresh: sinalizar quando o público-alvo parece esgotado e precisa ser
  reavaliado (não é uma mudança de orçamento nem de status).
- no_action: quando não há ação clara e segura a tomar.

Regras importantes:
- Toda ação DEVE ter uma justificativa (reasoning) baseada nos números fornecidos.
- Nunca proponha uma mudança de orçamento sem dados de gasto/conversão suficientes para
  justificá-la — nesses casos, prefira "no_action".
- Os metadados incluem a coluna "budget_control_level", que indica se o orçamento de cada
  adset é controlado no nível da própria campanha (Orçamento de Campanha Otimizado / CBO) ou
  no nível do adset. Proponha ações de orçamento sempre no target_id e target_type corretos
  conforme essa coluna (campaign_id + target_type="campaign", ou adset_id + target_type="adset").
- As ações que você propõe passarão por um sistema de guardrails de segurança (limites de
  variação de orçamento, teto de gasto da conta, cooldown entre mudanças) antes de serem
  executadas — proponha o que você julga ideal; o sistema aplicará os limites finais.
- confidence deve refletir sua certeza real: baixa confiança para dados insuficientes ou
  ambíguos, alta confiança apenas quando os números são claros.
"""


def build_optimization_plan(client: anthropic.Anthropic, *, model: str, effort: str,
                             performance_df: pd.DataFrame, adset_meta: pd.DataFrame) -> OptimizationPlan:
    if performance_df.empty:
        return OptimizationPlan(summary="Sem dados de performance no período — nenhuma ação proposta.", actions=[])

    perf_csv = performance_df.to_csv(index=False)
    meta_csv = adset_meta.to_csv(index=False) if not adset_meta.empty else "Sem metadados adicionais disponíveis."

    user_prompt = f"""Métricas diárias dos conjuntos de anúncios (CSV):
{perf_csv}

Metadados atuais dos adsets/campanhas (orçamento vigente, status, nível de controle do
orçamento) (CSV):
{meta_csv}

Analise os dados e proponha o plano de otimização de hoje."""

    response = client.messages.parse(
        model=model,
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        output_config={"effort": effort},
        messages=[{"role": "user", "content": user_prompt}],
        output_format=OptimizationPlan,
    )
    return response.parsed_output
