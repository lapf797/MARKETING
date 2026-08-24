"""Envio de métricas em tempo real para o Power BI via Push Dataset API, autenticando
com um App Registration do Azure AD (fluxo client credentials)."""
from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

AAD_TOKEN_URL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
POWERBI_SCOPE = "https://analysis.windows.net/powerbi/api/.default"
POWERBI_BASE_URL = "https://api.powerbi.com/v1.0/myorg"


class PowerBIClient:
    """Cliente para o Push Dataset API do Power BI."""

    def __init__(self, tenant_id: str, client_id: str, client_secret: str,
                 workspace_id: str, dataset_id: str, timeout: int = 30):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.workspace_id = workspace_id
        self.dataset_id = dataset_id
        self.timeout = timeout
        self._token: str | None = None

    def _get_token(self, *, force_refresh: bool = False) -> str:
        if self._token and not force_refresh:
            return self._token
        response = requests.post(
            AAD_TOKEN_URL.format(tenant_id=self.tenant_id),
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": POWERBI_SCOPE,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        self._token = response.json()["access_token"]
        return self._token

    def push_rows(self, table_name: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        url = f"{POWERBI_BASE_URL}/groups/{self.workspace_id}/datasets/{self.dataset_id}/tables/{table_name}/rows"
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {self._get_token()}", "Content-Type": "application/json"},
            json={"rows": rows},
            timeout=self.timeout,
        )
        if response.status_code == 401:
            # o token pode ter expirado entre chamadas — renova uma vez e tenta de novo
            response = requests.post(
                url,
                headers={"Authorization": f"Bearer {self._get_token(force_refresh=True)}",
                         "Content-Type": "application/json"},
                json={"rows": rows},
                timeout=self.timeout,
            )
        response.raise_for_status()
        logger.info("Enviadas %d linhas para a tabela %s do Power BI", len(rows), table_name)

    def clear_table(self, table_name: str) -> None:
        """Limpa uma tabela do push dataset — útil se preferir substituir em vez de acumular."""
        url = f"{POWERBI_BASE_URL}/groups/{self.workspace_id}/datasets/{self.dataset_id}/tables/{table_name}/rows"
        response = requests.delete(
            url, headers={"Authorization": f"Bearer {self._get_token()}"}, timeout=self.timeout,
        )
        response.raise_for_status()
