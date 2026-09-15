from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .money import integer_value, price_value


@dataclass
class Parsed:
    op: str
    fill_price: Optional[str] = None
    trigger: Optional[str] = None
    side: Optional[str] = None
    qty: Optional[int] = None
    grids: Optional[int] = None
    skip: Optional[bool] = None
    force: bool = False
    opening: bool = False
    note: str = ""
    set_key: Optional[str] = None
    set_val: Optional[str] = None
    choice: Optional[str] = None
    undo_n: int = 1
    name: Optional[str] = None
    raw: str = ""


# Capture the entire numeric token; validators must see malformed decimals too.
_PRICE = r"(?<![\d.eE+-])([+-]?(?:[\d.]+(?:[eE][+-]?\d+)?|(?i:NaN|sNaN|Infinity|Inf)))(?![\d.eE+-])"
_INT = _PRICE


def _p(x: str) -> str:
    return price_value(x)


def _strip(text: str) -> str:
    text = text.strip()
    text = text.replace("\t", " ")
    text = re.sub(r"<system_reminder>.*?</system_reminder>", "", text, flags=re.S)
    return text.strip()


def parse(text: str, pending_keys: Optional[set[str]] = None) -> Optional[Parsed]:
    raw = _strip(text)
    if not raw:
        return None
    pending_keys = pending_keys or set()

    compact = raw.replace(" ", "")

    if compact.lower() in {"q", "quit", "exit", "退出"}:
        return Parsed(op="quit", raw=raw)
    if compact in {"状态", "status", "st"}:
        return Parsed(op="status", raw=raw)
    if compact in {"历史", "history", "fills", "流水"}:
        return Parsed(op="history", raw=raw)
    if compact in {"帮助", "help", "?", "h"}:
        return Parsed(op="help", raw=raw)
    if compact in {"ls", "list", "账本", "列表"}:
        return Parsed(op="list", raw=raw)
    if compact in {"不动", "取消", "cancel", "reject"}:
        return Parsed(op="reject", raw=raw)
    if compact in {"确认", "触发"}:
        return Parsed(op="confirm", choice="1", raw=raw)

    if pending_keys and re.fullmatch(r"\d+", compact) and compact in pending_keys:
        return Parsed(op="confirm", choice=compact, raw=raw)

    m = re.fullmatch(r"(撤回|撤销|undo|回退)(?:(\d+)(?:批|笔|格)?)?", compact, re.I)
    if m:
        n = int(m.group(2) or "1")
        return Parsed(op="undo", undo_n=n, raw=raw)

    if re.search(r"只触发了?(一|1)格", raw):
        pm = re.search(r"(?:成交价?为?|按照成交)\s*" + _PRICE, raw)
        price = _p(pm.group(1)) if pm else None
        return Parsed(op="keep_one", fill_price=price, raw=raw)

    m = re.search(r"(?:修正|改)(?:成交价|是)?\s*" + _PRICE, raw)
    if m and ("成交" in raw or "修正" in raw) and "基准" not in raw:
        return Parsed(op="amend_price", fill_price=_p(m.group(1)), raw=raw)

    if re.search(r"跳格则按倍数委托|跳格倍数委托", raw):
        return Parsed(op="set", set_key="skip_fill", set_val="1", raw=raw)

    if re.search(r"取消净.*限制", raw):
        return Parsed(op="set", set_key="allow_net_buy_over_zero", set_val="1", note="also_short", raw=raw)

    m = re.search(r"初始持仓\s*(?:是|=)?\s*" + _INT, raw)
    if m and (("改" in raw) or compact.startswith("初始持仓")):
        return Parsed(op="set", set_key="initial_shares", set_val=m.group(1), raw=raw)

    m = re.search(r"(?:改基准价\s*|基准价\s*(?:改成|改为|是|=)\s*)" + _PRICE, raw)
    if m:
        return Parsed(op="set", set_key="base", set_val=_p(m.group(1)), raw=raw)

    if re.search(r"(买入卖出笔数为0|买卖笔数为0|清零笔数)", raw):
        return Parsed(op="set", set_key="counts", set_val="0", raw=raw)

    m = re.match(r"(?:open|打开|切换)\s+(\S+)$", raw, re.I)
    if m:
        return Parsed(op="open", name=m.group(1), raw=raw)

    m = re.match(r"(?:现价|mark)\s*" + _PRICE + r"$", compact, re.I)
    if m:
        return Parsed(op="mark", fill_price=_p(m.group(1)), raw=raw)

    work = re.sub(r"^\d+\.(?!\d)\s*", "", raw).strip()
    compact = work.replace(" ", "")

    opening = bool(re.search(r"建仓|初始[:：]", work))
    force = bool(re.search(r"强制|按照成交", work))
    skip: Optional[bool] = True if "跳格" in work else None

    side = None
    if re.search(r"[bB买]|低吸", work) and not re.search(r"[sS卖]|高抛", work):
        side = "buy"
    elif re.search(r"[sS卖]|高抛", work) and not re.search(r"[bB买]|低吸", work):
        side = "sell"
    if compact.endswith("b") or compact.endswith("B"):
        side = "buy"
    if compact.endswith("s") or compact.endswith("S"):
        side = "sell"

    qty = None
    m = re.search(_INT + r"\s*股", work)
    if m:
        qty = integer_value(m.group(1), "股数", minimum=1)
    elif "股" in work:
        raise ValueError("股数必须是正整数")

    trigger = None
    fill_price = None

    m = re.search(r"价格触发了?\s*" + _PRICE + r"[，,\s]*实际成交\s*" + _PRICE, work)
    if m:
        trigger, fill_price = _p(m.group(1)), _p(m.group(2))
        return Parsed(op="fill", fill_price=fill_price, trigger=trigger, side=side, qty=qty, skip=skip, force=force, opening=opening, raw=raw)

    m = re.search(r"(?:" + _PRICE + r"[，,\s]*)?触发(?:网格)?\s*" + _PRICE + r"(?:[，,\s]*成交\s*" + _PRICE + r"(?!股))?", work)
    if m:
        leading, trig, after = m.group(1), m.group(2), m.group(3)
        trigger = _p(trig)
        if after:
            fill_price = _p(after)
        elif leading:
            fill_price = _p(leading)
        else:
            fill_price = trigger
        return Parsed(op="fill", fill_price=fill_price, trigger=trigger, side=side, qty=qty, skip=skip, force=force, opening=opening, raw=raw)

    m = re.search(r"(?:实际)?成交价?为?\s*" + _PRICE + r"(?!股)", work)
    if m:
        fill_price = _p(m.group(1))

    m = re.search(_PRICE + r"\s*成交(?:\s*" + _INT + r"股)?", work)
    if m:
        fill_price = _p(m.group(1))
        if m.lastindex and m.group(2) and qty is None:
            qty = integer_value(m.group(2), "股数", minimum=1)

    m = re.fullmatch(r"(?:买入|买)" + _PRICE, compact)
    if m:
        return Parsed(op="fill", fill_price=_p(m.group(1)), side="buy", qty=qty, force=True, opening=opening, raw=raw)

    m = re.fullmatch(r"(?:卖出|卖)" + _PRICE, compact)
    if m:
        return Parsed(op="fill", fill_price=_p(m.group(1)), side="sell", qty=qty, force=True, opening=opening, raw=raw)

    m = re.search(_PRICE + r"\s*(?:卖出|卖)\s*" + _INT + r"股", work)
    if m:
        return Parsed(op="fill", fill_price=_p(m.group(1)), side="sell", qty=integer_value(m.group(2), "股数", minimum=1), skip=skip, force=force, opening=opening, raw=raw)

    m = re.search(_PRICE + r"\s*(?:买入|买)\s*" + _INT + r"股", work)
    if m:
        return Parsed(op="fill", fill_price=_p(m.group(1)), side="buy", qty=integer_value(m.group(2), "股数", minimum=1), skip=skip, force=force, opening=opening, raw=raw)

    if opening:
        m = re.search(_PRICE + r".{0,8}(?:卖出|卖)\s*" + _INT + r"股?", compact)
        if m:
            return Parsed(op="fill", fill_price=_p(m.group(1)), side="sell", qty=integer_value(m.group(2), "股数", minimum=1), opening=True, force=True, raw=raw)
        m = re.search(r"(?:卖出|卖)\s*" + _INT + r"股?[@\s]*" + _PRICE, work)
        if m:
            return Parsed(op="fill", fill_price=_p(m.group(2)), side="sell", qty=integer_value(m.group(1), "股数", minimum=1), opening=True, force=True, raw=raw)
        m = re.search(r"(?:买入|买)\s*" + _INT + r"股?[@\s]*" + _PRICE, work)
        if m:
            return Parsed(op="fill", fill_price=_p(m.group(2)), side="buy", qty=integer_value(m.group(1), "股数", minimum=1), opening=True, force=True, raw=raw)

    m = re.fullmatch(_PRICE + r"[bB]", compact)
    if m:
        return Parsed(op="fill", fill_price=_p(m.group(1)), side="buy", raw=raw)
    m = re.fullmatch(_PRICE + r"[sS]", compact)
    if m:
        return Parsed(op="fill", fill_price=_p(m.group(1)), side="sell", raw=raw)

    if fill_price:
        return Parsed(op="fill", fill_price=fill_price, trigger=trigger, side=side, qty=qty, skip=skip, force=force, opening=opening, raw=raw)

    m = re.fullmatch(_PRICE, compact)
    if m:
        return Parsed(op="fill", fill_price=_p(m.group(1)), side=side, qty=qty, skip=skip, force=force, opening=opening, raw=raw)

    m = re.match(r"set\s+(\w+)\s+(\S+)$", raw, re.I)
    if m:
        return Parsed(op="set", set_key=m.group(1), set_val=m.group(2), raw=raw)

    return Parsed(op="unknown", raw=raw, note=raw)
