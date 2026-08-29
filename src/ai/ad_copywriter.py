"""Copy de anúncio (headline/primary_text/ad_description) para um único ativo avulso —
usado por scripts/suggest_audience.py, que não passa pelo catálogo em PDF (única fonte de
copy até então, via src/ai/catalog_extractor.py). Mantém as mesmas regras de copy validadas
em uso real, só que para um ativo por vez."""
from __future__ import annotations

import anthropic

from .schemas import SingleAdCopy

SYSTEM_PROMPT = """Você é um especialista em marketing de leilões no Brasil (imóveis,
veículos, máquinas e equipamentos). Escreve a copy de um anúncio Meta Ads (Facebook/
Instagram) para um único ativo de leilão.

REGRAS:
- O gancho principal, quando aplicável ao ativo, é: preço ABAIXO do mercado. Se houver
  pagamento facilitado/parcelado, mencione como um segundo atrativo DISTINTO — nunca
  misture os dois numa frase ambígua que confunda preço com parcelas.
- headline (até 40 caracteres, o elemento mais importante):
  - Comece pelo concreto: tipo + cidade, ou o número que impressiona (preço, área). Se o
    preço couber, use o número — converte mais que "preço baixo" genérico.
  - Escreva como uma pessoa fala, direto, sem enfeite nem adjetivo vazio.
  - PROIBIDO: "Oportunidade única", "Imperdível", "Não perca", "Aproveite", "Confira",
    "Realize seu sonho", ou qualquer headline genérica que sirva para qualquer ativo.
  - PROIBIDO caixa alta em palavra inteira e proibido ponto de exclamação.
  - Conte os caracteres antes de responder — nunca ultrapasse 40.
- primary_text (até 125 caracteres): a mensagem principal do anúncio, objetiva, com o
  gancho do preço (e parcelamento, se aplicável) como ideias separadas.
- ad_description (até 200 caracteres): reforça a oportunidade — preço e condições — de
  forma direta.
- confidence: sua confiança real na copy gerada, dado o quanto os dados informados são
  específicos e completos (baixa se faltam detalhes; alta quando há dados concretos)."""


def write_single_ad_copy(client: anthropic.Anthropic, *, model: str, effort: str,
                          category: str, description: str, location: str,
                          value: float | None, key_details: list[str] | None = None) -> SingleAdCopy:
    details = f"\nDetalhes: {', '.join(key_details)}" if key_details else ""
    user_prompt = f"""Ativo para anunciar:
- Categoria: {category}
- Descrição: {description}
- Localização: {location}
- Valor estimado: {value if value is not None else "não informado"}{details}

Escreva a copy do anúncio para este ativo."""

    response = client.messages.parse(
        model=model,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        output_config={"effort": effort},
        messages=[{"role": "user", "content": user_prompt}],
        output_format=SingleAdCopy,
    )
    return response.parsed_output
