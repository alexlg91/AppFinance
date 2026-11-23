"""Conversions monétaires.

Les montants sont stockés en **centimes (entiers)** : plus aucune erreur d'arrondi
flottant dans les soldes (0.1 + 0.2 != 0.3 en float), contrairement au JSON d'origine.
"""
import math
from decimal import ROUND_HALF_UP, Decimal


def to_cents(value) -> int:
    """12.34 -> 1234. Lève ValueError pour NaN/inf/None/texte non numérique."""
    if value is None or isinstance(value, bool):
        raise ValueError("montant invalide")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("montant invalide")
    try:
        d = Decimal(str(value))
    except Exception as exc:  # Decimal lève InvalidOperation
        raise ValueError("montant invalide") from exc
    if not d.is_finite():
        raise ValueError("montant invalide")
    return int((d * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def from_cents(cents: int) -> float:
    """1234 -> 12.34"""
    return round(cents / 100, 2)
