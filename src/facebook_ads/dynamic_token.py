"""Busca o token de acesso do Facebook no endpoint get_token do Firebase (ver
functions/main.py) em vez de exigir um token estático via variável de ambiente — é o que
permite a aba "Configurações" do dashboard (login com Facebook) manter o pipeline
autenticado sem o usuário nunca precisar gerar/colar um token manualmente. Ver
docs/SETUP_FIREBASE_OAUTH.md para a configuração inicial."""
from __future__ import annotations

import requests


class DynamicTokenError(RuntimeError):
    """Erro ao buscar o token dinâmico — mensagem já pensada pra aparecer direto no log do
    GitHub Actions e explicar o que fazer."""


def fetch_access_token(endpoint_url: str, api_key: str, *, timeout: int = 15) -> str:
    try:
        response = requests.get(
            endpoint_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise DynamicTokenError(f"não foi possível contatar o endpoint de token ({endpoint_url}): {exc}") from exc

    if response.status_code == 401:
        raise DynamicTokenError(
            "o endpoint de token recusou a chave (FB_TOKEN_API_KEY) — confira o valor cadastrado nos Secrets."
        )
    if response.status_code == 404:
        raise DynamicTokenError(
            "nenhuma conta do Facebook conectada ainda — abra a aba Configurações do dashboard "
            "e clique em \"Conectar com Facebook\"."
        )
    if not response.ok:
        raise DynamicTokenError(f"endpoint de token retornou erro {response.status_code}: {response.text}")

    access_token = response.json().get("access_token")
    if not access_token:
        raise DynamicTokenError("endpoint de token respondeu sem access_token — resposta inesperada.")
    return access_token
