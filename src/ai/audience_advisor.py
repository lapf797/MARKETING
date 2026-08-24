"""Recomendação de público-alvo via Claude, com base na performance histórica real
da conta de anúncios — usada sempre que há um novo ativo de leilão para anunciar."""
from __future__ import annotations

import anthropic
import pandas as pd

from .schemas import AudienceRecommendation

SYSTEM_PROMPT = """Você é um especialista em mídia paga (Meta Ads) para uma empresa de leilões.
Seu trabalho é recomendar público-alvo para anúncios de ativos específicos (imóveis, veículos,
máquinas, equipamentos etc.) que serão leiloados, com base no histórico de performance de
campanhas anteriores da mesma conta.

Regras:
- Baseie a recomendação em dados reais fornecidos, citando padrões observados (idade, gênero,
  região) quando existirem dados suficientes.
- Quando não houver histórico suficiente, seja conservador e explique isso no campo "reasoning";
  reduza a confiança (confidence) de acordo.
- Sugira interesses e comportamentos que existam de fato como categorias de segmentação do Meta
  Ads (ex: "Real estate", "Automóveis", "Investimentos", "Compradores de imóveis"). Esses nomes
  serão resolvidos para IDs reais por um humano antes da ativação — não invente IDs.
- O orçamento diário sugerido deve ser proporcional ao valor do ativo e ao objetivo informado,
  nunca acima do teto máximo informado pelo usuário.
"""


def recommend_audience(client: anthropic.Anthropic, *, model: str, effort: str,
                        asset_description: str, asset_category: str, asset_value: float | None,
                        target_location: str, max_daily_budget_cents: int,
                        historical_breakdown: pd.DataFrame) -> AudienceRecommendation:
    history_summary = (
        historical_breakdown.to_csv(index=False)
        if not historical_breakdown.empty
        else "Nenhum histórico de campanhas anteriores disponível ainda — esta pode ser a primeira campanha da conta."
    )

    user_prompt = f"""Novo ativo para anunciar:
- Categoria: {asset_category}
- Descrição: {asset_description}
- Valor estimado: {asset_value if asset_value is not None else "não informado"}
- Localização alvo: {target_location}
- Orçamento diário máximo permitido: {max_daily_budget_cents / 100:.2f} (moeda da conta)

Histórico de performance por segmento (CSV, pode estar vazio se for a primeira campanha):
{history_summary}

Recomende o público-alvo ideal para este ativo específico."""

    response = client.messages.parse(
        model=model,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        output_config={"effort": effort},
        messages=[{"role": "user", "content": user_prompt}],
        output_format=AudienceRecommendation,
    )
    return response.parsed_output
