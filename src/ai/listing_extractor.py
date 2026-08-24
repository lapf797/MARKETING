"""Extração de dados estruturados de uma página de leilão a partir da URL, usando a
ferramenta de busca na web nativa da Claude (web_fetch) para ler a página diretamente —
o fetch roda na infraestrutura da Anthropic, não no ambiente onde este script executa,
então funciona mesmo em runners com rede restrita (ex: GitHub Actions)."""
from __future__ import annotations

import json
import re

import anthropic

from .schemas import AssetListing

SYSTEM_PROMPT = """Você lê páginas de anúncios de leilão (imóveis, veículos, máquinas,
equipamentos etc.) e extrai os dados do lote em formato estruturado.

Regras:
- Use a ferramenta de busca na web para acessar a URL fornecida e ler o conteúdo real da
  página antes de responder. Não responda de memória.
- Extraia apenas informações que realmente aparecem na página — nunca invente ou estime
  valores que não estão explícitos no conteúdo.
- "category" deve ser uma categoria curta e genérica (ex: "Imóveis", "Veículos",
  "Máquinas e Equipamentos", "Diversos"), não o nome específico do lote.
- "key_details" deve conter só atributos objetivos e curtos, um por item (ex: "3 quartos",
  "90m²", "ano 2021", "IPVA quitado") — não repita a descrição inteira ali.
- Se a página não puder ser acessada, não carregar conteúdo relevante, ou não for um
  anúncio de leilão, responda com "success": false e explique o motivo em
  "error_message" — nunca invente dados nesse caso.
- Responda SOMENTE com um objeto JSON válido, sem nenhum texto antes ou depois, sem
  bloco de código markdown, exatamente neste formato:

{
  "success": true,
  "error_message": null,
  "title": "...",
  "category": "...",
  "description": "...",
  "location": "...",
  "estimated_value": 000.00,
  "starting_bid": 000.00,
  "auction_end_at": "...",
  "lot_number": "...",
  "key_details": ["...", "..."],
  "extraction_notes": "..."
}

Use null para qualquer campo não encontrado na página (exceto "success" e "key_details",
que devem ser sempre, respectivamente, um booleano e uma lista — vazia se não houver
detalhes relevantes)."""


def _parse_json_block(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    return json.loads(text)


def extract_listing(client: anthropic.Anthropic, *, model: str, effort: str, url: str) -> AssetListing:
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        tools=[{"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 3}],
        output_config={"effort": effort},
        messages=[{
            "role": "user",
            "content": f"Leia esta página de leilão e extraia os dados do lote: {url}",
        }],
    )

    if response.stop_reason == "refusal":
        return AssetListing(
            source_url=url, success=False,
            error_message="A IA recusou processar esta página (verifique se a URL é apropriada).",
        )

    text_blocks = [block.text for block in response.content if block.type == "text"]
    if not text_blocks:
        return AssetListing(
            source_url=url, success=False,
            error_message="A IA não retornou texto com os dados extraídos.",
        )

    try:
        data = _parse_json_block(text_blocks[-1])
    except json.JSONDecodeError:
        return AssetListing(
            source_url=url, success=False,
            error_message=f"Não foi possível interpretar a resposta da IA como JSON: {text_blocks[-1][:300]}",
        )

    data["source_url"] = url
    return AssetListing(**data)
