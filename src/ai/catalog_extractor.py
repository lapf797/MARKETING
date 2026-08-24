"""Extração em lote de todos os ativos de um catálogo de leilão em PDF.

Usa a visão nativa da Claude para documentos: a IA lê o PDF inteiro — texto E fotos —
numa única chamada, sem precisar de nenhuma lógica escrita à mão para separar imagens do
binário do PDF (ao contrário de uma abordagem baseada em varredura de bytes JPEG, que é
frágil e específica de cada gerador de PDF).

A fórmula de copy abaixo (gatilhos, limites de caracteres, heurísticas de público por tipo
de ativo) foi validada em uso real de uma empresa de leilões — mantenha-a ao ajustar o
prompt, a menos que tenha um motivo de negócio para mudar.
"""
from __future__ import annotations

import base64
from pathlib import Path

import anthropic
import requests

from .schemas import CatalogAnalysis

MAX_PROPERTIES = 60

SYSTEM_PROMPT = """Você é um especialista em marketing de leilões no Brasil (imóveis,
veículos, máquinas e equipamentos). Analisa o catálogo de leilão em PDF anexo e extrai
TODOS os ativos listados, cada um já com copy de anúncio pronta para Meta Ads (Facebook/
Instagram) e público-alvo sugerido.

REGRAS CRÍTICAS DE EXTRAÇÃO:
- Extraia TODOS os ativos do catálogo — não pule nenhum, tenha o catálogo 3 ou 60 itens.
- NÃO invente ou alucine ativos que não aparecem no PDF. Use somente informações reais do
  documento. Se não houver nenhum ativo reconhecível, retorne total_properties: 0.
- O total_properties deve bater exatamente com a quantidade de ativos extraídos.
- Você pode VER as fotos incluídas no PDF — use a visão para reconhecer qual foto pertence
  a qual ativo. Ignore imagens que são claramente banners/logos/capa do leiloeiro (contêm
  branding institucional, datas do leilão em destaque, texto de agenda) — essas não são
  fotos de ativo nenhum. Em photo_page_reference, descreva em texto onde/qual é a foto
  correta daquele ativo específico (ex: "página 4, foto da fachada branca com portão de
  ferro") — isso ajuda um humano a localizar a imagem certa depois; não é uma URL.

PÚBLICO-ALVO INDIVIDUAL POR ATIVO (crítico — nunca repita o mesmo público para ativos
diferentes):
- Estude cada ativo individualmente (tipo, preço, localização, características) e defina
  o público ideal para AQUELE ativo específico.
- Perfis de referência por tipo:
  * Apartamento/casa residencial → famílias e profissionais buscando moradia na região
  * Imóvel de alto padrão → investidores e compradores de alto poder aquisitivo
  * Galpão industrial/comercial, sala/loja → empresários e investidores comerciais da região
  * Terreno/lote → construtores e investidores que querem construir
  * Fazenda/sítio/chácara → produtores e investidores rurais
  * Veículo de passeio → compradores individuais na faixa de preço compatível
  * Veículo utilitário/caminhão, máquina agrícola/industrial → empresários, produtores rurais,
    frotistas
- Em "interests", sugira de 4 a 8 interesses que existam de fato como categoria de
  segmentação no Meta Ads no Brasil (nomes genéricos e populares, ex: "Real estate",
  "Investimento imobiliário", "Automóveis", "Agronegócio") — sempre inclua algo relacionado
  a "leilão" quando fizer sentido.

COPY DO ANÚNCIO — REGRAS DETALHADAS:
- O gancho principal, quando aplicável ao ativo, é: preço ABAIXO do mercado. Se o negócio
  também oferecer pagamento facilitado/parcelado, mencione isso como um segundo atrativo
  DISTINTO — nunca misture os dois numa frase ambígua que confunda preço com parcelas.
- headline (até 40 caracteres, o elemento mais importante):
  - Única e específica por ativo — nunca repita a mesma headline em ativos diferentes.
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
- confidence: sua confiança real na extração e na recomendação para aquele ativo
  específico (baixa se a página estava confusa ou faltam dados; alta quando os dados do
  catálogo são claros).

Não decida orçamento nem data de pausa do anúncio — isso é calculado separadamente fora
da sua resposta, a partir do preço e da data do leilão que você extrair."""


def _load_pdf_bytes(pdf_source: str) -> bytes:
    if pdf_source.startswith("http://") or pdf_source.startswith("https://"):
        response = requests.get(pdf_source, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        return response.content
    return Path(pdf_source).read_bytes()


def analyze_catalog(client: anthropic.Anthropic, *, model: str, effort: str,
                     pdf_source: str, landing_page_url: str | None = None) -> CatalogAnalysis:
    """pdf_source: caminho local do PDF do catálogo, ou uma URL http(s) para baixá-lo."""
    pdf_bytes = _load_pdf_bytes(pdf_source)
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

    context = (f"URL de destino que os anúncios vão usar: {landing_page_url}"
               if landing_page_url else "Nenhuma URL de destino foi informada ainda.")

    response = client.messages.parse(
        model=model,
        max_tokens=32000,
        system=SYSTEM_PROMPT,
        output_config={"effort": effort},
        messages=[{
            "role": "user",
            "content": [
                {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_b64}},
                {"type": "text", "text": (
                    f"Analise este catálogo de leilão e extraia todos os ativos (até "
                    f"{MAX_PROPERTIES}). {context}"
                )},
            ],
        }],
        output_format=CatalogAnalysis,
    )
    analysis = response.parsed_output
    if len(analysis.properties) > MAX_PROPERTIES:
        analysis = analysis.model_copy(update={"properties": analysis.properties[:MAX_PROPERTIES]})
    return analysis
