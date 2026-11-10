from __future__ import annotations

from .engine import Applied, Engine, Fill, NeedConfirm
from .money import D, fmt_money, fmt_price


def _side_cn(side: str) -> str:
    return "买入" if side == "buy" else "卖出"


def render_ladder(engine: Engine) -> str:
    lv = engine.levels()
    return (
        "| 二次高抛 | 高抛网格价 | 当前基准价 | 低吸网格价 | 二次低吸 |\n"
        "|---|---|---|---|---|\n"
        f"| {engine.format_price(lv.sell2)} | {engine.format_price(lv.sell1)} | {engine.format_price(lv.base)} | {engine.format_price(lv.buy1)} | {engine.format_price(lv.buy2)} |"
    )


def render_status_table(engine: Engine, price: str | None = None) -> str:
    st = engine.state
    mk = engine.mark(price)
    net = st.net_bought()
    occ = D(mk.occupied)
    occ_note = "（净回笼现金）" if occ < 0 else ("（净买入支出）" if occ > 0 else "")
    pos_note = "（卖空）" if st.position < 0 else ""
    lines = [
        "| 项目 | 当前值 |",
        "|---|---|",
        f"| 初始基准价 | {engine.format_price(engine.initial_base())} |",
        f"| 当前基准价 | {engine.format_price(st.base)} |",
        f"| 初始持仓 | {st.initial_shares} 股 |",
    ]
    if st.opening_price is not None:
        lines.append(f"| 建仓价 | {engine.format_price(st.opening_price)} |")
        lines.append(f"| 建仓现金 | {engine.format_money(st.opening_cash)} |")
    lines += [
        f"| 当前净买量 | {net:+d} 股 |",
        f"| 当前持仓 | {st.position} 股{pos_note} |",
        f"| 买入笔数 | {st.buy_count} |",
        f"| 卖出笔数 | {st.sell_count} |",
        f"| 占用资金 | {engine.format_money(occ)}{occ_note} |",
        f"| 净回笼现金 | {engine.format_money(mk.net_cash, signed=True)} |",
        f"| 网格增益 | **{engine.format_money(mk.gain, signed=True)}** |",
    ]
    if st.ended:
        lines.append("| 状态 | 已结束（持仓 0） |")
    return "\n".join(lines)


def render_gain(engine: Engine, price: str | None = None) -> str:
    mk = engine.mark(price)
    st = engine.state
    return (
        f"**网格增益计算（按现价 {engine.format_price(mk.price)}）**\n"
        f"- 一直持有资产 = 初始持仓 × 现价 + 建仓现金 = {st.initial_shares} × {engine.format_price(mk.price)} + {engine.format_money(st.opening_cash)} = {engine.format_money(mk.hold)}\n"
        f"- 当前实际资产 = 持仓 × 现价 + 净回笼现金 = {st.position} × {engine.format_price(mk.price)} + {engine.format_money(mk.net_cash)} = {engine.format_money(mk.actual)}\n"
        f"- 网格增益 = {engine.format_money(mk.actual)} − {engine.format_money(mk.hold)} = **{engine.format_money(mk.gain, signed=True)}**"
    )


def render_fill(fill: Fill, places: int = 2) -> str:
    verb = _side_cn(fill.side)
    cash_label = "总支出" if fill.side == "buy" else "到账"
    kind = {"grid": "网格", "opening": "建仓", "adjust": "改账"}.get(fill.kind, fill.kind)
    if fill.kind == "adjust":
        return f"改账：{fill.note or '（无说明）'}"
    return (
        "| 项目 | 数值 |\n"
        "|---|---|\n"
        f"| 类型 | {kind} |\n"
        f"| 触发网格价 | {fmt_price(fill.trigger_price, places)} |\n"
        f"| 操作 | {verb} {fill.qty} 股 |\n"
        f"| 实际成交价 | {fmt_price(fill.fill_price, places)} |\n"
        f"| {verb}金额 | {fmt_money(fill.amount, places=places)} |\n"
        f"| 手续费 | {fmt_money(fill.fee, places=places)} |\n"
        f"| {cash_label} | {fmt_money(abs(D(fill.cash)), places=places)} |"
    )


def render_applied(engine: Engine, applied: Applied) -> str:
    fills = [f for f in applied.fills if f.kind != "adjust"]
    adjusts = [f for f in applied.fills if f.kind == "adjust"]
    parts: list[str] = []
    if applied.note:
        parts.append(applied.note)
    if adjusts:
        parts.extend("改账：" + (f.note or "") for f in adjusts)
    if len(fills) == 1:
        parts.append("## 本次成交")
        parts.append(render_fill(fills[0], engine.config.display_places))
    elif len(fills) > 1:
        parts.append(f"## 本次成交（跳 {len(fills)} 格）")
        parts.append("| 格 | 触发 | 方向 | 成交价 | 数量 | 金额 | 费用 | 现金流 |")
        parts.append("|---|---|---|---|---|---|---|---|")
        for i, f in enumerate(fills, 1):
            parts.append(
                f"| {i} | {engine.format_price(f.trigger_price)} | {_side_cn(f.side)} | {engine.format_price(f.fill_price)} | {f.qty} | {engine.format_money(f.amount)} | {engine.format_money(f.fee)} | {engine.format_money(f.cash, signed=True)} |"
            )
    parts.append("")
    parts.append("## 当前状态")
    parts.append(render_ladder(engine))
    parts.append("")
    parts.append(render_status_table(engine))
    parts.append("")
    parts.append(render_gain(engine))
    return "\n".join(parts).strip() + "\n"


def render_status(engine: Engine, name: str = "") -> str:
    title = f"# 账本 {name}\n\n" if name else ""
    return title + "## 当前状态\n" + render_ladder(engine) + "\n\n" + render_status_table(engine) + "\n\n" + render_gain(engine) + "\n"


def render_confirm(nc: NeedConfirm) -> str:
    lines = ["需要确认：", nc.message, ""]
    for o in nc.options:
        lines.append(f"  {o.key}. {o.label}")
    lines.append("")
    lines.append("回选项数字，或重新报一笔。")
    return "\n".join(lines)


def render_history(engine: Engine, last: int = 20) -> str:
    fills = engine.fills[-last:]
    if not fills:
        return "（无成交）"
    lines = [
        f"最近 {len(fills)} 条（共 {len(engine.fills)}）：",
        "| # | 类型 | 方向 | 触发 | 成交 | 数量 | 现金流 | 基准 | 持仓 | 备注 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for f in fills:
        kind = {"grid": "网格", "opening": "建仓", "adjust": "改账"}.get(f.kind, f.kind)
        if f.kind == "adjust":
            lines.append(
                f"| {f.id} | 改账 |  |  |  |  |  | {engine.format_price(f.base_after)} | {f.position_after} | {f.note} |"
            )
            continue
        lines.append(
            f"| {f.id} | {kind} | {_side_cn(f.side)} | {engine.format_price(f.trigger_price)} | {engine.format_price(f.fill_price)} | {f.qty} | {engine.format_money(f.cash, signed=True)} | {engine.format_price(f.base_after)} | {f.position_after} | {f.note} |"
        )
    return "\n".join(lines)


def render_prompt(name: str, engine: Engine) -> str:
    mk = engine.mark()
    return f"[{name} 基准{engine.format_price(engine.state.base)} 仓{engine.state.position} 增益{engine.format_money(mk.gain, signed=True)}] "


HELP = """网格记账：人工报成交入账，不下单、不拉行情。

GUI（计算器）
  python gui.py
  python ledger.py
  点「初始持仓」可改（允许负数），当前持仓按差额同步，保留净买量/网格增益。填了建仓价时，建仓现金和占用按建仓价重算，网格成交不改。无净买净卖限制。
  右下「＋」「－」按显示成交价的末位小数加减（至少按 0.01），只调整输入，不自动入账。
  每笔自动存档；右侧列表切换，可另存为 / 改名。
  价格、金额、费用与增益按四位小数计算；初始基准 53.75 显示两位，53.755 显示三位。
  非法输入弹窗并保留原值，不入账；每次最多 5000 格，超限整批拒绝。

报成交
  53.32b              买入成交 53.32，触发价按当前网格计算
  53.32s              卖出
  52.88               只报价格，触及网格则入账，否则询问
  57.08触发57.12      成交价 57.08，基准跟触发价 57.12
  58.73成交500股      指定数量（与跳格数不一致会先问）
  建仓 卖出 3400 @53.75
  按照成交52.88       强制按该成交价

改账
  撤回                撤最后一批（跳格一批全撤）
  撤回2               撤两批
  只触发了一格        最后一批只留第一格
  修正成交价 56.69
  改基准价 53.89
  初始持仓 -3400
  清零笔数
  取消净买入限制
  现价 53.35          只改对比现价，不成交

账本
  new 名 --base 53.75 --shares -3400 --opening-price 53.75
  open 名
  状态 / 历史 / 帮助 / quit
"""
