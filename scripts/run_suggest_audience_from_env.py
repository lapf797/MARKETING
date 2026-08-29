"""Wrapper que lê os parâmetros de variáveis de ambiente em vez de argumentos de linha de
comando, para ser disparado pelo GitHub Actions (workflow_dispatch) sem precisar de shell
interpolation — evita injeção de comando a partir de texto livre digitado no formulário do
GitHub (ex: a descrição do ativo). Veja .github/workflows/suggest-audience.yml."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import os

from scripts.suggest_audience import SuggestionError, run_suggestion


def _env(name: str) -> str | None:
    value = (os.environ.get(name) or "").strip()
    return value or None


def _env_float(name: str) -> float | None:
    value = _env(name)
    return float(value) if value is not None else None


def main() -> None:
    budget = _env_float("INPUT_BUDGET")
    if budget is None:
        print("ERRO: INPUT_BUDGET (orçamento diário máximo) é obrigatório.")
        sys.exit(1)

    try:
        run_suggestion(
            url=_env("INPUT_URL"),
            category=_env("INPUT_CATEGORY"),
            description=_env("INPUT_DESCRIPTION"),
            location=_env("INPUT_LOCATION"),
            value=_env_float("INPUT_VALUE"),
            budget=budget,
            leilao=_env("INPUT_LEILAO"),
            picture_url=_env("INPUT_PICTURE_URL"),
            link_url=_env("INPUT_LINK_URL"),
            account_id=_env("INPUT_ACCOUNT_ID"),
            page_id=_env("INPUT_PAGE_ID") or _env("FB_PAGE_ID"),
        )
    except SuggestionError as exc:
        print(f"ERRO: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
