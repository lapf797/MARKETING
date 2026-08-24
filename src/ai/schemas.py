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
