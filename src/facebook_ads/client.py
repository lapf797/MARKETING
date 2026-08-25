"""Cliente HTTP fino para a Graph API do Facebook Marketing (Meta Ads).

Usa chamadas REST diretas (em vez do SDK oficial `facebook-business`) para manter o
comportamento transparente, fácil de testar/mockar e sem depender de uma camada extra
de abstração — cada método corresponde a uma chamada HTTP única e óbvia.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Iterable

import requests

logger = logging.getLogger(__name__)

GRAPH_BASE_URL = "https://graph.facebook.com"


class FacebookAdsError(RuntimeError):
    """Erro retornado pela Graph API do Facebook."""

    def __init__(self, message: str, *, status_code: int | None = None, payload: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}


class FacebookAdsClient:
    """Wrapper sobre a Graph API para campanhas, adsets, ads e insights."""

    def __init__(self, access_token: str, ad_account_id: str, api_version: str, timeout: int = 30):
        self._token = access_token
        self.ad_account_id = ad_account_id if ad_account_id.startswith("act_") else f"act_{ad_account_id}"
        self.base_url = f"{GRAPH_BASE_URL}/{api_version}"
        self.timeout = timeout
        self._session = requests.Session()

    def _handle_response(self, response: requests.Response) -> dict[str, Any]:
        payload = response.json() if response.content else {}
        if response.status_code >= 400:
            error = payload.get("error", {})
            raise FacebookAdsError(
                error.get("message", f"Erro HTTP {response.status_code} na Graph API"),
                status_code=response.status_code,
                payload=payload,
            )
        return payload

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        query = dict(params)
        query.setdefault("access_token", self._token)
        response = self._session.get(f"{self.base_url}/{path.lstrip('/')}", params=query, timeout=self.timeout)
        return self._handle_response(response)

    def _post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        body = dict(data)
        body.setdefault("access_token", self._token)
        response = self._session.post(f"{self.base_url}/{path.lstrip('/')}", data=body, timeout=self.timeout)
        return self._handle_response(response)

    def _delete(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        query = dict(params or {})
        query.setdefault("access_token", self._token)
        response = self._session.delete(f"{self.base_url}/{path.lstrip('/')}", params=query, timeout=self.timeout)
        return self._handle_response(response)

    def _paginate(self, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        payload = self._get(path, params)
        results.extend(payload.get("data", []))
        next_url = payload.get("paging", {}).get("next")
        while next_url:
            response = self._session.get(next_url, timeout=self.timeout)
            payload = self._handle_response(response)
            results.extend(payload.get("data", []))
            next_url = payload.get("paging", {}).get("next")
        return results

    # ---------------------------------------------------------------- leitura

    def list_campaigns(self, *, status_filter: Iterable[str] | None = None) -> list[dict]:
        params: dict[str, Any] = {
            "fields": "id,name,status,effective_status,daily_budget,lifetime_budget,objective,created_time",
            "limit": 100,
        }
        if status_filter:
            params["effective_status"] = json.dumps(list(status_filter))
        return self._paginate(f"{self.ad_account_id}/campaigns", params)

    def list_adsets(self, campaign_id: str) -> list[dict]:
        fields = ("id,name,status,effective_status,daily_budget,lifetime_budget,"
                  "targeting,bid_strategy,optimization_goal")
        return self._paginate(f"{campaign_id}/adsets", {"fields": fields, "limit": 100})

    def list_ads(self, adset_id: str) -> list[dict]:
        return self._paginate(
            f"{adset_id}/ads", {"fields": "id,name,status,effective_status,creative", "limit": 100}
        )

    def get_object(self, object_id: str, fields: list[str]) -> dict:
        """Leitura genérica de um único objeto (campanha/adset/anúncio) por ID — usada
        tanto para buscar o targeting atual de um adset quanto para conferir, depois de uma
        mudança, o que a Meta de fato salvou (ela às vezes ajusta silenciosamente o que foi
        enviado)."""
        return self._get(object_id, {"fields": ",".join(fields)})

    def get_insights(self, object_id: str, *, date_preset: str | None = None,
                      since: str | None = None, until: str | None = None,
                      time_increment: int | str = 1, level: str = "campaign",
                      breakdowns: list[str] | None = None,
                      fields: list[str] | None = None) -> list[dict]:
        default_fields = [
            "campaign_id", "campaign_name", "adset_id", "adset_name", "ad_id", "ad_name",
            "spend", "impressions", "clicks", "ctr", "cpc", "cpm", "frequency", "reach",
            "actions", "cost_per_action_type", "date_start", "date_stop",
        ]
        params: dict[str, Any] = {
            "level": level,
            "fields": ",".join(fields or default_fields),
            "time_increment": time_increment,
            "limit": 500,
        }
        if breakdowns:
            params["breakdowns"] = ",".join(breakdowns)
        if date_preset:
            params["date_preset"] = date_preset
        elif since and until:
            params["time_range"] = json.dumps({"since": since, "until": until})
        return self._paginate(f"{object_id}/insights", params)

    # ---------------------------------------------------------------- escrita

    def update_campaign_budget(self, campaign_id: str, *, daily_budget_cents: int | None = None,
                                lifetime_budget_cents: int | None = None) -> dict:
        data: dict[str, Any] = {}
        if daily_budget_cents is not None:
            data["daily_budget"] = str(daily_budget_cents)
        if lifetime_budget_cents is not None:
            data["lifetime_budget"] = str(lifetime_budget_cents)
        return self._post(campaign_id, data)

    def update_adset_budget(self, adset_id: str, *, daily_budget_cents: int | None = None,
                             lifetime_budget_cents: int | None = None) -> dict:
        data: dict[str, Any] = {}
        if daily_budget_cents is not None:
            data["daily_budget"] = str(daily_budget_cents)
        if lifetime_budget_cents is not None:
            data["lifetime_budget"] = str(lifetime_budget_cents)
        return self._post(adset_id, data)

    def set_status(self, object_id: str, status: str) -> dict:
        """status: "ACTIVE" ou "PAUSED"."""
        return self._post(object_id, {"status": status})

    def update_adset_targeting(self, adset_id: str, targeting: dict) -> dict:
        return self._post(adset_id, {"targeting": json.dumps(targeting)})

    def create_campaign(self, *, name: str, objective: str, status: str = "PAUSED",
                         special_ad_categories: list[str] | None = None) -> dict:
        data = {
            "name": name,
            "objective": objective,
            "status": status,
            "special_ad_categories": json.dumps(special_ad_categories or []),
        }
        return self._post(f"{self.ad_account_id}/campaigns", data)

    def create_adset(self, *, campaign_id: str, name: str, daily_budget_cents: int,
                      targeting: dict, optimization_goal: str, billing_event: str,
                      bid_strategy: str = "LOWEST_COST_WITHOUT_CAP", status: str = "PAUSED",
                      promoted_object: dict | None = None, end_time: str | None = None) -> dict:
        data: dict[str, Any] = {
            "campaign_id": campaign_id,
            "name": name,
            "daily_budget": str(daily_budget_cents),
            "targeting": json.dumps(targeting),
            "optimization_goal": optimization_goal,
            "billing_event": billing_event,
            "bid_strategy": bid_strategy,
            "status": status,
        }
        if promoted_object:
            data["promoted_object"] = json.dumps(promoted_object)
        if end_time:
            data["end_time"] = end_time
        return self._post(f"{self.ad_account_id}/adsets", data)

    def upload_ad_image(self, image_bytes: bytes, *, filename: str = "creative.jpg") -> dict:
        """Envia uma imagem para a biblioteca de imagens da conta (POST /act_<id>/adimages,
        multipart) e devolve o hash que a Meta atribuiu a ela — usado depois em
        create_ad_creative(image_hash=...) no lugar de uma picture_url pública, para anunciar
        o criativo já composto (src/creative/overlay.py) em vez da foto crua do ativo."""
        url = f"{self.base_url}/{self.ad_account_id}/adimages"
        files = {filename: (filename, image_bytes, "image/jpeg")}
        data = {"access_token": self._token}
        response = self._session.post(url, data=data, files=files, timeout=self.timeout)
        payload = self._handle_response(response)
        image_data = payload.get("images", {}).get(filename, {})
        if not image_data.get("hash"):
            raise FacebookAdsError("Upload de imagem não retornou hash", payload=payload)
        return {"hash": image_data["hash"], "url": image_data.get("url")}

    def create_ad_creative(self, *, name: str, page_id: str, link: str, message: str,
                            headline: str, description: str, picture_url: str | None = None,
                            image_hash: str | None = None) -> dict:
        link_data: dict[str, Any] = {
            "message": message,
            "link": link,
            "name": headline,
            "description": description,
            "call_to_action": {"type": "LEARN_MORE", "value": {"link": link}},
        }
        if image_hash:
            link_data["image_hash"] = image_hash
        elif picture_url:
            link_data["picture"] = picture_url
        data = {
            "name": name,
            "object_story_spec": json.dumps({"link_data": link_data, "page_id": page_id}),
        }
        return self._post(f"{self.ad_account_id}/adcreatives", data)

    def create_ad(self, *, name: str, adset_id: str, creative_id: str, status: str = "PAUSED") -> dict:
        data = {
            "name": name,
            "adset_id": adset_id,
            "creative": json.dumps({"creative_id": creative_id}),
            "status": status,
        }
        return self._post(f"{self.ad_account_id}/ads", data)

    # ------------------------------------------------------------- segmentação

    def search(self, search_type: str, query: str, *, extra_params: dict[str, Any] | None = None,
               limit: int = 10) -> list[dict]:
        """Busca genérica no endpoint /search da Graph API — usada para resolver nomes
        livres (interesses, localizações) em IDs reais que a Meta aceita em targeting."""
        params: dict[str, Any] = {"type": search_type, "q": query, "limit": limit}
        params.update(extra_params or {})
        payload = self._get("search", params)
        return payload.get("data", [])

    # -------------------------------------------------------- públicos personalizados

    def create_custom_audience(self, *, name: str, description: str = "", subtype: str = "CUSTOM",
                                customer_file_source: str = "USER_PROVIDED_ONLY") -> dict:
        data: dict[str, Any] = {
            "name": name, "subtype": subtype, "customer_file_source": customer_file_source,
        }
        if description:
            data["description"] = description
        return self._post(f"{self.ad_account_id}/customaudiences", data)

    def add_users_to_custom_audience(self, audience_id: str, *, schema: list[str],
                                      hashed_rows: list[list[str]]) -> dict:
        """schema/hashed_rows seguem o formato da Custom Audience API: schema é a lista de
        tipos de identificador em cada linha (ex: ["EMAIL"] ou ["EMAIL", "PHONE"]), e cada
        linha de hashed_rows já deve vir com os valores normalizados e hasheados em SHA-256
        (ver src/facebook_ads/audiences.py) — a Graph API não aceita dado em texto puro."""
        payload = {"schema": schema, "data": hashed_rows}
        return self._post(f"{audience_id}/users", {"payload": json.dumps(payload)})

    def create_lookalike_audience(self, *, name: str, origin_audience_id: str,
                                   country: str = "BR", ratio: float = 0.05) -> dict:
        data = {
            "name": name,
            "subtype": "LOOKALIKE",
            "origin_audience_id": origin_audience_id,
            "lookalike_spec": json.dumps({"type": "similarity", "ratio": ratio, "country": country}),
        }
        return self._post(f"{self.ad_account_id}/customaudiences", data)

    def list_custom_audiences(self) -> list[dict]:
        fields = "id,name,subtype,approximate_count_lower_bound,approximate_count_upper_bound,operation_status"
        return self._paginate(f"{self.ad_account_id}/customaudiences", {"fields": fields, "limit": 100})

    def delete_audience(self, audience_id: str) -> dict:
        return self._delete(audience_id)
