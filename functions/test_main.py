"""Testes das partes puras/roteáveis do login com Facebook (main.py) — assinatura e
verificação do "state" anti-CSRF, dedução da redirect_uri a partir do request, e os
caminhos de erro que não dependem de credenciais reais da Meta nem do Firestore (que só o
Admin SDK, rodando de verdade no Firebase, consegue tocar). O caminho feliz completo (troca
de code por token, gravação no Firestore) só é verificável de ponta a ponta no próprio
Firebase — ver docs/SETUP_FIREBASE_OAUTH.md."""
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

os.environ.setdefault("FIREBASE_CONFIG", "{}")
os.environ.setdefault("META_APP_ID", "123456")
os.environ.setdefault("META_APP_SECRET", "segredoapp")
os.environ.setdefault("TOKEN_API_KEY", "chaveapi")

import main  # noqa: E402
from flask import Flask, request  # noqa: E402
from urllib.parse import parse_qs, urlparse  # noqa: E402

app = Flask(__name__)
BASE = "https://southamerica-east1-projeto-teste.cloudfunctions.net"


def test_sign_and_verify_state_roundtrip():
    state = main._sign_state("segredo123")
    assert main._verify_state(state, "segredo123")


def test_verify_state_rejects_wrong_secret():
    state = main._sign_state("segredo123")
    assert not main._verify_state(state, "outro-segredo")


def test_verify_state_rejects_expired_timestamp():
    old_state = f"{int(time.time()) - main.STATE_TTL_SECONDS - 100}.abcnaoimporta"
    assert not main._verify_state(old_state, "segredo123")


def test_verify_state_rejects_tampered_signature():
    state = main._sign_state("segredo123")
    timestamp, _ = state.split(".", 1)
    tampered = f"{timestamp}.{'f' * 64}"
    assert not main._verify_state(tampered, "segredo123")


def test_verify_state_rejects_malformed_string():
    assert not main._verify_state("sem-ponto-nenhum", "segredo123")
    assert not main._verify_state("", "segredo123")


def test_oauth_callback_url_derived_from_connect_facebook_request():
    with app.test_request_context(f"{BASE}/connect_facebook"):
        assert main._oauth_callback_url(request) == f"{BASE}/oauth_callback"


def test_oauth_callback_url_derived_from_oauth_callback_request_itself():
    with app.test_request_context(f"{BASE}/oauth_callback?code=abc&state=xyz"):
        assert main._oauth_callback_url(request) == f"{BASE}/oauth_callback"


def test_connect_facebook_redirects_to_facebook_oauth_dialog():
    with app.test_request_context(f"{BASE}/connect_facebook"):
        response = main.connect_facebook(request)
        assert response.status_code == 302
        location = response.headers["Location"]
        assert location.startswith("https://www.facebook.com/")
        query = parse_qs(urlparse(location).query)
        assert query["client_id"] == ["123456"]
        assert query["redirect_uri"] == [f"{BASE}/oauth_callback"]
        assert query["response_type"] == ["code"]


def test_connect_facebook_includes_required_ads_scopes():
    with app.test_request_context(f"{BASE}/connect_facebook"):
        response = main.connect_facebook(request)
        location = response.headers["Location"]
        for scope in ("ads_management", "ads_read", "business_management"):
            assert scope in location


def test_oauth_callback_shows_friendly_message_when_user_cancels():
    with app.test_request_context(f"{BASE}/oauth_callback?error=access_denied&error_description=cancelado+pelo+usuario"):
        response = main.oauth_callback(request)
        assert response.status_code == 200
        assert "cancelado" in response.get_data(as_text=True).lower()


def test_oauth_callback_escapes_error_description_to_avoid_reflected_xss():
    payload = "<script>alert(1)</script>"
    with app.test_request_context(f"{BASE}/oauth_callback", query_string={"error_description": payload}):
        response = main.oauth_callback(request)
    body = response.get_data(as_text=True)
    assert "<script>" not in body
    assert "&lt;script&gt;" in body


def test_oauth_callback_rejects_missing_state():
    with app.test_request_context(f"{BASE}/oauth_callback?code=abc"):
        response = main.oauth_callback(request)
        assert response.status_code == 200
        assert "inválido" in response.get_data(as_text=True) or "expirado" in response.get_data(as_text=True)


def test_oauth_callback_rejects_invalid_state():
    with app.test_request_context(f"{BASE}/oauth_callback?code=abc&state=forjado.0000"):
        response = main.oauth_callback(request)
        assert response.status_code == 200
        assert "inválido" in response.get_data(as_text=True) or "expirado" in response.get_data(as_text=True)


def test_get_token_rejects_missing_authorization_header():
    with app.test_request_context(f"{BASE}/get_token"):
        response = main.get_token(request)
        assert response.status_code == 401


def test_get_token_rejects_wrong_api_key():
    with app.test_request_context(f"{BASE}/get_token", headers={"Authorization": "Bearer chave-errada"}):
        response = main.get_token(request)
        assert response.status_code == 401


def test_get_token_rejects_malformed_authorization_header():
    with app.test_request_context(f"{BASE}/get_token", headers={"Authorization": "chaveapi"}):
        response = main.get_token(request)
        assert response.status_code == 401


def _fake_firestore(*, doc_exists: bool):
    fake_doc = MagicMock()
    fake_doc.exists = doc_exists
    fake_client = MagicMock()
    fake_client.collection.return_value.document.return_value.get.return_value = fake_doc
    return fake_client


def test_connection_status_true_when_token_document_exists():
    with app.test_request_context(f"{BASE}/connection_status"):
        with patch("main.firestore.client", return_value=_fake_firestore(doc_exists=True)):
            response = main.connection_status(request)
    assert response.status_code == 200
    assert json.loads(response.get_data(as_text=True)) == {"connected": True}


def test_connection_status_false_when_no_token_document_yet():
    with app.test_request_context(f"{BASE}/connection_status"):
        with patch("main.firestore.client", return_value=_fake_firestore(doc_exists=False)):
            response = main.connection_status(request)
    assert response.status_code == 200
    assert json.loads(response.get_data(as_text=True)) == {"connected": False}


def test_connection_status_never_leaks_the_access_token():
    with app.test_request_context(f"{BASE}/connection_status"):
        with patch("main.firestore.client", return_value=_fake_firestore(doc_exists=True)):
            response = main.connection_status(request)
    assert "access_token" not in response.get_data(as_text=True)
