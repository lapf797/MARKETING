"""Wrapper que lê os parâmetros de variáveis de ambiente em vez de argumentos de linha de
comando, para ser disparado pelo GitHub Actions (workflow_dispatch) sem precisar de shell
interpolation — evita injeção de comando a partir de texto livre digitado no formulário do
GitHub (ex: o nome do leilão). Veja .github/workflows/analyze-catalog.yml."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import os

from scripts.analyze_catalog import run_analysis


def _env(name: str) -> str | None:
    value = (os.environ.get(name) or "").strip()
    return value or None


def main() -> None:
    pdf = _env("INPUT_PDF_URL")
    if pdf is None:
        print("ERRO: INPUT_PDF_URL (URL pública do PDF do catálogo) é obrigatório.")
        sys.exit(1)

    run_analysis(
        pdf=pdf,
        leilao=_env("INPUT_LEILAO"),
        link_url=_env("INPUT_LINK_URL"),
        account_id=_env("INPUT_ACCOUNT_ID"),
        page_id=_env("INPUT_PAGE_ID") or _env("FB_PAGE_ID"),
    )


if __name__ == "__main__":
    main()
