"""Login com Facebook para o sistema de marketing (substitui o token manual de "Usuário do
Sistema" por um fluxo de "Conectar com Facebook" self-service, iniciado pela aba
Configurações do dashboard). Cinco funções:

- connect_facebook   : redireciona pro diálogo OAuth da Meta
- oauth_callback     : recebe o "code", troca por um token de longa duração (60 dias) e
                        salva no Firestore
- get_token          : endpoint que os workflows do GitHub Actions consultam pra pegar o
                        token atual (protegido por uma chave compartilhada)
- connection_status  : endpoint público (sem segredo nenhum, só um true/false) que o
                        dashboard consulta pra mostrar "conectado" ou não
- refresh_token      : roda toda semana sozinha, renova o token antes dele vencer — assim
                        ele nunca expira de verdade, sem precisar logar de novo

O token nunca é exposto ao navegador nem ao dashboard — só fica no Firestore, lido e escrito
sempre pelo lado do servidor (Admin SDK). Ver docs/SETUP_FIREBASE_OAUTH.md para a
configuração inicial (é só isso que exige uma pessoa mexendo nas telas do Firebase/Meta uma
única vez; depois disso é tudo automático)."""
from __future__ import annotations

import hashlib
import hmac
import html
import json
import time
import urllib.parse

import firebase_admin
import requests
from firebase_admin import firestore
from firebase_functions import https_fn, scheduler_fn
from firebase_functions.options import CorsOptions
from firebase_functions.params import SecretParam

firebase_admin.initialize_app()

META_APP_ID = SecretParam("META_APP_ID")
META_APP_SECRET = SecretParam("META_APP_SECRET")
TOKEN_API_KEY = SecretParam("TOKEN_API_KEY")

GRAPH_API_VERSION = "v23.0"
GRAPH_BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"
OAUTH_SCOPES = "ads_management,ads_read,business_management,pages_show_list,pages_read_engagement"
STATE_TTL_SECONDS = 600  # 10 minutos — tempo de sobra pra completar o login no Facebook
TOKENS_COLLECTION = "tokens"
TOKEN_DOC_ID = "facebook"


def _sign_state(secret: str) -> str:
    """Gera um "state" assinado (timestamp + HMAC) pra proteger contra CSRF no fluxo OAuth,
    sem precisar guardar sessão nenhuma no servidor — a própria string carrega a prova de
    que foi este servidor que a emitiu, e expira sozinha (STATE_TTL_SECONDS)."""
    timestamp = str(int(time.time()))
    signature = hmac.new(secret.encode(), timestamp.encode(), hashlib.sha256).hexdigest()
    return f"{timestamp}.{signature}"


def _verify_state(state: str, secret: str) -> bool:
    try:
        timestamp_str, signature = state.split(".", 1)
    except ValueError:
        return False
    expected = hmac.new(secret.encode(), timestamp_str.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return False
    return (time.time() - int(timestamp_str)) <= STATE_TTL_SECONDS


def _html_response(title: str, message: str, *, ok: bool) -> https_fn.Response:
    """title/message podem conter texto vindo do próprio request (ex: error_description da
    Meta) — sempre escapados antes de entrar no HTML, pra não abrir um XSS refletido."""
    color = "#0F7A4C" if ok else "#B3261E"
    safe_title = html.escape(title)
    safe_message = html.escape(message)
    body = f"""<!doctype html><html lang="pt-BR"><head><meta charset="UTF-8">
<title>{safe_title}</title>
<style>body{{font-family:system-ui,sans-serif;max-width:480px;margin:80px auto;text-align:center;color:#1a1a1a}}
h1{{color:{color}}}</style></head>
<body><h1>{safe_title}</h1><p>{safe_message}</p></body></html>"""
    return https_fn.Response(body, status=200, headers={"Content-Type": "text/html; charset=utf-8"})


def _oauth_callback_url(req: https_fn.Request) -> str:
    """URL do oauth_callback, deduzida a partir do request atual — não precisamos hardcodar
    o domínio (que só existe depois do primeiro deploy). Funciona tanto chamada de dentro do
    connect_facebook (deriva trocando o nome da função na URL) quanto de dentro do próprio
    oauth_callback (a URL do request já É a certa).

    O Cloud Run/Functions termina o HTTPS num proxy antes da requisição chegar aqui — por
    dentro, req.url às vezes aparece como "http://" mesmo a chamada pública tendo sido
    https. Forçamos "https://" sempre: os domínios *.cloudfunctions.net só são servidos por
    HTTPS mesmo, então isso nunca está errado, e evita a Meta recusar o login por achar a
    redirect_uri insegura."""
    path_without_query = req.url.split("?", 1)[0]
    if path_without_query.startswith("http://"):
        path_without_query = "https://" + path_without_query[len("http://"):]
    if path_without_query.endswith("/connect_facebook"):
        return path_without_query.rsplit("/", 1)[0] + "/oauth_callback"
    return path_without_query


@https_fn.on_request(secrets=[META_APP_ID])
def connect_facebook(req: https_fn.Request) -> https_fn.Response:
    redirect_uri = _oauth_callback_url(req)
    state = _sign_state(META_APP_ID.value)
    params = {
        "client_id": META_APP_ID.value,
        "redirect_uri": redirect_uri,
        "state": state,
        "scope": OAUTH_SCOPES,
        "response_type": "code",
    }
    auth_url = f"https://www.facebook.com/{GRAPH_API_VERSION}/dialog/oauth?{urllib.parse.urlencode(params)}"
    return https_fn.Response(status=302, headers={"Location": auth_url})


@https_fn.on_request(secrets=[META_APP_ID, META_APP_SECRET])
def oauth_callback(req: https_fn.Request) -> https_fn.Response:
    error = req.args.get("error_description") or req.args.get("error")
    if error:
        return _html_response("Login cancelado", f"O Facebook informou: {error}", ok=False)

    code = req.args.get("code")
    state = req.args.get("state")
    if not code or not state or not _verify_state(state, META_APP_ID.value):
        return _html_response(
            "Link expirado ou inválido",
            "Volte na aba Configurações do dashboard e clique em \"Conectar com Facebook\" de novo.",
            ok=False,
        )

    redirect_uri = _oauth_callback_url(req)
    try:
        short_lived = requests.get(f"{GRAPH_BASE_URL}/oauth/access_token", params={
            "client_id": META_APP_ID.value,
            "client_secret": META_APP_SECRET.value,
            "redirect_uri": redirect_uri,
            "code": code,
        }, timeout=30)
        short_lived.raise_for_status()
        short_lived_token = short_lived.json()["access_token"]

        long_lived = requests.get(f"{GRAPH_BASE_URL}/oauth/access_token", params={
            "grant_type": "fb_exchange_token",
            "client_id": META_APP_ID.value,
            "client_secret": META_APP_SECRET.value,
            "fb_exchange_token": short_lived_token,
        }, timeout=30)
        long_lived.raise_for_status()
        payload = long_lived.json()
    except requests.RequestException as exc:
        return _html_response("Erro ao conectar", f"A Meta recusou a troca do token: {exc}", ok=False)

    _store_token(payload["access_token"], expires_in=payload.get("expires_in", 5_184_000))
    return _html_response(
        "Conectado com sucesso!",
        "Sua conta do Facebook está conectada. Pode fechar esta aba e voltar pro dashboard — "
        "o sistema já vai usar esse acesso nas próximas execuções, e ele se renova sozinho.",
        ok=True,
    )


def _store_token(access_token: str, *, expires_in: int) -> None:
    db = firestore.client()
    db.collection(TOKENS_COLLECTION).document(TOKEN_DOC_ID).set({
        "access_token": access_token,
        "updated_at": firestore.SERVER_TIMESTAMP,
        "expires_at_epoch": int(time.time()) + int(expires_in),
    })


@https_fn.on_request(secrets=[TOKEN_API_KEY])
def get_token(req: https_fn.Request) -> https_fn.Response:
    auth_header = req.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer ") or not hmac.compare_digest(
        auth_header.removeprefix("Bearer "), TOKEN_API_KEY.value
    ):
        return https_fn.Response('{"error":"não autorizado"}', status=401,
                                  headers={"Content-Type": "application/json"})

    db = firestore.client()
    doc = db.collection(TOKENS_COLLECTION).document(TOKEN_DOC_ID).get()
    if not doc.exists:
        return https_fn.Response(
            '{"error":"nenhuma conta do Facebook conectada ainda — use a aba Configurações do dashboard"}',
            status=404, headers={"Content-Type": "application/json"},
        )

    data = doc.to_dict()
    return https_fn.Response(
        json.dumps({"access_token": data["access_token"]}),
        status=200, headers={"Content-Type": "application/json"},
    )


@https_fn.on_request(cors=CorsOptions(cors_origins="*", cors_methods=["GET"]))
def connection_status(req: https_fn.Request) -> https_fn.Response:
    """Endpoint público — não exige autenticação nem devolve o token, só um true/false, pra
    o dashboard (uma página estática sem segredo nenhum) mostrar se já tem conta conectada."""
    db = firestore.client()
    doc = db.collection(TOKENS_COLLECTION).document(TOKEN_DOC_ID).get()
    return https_fn.Response(
        json.dumps({"connected": doc.exists}),
        status=200, headers={"Content-Type": "application/json"},
    )


@scheduler_fn.on_schedule(schedule="every monday 03:00", secrets=[META_APP_ID, META_APP_SECRET])
def refresh_token(event: scheduler_fn.ScheduledEvent) -> None:
    """Renova o token de longa duração antes dele vencer (60 dias) — a Meta permite trocar
    um token de longa duração ainda válido por um novo, com mais 60 dias pela frente. Rodando
    isso toda semana, o token nunca chega perto de expirar de verdade."""
    db = firestore.client()
    doc_ref = db.collection(TOKENS_COLLECTION).document(TOKEN_DOC_ID)
    doc = doc_ref.get()
    if not doc.exists:
        return  # ninguém conectou ainda — nada a renovar

    current_token = doc.to_dict()["access_token"]
    response = requests.get(f"{GRAPH_BASE_URL}/oauth/access_token", params={
        "grant_type": "fb_exchange_token",
        "client_id": META_APP_ID.value,
        "client_secret": META_APP_SECRET.value,
        "fb_exchange_token": current_token,
    }, timeout=30)
    if not response.ok:
        # o token pode ter sido revogado manualmente, ou passou dos 60 dias sem renovar —
        # nesse caso só reconectar de novo pela aba Configurações resolve.
        return
    payload = response.json()
    _store_token(payload["access_token"], expires_in=payload.get("expires_in", 5_184_000))
