from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from copy import deepcopy
from functools import wraps
from typing import Any, Optional

from .money import D, display_places, fmt_money, fmt_price, integer_value, price_value, round_money, round_price, step_value


MAX_TRIGGERS = 5000


def _atomic(method):
    @wraps(method)
    def run(self, *args, **kwargs):
        before = deepcopy(self.__dict__)
        try:
            return method(self, *args, **kwargs)
        except Exception:
            self.__dict__.clear()
            self.__dict__.update(before)
            raise
    return run


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class Config:
    lot_size: int = 100
    up_pct: str = "0.85"
    down_pct: str = "0.8"
    buy_fee_rate: str = "0.00008"
    sell_fee_rate: str = "0.00008"
    stamp_tax_rate: str = "0.0005"
    skip_fill: bool = True
    allow_net_buy_over_zero: bool = True
    allow_short: bool = True
    end_at_zero: bool = False
    near_eps: str = "0.05"
    display_places: Optional[int] = None

    def __post_init__(self):
        self.lot_size = integer_value(self.lot_size, "单笔股数", minimum=1)
        self.up_pct = step_value(self.up_pct, "上涨步长")
        self.down_pct = step_value(self.down_pct, "下跌步长", down=True)
        for key in ("buy_fee_rate", "sell_fee_rate", "stamp_tax_rate"):
            if not 0 <= D(getattr(self, key)) < 1:
                raise ValueError("费用率必须不小于 0 且小于 1")
        if self.sell_total_rate() >= 1:
            raise ValueError("卖出总费用率必须小于 1")
        if D(self.near_eps) < 0:
            raise ValueError("临界范围不能为负数")
        if self.display_places is not None and self.display_places not in (2, 3):
            raise ValueError("显示位数必须是 2 或 3")

    def up_factor(self):
        return 1 + D(self.up_pct) / D(100)

    def down_factor(self):
        return 1 - D(self.down_pct) / D(100)

    def sell_total_rate(self):
        return D(self.sell_fee_rate) + D(self.stamp_tax_rate)

    def to_dict(self) -> dict:
        return {
            "lot_size": self.lot_size,
            "up_pct": self.up_pct,
            "down_pct": self.down_pct,
            "buy_fee_rate": self.buy_fee_rate,
            "sell_fee_rate": self.sell_fee_rate,
            "stamp_tax_rate": self.stamp_tax_rate,
            "skip_fill": self.skip_fill,
            "allow_net_buy_over_zero": self.allow_net_buy_over_zero,
            "allow_short": self.allow_short,
            "end_at_zero": self.end_at_zero,
            "near_eps": self.near_eps,
            "display_places": self.display_places,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Config:
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: d[k] for k in d if k in known})


@dataclass
class State:
    base: str
    initial_shares: int
    position: int
    buy_count: int = 0
    sell_count: int = 0
    buy_spend: str = "0.00"
    sell_proceeds: str = "0.00"
    opening_cash: str = "0.00"
    opening_price: Optional[str] = None
    last_price: Optional[str] = None
    ended: bool = False
    start_base: Optional[str] = None

    def net_bought(self) -> int:
        return self.position - self.initial_shares

    def occupied(self):
        trade = D(self.buy_spend) - D(self.sell_proceeds)
        if self.opening_price is None:
            return trade
        return trade - D(self.opening_cash)

    def net_cash(self):
        trade = D(self.sell_proceeds) - D(self.buy_spend)
        if self.opening_price is None:
            return trade
        return trade + D(self.opening_cash)

    def copy(self) -> State:
        return replace(self)

    def to_dict(self) -> dict:
        return {
            "base": self.base,
            "initial_shares": self.initial_shares,
            "position": self.position,
            "buy_count": self.buy_count,
            "sell_count": self.sell_count,
            "buy_spend": self.buy_spend,
            "sell_proceeds": self.sell_proceeds,
            "opening_cash": self.opening_cash,
            "opening_price": self.opening_price,
            "last_price": self.last_price,
            "ended": self.ended,
            "start_base": self.start_base,
        }

    @classmethod
    def from_dict(cls, d: dict) -> State:
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: d[k] for k in d if k in known})


@dataclass
class Fill:
    id: int
    batch_id: int
    kind: str
    side: str
    qty: int
    fill_price: str
    trigger_price: str
    amount: str
    fee: str
    cash: str
    base_after: str
    position_after: int
    note: str = ""
    ts: str = ""
    state_before: dict = field(default_factory=dict)
    config_before: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "batch_id": self.batch_id,
            "kind": self.kind,
            "side": self.side,
            "qty": self.qty,
            "fill_price": self.fill_price,
            "trigger_price": self.trigger_price,
            "amount": self.amount,
            "fee": self.fee,
            "cash": self.cash,
            "base_after": self.base_after,
            "position_after": self.position_after,
            "note": self.note,
            "ts": self.ts,
            "state_before": self.state_before,
            "config_before": self.config_before,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Fill:
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: d[k] for k in d if k in known})


@dataclass
class FillRequest:
    fill_price: Optional[str] = None
    trigger: Optional[str] = None
    side: Optional[str] = None
    qty: Optional[int] = None
    grids: Optional[int] = None
    skip: Optional[bool] = None
    force: bool = False
    opening: bool = False
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "fill_price": self.fill_price,
            "trigger": self.trigger,
            "side": self.side,
            "qty": self.qty,
            "grids": self.grids,
            "skip": self.skip,
            "force": self.force,
            "opening": self.opening,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, d: dict) -> FillRequest:
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: d[k] for k in d if k in known})


@dataclass
class ConfirmOption:
    key: str
    label: str
    overrides: dict


@dataclass
class NeedConfirm:
    reason: str
    message: str
    original: FillRequest
    options: list[ConfirmOption]

    def to_dict(self) -> dict:
        return {
            "reason": self.reason,
            "message": self.message,
            "original": self.original.to_dict(),
            "options": [{"key": o.key, "label": o.label, "overrides": o.overrides} for o in self.options],
        }

    @classmethod
    def from_dict(cls, d: dict) -> NeedConfirm:
        opts = [ConfirmOption(o["key"], o["label"], o["overrides"]) for o in d.get("options", [])]
        return cls(d["reason"], d["message"], FillRequest.from_dict(d["original"]), opts)


@dataclass
class Applied:
    fills: list[Fill]
    note: str = ""


@dataclass
class Ladder:
    buy2: str
    buy1: str
    base: str
    sell1: str
    sell2: str


@dataclass
class Mark:
    price: str
    hold: str
    actual: str
    gain: str
    occupied: str
    net_cash: str


def buy_level(base: str, config: Config) -> str:
    base = price_value(base, "基准价")
    level = price_value(D(base) * config.down_factor(), "低吸价")
    if D(level) >= D(base):
        raise ValueError(f"基准 {base} 在四位小数精度下无法走出下一低吸格，请调整步长")
    return level


def sell_level(base: str, config: Config) -> str:
    base = price_value(base, "基准价")
    level = price_value(D(base) * config.up_factor(), "高抛价")
    if D(level) <= D(base):
        raise ValueError(f"基准 {base} 在四位小数精度下无法走出下一高抛格，请调整步长")
    return level


def ladder(base: str, config: Config) -> Ladder:
    b1 = buy_level(base, config)
    s1 = sell_level(base, config)
    return Ladder(buy_level(b1, config), b1, str(round_price(D(base))), s1, sell_level(s1, config))


def buy_fee_cash(qty: int, price: str, rate) -> tuple[str, str, str]:
    qty = integer_value(qty, "股数", minimum=1)
    price = price_value(price, "成交价")
    if not 0 <= D(rate) < 1:
        raise ValueError("费用率必须不小于 0 且小于 1")
    amount = round_money(D(qty) * D(price))
    fee = round_money(amount * D(rate))
    spend = amount + fee
    return str(amount), str(fee), str(spend)


def sell_fee_cash(qty: int, price: str, rate) -> tuple[str, str, str]:
    qty = integer_value(qty, "股数", minimum=1)
    price = price_value(price, "成交价")
    if not 0 <= D(rate) < 1:
        raise ValueError("费用率必须不小于 0 且小于 1")
    amount = round_money(D(qty) * D(price))
    fee = round_money(amount * D(rate))
    proceeds = amount - fee
    return str(amount), str(fee), str(proceeds)


def initial_net_cash(shares: int, price: str, config: Config):
    """建仓现金：初始持仓按建仓价和费率算出的净现金。卖出为正，买入为负，零股为 0。"""
    shares = integer_value(shares, "初始持仓")
    if shares == 0:
        return D(0)
    if shares < 0:
        _, _, proceeds = sell_fee_cash(-shares, price, config.sell_total_rate())
        return D(proceeds)
    _, _, spend = buy_fee_cash(shares, price, config.buy_fee_rate)
    return -D(spend)


def _walk(base: str, side: str, price: str, config: Config, first: Optional[str], max_n: int) -> list[str]:
    triggers: list[str] = []
    b = base
    if first is not None:
        triggers.append(str(round_price(D(first))))
        b = triggers[0]
    px = D(price)
    seen = {b}
    while len(triggers) < max_n:
        nxt = buy_level(b, config) if side == "buy" else sell_level(b, config)
        if nxt == b:
            break
        hit = (side == "buy" and px <= D(nxt)) or (side == "sell" and px >= D(nxt))
        if not hit:
            break
        if nxt in seen and nxt != (triggers[-1] if triggers else None):
            break
        triggers.append(nxt)
        seen.add(nxt)
        b = nxt
    if max_n > 1 and len(triggers) == max_n:
        nxt = buy_level(b, config) if side == "buy" else sell_level(b, config)
        if (side == "buy" and px <= D(nxt)) or (side == "sell" and px >= D(nxt)):
            raise ValueError(f"一次跳格不能超过 {max_n} 格，本次未入账")
    return triggers


def _walk_n(base: str, side: str, n: int, config: Config, first: Optional[str]) -> list[str]:
    n = integer_value(n, "触发次数", minimum=1)
    if n > MAX_TRIGGERS:
        raise ValueError(f"触发次数不能超过 {MAX_TRIGGERS}")
    triggers: list[str] = []
    b = base
    if first is not None:
        triggers.append(str(round_price(D(first))))
        b = triggers[0]
    while len(triggers) < n:
        nxt = buy_level(b, config) if side == "buy" else sell_level(b, config)
        if nxt == b:
            raise ValueError(f"无法从基准 {b} 走出下一格（步长过小或价格过低）")
        triggers.append(nxt)
        b = nxt
    return triggers


def _merge_req(req: FillRequest, overrides: dict) -> FillRequest:
    data = req.to_dict()
    data.update({k: v for k, v in overrides.items() if k != "noop"})
    return FillRequest.from_dict(data)


class Engine:
    def __init__(
        self,
        config: Config,
        state: State,
        fills: Optional[list[Fill]] = None,
        next_id: int = 1,
        next_batch: int = 1,
        pending: Optional[NeedConfirm] = None,
    ):
        self.config = config
        self.state = state
        self.fills = fills or []
        self.next_id = next_id
        self.next_batch = next_batch
        self.pending = pending
        self.config = replace(config)
        if self.config.display_places is None:
            raw_start = state.start_base or (self.fills[0].state_before.get("base") if self.fills else None) or state.base
            self.config.display_places = display_places(raw_start)
        self.state = self._validated_state(state)
        self.ensure_start_base()
        self._migrate_opening_fills()

    @staticmethod
    def _validated_state(state: State) -> State:
        changes = {"base": price_value(state.base, "基准价")}
        labels = {"last_price": "现价", "start_base": "初始基准价", "opening_price": "建仓价"}
        for key, label in labels.items():
            raw = getattr(state, key)
            if raw is not None:
                changes[key] = price_value(raw, label)
        for key in ("initial_shares", "position", "buy_count", "sell_count"):
            changes[key] = integer_value(getattr(state, key), key, minimum=0 if key.endswith("count") else None)
        for key in ("buy_spend", "sell_proceeds", "opening_cash"):
            changes[key] = str(round_money(getattr(state, key)))
        return replace(state, **changes)

    def format_price(self, value) -> str:
        return fmt_price(value, self.config.display_places)

    def format_money(self, value, signed: bool = False) -> str:
        return fmt_money(value, signed=signed, places=self.config.display_places)

    def initial_base(self) -> str:
        if self.state.start_base:
            return str(round_price(D(self.state.start_base)))
        if self.fills:
            sb = self.fills[0].state_before.get("base")
            if sb:
                return str(round_price(D(sb)))
            if self.fills[0].kind == "opening":
                return str(round_price(D(self.fills[0].trigger_price)))
        return str(round_price(D(self.state.base)))

    def ensure_start_base(self) -> bool:
        if self.state.start_base:
            return False
        self.state.start_base = self.initial_base()
        return True

    def levels(self) -> Ladder:
        return ladder(self.state.base, self.config)

    def mark(self, price: Optional[str] = None) -> Mark:
        px = price or self.state.last_price or self.state.base
        px = price_value(px, "现价")
        hold = D(self.state.initial_shares) * D(px) + D(self.state.opening_cash)
        actual = D(self.state.position) * D(px) + self.state.net_cash()
        hold_s = str(round_money(hold))
        actual_s = str(round_money(actual))
        gain_s = str(round_money(actual - hold))
        return Mark(
            price=px,
            hold=hold_s,
            actual=actual_s,
            gain=gain_s,
            occupied=str(self.state.occupied()),
            net_cash=str(self.state.net_cash()),
        )

    def set_mark_price(self, price: str) -> None:
        price = price_value(price, "现价")
        self.mark(price)
        self.state.last_price = price

    @_atomic
    def submit(self, req: FillRequest) -> Applied | NeedConfirm:
        self.config = replace(self.config)
        if req.side not in (None, "buy", "sell"):
            raise ValueError("请选择买入或卖出")
        if req.fill_price is None and req.trigger is None:
            raise ValueError("请输入成交价")
        req = replace(
            req,
            fill_price=price_value(req.fill_price, "成交价") if req.fill_price is not None else None,
            trigger=price_value(req.trigger, "触发价") if req.trigger is not None else None,
            qty=integer_value(req.qty, "股数", minimum=1) if req.qty is not None else None,
            grids=integer_value(req.grids, "触发次数", minimum=1) if req.grids is not None else None,
        )
        if req.grids is not None and req.grids > MAX_TRIGGERS:
            raise ValueError(f"触发次数不能超过 {MAX_TRIGGERS}")
        if req.opening and req.qty is None:
            raise ValueError("建仓需要股数")
        self.pending = None
        if self.state.ended and not req.force:
            return self._confirm(
                req,
                "ended",
                "账本已结束（持仓为 0）。确认后仍要入账，选强制。",
                [("1", "强制入账", {"force": True}), ("2", "不动", {"noop": True})],
            )
        if req.opening:
            return self._apply_opening(req)

        side, confirm = self._infer_side(req)
        if confirm:
            return confirm
        req = replace(req, side=side)
        assert req.side in ("buy", "sell")

        skip = self.config.skip_fill if req.skip is None else req.skip
        fill_price = req.fill_price
        if fill_price is None:
            fill_price = req.trigger
        if fill_price is None:
            raise ValueError("需要成交价")
        fill_price = str(round_price(D(fill_price)))

        lot = self.config.lot_size
        max_n = MAX_TRIGGERS
        if skip:
            walked = _walk(self.state.base, req.side, fill_price, self.config, req.trigger, max_n)
        else:
            if req.trigger is not None:
                walked = [str(round_price(D(req.trigger)))]
            else:
                walked = _walk(self.state.base, req.side, fill_price, self.config, None, 1)

        if not walked:
            if req.trigger is not None:
                walked = [str(round_price(D(req.trigger)))]
            elif req.force:
                nxt = buy_level(self.state.base, self.config) if req.side == "buy" else sell_level(self.state.base, self.config)
                walked = [nxt]
            else:
                return self._no_touch(req, fill_price)

        n = len(walked)
        qty = req.qty
        grids = req.grids

        if grids is not None and grids != n:
            if req.force:
                walked = _walk_n(self.state.base, req.side, grids, self.config, req.trigger)
                n = len(walked)
            else:
                return self._grid_mismatch(req, n, grids, qty, fill_price, walked)

        if qty is not None:
            if qty <= 0:
                raise ValueError("数量必须为正")
            if n == 1 and grids in (None, 1) and (not skip or qty == lot or qty % lot != 0 or qty == n * lot):
                if qty != lot and qty % lot == 0 and skip and qty >= lot * 5 and not req.force and not req.opening:
                    return self._large_qty(req, qty, n, fill_price, walked)
                if qty % lot == 0 and skip and qty != n * lot and qty != lot and n > 1 and not req.force:
                    return self._qty_mismatch(req, n, qty, fill_price, walked)
            elif qty != n * lot:
                if req.force:
                    if qty % n == 0:
                        pass
                    elif grids is None and qty % lot == 0:
                        grids = qty // lot
                        walked = _walk_n(self.state.base, req.side, grids, self.config, req.trigger)
                        n = len(walked)
                    else:
                        return self._qty_mismatch(req, n, qty, fill_price, walked)
                else:
                    return self._qty_mismatch(req, n, qty, fill_price, walked)

        if qty is not None and qty >= lot * 5 and not req.force and not any(f.kind == "grid" for f in self.fills):
            if n != qty // lot or n >= 5:
                return self._large_qty(req, qty, n, fill_price, walked)

        per_qty = lot
        if qty is not None:
            if n == 1:
                per_qty = qty
            elif qty % n == 0:
                per_qty = qty // n
            else:
                per_qty = lot

        if not req.force:
            limit_msg = self._limits_message(req.side, per_qty * n)
            if limit_msg:
                return self._confirm(
                    req,
                    "limit",
                    limit_msg,
                    [
                        ("1", "仍然入账", {"force": True}),
                        ("2", "不动", {"noop": True}),
                    ],
                )

        fills = self._commit_batch(req.side, walked, fill_price, per_qty, kind="grid", note=req.note)
        return Applied(fills)

    @_atomic
    def confirm(self, key: str) -> Applied | NeedConfirm | None:
        if not self.pending:
            raise ValueError("没有待确认的事项")
        opt = next((o for o in self.pending.options if o.key == key), None)
        if opt is None:
            raise ValueError(f"没有选项 {key}")
        original = self.pending.original
        self.pending = None
        if opt.overrides.get("noop"):
            return None
        req = _merge_req(original, opt.overrides)
        req.force = True if "force" not in opt.overrides else bool(opt.overrides.get("force", True))
        if opt.overrides.get("opening"):
            req.opening = True
        result = self.submit(req)
        return result

    def reject(self) -> None:
        self.pending = None

    def _restore_before(self, fill: Fill) -> None:
        self.state = self._validated_state(State.from_dict(fill.state_before))
        if fill.config_before:
            config = Config.from_dict(fill.config_before)
            if config.display_places is None:
                config.display_places = self.config.display_places
            self.config = config

    @_atomic
    def undo_batch(self, n: int = 1) -> list[Fill]:
        n = integer_value(n, "撤回批数", minimum=1)
        available = len({f.batch_id for f in self.fills})
        if n > available:
            raise ValueError(f"只有 {available} 批记录，不能撤回 {n} 批；账本未改动")
        undone: list[Fill] = []
        for _ in range(n):
            if not self.fills:
                raise ValueError("没有可撤回的记录")
            batch_id = self.fills[-1].batch_id
            first = next(f for f in self.fills if f.batch_id == batch_id)
            self._restore_before(first)
            while self.fills and self.fills[-1].batch_id == batch_id:
                undone.append(self.fills.pop())
        self.pending = None
        undone.reverse()
        return undone

    def _opening_price_can_be_revised(self) -> bool:
        if self.state.opening_price is None or any(f.kind == "grid" for f in self.fills):
            return False
        if not self.fills:
            return True
        last = self.fills[-1]
        if last.kind != "adjust":
            return False
        note = last.note or ""
        return note.startswith("修正建仓价") or note.startswith("建仓")

    def _reprice_opening(self, price: str) -> Applied:
        price = price_value(price, "建仓价")
        cash = initial_net_cash(self.state.initial_shares, price, self.config)
        fill = self.adjust(
            f"修正建仓价 {self.format_price(price)}",
            opening_price=price,
            opening_cash=str(round_money(cash)),
        )
        return Applied([fill], note="已修正建仓价")

    @_atomic
    def keep_first_of_last_batch(self, fill_price: Optional[str] = None) -> Applied:
        if self._opening_price_can_be_revised():
            if fill_price is None:
                raise ValueError("上一批本来就只有一格")
            return self._reprice_opening(fill_price)
        if not self.fills:
            raise ValueError("没有可改的记录")
        batch_id = self.fills[-1].batch_id
        batch = [f for f in self.fills if f.batch_id == batch_id]
        if len(batch) == 1 and fill_price is None:
            raise ValueError("上一批本来就只有一格")
        first = batch[0]
        if first.kind == "adjust":
            raise ValueError("上一条是调整记录，不能修改成交；请先撤回该调整")
        price = price_value(fill_price if fill_price is not None else first.fill_price, "成交价")
        if first.kind == "opening":
            return self.amend_last_price(price)
        self._restore_before(first)
        self.fills = [f for f in self.fills if f.batch_id != batch_id]
        fills = self._commit_batch(
            first.side,
            [first.trigger_price],
            price,
            first.qty,
            kind=first.kind,
            note="只触发一格",
        )
        return Applied(fills, note="已改成只触发一格")

    @_atomic
    def amend_last_price(self, price: str) -> Applied:
        price = price_value(price, "成交价")
        if self._opening_price_can_be_revised():
            return self._reprice_opening(price)
        if not self.fills:
            raise ValueError("没有可改的记录")
        batch_id = self.fills[-1].batch_id
        batch = [f for f in self.fills if f.batch_id == batch_id]
        first = batch[0]
        if first.kind == "adjust":
            raise ValueError("上一条是调整记录，不能修改成交价；请先撤回该调整")
        self._restore_before(first)
        self.fills = [f for f in self.fills if f.batch_id != batch_id]
        if first.kind == "opening":
            return self._apply_opening(FillRequest(
                fill_price=price, trigger=first.trigger_price, side=first.side,
                qty=first.qty, opening=True, force=True, note=f"修正建仓成交价 {self.format_price(price)}",
            ))
        triggers = [f.trigger_price for f in batch]
        fills = self._commit_batch(
            first.side,
            triggers,
            str(round_price(D(price))),
            first.qty,
            kind=first.kind,
            note=f"修正成交价 {self.format_price(price)}",
        )
        return Applied(fills, note="已修正成交价")

    def unlock_limits(self) -> bool:
        changed = False
        if not self.config.allow_short:
            self.config.allow_short = True
            changed = True
        if not self.config.allow_net_buy_over_zero:
            self.config.allow_net_buy_over_zero = True
            changed = True
        if self.config.end_at_zero:
            self.config.end_at_zero = False
            changed = True
        if self.state.ended and self.state.position != 0:
            self.state.ended = False
            changed = True
        return changed

    def validate_steps(self, up_pct: Optional[str] = None, down_pct: Optional[str] = None) -> Config:
        config = replace(self.config,
                         up_pct=self.config.up_pct if up_pct is None else up_pct,
                         down_pct=self.config.down_pct if down_pct is None else down_pct)
        ladder(self.state.base, config)
        return config

    @_atomic
    def set_steps(self, up_pct: Optional[str] = None, down_pct: Optional[str] = None) -> Applied:
        config = self.validate_steps(up_pct, down_pct)
        parts = []
        if up_pct is not None:
            new = config.up_pct
            parts.append(f"上涨 {self.config.up_pct}% → {new}%")
        if down_pct is not None:
            new = config.down_pct
            parts.append(f"下跌 {self.config.down_pct}% → {new}%")
        if not parts:
            raise ValueError("没有要改的步长")
        note = "改步长 " + "，".join(parts)
        fill = self.adjust(note, config=config)
        lv = self.levels()
        return Applied(
            [fill],
            note=f"{note}；低吸 {self.format_price(lv.buy1)}  高抛 {self.format_price(lv.sell1)}",
        )

    @_atomic
    def set_initial_shares(self, shares: int) -> Applied:
        shares = integer_value(shares, "初始持仓")
        old = self.state.initial_shares
        config = replace(self.config, allow_short=True, allow_net_buy_over_zero=True, end_at_zero=False)
        changes: dict[str, Any] = {
            "initial_shares": shares,
            "position": self.state.position + shares - old,
        }
        if self.state.opening_price is not None:
            cash = initial_net_cash(shares, self.state.opening_price, self.config)
            changes["opening_cash"] = str(round_money(cash))
        fill = self.adjust(f"改初始持仓 {old} → {shares}", config=config, **changes)
        mk = self.mark()
        note = (
            f"初始持仓 {shares}（可负）  当前持仓 {self.state.position}  "
            f"净买 {self.state.net_bought():+d}  占用 {self.format_money(mk.occupied)}  "
            f"增益 {self.format_money(mk.gain)}"
        )
        return Applied([fill], note=note)

    @_atomic
    def adjust(self, note: str, config: Optional[Config] = None, **changes: Any) -> Fill:
        before = self.state.to_dict()
        config_before = self.config.to_dict()
        for k, v in changes.items():
            if not hasattr(self.state, k):
                raise ValueError(f"未知状态字段 {k}")
            setattr(self.state, k, v)
        self.state = self._validated_state(self.state)
        if config is not None:
            self.config = replace(config)
        self.levels()
        self.mark()
        fill = Fill(
            id=self.next_id,
            batch_id=self.next_batch,
            kind="adjust",
            side="buy",
            qty=0,
            fill_price=self.state.last_price or self.state.base,
            trigger_price=self.state.base,
            amount="0.0000",
            fee="0.0000",
            cash="0.0000",
            base_after=self.state.base,
            position_after=self.state.position,
            note=note,
            ts=_now(),
            state_before=before,
            config_before=config_before,
        )
        self.next_id += 1
        self.next_batch += 1
        self.fills.append(fill)
        return fill

    def to_dict(self) -> dict:
        return {
            "config": self.config.to_dict(),
            "state": self.state.to_dict(),
            "fills": [f.to_dict() for f in self.fills],
            "next_id": self.next_id,
            "next_batch": self.next_batch,
            "pending": self.pending.to_dict() if self.pending else None,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Engine:
        pending = NeedConfirm.from_dict(d["pending"]) if d.get("pending") else None
        return cls(
            config=Config.from_dict(d["config"]),
            state=State.from_dict(d["state"]),
            fills=[Fill.from_dict(f) for f in d.get("fills", [])],
            next_id=d.get("next_id", 1),
            next_batch=d.get("next_batch", 1),
            pending=pending,
        )

    @staticmethod
    def _fill_cash_legs(fill: Fill) -> tuple[Any, Any]:
        cash = abs(D(fill.cash))
        if fill.side == "buy":
            return cash, D(0)
        return D(0), cash

    @staticmethod
    def _take_trade_cash(bucket: dict, buy, sell) -> None:
        if "buy_spend" in bucket:
            bucket["buy_spend"] = str(round_money(D(bucket["buy_spend"]) - buy))
        if "sell_proceeds" in bucket:
            bucket["sell_proceeds"] = str(round_money(D(bucket["sell_proceeds"]) - sell))

    def _migrate_opening_fills(self) -> None:
        openings = [f for f in self.fills if f.kind == "opening"]
        if not openings or self.state.opening_price is not None:
            return
        openings.sort(key=lambda f: f.id)
        price = price_value(openings[0].fill_price, "建仓价")
        legs = {f.id: self._fill_cash_legs(f) for f in openings}
        buy = sell = D(0)
        for op in openings:
            part_buy, part_sell = legs[op.id]
            buy += part_buy
            sell += part_sell
        self.state.buy_spend = str(round_money(D(self.state.buy_spend) - buy))
        self.state.sell_proceeds = str(round_money(D(self.state.sell_proceeds) - sell))
        for fill in self.fills:
            if fill.kind == "opening":
                continue
            prior = [op for op in openings if op.id < fill.id]
            if not prior:
                continue
            part_buy = part_sell = D(0)
            for op in prior:
                b, s = legs[op.id]
                part_buy += b
                part_sell += s
            sb = fill.state_before
            self._take_trade_cash(sb, part_buy, part_sell)
            sb["opening_price"] = price
            if "initial_shares" in sb:
                sb["opening_cash"] = str(round_money(
                    initial_net_cash(integer_value(sb["initial_shares"], "初始持仓"), price, self.config)
                ))
        self.fills = [f for f in self.fills if f.kind != "opening"]
        self.state.opening_price = price
        self.state.opening_cash = str(round_money(
            initial_net_cash(self.state.initial_shares, price, self.config)
        ))
        self.state = self._validated_state(self.state)

    def _apply_opening(self, req: FillRequest) -> Applied | NeedConfirm:
        if req.side not in ("buy", "sell"):
            return self._confirm(
                req,
                "opening_side",
                "建仓需要方向（买/卖）。",
                [("1", "卖出建仓", {"side": "sell", "opening": True, "force": True}),
                 ("2", "买入建仓", {"side": "buy", "opening": True, "force": True}),
                 ("3", "不动", {"noop": True})],
            )
        price = req.fill_price or req.trigger
        if price is None or req.qty is None:
            raise ValueError("建仓需要价格和数量")
        price = price_value(price, "建仓价")
        trigger = price_value(req.trigger or price, "建仓价")
        ladder(trigger, self.config)
        signed = -req.qty if req.side == "sell" else req.qty
        cash = initial_net_cash(signed, price, self.config)
        verb = "卖出" if req.side == "sell" else "买入"
        fill = self.adjust(
            req.note or f"建仓 {verb} {req.qty} 股 @ {self.format_price(price)}",
            initial_shares=signed,
            position=self.state.position + signed - self.state.initial_shares,
            opening_price=price,
            opening_cash=str(round_money(cash)),
            base=trigger,
            last_price=price,
        )
        return Applied([fill], note="建仓（不计入买卖笔数，按初始数据入账）")

    def _commit_batch(
        self,
        side: str,
        triggers: list[str],
        fill_price: str,
        qty_each: int,
        kind: str,
        note: str,
    ) -> list[Fill]:
        qty_each = integer_value(qty_each, "股数", minimum=1)
        fill_price = price_value(fill_price, "成交价")
        triggers = [price_value(trig, "触发价") for trig in triggers]
        if not triggers:
            raise ValueError("需要至少一个触发网格")
        ladder(triggers[-1], self.config)
        amount, fee, cash_abs, cash = self._cash(side, qty_each, fill_price)
        batch_id = self.next_batch
        self.next_batch += 1
        out: list[Fill] = []
        for trig in triggers:
            before = self.state.to_dict()
            if side == "buy":
                self.state.position += qty_each
                self.state.buy_spend = str(round_money(D(self.state.buy_spend) + D(cash_abs)))
                if kind == "grid":
                    npen = max(qty_each // self.config.lot_size, 1)
                    self.state.buy_count += npen
            else:
                self.state.position -= qty_each
                self.state.sell_proceeds = str(round_money(D(self.state.sell_proceeds) + D(cash_abs)))
                if kind == "grid":
                    npen = max(qty_each // self.config.lot_size, 1)
                    self.state.sell_count += npen
            self.state.base = trig
            self.state.last_price = fill_price
            if self.config.end_at_zero and self.state.position == 0:
                self.state.ended = True
            fill = Fill(
                id=self.next_id,
                batch_id=batch_id,
                kind=kind,
                side=side,
                qty=qty_each,
                fill_price=fill_price,
                trigger_price=trig,
                amount=amount,
                fee=fee,
                cash=cash,
                base_after=self.state.base,
                position_after=self.state.position,
                note=note,
                ts=_now(),
                state_before=before,
                config_before=self.config.to_dict(),
            )
            self.next_id += 1
            self.fills.append(fill)
            out.append(fill)
        return out

    def _cash(self, side: str, qty: int, price: str) -> tuple[str, str, str, str]:
        if side == "buy":
            amount, fee, spend = buy_fee_cash(qty, price, self.config.buy_fee_rate)
            return amount, fee, spend, str(-D(spend))
        amount, fee, proceeds = sell_fee_cash(qty, price, self.config.sell_total_rate())
        return amount, fee, proceeds, proceeds

    def _infer_side(self, req: FillRequest) -> tuple[Optional[str], Optional[NeedConfirm]]:
        if req.side in ("buy", "sell"):
            return req.side, None
        lv = self.levels()
        if req.trigger is not None:
            t = D(req.trigger)
            if t < D(self.state.base):
                return "buy", None
            if t > D(self.state.base):
                return "sell", None
        price = req.fill_price
        if price is None:
            raise ValueError("需要成交价或触发价")
        p = D(price)
        if p <= D(lv.buy1):
            return "buy", None
        if p >= D(lv.sell1):
            return "sell", None
        if req.force:
            return None, self._no_touch(req, str(round_price(p)))
        near = D(self.config.near_eps)
        if abs(p - D(lv.buy1)) <= near:
            return None, self._near(req, "buy", lv.buy1, str(round_price(p)))
        if abs(p - D(lv.sell1)) <= near:
            return None, self._near(req, "sell", lv.sell1, str(round_price(p)))
        return None, self._no_touch(req, str(round_price(p)))

    def _limits_message(self, side: str, qty: int) -> Optional[str]:
        new_pos = self.state.position + qty if side == "buy" else self.state.position - qty
        new_net = new_pos - self.state.initial_shares
        msgs = []
        if not self.config.allow_short and new_pos < 0:
            msgs.append(f"会卖空（持仓将变为 {new_pos}）")
        if not self.config.allow_net_buy_over_zero and new_net > 0:
            msgs.append(f"净买量将大于 0（{new_net}）")
        return "；".join(msgs) if msgs else None

    def _confirm(self, req: FillRequest, reason: str, message: str, options: list[tuple[str, str, dict]]) -> NeedConfirm:
        nc = NeedConfirm(
            reason=reason,
            message=message,
            original=req,
            options=[ConfirmOption(k, lab, ov) for k, lab, ov in options],
        )
        self.pending = nc
        return nc

    def _near(self, req: FillRequest, side: str, trigger: str, price: str) -> NeedConfirm:
        name = "低吸" if side == "buy" else "高抛"
        diff = abs(D(price) - D(trigger))
        return self._confirm(
            req,
            "near",
            f"成交价 {self.format_price(price)} 距{name}网格 {self.format_price(trigger)} 差 {self.format_price(diff)}，未越过。触发还是不动？",
            [
                ("1", f"触发{name}（成交 {self.format_price(price)}，触发 {self.format_price(trigger)}）", {"side": side, "trigger": trigger, "fill_price": price, "grids": 1, "skip": False, "force": True}),
                ("2", "不动", {"noop": True}),
            ],
        )

    def _no_touch(self, req: FillRequest, price: str) -> NeedConfirm:
        lv = self.levels()
        return self._confirm(
            req,
            "no_touch",
            f"成交价 {self.format_price(price)} 未触及网格（低吸 {self.format_price(lv.buy1)} / 高抛 {self.format_price(lv.sell1)}）。强制触发？",
            [
                ("1", f"强制低吸（触发 {self.format_price(lv.buy1)}，成交 {self.format_price(price)}）", {"side": "buy", "trigger": lv.buy1, "fill_price": price, "grids": 1, "skip": False, "force": True}),
                ("2", f"强制高抛（触发 {self.format_price(lv.sell1)}，成交 {self.format_price(price)}）", {"side": "sell", "trigger": lv.sell1, "fill_price": price, "grids": 1, "skip": False, "force": True}),
                ("3", "不动", {"noop": True}),
            ],
        )

    def _qty_mismatch(self, req: FillRequest, n: int, qty: int, price: str, walked: list[str]) -> NeedConfirm:
        lot = self.config.lot_size
        q_grids = qty // lot if lot and qty % lot == 0 else None
        opts = [
            ("1", f"按跳格 {n} 格（{n * lot} 股，触发 {', '.join(self.format_price(p) for p in walked)}）", {"grids": n, "qty": n * lot, "skip": True, "force": True}),
        ]
        if q_grids:
            opts.append(("2", f"按报的 {qty} 股（{q_grids} 格）", {"grids": q_grids, "qty": qty, "skip": True, "force": True}))
        opts.append(("3", "只触发 1 格", {"grids": 1, "qty": lot, "skip": False, "force": True}))
        opts.append(("4", "不动", {"noop": True}))
        return self._confirm(
            req,
            "qty_mismatch",
            f"报了 {qty} 股，按价格跳格是 {n} 格（每格 {lot} 股）。按哪边入账？",
            opts,
        )

    def _grid_mismatch(self, req: FillRequest, n: int, grids: int, qty: Optional[int], price: str, walked: list[str]) -> NeedConfirm:
        lot = self.config.lot_size
        return self._confirm(
            req,
            "grid_mismatch",
            f"指定 {grids} 格，按价格走出 {n} 格。按哪边入账？",
            [
                ("1", f"按价格 {n} 格", {"grids": n, "qty": (qty if qty and n == 1 else n * lot), "force": True}),
                ("2", f"按指定 {grids} 格", {"grids": grids, "force": True}),
                ("3", "不动", {"noop": True}),
            ],
        )

    def _large_qty(self, req: FillRequest, qty: int, n: int, price: str, walked: list[str]) -> NeedConfirm:
        lot = self.config.lot_size
        g = qty // lot if qty % lot == 0 else n
        return self._confirm(
            req,
            "large_qty",
            f"{qty} 股远大于单笔 {lot}。这是建仓，还是跳格逐格？",
            [
                ("1", f"建仓 {req.side or ''} {qty} 股 @ {self.format_price(price)}（不计入成交，记为初始持仓）", {"opening": True, "qty": qty, "fill_price": price, "force": True, "side": req.side}),
                ("2", f"跳格逐格（{g} 笔）", {"opening": False, "qty": qty, "grids": g, "skip": True, "force": True}),
                ("3", "不动", {"noop": True}),
            ],
        )
