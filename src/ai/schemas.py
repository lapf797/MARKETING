"""Modelos Pydantic para as saídas estruturadas da IA (Claude) — garantem que a resposta
do modelo sempre venha em um formato que o resto do sistema consegue processar com segurança."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AudienceRecommendation(BaseModel):
    reasoning: str = Field(description="Raciocínio por trás da recomendação, em português, citando os dados usados.")
    age_min: int = Field(ge=13, le=65)
    age_max: int = Field(ge=13, le=65)
    gender_targeting: Literal["male", "female", "all"]
    interests: list[str] = Field(description="Nomes de interesses/comportamentos sugeridos para segmentação no Meta Ads.")
    geo_locations: list[str] = Field(description="Cidades, regiões ou área geográfica sugerida.")
    placements: list[str] = Field(description="Posicionamentos recomendados (feed, stories, reels, audience_network etc.).")
    suggested_daily_budget_cents: int = Field(ge=0)
    confidence: float = Field(ge=0.0, le=1.0)
    similar_past_campaigns: list[str] = Field(default_factory=list)


class OptimizationAction(BaseModel):
    action_type: Literal[
        "increase_budget", "decrease_budget", "pause", "resume",
        "flag_for_audience_refresh", "no_action",
    ]
    target_type: Literal["campaign", "adset", "ad"]
    target_id: str
    target_name: str
    current_value: str | None = None
    proposed_value: str | None = None
    reasoning: str
    confidence: float = Field(ge=0.0, le=1.0)


class OptimizationPlan(BaseModel):
    summary: str
    actions: list[OptimizationAction]


class AssetListing(BaseModel):
    """Dados de um lote de leilão extraídos de uma página web pela IA. Campos de
    conteúdo são opcionais porque a extração pode falhar parcialmente ou totalmente
    (página fora do ar, exige login, não é um lote de leilão etc.) — sempre confira
    "success" antes de usar os demais campos."""
    source_url: str
    success: bool = Field(description="False se a página não pôde ser acessada ou não continha um lote de leilão.")
    error_message: str | None = Field(default=None, description="Motivo da falha, preenchido apenas quando success=false.")
    title: str | None = None
    category: str | None = Field(default=None, description='Categoria curta e genérica, ex: "Imóveis", "Veículos", "Máquinas e Equipamentos".')
    description: str | None = Field(default=None, description="Descrição do lote em texto corrido, como aparece na página.")
    location: str | None = Field(default=None, description="Cidade/UF ou endereço do ativo.")
    estimated_value: float | None = Field(default=None, description="Valor de avaliação/mercado do ativo, se informado.")
    starting_bid: float | None = Field(default=None, description="Lance mínimo/inicial do leilão, se informado.")
    auction_end_at: str | None = Field(default=None, description="Data/hora de encerramento do leilão, como texto, se informado.")
    lot_number: str | None = None
    key_details: list[str] = Field(default_factory=list, description="Atributos curtos e objetivos úteis para segmentação (ex: '3 quartos', '90m²', 'ano 2021').")
    extraction_notes: str | None = Field(default=None, description="Observações sobre a extração: dados ausentes, ambiguidades etc.")


class PropertyAdListing(BaseModel):
    """Um ativo extraído de um catálogo de leilão em PDF (geralmente dezenas de lotes de
    uma vez), já com copy de anúncio pronta e público-alvo sugerido — grava-se como
    rascunho (src/safety/draft_log.py) para revisão humana antes de virar campanha real."""
    lot_number: str | None = None
    title: str
    category: str = Field(description='Categoria curta, ex: "Imóveis", "Veículos", "Máquinas e Equipamentos".')
    city: str | None = None
    state: str | None = Field(default=None, description="UF (sigla de 2 letras), quando o ativo for no Brasil.")
    price_text: str | None = Field(default=None, description="Preço/lance como aparece no catálogo (texto livre).")
    price_value: float | None = Field(default=None, description="Valor numérico do preço/lance, quando extraível do texto.")
    description: str = Field(description="Descrição do ativo, resumida a partir do catálogo.")
    auction_date: str | None = Field(default=None, description="Data do leilão (YYYY-MM-DD), se encontrada no catálogo.")
    photo_page_reference: str | None = Field(default=None, description="Referência textual de qual foto no PDF pertence a este ativo (ex: 'página 4, foto do apartamento com fachada branca') — usada apenas para o humano localizar a foto certa; não é uma URL.")

    age_min: int = Field(ge=13, le=65)
    age_max: int = Field(ge=13, le=65)
    gender_targeting: Literal["male", "female", "all"]
    interests: list[str] = Field(description="Interesses sugeridos para segmentação no Meta Ads (nomes; resolvidos para IDs reais na criação da campanha).")
    audience_reasoning: str

    headline: str = Field(description="Manchete do anúncio, até 40 caracteres, gancho específico deste ativo.")
    primary_text: str = Field(description="Texto principal do anúncio, até 125 caracteres.")
    ad_description: str = Field(description="Descrição do anúncio (link description), até 200 caracteres.")

    confidence: float = Field(ge=0.0, le=1.0)


class SingleAdCopy(BaseModel):
    """Copy de anúncio para um único ativo avulso (scripts/suggest_audience.py) — mesma
    função da copy já embutida em PropertyAdListing, mas gerada isoladamente porque o
    fluxo avulso não passa pelo catálogo em PDF."""
    headline: str = Field(description="Manchete do anúncio, até 40 caracteres, gancho específico deste ativo.")
    primary_text: str = Field(description="Texto principal do anúncio, até 125 caracteres.")
    ad_description: str = Field(description="Descrição do anúncio (link description), até 200 caracteres.")
    confidence: float = Field(ge=0.0, le=1.0)


class CatalogAnalysis(BaseModel):
    total_properties: int
    summary: str
    properties: list[PropertyAdListing]


class PlatformPlacement(BaseModel):
    platform: Literal["facebook", "instagram", "audience_network", "messenger"]
    placement: str = Field(description="Nome do posicionamento como aparece nos dados de insights (ex: 'feed', 'story', 'reels').")


class PlacementOptimizationPlan(BaseModel):
    """Ajuste de posicionamento e demografia com o MESMO orçamento — nunca propõe mudança
    de valor gasto, só concentra a verba onde/para quem já provou clique mais barato. Ver
    src/ai/placement_optimizer.py."""
    should_apply: bool = Field(description="False quando não há volume suficiente ou nenhum ajuste seguro a fazer — nesse caso, explique em reason_if_not_applying.")
    reason_if_not_applying: str | None = None
    platforms_to_keep: list[Literal["facebook", "instagram", "audience_network", "messenger"]] = Field(default_factory=list)
    placements_to_keep: list[PlatformPlacement] = Field(default_factory=list)
    age_min: int = Field(ge=18, le=65, default=18)
    age_max: int = Field(ge=18, le=65, default=65)
    gender_targeting: Literal["male", "female", "all"] = "all"
    expected_ctr: str | None = Field(default=None, description='Estimativa de CTR após o ajuste, ex: "1,8%".')
    expected_cpc: str | None = Field(default=None, description='Estimativa de CPC após o ajuste, ex: "R$ 0,45".')
    expected_clicks_change: str | None = Field(default=None, description='Estimativa de ganho em cliques com a mesma verba, ex: "+30%".')
    explanation: str = Field(description="Explicação do ajuste em 2-3 frases, linguagem simples.")
    creative_suggestion: str | None = Field(default=None, description="Sugestão de texto/chamada para elevar o CTR — não aplicada automaticamente.")
    confidence: float = Field(ge=0.0, le=1.0)
