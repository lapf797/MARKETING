"""Constrói o novo `targeting` do adset a partir de um PlacementOptimizationPlan — pura
transformação de dados, sem chamar a Graph API, para ficar fácil de testar isoladamente
(a parte que realmente importa acertar: nunca mexe em orçamento, nunca estreita a idade
abaixo do mínimo seguro, nunca perde o que já estava em geo_locations/interesses)."""
from __future__ import annotations

from src.ai.schemas import PlacementOptimizationPlan

FACEBOOK_POSITIONS = {
    "feed": "feed", "facebook_reels": "facebook_reels", "story": "story",
    "facebook_stories": "story", "instream_video": "instream_video",
    "video_feeds": "video_feeds", "marketplace": "marketplace", "search": "search",
    "right_hand_column": "right_hand_column", "profile_feed": "profile_feed",
}
INSTAGRAM_POSITIONS = {
    "feed": "stream", "stream": "stream", "story": "story", "instagram_stories": "story",
    "explore": "explore", "explore_home": "explore_home", "instagram_reels": "reels",
    "reels": "reels", "profile_feed": "profile_feed", "ig_search": "ig_search",
    "instagram_search": "ig_search",
}
_GENDER_CODES = {"male": [1], "female": [2], "all": [0]}
_AGE_FLOOR = 18
_AGE_CEILING = 65
_MIN_AGE_SPAN = 15


def _clamp_age(age_min: int, age_max: int) -> tuple[int, int]:
    # PlacementOptimizationPlan já restringe age_min/age_max a [18, 65] via Pydantic —
    # o clamp de piso/teto aqui é defesa em profundidade, caso esta função seja chamada
    # com um targeting vindo de outro lugar. O que este clamp realmente garante na
    # prática é a amplitude mínima de 15 anos, abaixo.
    age_min = max(_AGE_FLOOR, min(age_min, _AGE_CEILING))
    age_max = max(_AGE_FLOOR, min(age_max, _AGE_CEILING))
    if age_min > age_max:
        age_min, age_max = age_max, age_min
    if age_max - age_min < _MIN_AGE_SPAN:
        age_max = min(_AGE_CEILING, age_min + _MIN_AGE_SPAN)
        age_min = max(_AGE_FLOOR, age_max - _MIN_AGE_SPAN)
    return age_min, age_max


def _apply_age_gender(targeting: dict, plan: PlacementOptimizationPlan) -> dict:
    age_min, age_max = _clamp_age(plan.age_min, plan.age_max)
    targeting["age_min"] = age_min
    targeting["age_max"] = age_max
    targeting["genders"] = _GENDER_CODES[plan.gender_targeting]
    # A Meta exige declarar isso explicitamente para a segmentação manual não ser
    # sobrescrita pelo público automático "Advantage+".
    targeting["targeting_automation"] = {"advantage_audience": 0}
    return targeting


def build_placement_targeting(current_targeting: dict, plan: PlacementOptimizationPlan) -> dict:
    """Targeting completo (posicionamentos + idade/gênero), preservando geo_locations,
    interesses e públicos personalizados já existentes no adset."""
    targeting = dict(current_targeting)

    platforms = list(dict.fromkeys(p for p in plan.platforms_to_keep))
    if platforms:
        targeting["publisher_platforms"] = platforms
        fb_positions: list[str] = []
        ig_positions: list[str] = []
        for item in plan.placements_to_keep:
            placement = item.placement.lower()
            if item.platform == "facebook" and placement in FACEBOOK_POSITIONS:
                mapped = FACEBOOK_POSITIONS[placement]
                if mapped not in fb_positions:
                    fb_positions.append(mapped)
            elif item.platform == "instagram" and placement in INSTAGRAM_POSITIONS:
                mapped = INSTAGRAM_POSITIONS[placement]
                if mapped not in ig_positions:
                    ig_positions.append(mapped)
        if "facebook" in platforms and fb_positions:
            targeting["facebook_positions"] = fb_positions
        elif "facebook" not in platforms:
            targeting.pop("facebook_positions", None)
        if "instagram" in platforms and ig_positions:
            targeting["instagram_positions"] = ig_positions
        elif "instagram" not in platforms:
            targeting.pop("instagram_positions", None)

    return _apply_age_gender(targeting, plan)


def build_age_gender_only_targeting(current_targeting: dict, plan: PlacementOptimizationPlan) -> dict:
    """Fallback quando a Meta recusa o recorte de posicionamentos — aplica só idade/gênero,
    sem tocar em publisher_platforms/facebook_positions/instagram_positions."""
    return _apply_age_gender(dict(current_targeting), plan)
