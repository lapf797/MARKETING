"""Liga o motor de composição de criativos (src/creative/overlay.py) ao restante do
sistema: baixa a foto crua do rascunho, aplica realce + marca, e devolve os bytes prontos
para subir na Graph API (FacebookAdsClient.upload_ad_image)."""
from __future__ import annotations

from io import BytesIO

import requests
from PIL import Image

from src.config import AppConfig

from .overlay import BrandConfig, CreativeContent, compose_ad_creative


def _format_auction_date(pause_date: str | None) -> str | None:
    """`pause_date` vem como "AAAA-MM-DD" (ISO) dos rascunhos — convertido para o formato
    usado nos anúncios em português, "DD/MM/AAAA"."""
    if not pause_date:
        return None
    try:
        year, month, day = pause_date.split("-")
        return f"{day}/{month}/{year}"
    except ValueError:
        return None


def brand_config_from_app_config(config: AppConfig) -> BrandConfig:
    return BrandConfig(
        name=config.creative.brand_name,
        logo_path=config.creative.logo_path,
        color_dark=config.creative.color_dark,
        color_accent=config.creative.color_accent,
        color_secondary=config.creative.color_secondary,
    )


def generate_ad_image_bytes(*, picture_url: str, prop: dict, pause_date: str | None,
                             config: AppConfig, timeout: int = 30) -> bytes:
    """Baixa a foto do ativo, compõe o criativo final (foto realçada + marca + título +
    localização + selos) e devolve os bytes JPEG prontos para upload. Levanta exceção se a
    foto não puder ser baixada/aberta — quem chama decide se cai de volta para a
    picture_url crua (ver scripts/create_campaigns_from_drafts.py)."""
    response = requests.get(picture_url, timeout=timeout)
    response.raise_for_status()
    photo = Image.open(BytesIO(response.content))

    location_parts = [part for part in [prop.get("city"), prop.get("state")] if part]
    content = CreativeContent(
        headline=prop["headline"],
        location=", ".join(location_parts),
        auction_date=_format_auction_date(pause_date),
        show_below_market_badge=config.ads.highlight_below_market_price,
        show_installment_badge=config.ads.highlight_installments,
        installment_count=config.ads.installment_count,
    )
    canvas = compose_ad_creative(photo, content=content, brand=brand_config_from_app_config(config))

    buffer = BytesIO()
    canvas.save(buffer, format="JPEG", quality=92)
    return buffer.getvalue()
