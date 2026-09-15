from __future__ import annotations

import json
from datetime import datetime
from dataclasses import replace
from pathlib import Path
from typing import Optional

from .engine import Config, Engine, State
from .money import display_places, fmt_price, integer_value, price_value

ROOT = Path(__file__).resolve().parent.parent
BOOKS = ROOT / "books"
CURRENT_FILE = BOOKS / "_current.txt"
CALC_FILE = BOOKS / "_calc.json"


def set_books_dir(path) -> None:
    global BOOKS, CURRENT_FILE, CALC_FILE
    BOOKS = Path(path)
    CURRENT_FILE = BOOKS / "_current.txt"
    CALC_FILE = BOOKS / "_calc.json"
    BOOKS.mkdir(parents=True, exist_ok=True)


def _safe_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise ValueError("账本名称不能为空")
    bad = '<>:"/\\|?*'
    if any(c in name for c in bad):
        raise ValueError("账本名称含非法字符")
    if name.startswith("_"):
        raise ValueError("账本名称不能以下划线开头")
    return name


def book_path(name: str) -> Path:
    return BOOKS / f"{_safe_name(name)}.json"


def ensure_books_dir() -> None:
    BOOKS.mkdir(parents=True, exist_ok=True)


def list_books() -> list[str]:
    ensure_books_dir()
    names = []
    for p in sorted(BOOKS.glob("*.json")):
        if p.stem.startswith("_"):
            continue
        names.append(p.stem)
    return names


def current_name() -> Optional[str]:
    if CURRENT_FILE.exists():
        name = CURRENT_FILE.read_text(encoding="utf-8").strip()
        if name:
            return name
    names = list_books()
    return names[0] if names else None


def set_current(name: str) -> None:
    ensure_books_dir()
    CURRENT_FILE.write_text(_safe_name(name), encoding="utf-8")


def exists(name: str) -> bool:
    return book_path(name).exists()


def _normalize_calc_state(state) -> Optional[dict]:
    if not isinstance(state, dict):
        return None
    side = str(state.get("side", "sell")).strip().lower()
    if side not in ("sell", "buy"):
        side = "sell"
    out = {"side": side}
    if state.get("display_places") in (2, 3):
        out["display_places"] = state["display_places"]
    for key in ("start", "up", "down", "n"):
        if key not in state or state[key] is None:
            continue
        out[key] = str(state[key])
    return out


def load_calc_state() -> Optional[dict]:
    if not CALC_FILE.exists():
        return None
    try:
        data = json.loads(CALC_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return _normalize_calc_state(data)


def save_calc_state(state: dict) -> Path:
    data = _normalize_calc_state(state)
    if not data:
        raise ValueError("计算器状态无效")
    ensure_books_dir()
    tmp = CALC_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CALC_FILE)
    return CALC_FILE


def save(name: str, engine: Engine) -> Path:
    ensure_books_dir()
    name = _safe_name(name)
    path = book_path(name)
    data = {
        "name": name,
        "version": 2,
        "saved_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        **engine.to_dict(),
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def list_slots() -> list[dict]:
    ensure_books_dir()
    out = []
    for name in list_books():
        path = book_path(name)
        info = {
            "name": name,
            "saved_at": "",
            "mtime": path.stat().st_mtime,
            "base": "",
            "position": 0,
            "initial": 0,
            "buy_count": 0,
            "sell_count": 0,
        }
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            st = data.get("state") or {}
            info.update(
                {
                    "name": data.get("name", name),
                    "saved_at": data.get("saved_at") or "",
                    "base": fmt_price(st["base"], (data.get("config") or {}).get("display_places") or display_places(st.get("start_base") or st["base"])) if st.get("base") else "",
                    "position": st.get("position", 0),
                    "initial": st.get("initial_shares", 0),
                    "buy_count": st.get("buy_count", 0),
                    "sell_count": st.get("sell_count", 0),
                }
            )
        except Exception:
            pass
        out.append(info)
    out.sort(key=lambda x: x.get("mtime") or 0, reverse=True)
    return out


def duplicate(src: str, dest: str) -> str:
    dest = _safe_name(dest)
    if exists(dest):
        raise FileExistsError(f"存档已存在：{dest}")
    _, eng = load(src)
    save(dest, eng)
    return dest


def rename(old: str, new: str) -> str:
    old = _safe_name(old)
    new = _safe_name(new)
    if old == new:
        return new
    if not exists(old):
        raise FileNotFoundError(f"没有存档：{old}")
    if exists(new):
        raise FileExistsError(f"存档已存在：{new}")
    was_current = current_name() == old
    _, eng = load(old)
    save(new, eng)
    book_path(old).unlink()
    if was_current:
        set_current(new)
    return new


def load(name: str) -> tuple[str, Engine]:
    path = book_path(name)
    if not path.exists():
        raise FileNotFoundError(f"没有账本：{name}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("name", name), Engine.from_dict(data)


def new_engine(
    base: str,
    shares: int,
    opening_price: Optional[str] = None,
    config: Optional[Config] = None,
) -> Engine:
    config = replace(config or Config(), display_places=display_places(base))
    base = price_value(base, "初始基准价")
    shares = integer_value(shares, "初始持仓")
    if opening_price is not None:
        opening_price = price_value(opening_price, "建仓价")
    start = base
    if opening_price is not None:
        state = State(base=str(base), start_base=start, initial_shares=shares, position=0)
        engine = Engine(config, state)
        from .engine import FillRequest

        side = "sell" if shares < 0 else "buy"
        if shares == 0:
            engine = Engine(config, State(base=str(base), start_base=start, initial_shares=0, position=0))
        else:
            result = engine.submit(
                FillRequest(
                    fill_price=str(opening_price),
                    trigger=str(base),
                    side=side,
                    qty=abs(shares),
                    opening=True,
                    force=True,
                )
            )
            from .engine import NeedConfirm

            if isinstance(result, NeedConfirm):
                raise ValueError(result.message)
    else:
        engine = Engine(config, State(base=str(base), start_base=start, initial_shares=shares, position=shares))
    engine.levels()
    engine.mark()
    return engine


def create(
    name: str,
    base: str,
    shares: int,
    opening_price: Optional[str] = None,
    config: Optional[Config] = None,
) -> Engine:
    name = _safe_name(name)
    if exists(name):
        raise FileExistsError(f"账本已存在：{name}")
    engine = new_engine(base, shares, opening_price, config)
    save(name, engine)
    set_current(name)
    return engine
