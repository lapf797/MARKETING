"""Normalização e hash de identificadores de contato para os Públicos Personalizados
(Custom Audiences) do Facebook — a Graph API nunca recebe e-mail/telefone em texto puro,
só o hash SHA-256 do valor já normalizado exatamente como a Meta especifica; um hash de um
valor normalizado de forma diferente simplesmente não bate com o valor real do usuário do
lado da Meta, e o contato nunca é encontrado (falha silenciosa, sem erro de API)."""
from __future__ import annotations

import hashlib
import re


def hash_email(email: str) -> str:
    """E-mail: minúsculas + espaços nas pontas removidos, depois SHA-256."""
    normalized = (email or "").strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def hash_phone(phone: str, *, default_country_code: str = "55") -> str:
    """Telefone: só dígitos, com código do país na frente (sem "+" nem "00"), depois
    SHA-256. Decide se falta o código do país pela QUANTIDADE de dígitos, não por prefixo
    — um número local com DDD 55 (Santa Maria/RS, por exemplo) tem prefixo igual ao código
    do país do Brasil, então checar prefixo dá falso positivo; número de celular/fixo
    brasileiro com DDD (sem código do país) sempre tem 10 ou 11 dígitos."""
    digits = re.sub(r"\D", "", phone or "")
    digits = digits.lstrip("0")
    if len(digits) in (10, 11):
        digits = default_country_code + digits
    return hashlib.sha256(digits.encode("utf-8")).hexdigest()
