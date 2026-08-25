"""Compõe o criativo final do anúncio: a foto do ativo realçada (src/creative/enhance.py)
por baixo de uma moldura de marca — logo (ou selo de texto, se nenhuma logo for
configurada), faixa com título/localização, selos de "preço abaixo do mercado" e
parcelamento, e a data do leilão. Produz uma imagem quadrada 1080x1080, o formato mais
compatível entre feed do Facebook e do Instagram."""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageDraw

from . import fonts
from .enhance import enhance_photo

CANVAS_SIZE = 1080
PAD = 48


@dataclass
class BrandConfig:
    """Identidade visual aplicada ao criativo. Sem logo_path configurado, usa um selo de
    texto com `name` — nunca inventa uma marca gráfica. Cores padrão vêm da própria
    identidade visual já usada pela Milan Leilões (extraídas do protótipo de referência)."""
    name: str = "MILAN LEILÕES"
    site: str = ""
    logo_path: str | None = None
    color_dark: str = "#0F1F3D"
    color_accent: str = "#D6AF5A"
    color_secondary: str = "#03A3BE"


@dataclass
class CreativeContent:
    headline: str
    location: str = ""
    auction_date: str | None = None  # já formatada, ex: "15/12/2026"
    show_below_market_badge: bool = True
    show_installment_badge: bool = True
    installment_count: int = 48


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _fit_cover(image: Image.Image, size: int) -> Image.Image:
    """Redimensiona e recorta a imagem para preencher um quadrado `size`x`size`, mantendo
    a proporção — equivalente a `object-fit: cover` no CSS."""
    width, height = image.size
    scale = max(size / width, size / height)
    new_size = (round(width * scale), round(height * scale))
    resized = image.resize(new_size, Image.LANCZOS)
    left = (resized.width - size) // 2
    top = (resized.height - size) // 2
    return resized.crop((left, top, left + size, top + size))


def _add_vertical_scrim(image: Image.Image, *, color: tuple[int, int, int],
                         y_start: int, y_end: int, alpha_start: int, alpha_end: int) -> Image.Image:
    """Sobrepõe um degradê vertical de `color` (só a transparência varia) — usado para dar
    legibilidade ao texto sobre a foto, sem escurecer a imagem inteira."""
    width, height = image.size
    alpha_col = np.full(height, alpha_end, dtype=np.float32)
    span = max(y_end - y_start, 1)
    ramp = np.linspace(alpha_start, alpha_end, span)
    alpha_col[y_start:y_end] = ramp
    if y_start > 0:
        alpha_col[:y_start] = alpha_start
    alpha = np.tile(alpha_col.reshape(height, 1), (1, width)).astype(np.uint8)
    overlay = np.zeros((height, width, 4), dtype=np.uint8)
    overlay[..., 0] = color[0]
    overlay[..., 1] = color[1]
    overlay[..., 2] = color[2]
    overlay[..., 3] = alpha
    return Image.alpha_composite(image.convert("RGBA"), Image.fromarray(overlay, mode="RGBA"))


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: float, max_lines: int = 2) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)

    if len(lines) <= max_lines:
        return lines

    kept = lines[:max_lines]
    last = kept[-1]
    while last and draw.textlength(last + "…", font=font) > max_width:
        last = last[:-1].rstrip()
    kept[-1] = f"{last}…" if last else "…"
    return kept


def _draw_pill(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, *, font,
               fill: tuple[int, int, int], text_fill: str, pad_x: int = 20, pad_y: int = 12) -> tuple[int, int, int, int]:
    x, y = xy
    text_w = draw.textlength(text, font=font)
    ascent, descent = font.getmetrics()
    text_h = ascent + descent
    box = (x, y, x + text_w + 2 * pad_x, y + text_h + 2 * pad_y)
    draw.rounded_rectangle(box, radius=(box[3] - box[1]) / 2, fill=fill)
    draw.text((x + pad_x, y + pad_y), text, font=font, fill=text_fill)
    return box


def _load_logo(logo_path: str) -> Image.Image | None:
    try:
        if logo_path.startswith("http://") or logo_path.startswith("https://"):
            response = requests.get(logo_path, timeout=30)
            response.raise_for_status()
            return Image.open(BytesIO(response.content)).convert("RGBA")
        path = Path(logo_path)
        if path.exists():
            return Image.open(path).convert("RGBA")
    except Exception:
        return None
    return None


def _draw_brand_mark(canvas: Image.Image, draw: ImageDraw.ImageDraw, brand: BrandConfig, *,
                      x: int, y: int, max_height: int) -> int:
    """Desenha a logo configurada (se houver) ou, por padrão, um selo de texto com o nome
    da marca — nunca gera uma marca gráfica sozinha. Retorna a largura ocupada."""
    logo = _load_logo(brand.logo_path) if brand.logo_path else None
    if logo is not None:
        scale = max_height / logo.height
        resized = logo.resize((max(1, round(logo.width * scale)), max_height), Image.LANCZOS)
        canvas.alpha_composite(resized, (x, y))
        return resized.width
    font = fonts.bold(max_height)
    name = fonts.sanitize_text(brand.name)
    draw.text((x, y), name, font=font, fill="white")
    return round(draw.textlength(name, font=font))


def compose_ad_creative(photo: Image.Image, *, content: CreativeContent,
                         brand: BrandConfig | None = None) -> Image.Image:
    brand = brand or BrandConfig()
    dark = _hex_to_rgb(brand.color_dark)

    canvas = _fit_cover(enhance_photo(photo), CANVAS_SIZE).convert("RGBA")
    canvas = _add_vertical_scrim(canvas, color=dark, y_start=0, y_end=210, alpha_start=145, alpha_end=0)
    canvas = _add_vertical_scrim(canvas, color=dark, y_start=560, y_end=CANVAS_SIZE, alpha_start=0, alpha_end=248)
    draw = ImageDraw.Draw(canvas)

    # --- topo: marca + data do leilão -------------------------------------------------
    _draw_brand_mark(canvas, draw, brand, x=PAD, y=PAD, max_height=40)
    if content.auction_date:
        date_text = fonts.sanitize_text(f"Leilão em {content.auction_date}")
        date_font = fonts.bold(24)
        text_w = draw.textlength(date_text, font=date_font)
        pill_w = text_w + 40
        _draw_pill(draw, (CANVAS_SIZE - PAD - round(pill_w), PAD - 4), date_text,
                   font=date_font, fill=_hex_to_rgb(brand.color_accent), text_fill=brand.color_dark)

    # --- rodapé: título, localização e selos -------------------------------------------
    title_font = fonts.bold(56)
    location_font = fonts.regular(30)
    badge_font = fonts.bold(26)

    max_text_width = CANVAS_SIZE - 2 * PAD
    headline = fonts.sanitize_text(content.headline)
    title_lines = _wrap_text(draw, headline, title_font, max_text_width, max_lines=2)
    title_ascent, title_descent = title_font.getmetrics()
    title_line_height = title_ascent + title_descent + 6

    badges = []
    if content.show_below_market_badge:
        badges.append("Preço abaixo do mercado")
    if content.show_installment_badge and content.installment_count > 1:
        badges.append(f"Parcelamento em até {content.installment_count}x")

    badge_height = 0
    if badges:
        _, badge_descent = badge_font.getmetrics()
        badge_ascent = badge_font.getmetrics()[0]
        badge_height = badge_ascent + badge_descent + 24 + 14  # altura do pill + espaço acima

    location_height = (location_font.getmetrics()[0] + location_font.getmetrics()[1] + 10) if content.location else 0

    block_height = len(title_lines) * title_line_height + location_height + badge_height
    y = CANVAS_SIZE - PAD - block_height

    for line in title_lines:
        draw.text((PAD, y), line, font=title_font, fill="white")
        y += title_line_height

    if content.location:
        draw.text((PAD, y), fonts.sanitize_text(content.location), font=location_font, fill=brand.color_secondary)
        y += location_height

    if badges:
        x = PAD
        y += 14
        for badge_text in badges:
            box = _draw_pill(draw, (x, y), badge_text, font=badge_font,
                              fill=_hex_to_rgb(brand.color_accent), text_fill=brand.color_dark)
            x = box[2] + 14
            if x > CANVAS_SIZE - PAD - 160 and badge_text != badges[-1]:
                # não sobra espaço pro próximo selo ao lado — quebra pra linha seguinte
                x = PAD
                y = box[3] + 10

    return canvas.convert("RGB")
