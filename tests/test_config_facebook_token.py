"""Testes de src.config._resolve_facebook_access_token: decide entre o token estático
(FB_ACCESS_TOKEN) e o dinâmico (login com Facebook via Firebase, FB_TOKEN_ENDPOINT_URL +
FB_TOKEN_API_KEY) sem quebrar quem ainda usa só o token estático."""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import _resolve_facebook_access_token

ENV_KEYS = ("FB_ACCESS_TOKEN", "FB_TOKEN_ENDPOINT_URL", "FB_TOKEN_API_KEY")


def _clear_env(monkeypatch):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_falls_back_to_static_token_when_dynamic_not_configured(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("FB_ACCESS_TOKEN", "token-estatico-123")
    assert _resolve_facebook_access_token() == "token-estatico-123"


def test_uses_dynamic_token_when_endpoint_and_key_configured(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("FB_TOKEN_ENDPOINT_URL", "https://exemplo.cloudfunctions.net/get_token")
    monkeypatch.setenv("FB_TOKEN_API_KEY", "chaveapi")
    with patch("src.facebook_ads.dynamic_token.fetch_access_token", return_value="token-dinamico-456") as mock_fetch:
        result = _resolve_facebook_access_token()
    assert result == "token-dinamico-456"
    mock_fetch.assert_called_once_with("https://exemplo.cloudfunctions.net/get_token", "chaveapi")


def test_dynamic_config_does_not_require_static_token_to_be_set(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("FB_TOKEN_ENDPOINT_URL", "https://exemplo.cloudfunctions.net/get_token")
    monkeypatch.setenv("FB_TOKEN_API_KEY", "chaveapi")
    # FB_ACCESS_TOKEN propositalmente ausente
    with patch("src.facebook_ads.dynamic_token.fetch_access_token", return_value="token-dinamico"):
        assert _resolve_facebook_access_token() == "token-dinamico"


def test_partial_dynamic_config_falls_back_to_static_token(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("FB_TOKEN_ENDPOINT_URL", "https://exemplo.cloudfunctions.net/get_token")
    # sem FB_TOKEN_API_KEY — configuração incompleta, não deve tentar o caminho dinâmico
    monkeypatch.setenv("FB_ACCESS_TOKEN", "token-estatico-fallback")
    assert _resolve_facebook_access_token() == "token-estatico-fallback"


def test_raises_when_nothing_is_configured(monkeypatch):
    _clear_env(monkeypatch)
    try:
        _resolve_facebook_access_token()
        assert False, "deveria ter levantado RuntimeError"
    except RuntimeError as exc:
        assert "FB_ACCESS_TOKEN" in str(exc)
