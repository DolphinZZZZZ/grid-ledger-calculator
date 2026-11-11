from __future__ import annotations

import sys
import tkinter as tk
from datetime import datetime
from tkinter import messagebox

from . import book
from .calc import GridProjection, project
from .cli import run_line
from .engine import Applied, Config, Engine, FillRequest, NeedConfirm
from .format import _side_cn
from .money import D, display_places, fee_permyriad_to_rate, fmt_price, integer_value, price_value, rate_to_fee_permyriad
from .parse import parse


BG = "#1b1c1e"
PANEL = "#24262a"
KEY = "#3c3f46"
KEY_MUTED = "#32353b"
BUY = "#c0392b"
SELL = "#1e8449"
ENTER = "#d97606"
LCD_BG = "#0c1610"
LCD_FG = "#c6f08a"
LCD_DIM = "#6f8f55"
TEXT = "#f2f2f2"
MUTED = "#9aa0a8"
TAPE_BG = "#141414"
TAPE_FG = "#d7d2c3"
WARN = "#c9a227"


def _ui_font(size: int, bold: bool = False):
    return ("Microsoft YaHei UI", size, "bold" if bold else "normal")


def _mono(size: int, bold: bool = False):
    return ("Consolas", size, "bold" if bold else "normal")


def _lighten(color: str, amt: int = 24) -> str:
    h = color.lstrip("#")
    rgb = [min(255, int(h[i : i + 2], 16) + amt) for i in (0, 2, 4)]
    return "#%02x%02x%02x" % tuple(rgb)


class PriceBuffer:
    def __init__(self) -> None:
        self.text = ""
        self.fresh = False
        self._raw: str | None = None

    def press(self, ch: str) -> str:
        self._raw = None
        if self.fresh:
            self.text = ""
            self.fresh = False
        if ch == ".":
            if "." in self.text:
                return self.text
            if self.text in ("", "-"):
                self.text += "0."
                return self.text
            self.text += "."
            return self.text
        if ch.isdigit():
            digits = self.text.replace(".", "").replace("-", "")
            if len(digits) >= 8:
                return self.text
            self.text += ch
        return self.text

    def backspace(self) -> str:
        self._raw = None
        self.fresh = False
        self.text = self.text[:-1]
        return self.text

    def clear(self) -> str:
        self._raw = None
        self.text = ""
        self.fresh = False
        return self.text

    def set(self, value: str, fresh: bool = True, places: int | None = None) -> str:
        self._raw = value if places is not None else None
        self.text = fmt_price(value, places) if places is not None else value
        self.fresh = fresh
        return self.text

    def price(self) -> str | None:
        t = self.text.strip()
        if not t or t in {".", "-", "-.", "0."}:
            return None
        return self._raw if self._raw is not None else t


def format_tape_applied(engine: Engine, applied: Applied) -> str:
    lines = ["-" * 32]
    if applied.note:
        lines.append(applied.note)
    fills = [f for f in applied.fills if f.kind != "adjust"]
    adjusts = [f for f in applied.fills if f.kind == "adjust"]
    for f in adjusts:
        lines.append(f"改账  {f.note}")
    for f in fills:
        kind = {"grid": "", "opening": "建仓 "}.get(f.kind, f.kind + " ")
        verb = _side_cn(f.side)
        lines.append(f"{kind}{verb} {f.qty}股")
        lines.append(f"  成交 {engine.format_price(f.fill_price)}  触发 {engine.format_price(f.trigger_price)}")
        cash_lab = "支出" if f.side == "buy" else "到账"
        lines.append(f"  {cash_lab} {engine.format_money(abs(D(f.cash)))}  费 {engine.format_money(f.fee)}")
    mk = engine.mark()
    lines.append(f"基准 {engine.format_price(engine.state.base)}  仓 {engine.state.position}")
    lines.append(f"增益 {engine.format_money(mk.gain, signed=True)}")
    return "\n".join(lines)


def format_tape_confirm(nc: NeedConfirm) -> str:
    lines = ["-" * 32, "需要确认", nc.message]
    for o in nc.options:
        lines.append(f"  {o.key}. {o.label}")
    return "\n".join(lines)


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.name: str | None = None
        self.engine: Engine | None = None
        self.buf = PriceBuffer()
        self._book_var = tk.StringVar(value="")
        self.save_var = tk.StringVar(value="自动存档")
        self._filling_list = False
        self._slot_names: list[str] = []
        self.trigger_var = tk.StringVar(value="")
        self.qty_var = tk.StringVar(value="100")
        self.lcd_var = tk.StringVar(value="")
        self.msg_var = tk.StringVar(value="")
        self._confirm_btns: list[tk.Widget] = []
        self._calc_win: CalcWindow | None = None
        self._calc_state: dict | None = book.load_calc_state()

        self._build()
        self._load_initial()
        self._refresh()
        self.root.bind("<Key>", self._on_key)

    def _build(self) -> None:
        r = self.root
        r.title("网格记账")
        r.configure(bg=BG)
        r.minsize(960, 820)
        r.geometry("1040x920")

        header = tk.Frame(r, bg=BG)
        header.pack(fill="x", padx=12, pady=(10, 6))
        tk.Label(header, text="网格记账", fg=TEXT, bg=BG, font=_ui_font(16, True)).pack(side="left")
        tk.Label(header, textvariable=self._book_var, fg=LCD_FG, bg=BG, font=_ui_font(13, True)).pack(side="left", padx=(12, 8))
        tk.Label(header, textvariable=self.save_var, fg=MUTED, bg=BG, font=_ui_font(10)).pack(side="left")
        self._btn(header, "改名", self._rename_slot, KEY_MUTED).pack(side="right")
        self._btn(header, "另存为", self._save_as, KEY).pack(side="right", padx=6)
        self._btn(header, "新建", self._new_book, KEY).pack(side="right")
        self._btn(header, "计算器", self._open_calc, KEY).pack(side="right", padx=6)
        self._btn(header, "手续费", self._edit_fees, KEY).pack(side="right")
        r.protocol("WM_DELETE_WINDOW", self._on_close)

        body = tk.Frame(r, bg=BG)
        body.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        top = tk.Frame(body, bg=BG)
        top.pack(side="top", fill="x")

        left = tk.Frame(top, bg=BG)
        left.pack(side="left", fill="both", expand=True, padx=(0, 12))

        right = tk.Frame(top, bg=BG, width=420)
        right.pack(side="right", fill="y")
        right.pack_propagate(False)

        bottom = tk.Frame(body, bg=TAPE_BG)
        bottom.pack(side="top", fill="both", expand=True, pady=(8, 0))

        self._build_ladder(left)
        self._build_stats(left)
        self._build_lcd(left)
        self._build_fields(left)
        self._build_cmd(left)
        self._build_slots(right)
        self._build_pad(right)
        self._build_tape(bottom)

    def _btn(self, parent, text, cmd, bg, fg=TEXT, font=None) -> tk.Button:
        b = tk.Button(
            parent,
            text=text,
            command=cmd,
            bg=bg,
            fg=fg,
            activebackground=_lighten(bg),
            activeforeground=fg,
            bd=0,
            relief="flat",
            font=font or _ui_font(11),
            takefocus=0,
            cursor="hand2",
            padx=10,
            pady=4,
        )
        return b

    def _build_ladder(self, parent) -> None:
        box = tk.Frame(parent, bg=PANEL)
        box.pack(fill="x", pady=(0, 8))
        box.columnconfigure(2, weight=1)
        self.lv = {}
        self.step_lab = {}
        rows = [
            ("sell2", "二次高抛", None, False, MUTED, TEXT),
            ("sell1", "高抛", "up", False, BUY, BUY),
            ("base", "基准", None, True, MUTED, LCD_FG),
            ("buy1", "低吸", "down", False, SELL, SELL),
            ("buy2", "二次低吸", None, False, MUTED, TEXT),
        ]
        for i, (key, lab, step, accent, lab_fg, val_fg) in enumerate(rows):
            tk.Label(box, text=lab, fg=lab_fg, bg=PANEL, font=_ui_font(11), width=8, anchor="w").grid(
                row=i, column=0, sticky="w", padx=(12, 4), pady=4
            )
            step_w = tk.Label(
                box,
                text="",
                fg=LCD_DIM if step else PANEL,
                bg=PANEL,
                font=_ui_font(10),
                width=8,
                anchor="w",
                cursor="hand2" if step else "arrow",
            )
            step_w.grid(row=i, column=1, sticky="w")
            if step:
                step_w.bind("<Button-1>", lambda e, which=step: self._edit_step(which))
                self.step_lab[step] = step_w
            val = tk.Label(
                box,
                text="—",
                fg=val_fg,
                bg=PANEL,
                font=_mono(28 if accent else 18, True),
                anchor="center" if accent else "e",
                cursor="hand2",
            )
            val.grid(row=i, column=2, sticky="ew" if accent else "e", padx=4, pady=4)
            val.bind("<Button-1>", lambda e, k=key: self._use_level(k))
            self.lv[key] = val

    def _build_stats(self, parent) -> None:
        self.stat = {}
        rows = (
            (("start_base", "初始基准"), ("init", "初始持仓"), ("pos", "当前持仓"), ("net", "净买量")),
            (("cnt", "笔数"), ("gain", "增益"), ("cash", "占用")),
        )
        for items in rows:
            box = tk.Frame(parent, bg=BG)
            box.pack(fill="x", pady=(0, 6))
            for i, (key, lab) in enumerate(items):
                cell = tk.Frame(box, bg=PANEL)
                pad = (0, 6) if i < len(items) - 1 else (0, 0)
                cell.pack(side="left", fill="x", expand=True, padx=pad)
                tk.Label(cell, text=lab, fg=MUTED, bg=PANEL, font=_ui_font(9)).pack(anchor="w", padx=8, pady=(6, 0))
                v = tk.Label(cell, text="—", fg=TEXT, bg=PANEL, font=_ui_font(12, True))
                v.pack(anchor="w", padx=8, pady=(0, 6))
                self.stat[key] = v
                if key == "init":
                    cell.configure(cursor="hand2")
                    v.configure(cursor="hand2")
                    cell.bind("<Button-1>", lambda e: self._edit_initial())
                    v.bind("<Button-1>", lambda e: self._edit_initial())
                    for child in cell.winfo_children():
                        child.bind("<Button-1>", lambda e: self._edit_initial())

    def _build_lcd(self, parent) -> None:
        lcd = tk.Frame(parent, bg=LCD_BG, highlightbackground="#1f3a28", highlightthickness=1)
        lcd.pack(fill="x", pady=(0, 8))
        tk.Label(lcd, text="成交价", fg=LCD_DIM, bg=LCD_BG, font=_ui_font(9)).pack(anchor="w", padx=12, pady=(8, 0))
        self.lcd = tk.Label(
            lcd,
            textvariable=self.lcd_var,
            fg=LCD_FG,
            bg=LCD_BG,
            font=_mono(36, True),
            anchor="e",
        )
        self.lcd.pack(fill="x", padx=12, pady=(0, 4))
        self.lcd_hint = tk.Label(lcd, text="", fg=LCD_DIM, bg=LCD_BG, font=_ui_font(10), anchor="w")
        self.lcd_hint.pack(fill="x", padx=12, pady=(0, 8))

    def _build_fields(self, parent) -> None:
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=(0, 8))
        tk.Label(row, text="触发价", fg=MUTED, bg=BG, font=_ui_font(10)).pack(side="left")
        e1 = tk.Entry(
            row,
            textvariable=self.trigger_var,
            bg=PANEL,
            fg=TEXT,
            insertbackground=TEXT,
            bd=0,
            font=_mono(14),
            width=10,
        )
        e1.pack(side="left", padx=(6, 16), ipady=4)
        tk.Label(row, text="股数", fg=MUTED, bg=BG, font=_ui_font(10)).pack(side="left")
        self.qty_entry = tk.Entry(
            row,
            textvariable=self.qty_var,
            bg=PANEL,
            fg=TEXT,
            insertbackground=TEXT,
            bd=0,
            font=_mono(14),
            width=8,
        )
        self.qty_entry.pack(side="left", padx=6, ipady=4)
        tk.Label(row, text="空=自动触发 / 默认单笔跳格", fg=MUTED, bg=BG, font=_ui_font(9)).pack(side="left")
        self.trigger_entry = e1

    def _build_pad(self, parent) -> None:
        wrap = tk.Frame(parent, bg=BG)
        wrap.pack(fill="both", expand=True)
        self.pad = tk.Frame(wrap, bg=BG)
        self.pad.grid(row=0, column=0, sticky="nsew")
        self.confirm_pad = tk.Frame(wrap, bg=BG)
        wrap.grid_columnconfigure(0, weight=1)
        wrap.grid_rowconfigure(0, weight=1)

        keys = [
            ("7", 0, 0, KEY, lambda: self._press("7")),
            ("8", 0, 1, KEY, lambda: self._press("8")),
            ("9", 0, 2, KEY, lambda: self._press("9")),
            ("买", 0, 3, BUY, lambda: self._go("buy")),
            ("4", 1, 0, KEY, lambda: self._press("4")),
            ("5", 1, 1, KEY, lambda: self._press("5")),
            ("6", 1, 2, KEY, lambda: self._press("6")),
            ("卖", 1, 3, SELL, lambda: self._go("sell")),
            ("1", 2, 0, KEY, lambda: self._press("1")),
            ("2", 2, 1, KEY, lambda: self._press("2")),
            ("3", 2, 2, KEY, lambda: self._press("3")),
            ("入账", 2, 3, ENTER, lambda: self._go(None)),
            ("0", 3, 0, KEY, lambda: self._press("0")),
            (".", 3, 1, KEY, lambda: self._press(".")),
            ("⌫", 3, 2, KEY_MUTED, self._back),
            ("撤回", 3, 3, KEY_MUTED, self._undo),
            ("C", 4, 0, KEY_MUTED, self._clear),
            ("股", 4, 1, KEY_MUTED, self._to_qty),
            ("现价", 4, 2, KEY_MUTED, self._mark),
            ("一格", 4, 3, KEY_MUTED, self._keep_one),
            ("不动", 5, 0, KEY_MUTED, self._reject),
            ("改价", 5, 1, KEY_MUTED, self._amend),
            ("＋", 5, 2, BUY, lambda: self._nudge_price(1)),
            ("－", 5, 3, SELL, lambda: self._nudge_price(-1)),
        ]
        for text, row, col, color, cmd in keys:
            b = tk.Button(
                self.pad,
                text=text,
                command=cmd,
                bg=color,
                fg=TEXT,
                activebackground=_lighten(color),
                activeforeground=TEXT,
                bd=0,
                relief="flat",
                font=_ui_font(14, True),
                takefocus=0,
                cursor="hand2",
            )
            b.grid(row=row, column=col, sticky="nsew", padx=4, pady=4, ipadx=8, ipady=10)
        for i in range(4):
            self.pad.grid_columnconfigure(i, weight=1, uniform="keys")
        for i in range(6):
            self.pad.grid_rowconfigure(i, weight=1)

        self.confirm_msg = tk.Label(
            self.confirm_pad,
            text="",
            fg=TEXT,
            bg=PANEL,
            font=_ui_font(11),
            wraplength=400,
            justify="left",
            anchor="w",
        )
        self.confirm_msg.pack(fill="x", pady=(0, 8), ipady=8, ipadx=8)
        self.confirm_btns = tk.Frame(self.confirm_pad, bg=BG)
        self.confirm_btns.pack(fill="both", expand=True)

    def _build_cmd(self, parent) -> None:
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=(8, 0))
        tk.Label(row, text="命令", fg=MUTED, bg=BG, font=_ui_font(10)).pack(side="left")
        self.cmd_var = tk.StringVar()
        self.cmd_entry = tk.Entry(
            row,
            textvariable=self.cmd_var,
            bg=PANEL,
            fg=TEXT,
            insertbackground=TEXT,
            bd=0,
            font=_ui_font(11),
        )
        self.cmd_entry.pack(side="left", fill="x", expand=True, padx=6, ipady=5)
        self.cmd_entry.bind("<Return>", lambda e: self._run_cmd())
        self._btn(row, "执行", self._run_cmd, KEY).pack(side="left")
        tk.Label(parent, textvariable=self.msg_var, fg=MUTED, bg=BG, font=_ui_font(9), anchor="w").pack(fill="x", pady=(4, 0))

    def _build_slots(self, parent) -> None:
        box = tk.Frame(parent, bg=TAPE_BG)
        box.pack(fill="x")
        tk.Label(box, text="存档（点击切换）", fg=MUTED, bg=TAPE_BG, font=_ui_font(10)).pack(
            anchor="w", padx=8, pady=(8, 0)
        )
        self.slot_list = tk.Listbox(
            box,
            bg="#1a1a1a",
            fg=TAPE_FG,
            selectbackground=ENTER,
            selectforeground=TEXT,
            activestyle="none",
            bd=0,
            highlightthickness=0,
            font=_mono(10),
            height=5,
            exportselection=False,
        )
        self.slot_list.pack(fill="x", padx=8, pady=(4, 8))
        self.slot_list.bind("<<ListboxSelect>>", self._on_slot_select)

    def _build_tape(self, parent) -> None:
        tk.Label(parent, text="纸带", fg=MUTED, bg=TAPE_BG, font=_ui_font(10)).pack(
            anchor="w", padx=10, pady=(8, 0)
        )
        self.tape = tk.Text(
            parent,
            bg=TAPE_BG,
            fg=TAPE_FG,
            insertbackground=TAPE_FG,
            bd=0,
            font=_mono(11),
            wrap="word",
            height=8,
            state="disabled",
            highlightthickness=0,
        )
        self.tape.pack(fill="both", expand=True, padx=8, pady=8)
        self.tape.tag_configure("buy", foreground="#e07070")
        self.tape.tag_configure("sell", foreground="#7dcea0")
        self.tape.tag_configure("warn", foreground="#e8c35a")
        self.tape.tag_configure("dim", foreground="#888")

    def _load_initial(self) -> None:
        name = book.current_name()
        if name and book.exists(name):
            self.name, self.engine = book.load(name)
        elif book.list_books():
            self.name, self.engine = book.load(book.list_books()[0])
            book.set_current(self.name)
        self._persist_unlocked()
        self._rebuild_slots()

    def _persist_unlocked(self) -> None:
        if self.engine and self.name and self.engine.unlock_limits():
            self._autosave()

    def _autosave(self) -> None:
        if not self.engine or not self.name:
            return
        book.save(self.name, self.engine)
        book.set_current(self.name)
        self.save_var.set("已自动保存 " + datetime.now().strftime("%H:%M:%S"))
        self._rebuild_slots()

    def _rebuild_slots(self) -> None:
        self._filling_list = True
        try:
            self.slot_list.delete(0, "end")
            self._slot_names = []
            current_idx = 0
            slots = book.list_slots()
            if not slots:
                self._book_var.set("（无存档）")
                return
            for i, info in enumerate(slots):
                mark = "● " if info["name"] == self.name else "  "
                raw = info.get("saved_at") or ""
                when = raw.split("T", 1)[1][:8] if "T" in raw else ""
                line = f"{mark}{info['name']}  基准{info['base']}  仓{info['position']}  {when}"
                self.slot_list.insert("end", line)
                self._slot_names.append(info["name"])
                if info["name"] == self.name:
                    current_idx = i
                    if when:
                        self.save_var.set("已自动保存 " + when)
            if self.name:
                self._book_var.set(self.name)
            if self._slot_names:
                self.slot_list.selection_clear(0, "end")
                self.slot_list.selection_set(current_idx)
                self.slot_list.activate(current_idx)
                self.slot_list.see(current_idx)
        finally:
            self._filling_list = False

    def _on_slot_select(self, _event=None) -> None:
        if self._filling_list:
            return
        sel = self.slot_list.curselection()
        if not sel:
            return
        name = self._slot_names[sel[0]]
        self._open_book(name)

    def _open_book(self, name: str) -> None:
        if name == self.name:
            return
        if self.engine and self.name:
            try:
                book.save(self.name, self.engine)
            except Exception:
                pass
        self.name, self.engine = book.load(name)
        book.set_current(name)
        self._persist_unlocked()
        self._book_var.set(name)
        self.tape.configure(state="normal")
        self.tape.delete("1.0", "end")
        self.tape.configure(state="disabled")
        self._tape(f"切换存档 {name}", "dim")
        self._show_confirm(self.engine.pending if self.engine else None)
        self._rebuild_slots()
        self._refresh()

    def _save_as(self) -> None:
        if not self.engine or not self.name:
            self._flash("没有当前存档")
            return
        stamp = datetime.now().strftime("%m%d-%H%M")
        name = _ask_str(self.root, "另存为", "新存档名称", f"{self.name}-{stamp}")
        if not name:
            return
        try:
            book.save(self.name, self.engine)
            book.duplicate(self.name, name)
        except Exception as e:
            messagebox.showerror("另存为失败", str(e), parent=self.root)
            return
        self._tape(f"已另存为 {name}", "dim")
        self._open_book(name)

    def _rename_slot(self) -> None:
        if not self.name:
            self._flash("没有当前存档")
            return
        name = _ask_str(self.root, "改名", "存档新名称", self.name)
        if not name or name == self.name:
            return
        try:
            if self.engine:
                book.save(self.name, self.engine)
            book.rename(self.name, name)
        except Exception as e:
            messagebox.showerror("改名失败", str(e), parent=self.root)
            return
        self.name = name
        book.set_current(name)
        self._book_var.set(name)
        self._tape(f"存档已改名为 {name}", "dim")
        self._rebuild_slots()
        self._refresh()

    def _on_close(self) -> None:
        try:
            if self._calc_win is not None and self._calc_win.win.winfo_exists():
                self._remember_calc(self._calc_win.snapshot())
            if self.engine and self.name:
                book.save(self.name, self.engine)
                book.set_current(self.name)
        except Exception:
            pass
        self.root.destroy()

    def _reload(self) -> None:
        if self.name:
            cur = self.name
            self.name = None
            self._open_book(cur)

    def _sync_lcd(self) -> None:
        self.lcd_var.set(self.buf.text if self.buf.text else "0")

    def _press(self, ch: str) -> None:
        if self.engine and self.engine.pending and ch.isdigit():
            keys = {o.key for o in self.engine.pending.options}
            if ch in keys:
                self._confirm(ch)
                return
        self.buf.press(ch)
        self._sync_lcd()

    def _back(self) -> None:
        self.buf.backspace()
        self._sync_lcd()

    def _nudge_price(self, direction: int) -> None:
        try:
            price = D(self.buf.text)
            places = max(2, -price.as_tuple().exponent)
            adjusted = price + D(direction).scaleb(-places)
            price_value(adjusted, "成交价")
        except ValueError as e:
            self._input_error(e)
            return
        self.buf.set(fmt_price(adjusted, places), fresh=True)
        self._sync_lcd()

    def _clear(self) -> None:
        if self.engine and self.engine.pending:
            self._reject()
            return
        self.buf.clear()
        self.trigger_var.set("")
        self._sync_lcd()

    def _to_qty(self) -> None:
        p = self.buf.price()
        try:
            qty = integer_value(p, "股数", minimum=1)
        except ValueError as e:
            self._input_error(e)
            return
        self.qty_var.set(str(qty))
        self.buf.clear()
        self._sync_lcd()

    def _use_level(self, key: str) -> None:
        if not self.engine:
            return
        lv = self.engine.levels()
        price = getattr(lv, key)
        self.buf.set(price, fresh=True, places=self.engine.config.display_places)
        self._sync_lcd()
        if key.startswith("buy"):
            self.msg_var.set("已填低吸价，按 买 或 入账")
        elif key.startswith("sell"):
            self.msg_var.set("已填高抛价，按 卖 或 入账")
        else:
            self.msg_var.set("已填基准价")

    def _qty(self) -> int | None:
        raw = self.qty_var.get().strip()
        if not raw:
            return None
        try:
            q = int(raw)
        except ValueError:
            raise ValueError("股数必须是整数")
        if q <= 0:
            raise ValueError("股数必须为正")
        if self.engine and q == self.engine.config.lot_size:
            return None
        return q

    def _trigger(self) -> str | None:
        t = self.trigger_var.get().strip()
        return t or None

    def _go(self, side: str | None) -> None:
        price = self.buf.price()
        if not price:
            self._input_error("请输入价格")
            return
        try:
            qty = self._qty()
        except ValueError as e:
            self._input_error(e)
            return
        self._submit(
            FillRequest(
                fill_price=price,
                trigger=self._trigger(),
                side=side,
                qty=qty,
            )
        )

    def _submit(self, req: FillRequest) -> bool:
        if not self.engine or not self.name:
            self._flash("请先新建或打开账本")
            return False
        try:
            result = self.engine.submit(req)
        except Exception as e:
            self._input_error(e)
            return False
        self._after_result(result)
        self.buf.set(req.fill_price or req.trigger or self.buf.price(), fresh=True, places=self.engine.config.display_places)
        self._sync_lcd()
        return True

    def _after_result(self, result: Applied | NeedConfirm | None) -> None:
        if result is None:
            self._tape("已取消", "dim")
            self._show_confirm(None)
            self._autosave()
            self._refresh()
            return
        if isinstance(result, NeedConfirm):
            self._tape(format_tape_confirm(result), "warn")
            self._show_confirm(result)
            self._autosave()
            self._refresh()
            return
        tag = None
        fills = [f for f in result.fills if f.kind != "adjust"]
        if fills:
            tag = "buy" if fills[0].side == "buy" else "sell"
        self._tape(format_tape_applied(self.engine, result), tag)
        self._show_confirm(None)
        self.trigger_var.set("")
        if self.engine:
            self.qty_var.set(str(self.engine.config.lot_size))
        self._autosave()
        self._refresh()

    def _confirm(self, key: str) -> None:
        if not self.engine or not self.name or not self.engine.pending:
            return
        try:
            result = self.engine.confirm(key)
        except Exception as e:
            self._input_error(e)
            return
        self._after_result(result)

    def _reject(self) -> None:
        if not self.engine or not self.name:
            return
        if not self.engine.pending:
            return
        self.engine.reject()
        self._after_result(None)

    def _undo(self) -> None:
        if not self.engine or not self.name:
            return
        try:
            undone = self.engine.undo_batch(1)
        except Exception as e:
            self._input_error(e)
            return
        self._tape(f"撤回 {len(undone)} 条\n基准 {self.engine.format_price(self.engine.state.base)}  仓 {self.engine.state.position}", "dim")
        self._show_confirm(None)
        self._autosave()
        self._refresh()

    def _keep_one(self) -> None:
        if not self.engine or not self.name:
            return
        try:
            result = self.engine.keep_first_of_last_batch(self.buf.price())
        except Exception as e:
            self._input_error(e)
            return
        self._after_result(result)

    def _amend(self) -> None:
        price = self.buf.price()
        if not price:
            self._input_error("先输入要改成的成交价")
            return
        if not self.engine or not self.name:
            return
        try:
            result = self.engine.amend_last_price(price)
        except Exception as e:
            self._input_error(e)
            return
        self._after_result(result)

    def _mark(self) -> None:
        price = self.buf.price()
        if not price or not self.engine or not self.name:
            self._input_error("先输入现价")
            return
        try:
            self.engine.set_mark_price(price)
        except ValueError as e:
            self._input_error(e)
            return
        self._tape(f"现价 {self.engine.format_price(price)}\n增益 {self.engine.format_money(self.engine.mark().gain, signed=True)}", "dim")
        self.buf.fresh = True
        self._autosave()
        self._refresh()

    def _edit_step(self, which: str) -> None:
        if not self.engine or not self.name:
            self._flash("请先新建或打开账本")
            return
        if which == "up":
            cur = self.engine.config.up_pct
            title, prompt = "上涨步长", "高抛步长（%），例如 0.85"
        else:
            cur = self.engine.config.down_pct
            title, prompt = "下跌步长", "低吸步长（%），例如 0.8"
        validator = (lambda value: self.engine.validate_steps(up_pct=value)) if which == "up" else (lambda value: self.engine.validate_steps(down_pct=value))
        val = _ask_str(self.root, title, prompt, str(cur), validator=validator)
        if val is None:
            return
        try:
            if which == "up":
                result = self.engine.set_steps(up_pct=val)
            else:
                result = self.engine.set_steps(down_pct=val)
        except Exception as e:
            self._input_error(e)
            return
        self._after_result(result)

    def _edit_fees(self) -> None:
        if not self.engine or not self.name:
            self._flash("请先新建或打开账本")
            return
        cfg = self.engine.config
        dlg = FeeDialog(self.root, cfg.buy_fee_rate, cfg.sell_fee_rate, cfg.stamp_tax_rate)
        if not dlg.result:
            return
        rates = dlg.result
        if (
            rates["buy_fee_rate"] == cfg.buy_fee_rate
            and rates["sell_fee_rate"] == cfg.sell_fee_rate
            and rates["stamp_tax_rate"] == cfg.stamp_tax_rate
        ):
            return
        try:
            result = self.engine.set_fee_rates(**rates)
        except Exception as e:
            self._input_error(e)
            return
        if not result.fills:
            return
        self._after_result(result)

    def _edit_initial(self) -> None:
        if not self.engine or not self.name:
            self._flash("请先新建或打开账本")
            return
        val = _ask_int(
            self.root,
            "初始持仓",
            "可负。当前持仓按差额同步，保留净买量和网格增益。填了建仓价时，建仓现金和占用按建仓价重算。",
            self.engine.state.initial_shares,
        )
        if val is None:
            return
        try:
            result = self.engine.set_initial_shares(val)
        except Exception as e:
            self._input_error(e)
            return
        self._after_result(result)

    def _run_cmd(self) -> None:
        line = self.cmd_var.get().strip()
        if not line:
            return
        if not self.engine or not self.name:
            self._flash("请先新建或打开账本")
            return
        try:
            p = parse(line, {o.key for o in self.engine.pending.options} if self.engine.pending else None)
        except ValueError as e:
            self._input_error(e)
            return
        if p and p.op == "fill":
            accepted = self._submit(
                FillRequest(
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
            )
            if accepted:
                self.cmd_var.set("")
            return
        try:
            out, eng, _ = run_line(self.name, self.engine, line)
        except Exception as e:
            self._input_error(e)
            return
        if isinstance(eng, tuple):
            self.name, self.engine = eng
        else:
            self.engine = eng
        self._tape(out.strip() or "OK", "dim")
        self.cmd_var.set("")
        self._show_confirm(self.engine.pending if self.engine else None)
        self._autosave()
        self._refresh()

    def _new_book(self) -> None:
        dlg = NewBookDialog(self.root)
        if not dlg.result:
            return
        try:
            engine = book.create(**dlg.result)
        except Exception as e:
            messagebox.showerror("新建失败", str(e), parent=self.root)
            return
        self.name = dlg.result["name"]
        self.engine = engine
        book.set_current(self.name)
        self.save_var.set("已自动保存 " + datetime.now().strftime("%H:%M:%S"))
        self._rebuild_slots()
        self._tape(f"新建存档 {self.name}", "dim")
        self._refresh()

    def _show_confirm(self, nc: NeedConfirm | None) -> None:
        for w in self.confirm_btns.winfo_children():
            w.destroy()
        if nc is None:
            self.confirm_pad.grid_forget()
            self.pad.grid(row=0, column=0, sticky="nsew")
            return
        self.pad.grid_forget()
        self.confirm_pad.grid(row=0, column=0, sticky="nsew")
        self.confirm_msg.configure(text=nc.message)
        for o in nc.options:
            color = KEY_MUTED if o.overrides.get("noop") else ENTER
            b = tk.Button(
                self.confirm_btns,
                text=f"{o.key}. {o.label}",
                command=lambda k=o.key: self._confirm(k),
                bg=color,
                fg=TEXT,
                activebackground=_lighten(color),
                bd=0,
                relief="flat",
                font=_ui_font(12, True),
                takefocus=0,
                cursor="hand2",
                wraplength=380,
                justify="left",
            )
            b.pack(fill="x", pady=4, ipady=10)

    def _refresh(self) -> None:
        if not self.engine:
            for lab in self.lv.values():
                lab.configure(text="—")
            for lab in self.stat.values():
                lab.configure(text="—")
            for lab in self.step_lab.values():
                lab.configure(text="")
            self.lcd_hint.configure(text="没有账本")
            self.msg_var.set("点「新建」开始")
            self._sync_lcd()
            return
        lv = self.engine.levels()
        self.lv["buy2"].configure(text=self.engine.format_price(lv.buy2))
        self.lv["buy1"].configure(text=self.engine.format_price(lv.buy1))
        self.lv["base"].configure(text=self.engine.format_price(lv.base))
        self.lv["sell1"].configure(text=self.engine.format_price(lv.sell1))
        self.lv["sell2"].configure(text=self.engine.format_price(lv.sell2))
        self.step_lab["up"].configure(text=f"{self.engine.config.up_pct}%")
        self.step_lab["down"].configure(text=f"{self.engine.config.down_pct}%")
        st = self.engine.state
        mk = self.engine.mark()
        self.stat["start_base"].configure(text=self.engine.format_price(self.engine.initial_base()))
        self.stat["init"].configure(text=str(st.initial_shares))
        self.stat["pos"].configure(text=str(st.position))
        self.stat["net"].configure(text=f"{st.net_bought():+d}")
        self.stat["cnt"].configure(text=f"买{st.buy_count}/卖{st.sell_count}")
        gain = self.engine.format_money(mk.gain, signed=True)
        self.stat["gain"].configure(text=gain, fg="#7dcea0" if D(mk.gain) >= 0 else "#e07070")
        self.stat["cash"].configure(text=self.engine.format_money(mk.occupied))
        self.lcd_hint.configure(
            text=f"高抛 {self.engine.format_price(lv.sell1)}    基准 {self.engine.format_price(lv.base)}    低吸 {self.engine.format_price(lv.buy1)}"
        )
        pending = "待确认：按数字键选" if self.engine.pending else ""
        self.msg_var.set(pending or f"{self.name}  现价 {self.engine.format_price(mk.price)}")
        title = f"网格记账 — {self.name}  基准 {self.engine.format_price(st.base)}"
        self.root.title(title)
        self._sync_lcd()

    def _tape(self, text: str, tag: str | None = None) -> None:
        self.tape.configure(state="normal")
        if self.tape.index("end-1c") != "1.0":
            self.tape.insert("end", "\n")
        start = self.tape.index("end-1c")
        self.tape.insert("end", text)
        if tag:
            self.tape.tag_add(tag, start, "end-1c")
        self.tape.see("end")
        self.tape.configure(state="disabled")

    def _flash(self, msg: str) -> None:
        self.msg_var.set(msg)
        self._tape(msg, "warn")

    def _input_error(self, error) -> None:
        self._flash(str(error))
        messagebox.showerror("输入有误", str(error), parent=self.root)

    def _calc_defaults(self) -> dict:
        if self.engine:
            return {
                "side": "sell",
                "start": self.engine.state.base,
                "display_places": self.engine.config.display_places,
                "up": self.engine.config.up_pct,
                "down": self.engine.config.down_pct,
                "n": "5",
            }
        return {"side": "sell", "start": "53.75", "up": "0.85", "down": "0.8", "n": "5"}

    def _remember_calc(self, state: dict) -> None:
        self._calc_state = dict(state)
        try:
            book.save_calc_state(self._calc_state)
        except Exception:
            pass

    def _on_calc_closed(self, state: dict) -> None:
        self._remember_calc(state)
        self._calc_win = None

    def _open_calc(self) -> None:
        if self._calc_win is not None:
            try:
                if self._calc_win.win.winfo_exists():
                    self._calc_win._close()
                    return
            except tk.TclError:
                pass
        defaults = self._calc_state if self._calc_state else self._calc_defaults()
        self._calc_win = CalcWindow(
            self.root,
            defaults,
            fill_from_book=self._calc_defaults,
            on_close=self._on_calc_closed,
            on_change=self._remember_calc,
        )

    def _on_key(self, event: tk.Event) -> str | None:
        w = event.widget
        try:
            if w is not None and w.winfo_toplevel() is not self.root:
                return None
        except (tk.TclError, AttributeError):
            return None
        w = self.root.focus_get()
        if w in (self.cmd_entry, self.trigger_entry, self.qty_entry):
            return None
        if event.keysym in ("BackSpace",):
            self._back()
            return "break"
        if event.keysym in ("Escape",):
            self._clear()
            return "break"
        if event.keysym in ("Return", "KP_Enter"):
            self._go(None)
            return "break"
        ch = event.char
        if ch in "0123456789.":
            self._press(ch)
            return "break"
        if ch in ("b", "B"):
            self._go("buy")
            return "break"
        if ch in ("s", "S"):
            self._go("sell")
            return "break"
        if ch in ("u", "U"):
            self._undo()
            return "break"
        return None


class CalcWindow:
    def __init__(self, parent: tk.Tk, defaults: dict, fill_from_book=None, on_close=None, on_change=None) -> None:
        self._fill_from_book = fill_from_book
        self._on_close = on_close
        self._on_change = on_change
        win = tk.Toplevel(parent)
        self.win = win
        win.title("网格计算器")
        win.configure(bg=BG)
        win.transient(parent)
        win.minsize(440, 560)
        parent.update_idletasks()
        try:
            x = parent.winfo_rootx() + parent.winfo_width() + 12
            y = parent.winfo_rooty()
            win.geometry(f"480x680+{x}+{y}")
        except tk.TclError:
            win.geometry("480x680")
        win.protocol("WM_DELETE_WINDOW", self._close)

        side = str(defaults.get("side", "sell"))
        if side not in ("sell", "buy"):
            side = "sell"
        self.side_var = tk.StringVar(value=side)
        self.start_var = tk.StringVar()
        self._start_source = None
        self._set_start(defaults)
        self.start_var.trace_add("write", lambda *_: self._clear_start_source())
        self.up_var = tk.StringVar(value=str(defaults.get("up", "0.85")))
        self.down_var = tk.StringVar(value=str(defaults.get("down", "0.8")))
        self.n_var = tk.StringVar(value=str(defaults.get("n", "5")))
        self.err_var = tk.StringVar(value="")
        self.stop_var = tk.StringVar(value="—")
        self.avg_var = tk.StringVar(value="—")

        pad = tk.Frame(win, bg=BG)
        pad.pack(fill="both", expand=True, padx=12, pady=10)

        tk.Label(pad, text="网格计算器", fg=TEXT, bg=BG, font=_ui_font(16, True)).pack(anchor="w")
        tk.Label(
            pad,
            text="选一个方向，按触发价逐格推演。不算费用，不改账本。",
            fg=MUTED,
            bg=BG,
            font=_ui_font(9),
        ).pack(anchor="w", pady=(0, 8))

        dir_box = tk.Frame(pad, bg=BG)
        dir_box.pack(fill="x", pady=(0, 8))
        tk.Label(dir_box, text="方向", fg=MUTED, bg=BG, font=_ui_font(9)).pack(anchor="w")
        dir_btns = tk.Frame(dir_box, bg=BG)
        dir_btns.pack(fill="x", pady=(4, 0))
        self.sell_btn = tk.Button(
            dir_btns,
            text="上涨卖出",
            command=lambda: self._set_side("sell"),
            fg=TEXT,
            bd=0,
            relief="flat",
            font=_ui_font(12, True),
            takefocus=0,
            cursor="hand2",
            pady=8,
        )
        self.buy_btn = tk.Button(
            dir_btns,
            text="下跌买入",
            command=lambda: self._set_side("buy"),
            fg=TEXT,
            bd=0,
            relief="flat",
            font=_ui_font(12, True),
            takefocus=0,
            cursor="hand2",
            pady=8,
        )
        self.sell_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.buy_btn.pack(side="left", fill="x", expand=True)

        form = tk.Frame(pad, bg=BG)
        form.pack(fill="x")
        start_cell = tk.Frame(form, bg=PANEL)
        start_cell.grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=4)
        tk.Label(start_cell, text="起始价格", fg=MUTED, bg=PANEL, font=_ui_font(9)).pack(anchor="w", padx=8, pady=(6, 0))
        tk.Entry(
            start_cell,
            textvariable=self.start_var,
            bg=LCD_BG,
            fg=LCD_FG,
            insertbackground=LCD_FG,
            bd=0,
            font=_mono(16),
        ).pack(fill="x", padx=8, pady=(0, 8), ipady=4)

        n_cell = tk.Frame(form, bg=PANEL)
        n_cell.grid(row=0, column=1, sticky="ew", pady=4)
        tk.Label(n_cell, text="触发次数", fg=MUTED, bg=PANEL, font=_ui_font(9)).pack(anchor="w", padx=8, pady=(6, 0))
        tk.Entry(
            n_cell,
            textvariable=self.n_var,
            bg=LCD_BG,
            fg=LCD_FG,
            insertbackground=LCD_FG,
            bd=0,
            font=_mono(16),
        ).pack(fill="x", padx=8, pady=(0, 8), ipady=4)

        step_cell = tk.Frame(form, bg=PANEL)
        step_cell.grid(row=1, column=0, columnspan=2, sticky="ew", pady=4)
        self.step_lab = tk.Label(step_cell, text="上涨步长 %", fg=MUTED, bg=PANEL, font=_ui_font(9))
        self.step_lab.pack(anchor="w", padx=8, pady=(6, 0))
        self.step_entry = tk.Entry(
            step_cell,
            textvariable=self.up_var,
            bg=LCD_BG,
            fg=LCD_FG,
            insertbackground=LCD_FG,
            bd=0,
            font=_mono(16),
        )
        self.step_entry.pack(fill="x", padx=8, pady=(0, 8), ipady=4)
        form.columnconfigure(0, weight=1)
        form.columnconfigure(1, weight=1)

        btns = tk.Frame(pad, bg=BG)
        btns.pack(fill="x", pady=(8, 4))
        tk.Button(
            btns,
            text="计算",
            command=self._compute,
            bg=ENTER,
            fg=TEXT,
            activebackground=_lighten(ENTER),
            bd=0,
            relief="flat",
            font=_ui_font(12, True),
            takefocus=0,
            cursor="hand2",
            padx=16,
            pady=6,
        ).pack(side="left")
        if fill_from_book is not None:
            tk.Button(
                btns,
                text="填入账本参数",
                command=self._fill_book,
                bg=KEY,
                fg=TEXT,
                activebackground=_lighten(KEY),
                bd=0,
                relief="flat",
                font=_ui_font(11),
                takefocus=0,
                cursor="hand2",
                padx=12,
                pady=6,
            ).pack(side="left", padx=(8, 0))

        tk.Label(pad, textvariable=self.err_var, fg=WARN, bg=BG, font=_ui_font(10), wraplength=440, justify="left").pack(
            anchor="w", pady=(4, 6)
        )

        card = tk.Frame(pad, bg=PANEL)
        card.pack(fill="x")
        self.card_title = tk.Label(card, text="上涨卖出", fg=BUY, bg=PANEL, font=_ui_font(11, True))
        self.card_title.pack(anchor="w", padx=10, pady=(8, 0))
        row = tk.Frame(card, bg=PANEL)
        row.pack(fill="x", padx=10, pady=(4, 8))
        left = tk.Frame(row, bg=PANEL)
        left.pack(side="left", fill="x", expand=True)
        tk.Label(left, text="停止价", fg=MUTED, bg=PANEL, font=_ui_font(9)).pack(anchor="w")
        tk.Label(left, textvariable=self.stop_var, fg=TEXT, bg=PANEL, font=_mono(18, True)).pack(anchor="w")
        right = tk.Frame(row, bg=PANEL)
        right.pack(side="left", fill="x", expand=True)
        tk.Label(right, text="均价", fg=MUTED, bg=PANEL, font=_ui_font(9)).pack(anchor="w")
        tk.Label(right, textvariable=self.avg_var, fg=TEXT, bg=PANEL, font=_mono(18, True)).pack(anchor="w")

        tk.Label(pad, text="格次表（触发价）", fg=MUTED, bg=BG, font=_ui_font(9)).pack(anchor="w", pady=(10, 4))
        table_box = tk.Frame(pad, bg=TAPE_BG)
        table_box.pack(fill="both", expand=True)
        scroll = tk.Scrollbar(table_box)
        scroll.pack(side="right", fill="y")
        self.table = tk.Text(
            table_box,
            bg=TAPE_BG,
            fg=TAPE_FG,
            insertbackground=TAPE_FG,
            bd=0,
            font=_mono(12),
            yscrollcommand=scroll.set,
            state="disabled",
            wrap="none",
        )
        self.table.pack(side="left", fill="both", expand=True)
        scroll.config(command=self.table.yview)

        win.bind("<Return>", lambda e: self._compute())
        self._sync_side()
        self._compute()
        self._remember()

    def snapshot(self) -> dict:
        state = {
            "side": self.side_var.get(),
            "start": self._start_value(),
            "up": self.up_var.get(),
            "down": self.down_var.get(),
            "n": self.n_var.get(),
        }
        try:
            state["display_places"] = self._start_places()
        except ValueError:
            pass
        return state

    def _clear_start_source(self) -> None:
        self._start_source = None

    def _set_start(self, defaults: dict) -> None:
        raw = str(defaults.get("start", "53.75"))
        places = defaults.get("display_places")
        try:
            price_value(raw, "起始价格")
        except ValueError:
            places = None
        self.start_var.set(fmt_price(raw, places) if places in (2, 3) else raw)
        self._start_source = (raw, places) if places in (2, 3) else None

    def _start_value(self) -> str:
        return self._start_source[0] if self._start_source else self.start_var.get()

    def _start_places(self) -> int:
        return self._start_source[1] if self._start_source else display_places(self.start_var.get())

    def _remember(self) -> None:
        if self._on_change is not None:
            self._on_change(self.snapshot())

    def _close(self) -> None:
        state = self.snapshot()
        self.win.destroy()
        if self._on_close is not None:
            self._on_close(state)

    def _set_side(self, side: str) -> None:
        if self.side_var.get() == side:
            return
        self.side_var.set(side)
        self._sync_side()
        self._compute()

    def _sync_side(self) -> None:
        sell = self.side_var.get() == "sell"
        self.sell_btn.configure(bg=BUY if sell else KEY_MUTED, activebackground=_lighten(BUY if sell else KEY_MUTED))
        self.buy_btn.configure(bg=SELL if not sell else KEY_MUTED, activebackground=_lighten(SELL if not sell else KEY_MUTED))
        self.step_lab.configure(text="上涨步长 %" if sell else "下跌步长 %")
        self.step_entry.configure(textvariable=self.up_var if sell else self.down_var)
        self.card_title.configure(text="上涨卖出" if sell else "下跌买入", fg=BUY if sell else SELL)

    def _fill_book(self) -> None:
        if self._fill_from_book is None:
            return
        d = self._fill_from_book()
        self._set_start(d)
        self.up_var.set(str(d.get("up", "")))
        self.down_var.set(str(d.get("down", "")))
        if not self.n_var.get().strip():
            self.n_var.set(str(d.get("n", "5")))
        self._compute()
        self._remember()

    def _show_table(self, text: str) -> None:
        self.table.configure(state="normal")
        self.table.delete("1.0", "end")
        self.table.insert("1.0", text)
        self.table.configure(state="disabled")

    def _clear_result(self) -> None:
        self.stop_var.set("—")
        self.avg_var.set("—")
        self._show_table("")

    def _render(self, p: GridProjection) -> None:
        self.stop_var.set(fmt_price(p.stop, p.display_places))
        self.avg_var.set(fmt_price(p.avg, p.display_places))
        col = "卖出价" if p.side == "sell" else "买入价"
        lines = [f"{'格次':>4}  {col:>8}"]
        for i, px in enumerate(p.prices, 1):
            lines.append(f"{i:4d}  {fmt_price(px, p.display_places):>8}")
        self._show_table("\n".join(lines))

    def _compute(self) -> None:
        side = self.side_var.get()
        step = self.up_var.get() if side == "sell" else self.down_var.get()
        try:
            p = project(self._start_value(), self.n_var.get(), step, side, places=self._start_places())
        except Exception as e:
            self.err_var.set(str(e))
            self._clear_result()
            messagebox.showerror("输入有误", str(e), parent=self.win)
            return
        self.err_var.set("")
        self._render(p)
        self._remember()


def _ask_str(parent: tk.Tk, title: str, prompt: str, initial: str, validator=None) -> str | None:
    out: dict = {"v": None}
    win = tk.Toplevel(parent)
    win.title(title)
    win.configure(bg=BG)
    win.transient(parent)
    win.grab_set()
    win.geometry("420x180")
    tk.Label(win, text=prompt, fg=TEXT, bg=BG, font=_ui_font(10), wraplength=380, justify="left").pack(
        anchor="w", padx=16, pady=(16, 8)
    )
    var = tk.StringVar(value=initial)
    entry = tk.Entry(win, textvariable=var, bg=PANEL, fg=TEXT, insertbackground=TEXT, bd=0, font=_mono(14))
    entry.pack(fill="x", padx=16, ipady=6)
    entry.focus_set()
    entry.selection_range(0, "end")

    def ok():
        raw = var.get().strip()
        if not raw:
            messagebox.showerror("输入有误", "输入不能为空", parent=win)
            return
        if validator is not None:
            try:
                validator(raw)
            except Exception as e:
                messagebox.showerror("输入有误", str(e), parent=win)
                return
        out["v"] = raw
        win.destroy()

    def cancel():
        win.destroy()

    btns = tk.Frame(win, bg=BG)
    btns.pack(fill="x", padx=16, pady=16)
    tk.Button(btns, text="确定", command=ok, bg=ENTER, fg=TEXT, bd=0, font=_ui_font(11, True), padx=16, pady=6).pack(
        side="right"
    )
    tk.Button(btns, text="取消", command=cancel, bg=KEY, fg=TEXT, bd=0, font=_ui_font(11), padx=16, pady=6).pack(
        side="right", padx=(0, 8)
    )
    win.bind("<Return>", lambda e: ok())
    win.bind("<Escape>", lambda e: cancel())
    parent.wait_window(win)
    return out["v"]


def _ask_int(parent: tk.Tk, title: str, prompt: str, initial: int) -> int | None:
    out: dict = {"v": None}
    win = tk.Toplevel(parent)
    win.title(title)
    win.configure(bg=BG)
    win.transient(parent)
    win.grab_set()
    win.geometry("420x200")
    tk.Label(win, text=prompt, fg=TEXT, bg=BG, font=_ui_font(10), wraplength=380, justify="left").pack(
        anchor="w", padx=16, pady=(16, 8)
    )
    var = tk.StringVar(value=str(initial))
    entry = tk.Entry(win, textvariable=var, bg=PANEL, fg=TEXT, insertbackground=TEXT, bd=0, font=_mono(16))
    entry.pack(fill="x", padx=16, ipady=6)
    entry.focus_set()
    entry.selection_range(0, "end")

    def ok():
        raw = var.get().strip()
        try:
            out["v"] = int(raw)
        except ValueError:
            messagebox.showerror("输入有误", "请输入整数（可为负）", parent=win)
            return
        win.destroy()

    def cancel():
        win.destroy()

    btns = tk.Frame(win, bg=BG)
    btns.pack(fill="x", padx=16, pady=16)
    tk.Button(btns, text="确定", command=ok, bg=ENTER, fg=TEXT, bd=0, font=_ui_font(11, True), padx=16, pady=6).pack(
        side="right"
    )
    tk.Button(btns, text="取消", command=cancel, bg=KEY, fg=TEXT, bd=0, font=_ui_font(11), padx=16, pady=6).pack(
        side="right", padx=(0, 8)
    )
    win.bind("<Return>", lambda e: ok())
    win.bind("<Escape>", lambda e: cancel())
    parent.wait_window(win)
    return out["v"]


class FeeDialog:
    def __init__(self, parent: tk.Tk, buy: str, sell: str, stamp: str):
        self.result = None
        win = tk.Toplevel(parent)
        win.title("手续费")
        win.configure(bg=BG)
        win.transient(parent)
        win.grab_set()
        win.geometry("440x300")
        vars = {
            "buy": tk.StringVar(value=rate_to_fee_permyriad(buy)),
            "sell": tk.StringVar(value=rate_to_fee_permyriad(sell)),
            "stamp": tk.StringVar(value=rate_to_fee_permyriad(stamp)),
        }
        labels = (
            ("buy", "买入手续费（万分之）"),
            ("sell", "卖出手续费（万分之）"),
            ("stamp", "印花税（万分之，仅卖出）"),
        )
        for key, lab in labels:
            tk.Label(win, text=lab, fg=MUTED, bg=BG, font=_ui_font(10)).pack(anchor="w", padx=16, pady=(12, 0))
            tk.Entry(win, textvariable=vars[key], bg=PANEL, fg=TEXT, insertbackground=TEXT, bd=0, font=_mono(14)).pack(
                fill="x", padx=16, ipady=5
            )

        def ok():
            try:
                buy_rate = fee_permyriad_to_rate(vars["buy"].get(), "买入手续费")
                sell_rate = fee_permyriad_to_rate(vars["sell"].get(), "卖出手续费")
                stamp_rate = fee_permyriad_to_rate(vars["stamp"].get(), "印花税")
                if D(sell_rate) + D(stamp_rate) >= 1:
                    raise ValueError("卖出手续费与印花税合计必须小于万分之 10000")
            except Exception as e:
                messagebox.showerror("输入有误", str(e), parent=win)
                return
            self.result = {
                "buy_fee_rate": buy_rate,
                "sell_fee_rate": sell_rate,
                "stamp_tax_rate": stamp_rate,
            }
            win.destroy()

        tk.Button(win, text="确定", command=ok, bg=ENTER, fg=TEXT, bd=0, font=_ui_font(12, True), pady=8).pack(
            fill="x", padx=16, pady=16
        )
        win.bind("<Return>", lambda e: ok())
        win.bind("<Escape>", lambda e: win.destroy())
        parent.wait_window(win)


class NewBookDialog:
    def __init__(self, parent: tk.Tk):
        self.result = None
        win = tk.Toplevel(parent)
        win.title("新建账本")
        win.configure(bg=BG)
        win.transient(parent)
        win.grab_set()
        win.geometry("380x520")
        default_name = "实盘"
        if book.exists(default_name):
            default_name = "网格2"
        vars = {
            "name": tk.StringVar(value=default_name),
            "base": tk.StringVar(value="53.75"),
            "shares": tk.StringVar(value="0"),
            "opening": tk.StringVar(value=""),
            "lot": tk.StringVar(value="100"),
            "up": tk.StringVar(value="0.85"),
            "down": tk.StringVar(value="0.8"),
        }
        labels = [
            ("name", "名称"),
            ("base", "起始基准价"),
            ("shares", "初始持仓（可负，如 -3400）"),
            ("opening", "建仓价（空=已持有）"),
            ("lot", "单笔股数"),
            ("up", "上涨步长 %"),
            ("down", "下跌步长 %"),
        ]
        for key, lab in labels:
            tk.Label(win, text=lab, fg=MUTED, bg=BG, font=_ui_font(10)).pack(anchor="w", padx=16, pady=(10, 0))
            tk.Entry(win, textvariable=vars[key], bg=PANEL, fg=TEXT, insertbackground=TEXT, bd=0, font=_mono(13)).pack(
                fill="x", padx=16, ipady=5
            )

        tk.Label(
            win,
            text="无净买/净卖限制，允许负仓。",
            fg=MUTED,
            bg=BG,
            font=_ui_font(9),
        ).pack(anchor="w", padx=16, pady=(8, 0))

        def ok():
            try:
                shares = int(vars["shares"].get().strip())
                opening = vars["opening"].get().strip() or None
                cfg = Config(
                    lot_size=int(vars["lot"].get().strip()),
                    up_pct=vars["up"].get().strip(),
                    down_pct=vars["down"].get().strip(),
                    allow_net_buy_over_zero=True,
                    allow_short=True,
                    end_at_zero=False,
                )
                candidate = {
                    "name": vars["name"].get().strip(),
                    "base": vars["base"].get().strip(),
                    "shares": shares,
                    "opening_price": opening,
                    "config": cfg,
                }
                book.book_path(candidate["name"])
                if book.exists(candidate["name"]):
                    raise ValueError("账本名称已存在")
                book.new_engine(**{key: value for key, value in candidate.items() if key != "name"})
                self.result = candidate
            except Exception as e:
                messagebox.showerror("输入有误", str(e), parent=win)
                return
            win.destroy()

        tk.Button(win, text="创建", command=ok, bg=ENTER, fg=TEXT, bd=0, font=_ui_font(12, True), pady=8).pack(
            fill="x", padx=16, pady=16
        )
        win.bind("<Return>", lambda e: ok())
        parent.wait_window(win)


def _dpi() -> None:
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                import ctypes

                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass


def main() -> int:
    _dpi()
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
