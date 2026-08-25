"""Fontes usadas nos criativos de anúncio — vendorizadas em assets/fonts/ (Instrument
Sans, licença SIL Open Font License) em vez de depender de fontes instaladas no sistema
operacional, para o resultado ficar idêntico em qualquer máquina (seu computador, o runner
do GitHub Actions, etc). O bitmap font padrão do Pillow não tem os acentos do português."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

FONTS_DIR = Path(__file__).resolve().parents[2] / "assets" / "fonts"
BOLD_PATH = FONTS_DIR / "InstrumentSans-Bold.ttf"
REGULAR_PATH = FONTS_DIR / "InstrumentSans-Regular.ttf"


@lru_cache(maxsize=32)
def bold(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(BOLD_PATH), size)


@lru_cache(maxsize=32)
def regular(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(REGULAR_PATH), size)


# Instrument Sans não tem os glifos de "²"/"³" (testado com fonttools) — muito comuns em
# anúncios de imóveis brasileiros ("terreno de 500m²"). Sem isso, o Pillow desenha um
# quadrado vazio (tofu box) no lugar. Trocamos por um equivalente legível antes de desenhar.
_GLYPH_FALLBACKS = str.maketrans({"²": "2", "³": "3"})


def sanitize_text(text: str) -> str:
    """Troca caracteres sem glifo na fonte por um equivalente visível."""
    return text.translate(_GLYPH_FALLBACKS)
