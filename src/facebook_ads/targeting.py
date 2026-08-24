"""Resolve segmentação em texto livre (interesses, cidade/UF) para os IDs reais que a
Graph API exige em `targeting` — sem isso, uma campanha criada por código nunca consegue
aplicar interesses nem geolocalização de verdade, só o nome que a IA sugeriu."""
from __future__ import annotations

import unicodedata

from .client import FacebookAdsClient

_CAPITALS_BR = {
    "rio branco", "maceio", "macapa", "manaus", "salvador", "fortaleza", "brasilia",
    "vitoria", "goiania", "sao luis", "cuiaba", "campo grande", "belo horizonte", "belem",
    "joao pessoa", "curitiba", "recife", "teresina", "rio de janeiro", "natal",
    "porto alegre", "porto velho", "boa vista", "florianopolis", "sao paulo", "aracaju",
    "palmas",
}

_UF_NAMES = {
    "AC": "acre", "AL": "alagoas", "AP": "amapa", "AM": "amazonas", "BA": "bahia",
    "CE": "ceara", "DF": "distrito federal", "ES": "espirito santo", "GO": "goias",
    "MA": "maranhao", "MT": "mato grosso", "MS": "mato grosso do sul", "MG": "minas gerais",
    "PA": "para", "PB": "paraiba", "PR": "parana", "PE": "pernambuco", "PI": "piaui",
    "RJ": "rio de janeiro", "RN": "rio grande do norte", "RS": "rio grande do sul",
    "RO": "rondonia", "RR": "roraima", "SC": "santa catarina", "SP": "sao paulo",
    "SE": "sergipe", "TO": "tocantins",
}


def _normalize(name: str) -> str:
    decomposed = unicodedata.normalize("NFD", name or "")
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return stripped.strip().lower()


def resolve_geo_locations(client: FacebookAdsClient, *, city: str | None, state: str | None) -> dict:
    """Resolve cidade/UF em um `geo_locations` real da Meta: cidade específica com raio
    (50km em capitais, 80km nas demais — cidades menores têm menos densidade de usuários
    por km², precisam de raio maior para alcance suficiente), com fallback para o estado
    inteiro e depois para o Brasil inteiro se nada for encontrado."""
    if city:
        try:
            results = client.search(
                "adgeolocation", city,
                extra_params={"location_types": '["city"]', "country_code": "BR"}, limit=20,
            )
        except Exception:
            results = []
        target = _normalize(city)
        exact = [r for r in results if _normalize(r.get("name", "")) == target]
        match = None
        if state and exact:
            state_name = _normalize(_UF_NAMES.get(state.upper(), state))
            match = next((r for r in exact if _normalize(r.get("region", "")) == state_name), None)
        match = match or (exact[0] if exact else None) or (results[0] if results else None)
        if match:
            is_capital = _normalize(match.get("name", "")) in _CAPITALS_BR
            radius = 50 if is_capital else 80
            return {"cities": [{"key": str(match["key"]), "radius": radius, "distance_unit": "kilometer"}]}

    if state:
        try:
            results = client.search(
                "adgeolocation", state,
                extra_params={"location_types": '["region"]', "country_code": "BR"}, limit=10,
            )
        except Exception:
            results = []
        if results:
            return {"regions": [{"key": str(results[0]["key"])}]}

    return {"countries": ["BR"]}


def resolve_geo_locations_free_text(client: FacebookAdsClient, texts: list[str], *,
                                     max_cities: int = 5) -> dict:
    """Como resolve_geo_locations, mas para entradas de texto livre (ex: "São Paulo, SP
    (raio 25km)", como a IA às vezes descreve uma localização) em vez de cidade/UF já
    separados — usada pela recomendação avulsa de público (scripts/suggest_audience.py).
    Busca cada texto como cidade; junta os IDs encontrados em uma lista de cidades com
    raio padrão (50km); sem nenhum resultado, cai para o Brasil inteiro."""
    cities: list[dict] = []
    seen_keys: set[str] = set()
    for text in (texts or [])[:max_cities]:
        if not text:
            continue
        try:
            results = client.search(
                "adgeolocation", text,
                extra_params={"location_types": '["city"]', "country_code": "BR"}, limit=1,
            )
        except Exception:
            continue
        if not results:
            continue
        key = str(results[0]["key"])
        if key not in seen_keys:
            seen_keys.add(key)
            is_capital = _normalize(results[0].get("name", "")) in _CAPITALS_BR
            cities.append({"key": key, "radius": 50 if is_capital else 80, "distance_unit": "kilometer"})
    if cities:
        return {"cities": cities}
    return {"countries": ["BR"]}


def resolve_interests(client: FacebookAdsClient, terms: list[str], *, max_terms: int = 12) -> list[dict]:
    """Resolve nomes de interesse sugeridos pela IA nos IDs reais que a Meta aceita em
    targeting.flexible_spec — a Graph API só aceita interesse por ID, nunca por nome."""
    found: list[dict] = []
    seen_ids: set[str] = set()
    for term in (terms or [])[:max_terms]:
        if not term:
            continue
        try:
            results = client.search("adinterest", term, limit=1)
        except Exception:
            continue
        if not results:
            continue
        hit = results[0]
        interest_id = str(hit.get("id", ""))
        if interest_id and interest_id not in seen_ids:
            seen_ids.add(interest_id)
            found.append({"id": interest_id, "name": hit.get("name", term)})
    return found
