from __future__ import annotations

from dataclasses import dataclass

from .engine import Config, MAX_TRIGGERS, _walk_n
from .money import D, display_places, integer_value, price_value, round_price, step_value


SIDES = {"sell": "sell", "buy": "buy", "上涨": "sell", "卖出": "sell", "下跌": "buy", "买入": "buy"}


@dataclass(frozen=True)
class GridProjection:
    side: str
    start: str
    n: int
    step_pct: str
    prices: tuple[str, ...]
    stop: str
    avg: str
    display_places: int


def _pct(raw: str, label: str) -> str:
    return step_value(raw, label, down="下跌" in label)


def _price(raw: str) -> str:
    return price_value(raw, "起始价格")


def _n(raw) -> int:
    n = integer_value(raw, "触发次数", minimum=1)
    if n > MAX_TRIGGERS:
        raise ValueError(f"触发次数不能超过 {MAX_TRIGGERS}")
    return n


def _side(raw: str) -> str:
    key = str(raw).strip().lower()
    if key in SIDES:
        return SIDES[key]
    raise ValueError("请选择上涨卖出或下跌买入")


def _avg(prices: tuple[str, ...]) -> str:
    return str(round_price(sum(D(p) for p in prices) / len(prices)))


def project(start: str, n, step_pct: str, side: str, places: int | None = None) -> GridProjection:
    start_s = _price(start)
    n_i = _n(n)
    side_s = _side(side)
    places = display_places(start) if places is None else places
    if places not in (2, 3):
        raise ValueError("显示位数必须是 2 或 3")
    if side_s == "sell":
        pct = _pct(step_pct, "上涨步长")
        cfg = Config(up_pct=pct)
    else:
        pct = _pct(step_pct, "下跌步长")
        cfg = Config(down_pct=pct)
    prices = tuple(_walk_n(start_s, side_s, n_i, cfg, None))
    return GridProjection(
        side=side_s,
        start=start_s,
        n=n_i,
        step_pct=pct,
        prices=prices,
        stop=prices[-1],
        avg=_avg(prices),
        display_places=places,
    )
