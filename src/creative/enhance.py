"""Realce automático da foto do ativo antes de virar criativo de anúncio: aumenta fotos
pequenas para o tamanho mínimo recomendado pela Meta, corrige contraste e nitidez. O
objetivo é a foto real do ativo ficar mais nítida e vibrante, sem parecer editada demais —
por isso os ajustes são sutis."""
from __future__ import annotations

from PIL import Image, ImageEnhance, ImageOps

MIN_DIMENSION = 1080


def enhance_photo(image: Image.Image) -> Image.Image:
    image = ImageOps.exif_transpose(image) or image  # respeita a orientação salva pela câmera
    image = image.convert("RGB")

    width, height = image.size
    shortest_side = min(width, height)
    if shortest_side < MIN_DIMENSION:
        scale = MIN_DIMENSION / shortest_side
        image = image.resize((round(width * scale), round(height * scale)), Image.LANCZOS)

    image = ImageOps.autocontrast(image, cutoff=1)
    image = ImageEnhance.Color(image).enhance(1.12)
    image = ImageEnhance.Contrast(image).enhance(1.05)
    image = ImageEnhance.Sharpness(image).enhance(1.3)
    return image
