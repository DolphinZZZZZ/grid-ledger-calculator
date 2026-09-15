from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from typing import Optional

from . import book
from .engine import Applied, Config, FillRequest, NeedConfirm
from .format import HELP, render_applied, render_confirm, render_history, render_prompt, render_status
from .money import integer_value, price_value
from .parse import Parsed, parse


def _utf8() -> None:
    if sys.platform == "win32":
        for stream in (sys.stdin, sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass


def _pending_keys(engine) -> set[str]:
    if not engine.pending:
        return set()
    return {o.key for o in engine.pending.options}


def _print(text: str) -> None:
    sys.stdout.write(text if text.endswith("\n") else text + "\n")
    sys.stdout.flush()


def _req(p: Parsed) -> FillRequest:
    return FillRequest(
        fill_price=p.fill_price,
        trigger=p.trigger,
        side=p.side,
        qty=p.qty,
        grids=p.grids,
        skip=p.skip,
        force=p.force,
        opening=p.opening,
        note=p.note,
    )


def _set_value(engine, key: str, val: str, note: str = "") -> Applied:
    key = key.replace("-", "_")
    aliases = {
        "base": "base",
        "基准": "base",
        "基准价": "base",
        "initial_shares": "initial_shares",
        "初始持仓": "initial_shares",
        "skip_fill": "skip_fill",
        "skip": "skip_fill",
        "allow_net_buy_over_zero": "allow_net_buy_over_zero",
        "allow_short": "allow_short",
        "end_at_zero": "end_at_zero",
        "lot": "lot_size",
        "lot_size": "lot_size",
        "up": "up_pct",
        "down": "down_pct",
        "counts": "counts",
        "buy_count": "buy_count",
        "sell_count": "sell_count",
    }
    k = aliases.get(key, key)

    def _truthy(v: str) -> bool:
        return v.lower() not in {"0", "false", "off", "no", "否"}

    if k in {"skip_fill", "allow_net_buy_over_zero", "allow_short", "end_at_zero"}:
        changes = {k: _truthy(val)}
        if note == "also_short" or k == "allow_net_buy_over_zero":
            if _truthy(val):
                changes.update(allow_short=True, end_at_zero=False)
        fill = engine.adjust(note or f"set {k}={val}", config=replace(engine.config, **changes))
        return Applied([fill], note=f"已改 {k}={val}")
    if k == "counts":
        fill = engine.adjust("清零买卖笔数", buy_count=0, sell_count=0)
        return Applied([fill], note="买入/卖出笔数已清零")
    if k == "base":
        base = price_value(val, "基准价")
        fill = engine.adjust(f"改基准价 {engine.format_price(base)}", base=base)
        return Applied([fill], note=f"基准价 {engine.format_price(engine.state.base)}")
    if k == "initial_shares":
        return engine.set_initial_shares(integer_value(val, "初始持仓"))
    if k in {"buy_count", "sell_count", "position", "lot_size"}:
        ival = integer_value(val, "股数" if k == "lot_size" else k)
        if k == "lot_size":
            fill = engine.adjust(f"单笔 {ival}", config=replace(engine.config, lot_size=ival))
        else:
            fill = engine.adjust(f"改 {k}={ival}", **{k: ival})
        return Applied([fill], note=f"{k}={ival}")
    if k in {"up_pct", "down_pct"}:
        if k == "up_pct":
            return engine.set_steps(up_pct=val)
        return engine.set_steps(down_pct=val)
    raise ValueError(f"不能改的字段：{key}")


def run_parsed(name: str, engine, p: Parsed) -> tuple[str, object, bool]:
    """Returns (output, engine_or_new, quit)."""
    if p.op == "quit":
        return "", engine, True
    if p.op == "help":
        return HELP, engine, False
    if p.op == "list":
        names = book.list_books()
        cur = book.current_name()
        if not names:
            return "（还没有账本）", engine, False
        lines = []
        for n in names:
            mark = " *" if n == cur else ""
            lines.append(f"{n}{mark}")
        return "\n".join(lines), engine, False
    if p.op == "open":
        if not p.name:
            raise ValueError("open 需要账本名")
        n, eng = book.load(p.name)
        book.set_current(n)
        return render_status(eng, n), (n, eng), False
    if p.op == "status":
        return render_status(engine, name), engine, False
    if p.op == "history":
        return render_history(engine), engine, False
    if p.op == "mark":
        engine.set_mark_price(p.fill_price or engine.state.base)
        book.save(name, engine)
        return render_status(engine, name), engine, False
    if p.op == "reject":
        engine.reject()
        book.save(name, engine)
        return "已取消待确认项。", engine, False
    if p.op == "confirm":
        result = engine.confirm(p.choice or "1")
        book.save(name, engine)
        if result is None:
            return "已取消待确认项。", engine, False
        if isinstance(result, NeedConfirm):
            return render_confirm(result), engine, False
        return render_applied(engine, result), engine, False
    if p.op == "undo":
        undone = engine.undo_batch(p.undo_n)
        book.save(name, engine)
        return f"已撤回 {len(undone)} 条。\n\n" + render_status(engine, name), engine, False
    if p.op == "keep_one":
        result = engine.keep_first_of_last_batch(p.fill_price)
        book.save(name, engine)
        return render_applied(engine, result), engine, False
    if p.op == "amend_price":
        result = engine.amend_last_price(p.fill_price or "")
        book.save(name, engine)
        return render_applied(engine, result), engine, False
    if p.op == "set":
        result = _set_value(engine, p.set_key or "", p.set_val or "", p.note)
        book.save(name, engine)
        return render_applied(engine, result), engine, False
    if p.op == "fill":
        result = engine.submit(_req(p))
        book.save(name, engine)
        if isinstance(result, NeedConfirm):
            return render_confirm(result), engine, False
        return render_applied(engine, result), engine, False
    if p.op == "unknown":
        raise ValueError(f"听不懂：{p.raw}\n输入 help 看用法。")
    raise ValueError(f"未处理的命令：{p.op}")


def run_line(name: str, engine, line: str) -> tuple[str, object, bool]:
    p = parse(line, _pending_keys(engine))
    if p is None:
        return "", engine, False
    return run_parsed(name, engine, p)


def _load_current(name: Optional[str] = None):
    n = name or book.current_name()
    if not n:
        raise FileNotFoundError("还没有账本。先：python ledger.py new 名称 --base 53.75 --shares 0")
    return book.load(n)


def cmd_new(args: argparse.Namespace) -> int:
    cfg = Config(
        lot_size=args.lot,
        up_pct=str(args.up),
        down_pct=str(args.down),
        skip_fill=not args.no_skip,
        allow_net_buy_over_zero=not args.net_buy_limit,
        allow_short=not args.no_short,
        end_at_zero=args.end_at_zero,
    )
    engine = book.create(
        args.name,
        base=str(args.base),
        shares=args.shares,
        opening_price=str(args.opening_price) if args.opening_price is not None else None,
        config=cfg,
    )
    _print(f"已建账本 {args.name} -> {book.book_path(args.name)}")
    _print(render_status(engine, args.name))
    return 0


def _repl(name: str, engine) -> int:
    _print("输入 help 看用法，quit 退出。")
    _print(render_status(engine, name))
    while True:
        try:
            line = input(render_prompt(name, engine))
        except (EOFError, KeyboardInterrupt):
            _print("")
            return 0
        try:
            out, eng, should_quit = run_line(name, engine, line)
        except Exception as e:
            _print(str(e))
            continue
        if should_quit:
            return 0
        if isinstance(eng, tuple):
            name, engine = eng
        else:
            engine = eng
        if out:
            _print(out)
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    _utf8()
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog="ledger", add_help=False)
    parser.add_argument("-h", "--help", action="store_true")
    sub = parser.add_subparsers(dest="cmd")

    p_new = sub.add_parser("new", add_help=False)
    p_new.add_argument("name")
    p_new.add_argument("--base", required=True, type=str)
    p_new.add_argument("--shares", required=True, type=int)
    p_new.add_argument("--opening-price", default=None, type=str)
    p_new.add_argument("--lot", default=100, type=int)
    p_new.add_argument("--up", default="0.85", type=str)
    p_new.add_argument("--down", default="0.8", type=str)
    p_new.add_argument("--no-skip", action="store_true")
    p_new.add_argument("--net-buy-limit", action="store_true")
    p_new.add_argument("--no-short", action="store_true")
    p_new.add_argument("--end-at-zero", action="store_true")

    sub.add_parser("list", add_help=False)
    p_open = sub.add_parser("open", add_help=False)
    p_open.add_argument("name")

    if not argv or argv[0] in {"gui", "ui"}:
        from .gui import main as gui_main

        return gui_main()
    if argv[0] == "repl":
        n, eng = _load_current()
        return _repl(n, eng)
    if argv[0] in {"-h", "--help", "help"}:
        _print(HELP)
        return 0

    if argv[0] == "new":
        args = parser.parse_args(argv)
        return cmd_new(args)
    if argv[0] == "list":
        _print(run_parsed("", None, Parsed(op="list"))[0])
        return 0
    if argv[0] == "open":
        if len(argv) < 2:
            _print("open 需要账本名")
            return 2
        n, eng = book.load(argv[1])
        book.set_current(n)
        rest = argv[2:]
        if not rest:
            _print(render_status(eng, n))
            return 0
        return _run_tokens(n, eng, rest)

    name = None
    rest = argv
    if book.exists(argv[0]):
        name = argv[0]
        rest = argv[1:]
    n, eng = _load_current(name)
    if not rest:
        return _repl(n, eng)
    return _run_tokens(n, eng, rest)


def _run_tokens(name: str, engine, tokens: list[str]) -> int:
    line = " ".join(tokens)
    try:
        out, eng, _ = run_line(name, engine, line)
    except Exception as e:
        _print(str(e))
        return 1
    if out:
        _print(out)
    return 0
