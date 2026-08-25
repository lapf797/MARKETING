"""Testes da construção de targeting a partir do plano de otimização de posicionamento —
a parte crítica é nunca deixar a idade estreitar abaixo do mínimo seguro nem tocar em
orçamento/geo/interesses já existentes no adset."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ai.schemas import PlacementOptimizationPlan, PlatformPlacement
from src.facebook_ads.placement_targeting import (
    build_age_gender_only_targeting,
    build_placement_targeting,
)


def make_plan(**overrides):
    defaults = dict(
        should_apply=True, age_min=30, age_max=50, gender_targeting="all",
        platforms_to_keep=["facebook", "instagram"],
        placements_to_keep=[
            PlatformPlacement(platform="facebook", placement="feed"),
            PlatformPlacement(platform="instagram", placement="reels"),
        ],
        explanation="teste", confidence=0.8,
    )
    defaults.update(overrides)
    return PlacementOptimizationPlan(**defaults)


def test_preserves_geo_and_interests_untouched():
    current = {
        "geo_locations": {"cities": [{"key": "1", "radius": 50}]},
        "flexible_spec": [{"interests": [{"id": "1", "name": "x"}]}],
        "age_min": 18, "age_max": 65, "genders": [0],
    }
    result = build_placement_targeting(current, make_plan())
    assert result["geo_locations"] == current["geo_locations"]
    assert result["flexible_spec"] == current["flexible_spec"]


def test_maps_platforms_and_positions():
    result = build_placement_targeting({"age_min": 18, "age_max": 65, "genders": [0]}, make_plan())
    assert result["publisher_platforms"] == ["facebook", "instagram"]
    assert result["facebook_positions"] == ["feed"]
    assert result["instagram_positions"] == ["reels"]


def test_unmapped_placement_name_is_dropped_silently():
    plan = make_plan(placements_to_keep=[PlatformPlacement(platform="facebook", placement="nome_desconhecido")])
    result = build_placement_targeting({"age_min": 18, "age_max": 65, "genders": [0]}, plan)
    assert "facebook_positions" not in result  # nada de valido pra manter


def test_age_span_widened_to_minimum_15_years():
    plan = make_plan(age_min=30, age_max=35)  # so 5 anos de amplitude
    result = build_placement_targeting({"age_min": 18, "age_max": 65, "genders": [0]}, plan)
    assert result["age_max"] - result["age_min"] >= 15


def test_gender_mapping():
    for gender, expected in [("male", [1]), ("female", [2]), ("all", [0])]:
        plan = make_plan(gender_targeting=gender)
        result = build_placement_targeting({"age_min": 18, "age_max": 65, "genders": [0]}, plan)
        assert result["genders"] == expected


def test_advantage_audience_disabled():
    result = build_placement_targeting({"age_min": 18, "age_max": 65, "genders": [0]}, make_plan())
    assert result["targeting_automation"] == {"advantage_audience": 0}


def test_fallback_never_touches_placements():
    current = {"age_min": 18, "age_max": 65, "genders": [0],
               "publisher_platforms": ["facebook"], "facebook_positions": ["feed"]}
    result = build_age_gender_only_targeting(current, make_plan(age_min=25, age_max=45))
    assert result["publisher_platforms"] == ["facebook"]
    assert result["facebook_positions"] == ["feed"]
    assert result["age_min"] == 25
    assert result["age_max"] == 45


def test_no_platforms_to_keep_leaves_existing_publisher_platforms_untouched():
    current = {"age_min": 18, "age_max": 65, "genders": [0], "publisher_platforms": ["facebook", "instagram"]}
    plan = make_plan(platforms_to_keep=[], placements_to_keep=[])
    result = build_placement_targeting(current, plan)
    assert result["publisher_platforms"] == ["facebook", "instagram"]
