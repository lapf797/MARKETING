"""Testes de normalização/hash para Públicos Personalizados — um hash normalizado errado
não dá erro de API nenhum, só silenciosamente nunca encontra o contato do lado da Meta,
então vale conferir contra o hash esperado calculado à mão, não só "produziu algo"."""
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.facebook_ads.audiences import hash_email, hash_phone


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_email_lowercased_and_trimmed_before_hash():
    assert hash_email("  Fulano@Exemplo.com  ") == _sha256("fulano@exemplo.com")


def test_email_already_normalized():
    assert hash_email("fulano@exemplo.com") == _sha256("fulano@exemplo.com")


def test_phone_local_gets_country_code_prepended():
    # DDD 11 (São Paulo) + celular de 9 digitos = 11 digitos locais -> vira 5511999998888
    assert hash_phone("(11) 99999-8888") == _sha256("5511999998888")


def test_phone_landline_10_digits_gets_country_code():
    assert hash_phone("(11) 3333-4444") == _sha256("551133334444")


def test_phone_already_with_country_code_is_kept_as_is():
    assert hash_phone("+55 11 99999-8888") == _sha256("5511999998888")


def test_phone_ddd_55_local_number_not_mistaken_for_country_code():
    # DDD 55 (Santa Maria/RS) sem codigo do pais - 11 digitos locais, deve GANHAR o
    # prefixo 55 do Brasil (virando 13 digitos), não ser tratado como já tendo o código.
    result = hash_phone("55 99999-8888")
    assert result == _sha256("5555999998888")


def test_phone_strips_leading_zero():
    assert hash_phone("011 99999-8888") == _sha256("5511999998888")


def test_phone_empty_does_not_crash():
    result = hash_phone("")
    assert result == _sha256("")
