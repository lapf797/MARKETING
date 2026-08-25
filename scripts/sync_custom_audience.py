"""Cria/atualiza um público personalizado no Facebook a partir de uma lista de contatos
(CSV com coluna de e-mail e/ou telefone) — normalmente uma exportação de arrematantes ou
leads de leilões anteriores — e gera um público semelhante (lookalike) a partir dele. O
público semelhante mais recente passa a ser usado automaticamente em toda nova campanha
criada por scripts/create_campaigns_from_drafts.py, combinado com os interesses sugeridos
pela IA (desligue em config/settings.yaml -> ads.use_lookalike_audience: false).

Uso:
    python scripts/sync_custom_audience.py --csv contatos.csv --name "Compradores de Leilao" \\
        --email-column email --phone-column celular

O CSV precisa de cabeçalho e de pelo menos uma coluna de e-mail ou telefone. Uma linha só
entra na sincronização se TODAS as colunas informadas (--email-column e/ou --phone-column)
estiverem preenchidas nela.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import load_config
from src.facebook_ads.audiences import hash_email, hash_phone
from src.facebook_ads.client import FacebookAdsClient
from src.safety.audience_registry import record_sync

BATCH_SIZE = 2000


def _read_rows(csv_path: Path, *, email_column: str | None,
                phone_column: str | None) -> tuple[list[str], list[list[str]]]:
    schema = []
    if email_column:
        schema.append("EMAIL")
    if phone_column:
        schema.append("PHONE")
    if not schema:
        raise ValueError("informe pelo menos --email-column ou --phone-column")

    rows: list[list[str]] = []
    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for record in reader:
            row = []
            if email_column:
                email = (record.get(email_column) or "").strip()
                row.append(hash_email(email) if email else "")
            if phone_column:
                phone = (record.get(phone_column) or "").strip()
                row.append(hash_phone(phone) if phone else "")
            if row and all(row):
                rows.append(row)
    return schema, rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sincroniza um público personalizado + semelhante no Facebook a partir de um CSV de contatos."
    )
    parser.add_argument("--csv", required=True, help="Caminho do CSV com os contatos")
    parser.add_argument("--name", required=True, help='Nome do público, ex: "Compradores de Leilao"')
    parser.add_argument("--email-column", default=None, help="Nome da coluna de e-mail no CSV")
    parser.add_argument("--phone-column", default=None, help="Nome da coluna de telefone no CSV (com DDD)")
    parser.add_argument("--ratio", type=float, default=None,
                         help="Tamanho do público semelhante, 0.01 a 0.20 (padrão: ads.lookalike_ratio do settings.yaml)")
    parser.add_argument("--country", default=None,
                         help="País do público semelhante (padrão: ads.lookalike_country do settings.yaml)")
    parser.add_argument("--skip-lookalike", action="store_true",
                         help="Só sincroniza o público personalizado, sem criar/atualizar o semelhante")
    args = parser.parse_args()

    config = load_config()
    fb_client = FacebookAdsClient(config.facebook.access_token, config.facebook.ad_account_id,
                                   config.facebook.api_version)

    schema, rows = _read_rows(Path(args.csv), email_column=args.email_column, phone_column=args.phone_column)
    if not rows:
        print("Nenhum contato válido encontrado no CSV (cada linha precisa ter todas as colunas informadas preenchidas).")
        return
    print(f"{len(rows)} contato(s) válido(s) no CSV (schema: {', '.join(schema)}).")

    print(f'Criando público personalizado "{args.name}"...')
    audience = fb_client.create_custom_audience(
        name=args.name, description="Sincronizado via scripts/sync_custom_audience.py",
    )
    audience_id = audience["id"]

    sent = 0
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        fb_client.add_users_to_custom_audience(audience_id, schema=schema, hashed_rows=batch)
        sent += len(batch)
        print(f"  enviado(s) {sent}/{len(rows)}...")

    lookalike_id = None
    if not args.skip_lookalike:
        ratio = args.ratio if args.ratio is not None else config.ads.lookalike_ratio
        country = args.country or config.ads.lookalike_country
        print("Criando público semelhante (lookalike)...")
        print("Aviso: a Meta precisa de um número mínimo de contatos correspondidos no público de "
              "origem para aceitar o semelhante — se a base for pequena ou a conta for nova, isso "
              "pode falhar agora e funcionar em algumas horas, depois que a Meta processar o público.")
        try:
            lookalike = fb_client.create_lookalike_audience(
                name=f"{args.name} - Semelhante", origin_audience_id=audience_id,
                country=country, ratio=ratio,
            )
            lookalike_id = lookalike["id"]
            print(f"Público semelhante criado: {lookalike_id}")
        except Exception as exc:
            print(f"Não foi possível criar o público semelhante agora: {exc}")
            print("O público personalizado foi criado normalmente. Depois que a Meta tiver processado "
                  "os contatos, rode de novo (sem --skip-lookalike) para tentar criar o semelhante.")

    record_sync(name=args.name, custom_audience_id=audience_id,
                lookalike_audience_id=lookalike_id, members_sent=sent)

    print(f"\nPúblico personalizado: {audience_id}")
    if lookalike_id:
        print(f"Público semelhante: {lookalike_id} (usado automaticamente em novas campanhas do catálogo)")
    print("Registrado em logs/custom_audiences.json.")


if __name__ == "__main__":
    main()
