"""Testes de src/facebook_ads/dynamic_token.py — busca do token do Facebook no endpoint
get_token do Firebase (login com Facebook via aba Configurações), sem chamada de rede real
(requests.get é mockado)."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.facebook_ads.dynamic_token import DynamicTokenError, fetch_access_token


def _mock_response(status_code: int, json_payload: dict | None = None, text: str = "") -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = status_code < 400
    response.json.return_value = json_payload or {}
    response.text = text
    return response


@patch("src.facebook_ads.dynamic_token.requests.get")
def test_fetch_access_token_returns_token_on_success(mock_get):
    mock_get.return_value = _mock_response(200, {"access_token": "EAAtoken123"})
    token = fetch_access_token("https://exemplo.cloudfunctions.net/get_token", "chaveapi")
    assert token == "EAAtoken123"
    call = mock_get.call_args
    assert call.kwargs["headers"]["Authorization"] == "Bearer chaveapi"


@patch("src.facebook_ads.dynamic_token.requests.get")
def test_fetch_access_token_raises_friendly_error_on_401(mock_get):
    mock_get.return_value = _mock_response(401)
    try:
        fetch_access_token("https://exemplo.cloudfunctions.net/get_token", "chave-errada")
        assert False, "deveria ter levantado DynamicTokenError"
    except DynamicTokenError as exc:
        assert "chave" in str(exc).lower()


@patch("src.facebook_ads.dynamic_token.requests.get")
def test_fetch_access_token_raises_friendly_error_on_404_not_connected_yet(mock_get):
    mock_get.return_value = _mock_response(404)
    try:
        fetch_access_token("https://exemplo.cloudfunctions.net/get_token", "chaveapi")
        assert False, "deveria ter levantado DynamicTokenError"
    except DynamicTokenError as exc:
        assert "Configurações" in str(exc)


@patch("src.facebook_ads.dynamic_token.requests.get")
def test_fetch_access_token_raises_on_missing_access_token_field(mock_get):
    mock_get.return_value = _mock_response(200, {})
    try:
        fetch_access_token("https://exemplo.cloudfunctions.net/get_token", "chaveapi")
        assert False, "deveria ter levantado DynamicTokenError"
    except DynamicTokenError:
        pass


@patch("src.facebook_ads.dynamic_token.requests.get")
def test_fetch_access_token_raises_on_network_error(mock_get):
    import requests
    mock_get.side_effect = requests.ConnectionError("timeout")
    try:
        fetch_access_token("https://exemplo.cloudfunctions.net/get_token", "chaveapi")
        assert False, "deveria ter levantado DynamicTokenError"
    except DynamicTokenError as exc:
        assert "não foi possível contatar" in str(exc)
