"""Gera uma prévia local do criativo de anúncio (foto realçada + marca + título + selos)
sem gastar chamada nenhuma de API (Facebook ou Claude) — útil pra ajustar texto, cores ou
a logo antes de aprovar um rascunho de verdade.

Uso:
    python scripts/preview_ad_creative.py --photo foto_do_imovel.jpg \\
        --headline "Casa 3 quartos com piscina no Jardim das Flores" \\
        --location "Porto Alegre, RS" --auction-date 15/12/2026

    # Usando uma logo diferente da configurada em config/settings.yaml, só para testar:
    python scripts/preview_ad_creative.py --photo foto.jpg --headline "..." --logo minha_logo.png

Por padrão usa a marca (nome/cores/logo) de config/settings.yaml -> creative:. A imagem
final é salva em preview_creative.jpg (ajustável com --output) — não é commitada
automaticamente, é só pra você olhar antes de aprovar.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image

from src.config import load_config
from src.creative.overlay import CreativeContent, compose_ad_creative
from src.creative.pipeline import brand_config_from_app_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera uma prévia local do criativo de anúncio, sem usar nenhuma API.")
    parser.add_argument("--photo", required=True, help="Caminho de uma foto local do ativo")
    parser.add_argument("--headline", required=True, help="Título do anúncio (ex: 'Casa 3 quartos no Jardim das Flores')")
    parser.add_argument("--location", default="", help='Localização exibida, ex: "Porto Alegre, RS"')
    parser.add_argument("--auction-date", default=None, help="Data do leilão já formatada, ex: 15/12/2026")
    parser.add_argument("--no-below-market", action="store_true", help='Não mostra o selo "Preço abaixo do mercado"')
    parser.add_argument("--no-installments", action="store_true", help="Não mostra o selo de parcelamento")
    parser.add_argument("--installments", type=int, default=None,
                         help="Número de parcelas a destacar (padrão: ads.installment_count do settings.yaml)")
    parser.add_argument("--logo", default=None, help="Caminho/URL de logo para usar nesta prévia, sobrepondo o configurado")
    parser.add_argument("--output", default="preview_creative.jpg", help="Onde salvar a prévia (padrão: preview_creative.jpg)")
    args = parser.parse_args()

    config = load_config()
    brand = brand_config_from_app_config(config)
    if args.logo:
        brand.logo_path = args.logo

    photo_path = Path(args.photo)
    if not photo_path.exists():
        parser.error(f"foto não encontrada: {photo_path}")
    photo = Image.open(photo_path)

    content = CreativeContent(
        headline=args.headline,
        location=args.location,
        auction_date=args.auction_date,
        show_below_market_badge=not args.no_below_market,
        show_installment_badge=not args.no_installments,
        installment_count=args.installments if args.installments is not None else config.ads.installment_count,
    )

    canvas = compose_ad_creative(photo, content=content, brand=brand)
    output_path = Path(args.output)
    canvas.save(output_path, format="JPEG", quality=92)
    print(f"Prévia salva em {output_path.resolve()} ({canvas.size[0]}x{canvas.size[1]}).")
    if not brand.logo_path:
        print('Sem logo configurada — usando o selo de texto com o nome da marca. '
              'Defina creative.logo_path em config/settings.yaml (ou use --logo aqui) para usar a logo real.')


if __name__ == "__main__":
    main()
