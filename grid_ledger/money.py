from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Union

Number = Union[Decimal, int, str]


FOURPLACE = Decimal("0.0001")
ZERO = Decimal("0")


def D(x: Number) -> Decimal:
    try:
        value = x if isinstance(x, Decimal) else Decimal(str(x).strip())
    except (InvalidOperation, ValueError, TypeError) as e:
        raise ValueError("请输入有效数字") from e
    if not value.is_finite():
        raise ValueError("数字必须是有限值")
    return value


def round_money(x: Number) -> Decimal:
    try:
        return D(x).quantize(FOURPLACE, rounding=ROUND_HALF_UP)
    except InvalidOperation as e:
        raise ValueError("数值过大，无法按四位小数计算") from e


def round_price(x: Number) -> Decimal:
    return round_money(x)


def price_value(raw: Number, label: str = "价格") -> str:
    try:
        value = round_price(raw)
    except ValueError as e:
        raise ValueError(f"{label}：{e}") from e
    if value <= 0:
        raise ValueError(f"{label}按四位小数取整后必须大于 0")
    return str(value)


def integer_value(raw, label: str, minimum: int | None = None) -> int:
    try:
        value = int(str(raw).strip())
    except (ValueError, TypeError) as e:
        raise ValueError(f"{label}必须是整数") from e
    if minimum is not None and value < minimum:
        raise ValueError(f"{label}必须{'大于 0' if minimum == 1 else '不小于 ' + str(minimum)}")
    return value


def step_value(raw: str, label: str, down: bool = False) -> str:
    value = D(str(raw).strip().removesuffix("%"))
    if value <= 0 or (down and value >= 100):
        raise ValueError(f"{label}必须大于 0" + (" 且小于 100%" if down else ""))
    return format(value, "f")


def display_places(raw: Number) -> int:
    return max(2, min(3, -D(raw).as_tuple().exponent))


def fmt_money(x: Number, signed: bool = False, places: int = 2) -> str:
    d = D(x).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    s = format(d, f",.{places}f")
    if signed and d > 0:
        return "+" + s
    return s


def fmt_price(x: Number, places: int = 2) -> str:
    d = D(x).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    return format(d, f".{places}f")
