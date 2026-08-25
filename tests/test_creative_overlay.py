"""Testes do motor de composição de criativos (src/creative/overlay.py): as funções
puras de geometria/texto isoladamente, e a composição completa produzindo uma imagem
1080x1080 válida em cada combinação de conteúdo (com/sem logo, com/sem data, título
longo o suficiente para quebrar linha e truncar)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw

from src.creative import fonts
from src.creative.overlay import (
    BrandConfig,
    CreativeContent,
    _draw_pill,
    _fit_cover,
    _hex_to_rgb,
    _wrap_text,
    compose_ad_creative,
)


def test_hex_to_rgb():
    assert _hex_to_rgb("#0F1F3D") == (15, 31, 61)
    assert _hex_to_rgb("D6AF5A") == (214, 175, 90)


def test_fit_cover_produces_exact_square_regardless_of_input_aspect_ratio():
    wide = Image.new("RGB", (2000, 800), "red")
    tall = Image.new("RGB", (600, 1800), "blue")
    square = Image.new("RGB", (500, 500), "green")
    for img in (wide, tall, square):
        result = _fit_cover(img, 1080)
        assert result.size == (1080, 1080)


def test_wrap_text_splits_on_word_boundaries_within_max_width():
    canvas = Image.new("RGB", (10, 10))
    draw = ImageDraw.Draw(canvas)
    font = fonts.bold(56)
    lines = _wrap_text(draw, "Casa 3 quartos com piscina e área gourmet no bairro Jardim das Flores",
                        font, max_width=984, max_lines=2)
    assert len(lines) <= 2
    for line in lines:
        assert draw.textlength(line, font=font) <= 984


def test_wrap_text_truncates_with_ellipsis_when_exceeding_max_lines():
    canvas = Image.new("RGB", (10, 10))
    draw = ImageDraw.Draw(canvas)
    font = fonts.bold(56)
    long_text = "Terreno 500m2 em condomínio fechado com vista panorâmica incrível e infraestrutura completa"
    lines = _wrap_text(draw, long_text, font, max_width=984, max_lines=2)
    assert len(lines) == 2
    assert lines[-1].endswith("…")


def test_wrap_text_empty_string_returns_single_empty_line():
    canvas = Image.new("RGB", (10, 10))
    draw = ImageDraw.Draw(canvas)
    font = fonts.regular(30)
    assert _wrap_text(draw, "", font, max_width=500) == [""]


def test_draw_pill_box_starts_at_given_origin_and_wraps_text_with_padding():
    canvas = Image.new("RGB", (1080, 1080))
    draw = ImageDraw.Draw(canvas)
    font = fonts.bold(26)
    box = _draw_pill(draw, (48, 48), "Preço abaixo do mercado", font=font,
                      fill=(214, 175, 90), text_fill="#0F1F3D")
    x0, y0, x1, y1 = box
    assert (x0, y0) == (48, 48)
    text_w = draw.textlength("Preço abaixo do mercado", font=font)
    assert x1 - x0 == text_w + 40  # 2 * pad_x padrão
    assert y1 > y0


def test_sanitize_text_replaces_glyphs_missing_from_the_bundled_font():
    assert fonts.sanitize_text("Terreno 500m²") == "Terreno 500m2"
    assert fonts.sanitize_text("Área de 30m³") == "Área de 30m3"
    assert fonts.sanitize_text("Sem caracteres especiais") == "Sem caracteres especiais"


def _base_photo() -> Image.Image:
    return Image.new("RGB", (1600, 1200), (120, 160, 200))


def test_compose_ad_creative_returns_1080_square_rgb_image():
    content = CreativeContent(headline="Apartamento Centro", location="Caxias do Sul, RS")
    result = compose_ad_creative(_base_photo(), content=content)
    assert result.size == (1080, 1080)
    assert result.mode == "RGB"


def test_compose_ad_creative_works_with_small_photo_below_minimum_dimension():
    small_photo = Image.new("RGB", (400, 300), (100, 100, 100))
    content = CreativeContent(headline="Terreno 500m²", auction_date="03/01/2027")
    result = compose_ad_creative(small_photo, content=content)
    assert result.size == (1080, 1080)


def test_compose_ad_creative_default_brand_uses_text_wordmark_without_logo_path():
    brand = BrandConfig()
    assert brand.logo_path is None
    content = CreativeContent(headline="Casa 2 quartos")
    result = compose_ad_creative(_base_photo(), content=content, brand=brand)
    assert result.size == (1080, 1080)


def test_compose_ad_creative_with_missing_logo_path_falls_back_to_text_without_crashing():
    brand = BrandConfig(logo_path="/caminho/que/nao/existe/logo.png")
    content = CreativeContent(headline="Casa 2 quartos")
    result = compose_ad_creative(_base_photo(), content=content, brand=brand)
    assert result.size == (1080, 1080)


def test_compose_ad_creative_with_real_logo_file_composites_without_crashing(tmp_path):
    logo_path = tmp_path / "logo.png"
    logo = Image.new("RGBA", (300, 100), (214, 175, 90, 255))
    logo.save(logo_path)
    brand = BrandConfig(logo_path=str(logo_path))
    content = CreativeContent(headline="Casa 2 quartos", location="Gramado, RS", auction_date="20/09/2026")
    result = compose_ad_creative(_base_photo(), content=content, brand=brand)
    assert result.size == (1080, 1080)


def test_compose_ad_creative_without_badges_or_location_still_valid():
    content = CreativeContent(
        headline="Apartamento", location="", auction_date=None,
        show_below_market_badge=False, show_installment_badge=False,
    )
    result = compose_ad_creative(_base_photo(), content=content)
    assert result.size == (1080, 1080)
