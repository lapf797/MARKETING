"""Login com Facebook e disparo de workflows para o sistema de marketing — as duas coisas
que a aba Configurações do dashboard usa para não depender da interface do GitHub. Seis
funções:

- connect_facebook          : redireciona pro diálogo OAuth da Meta
- oauth_callback            : recebe o "code", troca por um token de longa duração (60
                               dias) e salva no Firestore
- get_token                 : endpoint que os workflows do GitHub Actions consultam pra
                               pegar o token atual (protegido por uma chave compartilhada)
- connection_status         : endpoint público (sem segredo nenhum, só um true/false) que
                               o dashboard consulta pra mostrar "conectado" ou não
- refresh_token             : roda toda semana sozinha, renova o token antes dele vencer —
                               assim ele nunca expira de verdade, sem precisar logar de novo
- trigger_suggest_audience  : recebe o formulário do dashboard e dispara o workflow
                               "Sugerir publico-alvo" no GitHub Actions, sem o usuário
                               precisar sair do dashboard (protegido por uma chave própria,
                               separada da do login — vazamento dela não expõe o token do
                               Facebook)
- trigger_approve_draft     : aprova ou rejeita um rascunho de anúncio direto do dashboard,
                               disparando o workflow "Aprovar rascunho" — fecha o ciclo
                               revisar → aprovar sem precisar do GitHub em nenhum passo
- trigger_analyze_catalog   : recebe a URL do PDF do catálogo do leilão do dashboard e
                               dispara o workflow "Analisar catalogo do leilao" — gera de
                               uma vez o rascunho de todos os lotes do catálogo (até 60)
- list_recent_runs          : lista as últimas execuções dos três workflows disparáveis
                               pelo dashboard (status, conclusão, link do log) — pra nunca
                               mais uma falha passar em silêncio sem o usuário saber

O token do Facebook nunca é exposto ao navegador nem ao dashboard — só fica no Firestore,
lido e escrito sempre pelo lado do servidor (Admin SDK). Ver docs/SETUP_FIREBASE_OAUTH.md
para a configuração inicial (é só isso que exige uma pessoa mexendo nas telas do
Firebase/Meta/GitHub uma única vez; depois disso é tudo automático)."""
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
from firebase_functions.params import SecretParam, StringParam

firebase_admin.initialize_app()

META_APP_ID = SecretParam("META_APP_ID")
META_APP_SECRET = SecretParam("META_APP_SECRET")
TOKEN_API_KEY = SecretParam("TOKEN_API_KEY")

# Chave própria pra proteger trigger_suggest_audience — separada da TOKEN_API_KEY de
# propósito: essa aqui só autoriza disparar um workflow no GitHub, nunca lê o token do
# Facebook, então um eventual vazamento dela tem um alcance bem menor.
DASHBOARD_TRIGGER_KEY = SecretParam("DASHBOARD_TRIGGER_KEY")
# Personal Access Token do GitHub com permissão de "Actions: write" no repositório —
# usado só pra chamar a API de workflow_dispatch. Ver docs/SETUP_FIREBASE_OAUTH.md.
GITHUB_PAT = SecretParam("GITHUB_PAT")

# Não é segredo (é só um identificador, como o próprio client_id) — por isso StringParam em
# vez de SecretParam, e com default vazio pra não travar o deploy antes de existir uma
# Configuração criada no App da Meta. Apps novos da Meta vêm só com "Login do Facebook para
# Empresas" (não o clássico "Login do Facebook"), que exige um config_id de uma Configuração
# em vez de pedir escopos soltos — ver docs/SETUP_FIREBASE_OAUTH.md.
META_LOGIN_CONFIG_ID = StringParam("META_LOGIN_CONFIG_ID", default="")

GRAPH_API_VERSION = "v23.0"
GRAPH_BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"
OAUTH_SCOPES = "ads_management,ads_read,business_management,pages_show_list,pages_read_engagement"
STATE_TTL_SECONDS = 600  # 10 minutos — tempo de sobra pra completar o login no Facebook
TOKENS_COLLECTION = "tokens"
TOKEN_DOC_ID = "facebook"

GITHUB_OWNER = "lapf797"
GITHUB_REPO = "MARKETING"
GITHUB_REF = "claude/facebook-ads-marketing-system-66a3tq"
GITHUB_API_BASE = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"

# Os três workflows disparáveis pelo dashboard — list_recent_runs mostra o histórico dos
# três juntos, pra qualquer disparo (sugerir público, analisar catálogo, aprovar rascunho)
# ficar visível mesmo se falhar antes de gerar qualquer rascunho.
TRACKED_WORKFLOWS = ("suggest-audience.yml", "analyze-catalog.yml", "approve-draft.yml")


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
    """URL do oauth_callback, montada a partir do HOST do request atual — não dá pra
    hardcodar o domínio (só existe depois do primeiro deploy), mas também não dá pra
    deduzir pelo CAMINHO da requisição: o Cloud Functions usa o nome da função
    (connect_facebook/oauth_callback) só para rotear até o serviço certo — por dentro, o
    caminho que a função enxerga já chega "consumido" (só "/"), então tentar trocar o nome
    da função no path (como esta função fazia antes) sempre produzia só o domínio, sem
    "/oauth_callback" no final. Usamos só o host (que esse roteamento preserva) e montamos
    o caminho certo à mão. Forçamos "https://" sempre — os domínios *.cloudfunctions.net só
    são servidos por HTTPS mesmo, então isso nunca está errado, e evita a Meta recusar o
    login por achar a redirect_uri insegura."""
    host = urllib.parse.urlparse(req.url).netloc
    return f"https://{host}/oauth_callback"


@https_fn.on_request(secrets=[META_APP_ID])
def connect_facebook(req: https_fn.Request) -> https_fn.Response:
    redirect_uri = _oauth_callback_url(req)
    state = _sign_state(META_APP_ID.value)
    params = {
        "client_id": META_APP_ID.value,
        "redirect_uri": redirect_uri,
        "state": state,
        "response_type": "code",
    }
    # Apps novos da Meta vêm só com "Login do Facebook para Empresas": as permissões são
    # definidas numa Configuração (com um config_id), em vez de pedidas soltas via "scope".
    config_id = META_LOGIN_CONFIG_ID.value
    if config_id:
        params["config_id"] = config_id
    else:
        params["scope"] = OAUTH_SCOPES
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


def _check_bearer(req: https_fn.Request, expected: str) -> bool:
    auth_header = req.headers.get("Authorization", "")
    return auth_header.startswith("Bearer ") and hmac.compare_digest(
        auth_header.removeprefix("Bearer "), expected
    )


def _dispatch_workflow(workflow_file: str, inputs: dict) -> https_fn.Response:
    """Dispara um workflow_dispatch no GitHub Actions em nome do usuário — usada tanto por
    trigger_suggest_audience quanto por trigger_approve_draft, só muda o arquivo e os inputs."""
    try:
        response = requests.post(
            f"{GITHUB_API_BASE}/actions/workflows/{workflow_file}/dispatches",
            headers={
                "Authorization": f"Bearer {GITHUB_PAT.value}",
                "Accept": "application/vnd.github+json",
            },
            json={"ref": GITHUB_REF, "inputs": inputs},
            timeout=15,
        )
    except requests.RequestException as exc:
        return https_fn.Response(json.dumps({"error": f"não foi possível contatar o GitHub: {exc}"}),
                                  status=502, headers={"Content-Type": "application/json"})

    if response.status_code != 204:
        return https_fn.Response(
            json.dumps({"error": f"o GitHub recusou o disparo (status {response.status_code}): {response.text}"}),
            status=502, headers={"Content-Type": "application/json"},
        )

    return https_fn.Response(json.dumps({"ok": True}), status=200,
                              headers={"Content-Type": "application/json"})


@https_fn.on_request(secrets=[DASHBOARD_TRIGGER_KEY, GITHUB_PAT],
                      cors=CorsOptions(cors_origins="*", cors_methods=["POST"]))
def trigger_suggest_audience(req: https_fn.Request) -> https_fn.Response:
    """Recebe o formulário do card "Sugerir público-alvo" do dashboard e dispara o workflow
    "Sugerir publico-alvo" (suggest-audience.yml) no GitHub Actions em nome do usuário —
    equivalente a clicar "Run workflow" na aba Actions, só que sem sair do dashboard. O
    workflow sempre gera um RASCUNHO para revisão (nunca cria campanha ao vivo direto) —
    ver scripts/suggest_audience.py."""
    if not _check_bearer(req, DASHBOARD_TRIGGER_KEY.value):
        return https_fn.Response('{"error":"não autorizado"}', status=401,
                                  headers={"Content-Type": "application/json"})

    body = req.get_json(silent=True) or {}
    budget = str(body.get("budget") or "").strip()
    if not budget:
        return https_fn.Response('{"error":"orçamento diário é obrigatório"}', status=400,
                                  headers={"Content-Type": "application/json"})
    leilao = str(body.get("leilao") or "").strip()
    if not leilao:
        return https_fn.Response('{"error":"nome do leilão é obrigatório"}', status=400,
                                  headers={"Content-Type": "application/json"})

    workflow_inputs = {"budget": budget, "leilao": leilao}
    for field in ("url", "category", "description", "location", "value", "picture_url", "link_url"):
        value = str(body.get(field) or "").strip()
        if value:
            workflow_inputs[field] = value

    return _dispatch_workflow("suggest-audience.yml", workflow_inputs)


@https_fn.on_request(secrets=[DASHBOARD_TRIGGER_KEY, GITHUB_PAT],
                      cors=CorsOptions(cors_origins="*", cors_methods=["POST"]))
def trigger_approve_draft(req: https_fn.Request) -> https_fn.Response:
    """Aprova, rejeita ou ajusta o orçamento de um rascunho de anúncio direto do card
    "Rascunhos de anúncios" do dashboard, disparando o workflow "Aprovar rascunho"
    (approve-draft.yml) — que roda scripts/create_campaigns_from_drafts.py --draft-id <id>
    --confirm (aprovar), --reject (rejeitar) ou --budget <valor> (ajustar orçamento). Só
    aprovar de fato escreve algo real no Facebook Ads."""
    if not _check_bearer(req, DASHBOARD_TRIGGER_KEY.value):
        return https_fn.Response('{"error":"não autorizado"}', status=401,
                                  headers={"Content-Type": "application/json"})

    body = req.get_json(silent=True) or {}
    draft_id = str(body.get("draft_id") or "").strip()
    if not draft_id:
        return https_fn.Response('{"error":"draft_id é obrigatório"}', status=400,
                                  headers={"Content-Type": "application/json"})
    action = str(body.get("action") or "").strip()
    if action not in ("approve", "reject", "set_budget"):
        return https_fn.Response(
            '{"error":"action deve ser \\"approve\\", \\"reject\\" ou \\"set_budget\\""}',
            status=400, headers={"Content-Type": "application/json"},
        )

    workflow_inputs = {"draft_id": draft_id, "action": action}
    if action == "set_budget":
        budget = str(body.get("budget") or "").strip()
        try:
            valid = budget and float(budget) > 0
        except ValueError:
            valid = False
        if not valid:
            return https_fn.Response('{"error":"orçamento diário inválido"}', status=400,
                                      headers={"Content-Type": "application/json"})
        workflow_inputs["budget"] = budget

    return _dispatch_workflow("approve-draft.yml", workflow_inputs)


@https_fn.on_request(secrets=[DASHBOARD_TRIGGER_KEY, GITHUB_PAT],
                      cors=CorsOptions(cors_origins="*", cors_methods=["POST"]))
def trigger_analyze_catalog(req: https_fn.Request) -> https_fn.Response:
    """Recebe o formulário do card "Analisar catálogo do leilão" do dashboard e dispara o
    workflow "Analisar catalogo do leilao" (analyze-catalog.yml) — lê o PDF inteiro (até 60
    lotes) numa passada só e gera um rascunho por lote para revisão, todos agrupados sob o
    mesmo nome de leilão."""
    if not _check_bearer(req, DASHBOARD_TRIGGER_KEY.value):
        return https_fn.Response('{"error":"não autorizado"}', status=401,
                                  headers={"Content-Type": "application/json"})

    body = req.get_json(silent=True) or {}
    pdf_url = str(body.get("pdf_url") or "").strip()
    if not pdf_url:
        return https_fn.Response('{"error":"URL do PDF do catálogo é obrigatória"}', status=400,
                                  headers={"Content-Type": "application/json"})
    leilao = str(body.get("leilao") or "").strip()
    if not leilao:
        return https_fn.Response('{"error":"nome do leilão é obrigatório"}', status=400,
                                  headers={"Content-Type": "application/json"})

    workflow_inputs = {"pdf_url": pdf_url, "leilao": leilao}
    for field in ("link_url", "account_id", "page_id"):
        value = str(body.get(field) or "").strip()
        if value:
            workflow_inputs[field] = value

    return _dispatch_workflow("analyze-catalog.yml", workflow_inputs)


@https_fn.on_request(secrets=[DASHBOARD_TRIGGER_KEY, GITHUB_PAT],
                      cors=CorsOptions(cors_origins="*", cors_methods=["GET"]))
def list_recent_runs(req: https_fn.Request) -> https_fn.Response:
    """Lista as últimas execuções dos três workflows disparáveis pelo dashboard, mais
    recentes primeiro — mostrado no card "Execuções recentes". Existe porque um disparo pode
    falhar antes de gerar qualquer rascunho (ex: um Secret faltando) e, sem isso, o usuário
    só saberia que "não apareceu nada", sem nenhuma pista do motivo."""
    if not _check_bearer(req, DASHBOARD_TRIGGER_KEY.value):
        return https_fn.Response('{"error":"não autorizado"}', status=401,
                                  headers={"Content-Type": "application/json"})

    runs = []
    for workflow_file in TRACKED_WORKFLOWS:
        try:
            response = requests.get(
                f"{GITHUB_API_BASE}/actions/workflows/{workflow_file}/runs",
                headers={
                    "Authorization": f"Bearer {GITHUB_PAT.value}",
                    "Accept": "application/vnd.github+json",
                },
                params={"per_page": 5, "branch": GITHUB_REF},
                timeout=15,
            )
            response.raise_for_status()
        except requests.RequestException:
            # Um workflow com problema de leitura não deve impedir de ver os outros.
            continue

        for run in response.json().get("workflow_runs", []):
            runs.append({
                "workflow": workflow_file,
                "run_number": run.get("run_number"),
                "status": run.get("status"),
                "conclusion": run.get("conclusion"),
                "html_url": run.get("html_url"),
                "created_at": run.get("created_at"),
                "updated_at": run.get("updated_at"),
            })

    runs.sort(key=lambda r: r["created_at"] or "", reverse=True)
    return https_fn.Response(json.dumps({"runs": runs[:15]}), status=200,
                              headers={"Content-Type": "application/json"})
