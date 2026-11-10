import copy
import random
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

from grid_ledger import book
from grid_ledger.calc import project
from grid_ledger.cli import run_line
from grid_ledger.engine import Config, Engine, FillRequest, MAX_TRIGGERS, State
from grid_ledger.money import D, fmt_money, fmt_price, round_money
from grid_ledger.parse import parse


def round_units(value):
    return (2 * value.numerator + value.denominator) // (2 * value.denominator)


def decimal_text(units):
    sign = "-" if units < 0 else ""
    return f"{sign}{abs(units) // 10000}.{abs(units) % 10000:04d}"


def empty_engine():
    return Engine(Config(), State(base="53.75", initial_shares=0, position=0))


class TestFourDecimalMath(unittest.TestCase):
    def test_independent_integer_grid_reference(self):
        rng = random.Random(20260914)
        for _ in range(150):
            start = decimal_text(rng.randrange(100000, 10000000))
            side = rng.choice(["buy", "sell"])
            step = rng.choice(["0.01", "0.8", "0.85", "1.125"])
            n = rng.randrange(1, 80)
            units = round_units(Fraction(start) * 10000)
            factor = 1 + Fraction(step) / 100 * (1 if side == "sell" else -1)
            expected = []
            for _ in range(n):
                units = round_units(units * factor)
                expected.append(units)
            actual = project(start, n, step, side)
            self.assertEqual(actual.prices, tuple(decimal_text(x) for x in expected))
            self.assertEqual(actual.avg, decimal_text(round_units(Fraction(sum(expected), n))))

    def test_display_precision_does_not_change_math(self):
        two = project("53.75", 5, "0.85", "sell")
        three = project("53.750", 5, "0.85", "sell")
        self.assertEqual(two.prices, three.prices)
        self.assertEqual((two.display_places, three.display_places), (2, 3))
        self.assertEqual(fmt_price(two.stop, two.display_places), "56.07")
        self.assertEqual(fmt_price(three.stop, three.display_places), "56.074")
        self.assertEqual(fmt_money("1.2250"), "1.23")
        self.assertEqual(fmt_money("1.2345", places=3), "1.235")

    def test_new_book_preserves_third_decimal(self):
        eng = book.new_engine("53.755", 0)
        self.assertEqual(eng.state.base, "53.7550")
        self.assertEqual(eng.config.display_places, 3)
        self.assertEqual(eng.levels().sell1, project("53.755", 1, "0.85", "sell").stop)
        self.assertEqual(eng.format_price(eng.levels().sell1), "54.212")
        loaded = Engine.from_dict(eng.to_dict())
        self.assertEqual(loaded.config.display_places, 3)

    def test_zero_or_stagnant_next_grid_is_rejected(self):
        for args in [("0.0001", 1, "60", "buy"), ("0.01", 6, "60", "buy"),
                     ("10", 1, "0.000001", "sell")]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                project(*args)


class TestInputValidation(unittest.TestCase):
    def test_invalid_fill_does_not_change_any_engine_state(self):
        eng = empty_engine()
        eng.submit(FillRequest(fill_price="53.50"))
        requests = []
        for price in ("0", "-1", "0.00001", "NaN", "Infinity", "bad", "1e999"):
            requests.extend([FillRequest(fill_price=price, force=True),
                             FillRequest(fill_price="53.75", trigger=price, force=True),
                             FillRequest(fill_price=price, side="sell", qty=100, opening=True)])
        for qty in (0, -100, "1.5"):
            requests.extend([FillRequest(fill_price="53.32", qty=qty),
                             FillRequest(fill_price="53.75", qty=qty, side="sell", opening=True)])
        for count in (0, -1, "1.5", MAX_TRIGGERS + 1):
            requests.append(FillRequest(fill_price="53.32", grids=count, force=True))
        for req in requests:
            with self.subTest(req=req):
                before = copy.deepcopy(eng.to_dict())
                with self.assertRaises(ValueError):
                    eng.submit(req)
                self.assertEqual(eng.to_dict(), before)

    def test_invalid_configuration_and_partial_step_change(self):
        for values in ({"lot_size": 0}, {"lot_size": -100}, {"down_pct": "100"},
                       {"down_pct": "101"}, {"up_pct": "0"}, {"up_pct": "NaN"},
                       {"buy_fee_rate": "-0.1"}, {"sell_fee_rate": "1"}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                Config(**values)
        eng = empty_engine()
        before = copy.deepcopy(eng.to_dict())
        with self.assertRaises(ValueError):
            eng.set_steps(up_pct="1", down_pct="101")
        self.assertEqual(eng.to_dict(), before)

    def test_negative_reported_quantity_is_not_made_positive(self):
        for text in ("53.32买入-100股", "建仓 卖出 -3400 @53.75", "成交-1"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse(text)

    def test_explicit_trigger_cannot_leave_an_unusable_grid(self):
        eng = empty_engine()
        for opening in (False, True):
            before = copy.deepcopy(eng.to_dict())
            with self.assertRaises(ValueError):
                eng.submit(FillRequest(fill_price="53.32", trigger="0.0001", side="buy",
                                       qty=100, skip=False, opening=opening, force=True))
            self.assertEqual(eng.to_dict(), before)


class TestCorrections(unittest.TestCase):
    def test_opening_amend_has_zero_grid_gain(self):
        for shares in (-3400, 3400):
            with self.subTest(shares=shares):
                eng = book.new_engine("53.75", shares, "53.75")
                eng.amend_last_price("53.76")
                self.assertEqual(eng.state.position, shares)
                self.assertEqual(eng.state.initial_shares, shares)
                self.assertEqual(eng.state.opening_cash, str(eng.state.net_cash()))
                self.assertEqual(eng.mark().gain, "0.0000")
                self.assertEqual((eng.state.buy_count, eng.state.sell_count), (0, 0))
                eng.keep_first_of_last_batch("53.77")
                self.assertEqual(eng.mark().gain, "0.0000")
                self.assertEqual(eng.state.base, "53.7500")

    def test_adjustment_cannot_be_replaced_by_a_trade(self):
        eng = empty_engine()
        eng.set_initial_shares(-3000)
        for change in (eng.amend_last_price, eng.keep_first_of_last_batch):
            before = copy.deepcopy(eng.to_dict())
            with self.assertRaises(ValueError):
                change("53.35")
            self.assertEqual(eng.to_dict(), before)

    def test_invalid_amend_does_not_remove_last_batch(self):
        eng = empty_engine()
        eng.submit(FillRequest(fill_price="55.10", side="sell"))
        for value in ("bad", "0", "-1", "NaN"):
            before = copy.deepcopy(eng.to_dict())
            with self.assertRaises(ValueError):
                eng.amend_last_price(value)
            self.assertEqual(eng.to_dict(), before)

    def test_step_undo_roundtrip_restores_config_and_prices(self):
        eng = empty_engine()
        before = copy.deepcopy(eng.to_dict())
        eng.set_steps(up_pct="1", down_pct="1.2")
        loaded = Engine.from_dict(eng.to_dict())
        loaded.undo_batch()
        self.assertEqual(loaded.config.to_dict(), before["config"])
        self.assertEqual(loaded.state.to_dict(), before["state"])
        self.assertEqual(loaded.levels().sell1, "54.2069")
        self.assertEqual(loaded.fills, [])

    def test_excessive_undo_is_atomic(self):
        eng = empty_engine()
        eng.submit(FillRequest(fill_price="54.21", side="sell"))
        before = copy.deepcopy(eng.to_dict())
        with self.assertRaises(ValueError):
            eng.undo_batch(2)
        self.assertEqual(eng.to_dict(), before)

    def test_adjust_validation_is_atomic(self):
        eng = empty_engine()
        before = copy.deepcopy(eng.to_dict())
        with self.assertRaises(ValueError):
            eng.adjust("bad", position=100, buy_count=-1)
        self.assertEqual(eng.to_dict(), before)


class TestLongGrid(unittest.TestCase):
    def test_six_hundred_grids_are_all_recorded(self):
        projected = project("100", 600, "0.01", "sell")
        eng = Engine(Config(up_pct="0.01"), State(base="100", initial_shares=0, position=0))
        result = eng.submit(FillRequest(fill_price=projected.stop, side="sell"))
        self.assertEqual(len(result.fills), 600)
        self.assertEqual(eng.state.position, -60000)
        self.assertEqual(eng.state.base, projected.stop)

    def test_over_limit_rejects_whole_batch(self):
        projected = project("100", MAX_TRIGGERS, "0.01", "sell")
        eng = Engine(Config(up_pct="0.01"), State(base="100", initial_shares=0, position=0))
        before = copy.deepcopy(eng.to_dict())
        beyond = str(D(projected.stop) * D("1.0002"))
        with self.assertRaises(ValueError):
            eng.submit(FillRequest(fill_price=beyond, side="sell"))
        self.assertEqual(eng.to_dict(), before)


class TestBookValidation(unittest.TestCase):
    def setUp(self):
        self.old = book.BOOKS
        self.tmp = tempfile.TemporaryDirectory()
        book.set_books_dir(self.tmp.name)

    def tearDown(self):
        book.set_books_dir(self.old)
        self.tmp.cleanup()

    def test_invalid_cli_input_preserves_saved_book(self):
        eng = book.create("测试", "53.75", 0)
        path = book.book_path("测试")
        before = path.read_bytes()
        for line in ("0", "改基准价 0", "set down 101", "set lot -100", "53.32买入-100股",
                     "53.32成交100.5股", "初始持仓1.5", "修正成交价53.75.5",
                     "成交价53.75.5", "53.32成交NaN股", "53.32成交100a股"):
            with self.subTest(line=line), self.assertRaises(ValueError):
                run_line("测试", eng, line)
            self.assertEqual(path.read_bytes(), before)
        run_line("测试", eng, "改基准价 53.895")
        self.assertEqual(eng.state.base, "53.8950")
        run_line("测试", eng, "set lot 200")
        run_line("测试", eng, "撤回")
        self.assertEqual(eng.config.lot_size, 100)

    def test_invalid_new_book_is_not_saved(self):
        for value in ("0", "NaN", "-53.75"):
            with self.assertRaises(ValueError):
                book.create("失败", value, 0)
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])

    def test_opening_fill_becomes_initial_cash_without_touching_grid(self):
        raw = {
            "config": {"up_pct": "0.85", "down_pct": "0.8", "display_places": 2},
            "state": {
                "base": "53.32",
                "initial_shares": -500,
                "position": -400,
                "buy_count": 1,
                "sell_count": 0,
                "buy_spend": "5332.4266",
                "sell_proceeds": "182644.0050",
                "opening_cash": "182644.0050",
                "last_price": "53.32",
                "ended": False,
                "start_base": "53.75",
            },
            "fills": [
                {
                    "id": 1, "batch_id": 1, "kind": "opening", "side": "sell", "qty": 3400,
                    "fill_price": "53.75", "trigger_price": "53.75",
                    "amount": "182750.0000", "fee": "105.9950", "cash": "182644.0050",
                    "base_after": "53.75", "position_after": -3400, "note": "建仓",
                    "state_before": {
                        "base": "53.75", "initial_shares": 0, "position": 0,
                        "buy_spend": "0.00", "sell_proceeds": "0.00", "opening_cash": "0.00",
                    },
                    "config_before": {},
                },
                {
                    "id": 2, "batch_id": 2, "kind": "grid", "side": "buy", "qty": 100,
                    "fill_price": "53.32", "trigger_price": "53.32",
                    "amount": "5332.0000", "fee": "0.4266", "cash": "-5332.4266",
                    "base_after": "53.32", "position_after": -3300, "note": "",
                    "state_before": {
                        "base": "53.75", "initial_shares": -3400, "position": -3400,
                        "buy_spend": "0.00", "sell_proceeds": "182644.0050", "opening_cash": "182644.0050",
                    },
                    "config_before": {},
                },
            ],
            "next_id": 3,
            "next_batch": 3,
        }
        price = D("53.32")
        old_net = D("182644.0050") - D("5332.4266")
        old_gain = (-400 * price + old_net) - (-500 * price + D("182644.0050"))
        eng = Engine.from_dict(raw)
        self.assertEqual([f.kind for f in eng.fills], ["grid"])
        self.assertEqual(eng.fills[0].cash, "-5332.4266")
        self.assertEqual(eng.state.opening_price, "53.7500")
        self.assertEqual(eng.state.sell_proceeds, "0.0000")
        self.assertEqual(eng.state.buy_spend, "5332.4266")
        self.assertEqual(eng.state.opening_cash, "26859.4125")
        self.assertEqual(eng.fills[0].state_before["sell_proceeds"], "0.0000")
        self.assertEqual(eng.fills[0].state_before["opening_cash"], "182644.0050")
        self.assertEqual(eng.mark().gain, str(round_money(old_gain)))
        eng.undo_batch()
        self.assertEqual(eng.state.initial_shares, -3400)
        self.assertEqual(eng.state.position, -3400)
        self.assertEqual(eng.state.opening_cash, "182644.0050")
        self.assertEqual(eng.state.sell_proceeds, "0.0000")
        self.assertEqual(eng.mark().gain, "0.0000")

    def test_legacy_cash_is_not_recalculated(self):
        state = State(base="53.34", initial_shares=-3400, position=-3300,
                      buy_count=2, sell_count=1, buy_spend="10620.85",
                      sell_proceeds="187975.91", opening_cash="182644.00",
                      last_price="53.35", start_base="53.75")
        legacy = {"config": {"up_pct": "0.85", "down_pct": "0.8"}, "state": state.to_dict()}
        eng = Engine.from_dict(legacy)
        self.assertEqual(eng.state.opening_cash, "182644.0000")
        self.assertEqual(eng.mark().gain, "46.0600")
        self.assertEqual(eng.config.display_places, 2)


if __name__ == "__main__":
    unittest.main()
