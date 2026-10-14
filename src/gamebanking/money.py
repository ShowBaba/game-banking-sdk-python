"""Money helpers. Amounts are integers in minor units; a currency's exponent is
its number of decimal places. Nothing here uses floating point."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Union

_DECIMAL = re.compile(r"^-?\d+(\.\d+)?$")


def to_minor(amount: Union[str, Decimal, int], exponent: int) -> int:
    """Converts a decimal amount to minor units: ``to_minor("100.50", 2) == 10050``.

    Raises ``ValueError`` if the amount has more decimal places than the
    currency allows. Floats are refused, because they cannot hold most
    decimal amounts exactly.
    """
    _check_exponent(exponent)
    if isinstance(amount, float):
        raise TypeError("pass amounts as str, Decimal or int, not float")
    if isinstance(amount, bool):
        raise TypeError("amount must not be a bool")
    if isinstance(amount, str):
        text = amount.strip().replace(",", "")
        if not _DECIMAL.match(text):
            raise ValueError(f"not a decimal amount: {amount!r}")
        try:
            amount = Decimal(text)
        except InvalidOperation as e:  # pragma: no cover - regex already guards this
            raise ValueError(f"not a decimal amount: {amount!r}") from e
    scaled = Decimal(amount) * (Decimal(10) ** exponent)
    if scaled != scaled.to_integral_value():
        raise ValueError(f"{amount} has more than {exponent} decimal places")
    return int(scaled)


def format_minor(minor: int, exponent: int) -> str:
    """Formats minor units as a plain decimal string: ``format_minor(10050, 2) == "100.50"``."""
    _check_exponent(exponent)
    if isinstance(minor, bool) or not isinstance(minor, int):
        raise TypeError("minor must be an int")
    sign = "-" if minor < 0 else ""
    digits = str(abs(minor))
    if exponent == 0:
        return sign + digits
    digits = digits.rjust(exponent + 1, "0")
    return f"{sign}{digits[:-exponent]}.{digits[-exponent:]}"


def _check_exponent(exponent: int) -> None:
    if isinstance(exponent, bool) or not isinstance(exponent, int) or not 0 <= exponent <= 6:
        raise ValueError("exponent must be an int from 0 to 6")
