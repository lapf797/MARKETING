"""Otimização de posicionamento e demografia SEM mexer em orçamento — um segundo tipo de
ajuste diário, complementar ao de src/ai/optimizer.py (que decide QUANTO gastar). Este
decide ONDE e PARA QUEM o orçamento já definido é exibido: concentra a verba nos
posicionamentos e faixas de público que já provaram clique mais barato, em vez de mudar o
valor gasto. É a alavanca mais conservadora das duas — nunca altera dinheiro."""
from __future__ import annotations

import anthropic

from .schemas import PlacementOptimizationPlan

SYSTEM_PROMPT = """Você é especialista em tráfego pago (Meta Ads) para uma empresa de
leilões no Brasil.

OBJETIVO: otimizar o anúncio como um todo SEM alterar o orçamento diário (o gasto continua
exatamente o mesmo). Com a MESMA verba, a campanha deve: (1) baixar o CPC (custo por
clique), (2) subir o CTR e (3) gerar mais cliques no total. A alavanca é concentrar a verba
nos posicionamentos e faixas de público que já provaram entregar clique mais barato e com
mais frequência.

REGRAS:
- Mantenha os posicionamentos que combinam CTR acima da média da campanha COM CPC abaixo da
  média, e que tenham volume relevante (pelo menos 3% das exibições). Corte os que têm CPC
  alto mesmo com CTR razoável — eles encarecem o clique. Nunca deixe a lista de
  posicionamentos vazia nem mantenha só um posicionamento de pouquíssimo volume: precisa
  sobrar espaço para a Meta entregar toda a verba e assim gerar mais cliques.
- Ajuste idade mínima/máxima para cobrir as faixas com clique mais barato e maior volume,
  sem estreitar demais — amplitude mínima de 15 anos, sempre entre 18 e 65. Estreitar
  demais encarece o CPC.
- Só restrinja o gênero se a diferença de CTR ou de CPC entre homens e mulheres for grande
  (mais de 40%).
- NUNCA sugira mudança de orçamento — isso é decidido por outro processo, separado deste.
- Se o volume de dados ainda for baixo para decidir com segurança, ou se a segmentação
  atual já parecer ótima (nenhum corte claro a fazer), responda should_apply: false e
  explique o motivo em reason_if_not_applying — não force um ajuste sem base nos dados.
- A sugestão de texto/chamada (creative_suggestion) deve ser objetiva e com gatilho de
  urgência do leilão, para elevar o CTR e, por consequência, baratear o clique — mas não é
  aplicada automaticamente, é só uma sugestão para revisão humana.
- confidence deve refletir sua certeza real: baixa para dados insuficientes ou ambíguos.

Responda em português do Brasil."""


def build_placement_plan(client: anthropic.Anthropic, *, model: str, effort: str,
                          campaign_name: str, overall: dict, by_platform_placement: list[dict],
                          by_age_gender: list[dict], current_targeting: dict) -> PlacementOptimizationPlan:
    user_prompt = f"""CAMPANHA: {campaign_name}

DESEMPENHO GERAL: {overall}

DESEMPENHO POR PLATAFORMA E POSICIONAMENTO (com CPC): {by_platform_placement}

DESEMPENHO POR IDADE E GÊNERO (com CPC): {by_age_gender}

SEGMENTAÇÃO ATUAL:
- Idade: {current_targeting.get("age_min")}-{current_targeting.get("age_max")}
- Gêneros: {current_targeting.get("genders")}
- Plataformas: {current_targeting.get("publisher_platforms") or "não restrito"}"""

    response = client.messages.parse(
        model=model,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        output_config={"effort": effort},
        messages=[{"role": "user", "content": user_prompt}],
        output_format=PlacementOptimizationPlan,
    )
    return response.parsed_output
