import unittest

from grid_ledger.engine import (
    Config,
    Engine,
    FillRequest,
    NeedConfirm,
    State,
    buy_fee_cash,
    buy_level,
    initial_net_cash,
    sell_fee_cash,
    sell_level,
)
from grid_ledger.money import D


class TestLevels(unittest.TestCase):
    def test_from_53_70(self):
        cfg = Config()
        self.assertEqual(sell_level("53.70", cfg), "54.1565")
        self.assertEqual(buy_level("53.70", cfg), "53.2704")
        self.assertEqual(sell_level("54.16", cfg), "54.6204")
        self.assertEqual(sell_level("54.62", cfg), "55.0843")
        self.assertEqual(sell_level("55.08", cfg), "55.5482")

    def test_from_53_75(self):
        cfg = Config()
        self.assertEqual(buy_level("53.75", cfg), "53.3200")
        self.assertEqual(buy_level("53.32", cfg), "52.8934")
        self.assertEqual(sell_level("52.89", cfg), "53.3396")
        self.assertEqual(buy_level("53.34", cfg), "52.9133")
        self.assertEqual(buy_level("52.91", cfg), "52.4867")
        self.assertEqual(sell_level("53.34", cfg), "53.7934")
        self.assertEqual(sell_level("53.79", cfg), "54.2472")


class TestStartBase(unittest.TestCase):
    def test_start_base_stays_after_fills(self):
        eng = Engine(Config(), State(base="53.75", initial_shares=0, position=0))
        self.assertEqual(eng.initial_base(), "53.7500")
        eng.submit(FillRequest(fill_price="53.75", side="sell", qty=3400, opening=True, force=True))
        eng.submit(FillRequest(fill_price="53.32", side="buy"))
        self.assertEqual(eng.state.base, "53.3200")
        self.assertEqual(eng.initial_base(), "53.7500")


class TestSteps(unittest.TestCase):
    def test_set_steps_rebuilds_ladder(self):
        eng = Engine(Config(), State(base="53.34", initial_shares=0, position=0))
        self.assertEqual(sell_level("53.34", eng.config), "53.7934")
        self.assertEqual(buy_level("53.34", eng.config), "52.9133")
        eng.set_steps(up_pct="1", down_pct="1")
        self.assertEqual(eng.config.up_pct, "1")
        self.assertEqual(eng.config.down_pct, "1")
        self.assertEqual(sell_level("53.34", eng.config), "53.8734")
        self.assertEqual(buy_level("53.34", eng.config), "52.8066")
        lv = eng.levels()
        self.assertEqual(lv.sell1, "53.8734")
        self.assertEqual(lv.buy1, "52.8066")

    def test_set_steps_strips_percent(self):
        eng = Engine(Config(), State(base="53.34", initial_shares=0, position=0))
        eng.set_steps(up_pct="0.9%")
        self.assertEqual(eng.config.up_pct, "0.9")


class TestSkip(unittest.TestCase):
    def test_skip_sells_from_53_70_to_55_10(self):
        eng = Engine(Config(), State(base="53.70", initial_shares=2500, position=2500))
        result = eng.submit(FillRequest(fill_price="55.10", side="sell"))
        self.assertNotIsInstance(result, NeedConfirm)
        self.assertEqual(len(result.fills), 3)
        self.assertEqual([f.trigger_price for f in result.fills], ["54.1565", "54.6168", "55.0810"])
        self.assertEqual(eng.state.base, "55.0810")
        self.assertEqual(eng.state.position, 2200)
        self.assertEqual(eng.state.sell_count, 3)
        for f in result.fills:
            self.assertEqual(f.fill_price, "55.1000")
            self.assertEqual(f.qty, 100)


class TestUndo(unittest.TestCase):
    def test_undo_batch(self):
        eng = Engine(Config(), State(base="53.70", initial_shares=2500, position=2500))
        eng.submit(FillRequest(fill_price="55.10", side="sell"))
        eng.undo_batch()
        self.assertEqual(eng.state.base, "53.7000")
        self.assertEqual(eng.state.position, 2500)
        self.assertEqual(eng.fills, [])

    def test_keep_one(self):
        eng = Engine(Config(), State(base="53.70", initial_shares=2500, position=2500))
        eng.submit(FillRequest(fill_price="55.10", side="sell"))
        eng.keep_first_of_last_batch("55.10")
        self.assertEqual(len([f for f in eng.fills if f.kind == "grid"]), 1)
        self.assertEqual(eng.state.base, "54.1565")
        self.assertEqual(eng.state.position, 2400)


class TestInitialAndShort(unittest.TestCase):
    def test_set_initial_syncs_position_and_preserves_net_and_gain(self):
        from grid_ledger.money import D

        eng = Engine(Config(), State(base="53.75", initial_shares=0, position=0))
        eng.submit(FillRequest(fill_price="53.75", side="sell", qty=3400, opening=True, force=True))
        eng.submit(FillRequest(fill_price="53.32", side="buy"))
        eng.submit(FillRequest(fill_price="52.88"))
        eng.submit(FillRequest(fill_price="53.35"))
        self.assertEqual(eng.state.position, -3300)
        self.assertEqual(eng.state.initial_shares, -3400)
        self.assertEqual(eng.state.net_bought(), 100)
        before = eng.mark("53.35")
        self.assertEqual(before.gain, "46.0561")
        self.assertEqual(before.actual, "1300.0611")

        trade_cash = (eng.state.buy_spend, eng.state.sell_proceeds)
        grids = [f.to_dict() for f in eng.fills if f.kind == "grid"]
        eng.set_initial_shares(-3000)
        self.assertEqual(eng.state.position, -2900)
        self.assertEqual(eng.state.initial_shares, -3000)
        self.assertEqual(eng.state.net_bought(), 100)
        self.assertEqual((eng.state.buy_spend, eng.state.sell_proceeds), trade_cash)
        self.assertEqual([f.to_dict() for f in eng.fills if f.kind == "grid"], grids)
        self.assertEqual(eng.state.opening_cash, "161156.4750")
        after = eng.mark("53.35")
        self.assertEqual(D(after.hold), D(-3000) * D("53.35") + D("161156.4750"))
        self.assertEqual(after.gain, before.gain)
        self.assertNotEqual(after.occupied, before.occupied)
        self.assertTrue(eng.config.allow_short)
        self.assertTrue(eng.config.allow_net_buy_over_zero)

    def test_set_initial_before_trades(self):
        for old, new in ((0, 1500), (1000, 1500), (1000, -500), (-500, -1000), (-1000, 0)):
            with self.subTest(old=old, new=new):
                eng = Engine(Config(), State(base="53.75", initial_shares=old, position=old))
                eng.set_initial_shares(new)
                self.assertEqual(eng.state.initial_shares, new)
                self.assertEqual(eng.state.position, new)
                self.assertEqual(eng.state.net_bought(), 0)
                self.assertEqual(eng.mark().gain, "0.0000")
                self.assertEqual((eng.state.buy_count, eng.state.sell_count), (0, 0))

    def test_set_initial_after_sales_preserves_trade_totals(self):
        eng = Engine(Config(), State(base="53.70", initial_shares=2500, position=2500))
        eng.submit(FillRequest(fill_price="55.10", side="sell"))
        before = eng.state.to_dict()
        gain = eng.mark().gain
        result = eng.set_initial_shares(1500)
        expected = dict(before, initial_shares=1500, position=1200)
        self.assertEqual(eng.state.to_dict(), expected)
        self.assertEqual(eng.state.net_bought(), -300)
        self.assertEqual(eng.mark().gain, gain)
        self.assertEqual(result.fills[0].kind, "adjust")
        self.assertEqual(result.fills[0].position_after, 1200)

    def test_set_initial_roundtrip_and_undo(self):
        eng = Engine(Config(), State(base="53.70", initial_shares=2500, position=2500))
        eng.submit(FillRequest(fill_price="55.10", side="sell"))
        before = eng.to_dict()
        eng.set_initial_shares(-500)
        loaded = Engine.from_dict(eng.to_dict())
        self.assertEqual((loaded.state.initial_shares, loaded.state.position), (-500, -800))
        loaded.undo_batch()
        self.assertEqual(loaded.state.to_dict(), before["state"])
        self.assertEqual(loaded.config.to_dict(), before["config"])
        self.assertEqual([fill.to_dict() for fill in loaded.fills], before["fills"])

    def test_invalid_initial_does_not_change_account(self):
        eng = Engine(Config(), State(base="53.70", initial_shares=2500, position=2200))
        before = eng.to_dict()
        for value in ("1.5", "bad", "NaN"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    eng.set_initial_shares(value)
                self.assertEqual(eng.to_dict(), before)

    def test_unlock_allows_negative_position(self):
        cfg = Config(allow_short=False, allow_net_buy_over_zero=False, skip_fill=False)
        eng = Engine(cfg, State(base="53.70", initial_shares=0, position=0))
        blocked = eng.submit(FillRequest(fill_price="54.16", side="sell"))
        self.assertIsInstance(blocked, NeedConfirm)
        self.assertEqual(blocked.reason, "limit")
        eng.reject()
        eng.unlock_limits()
        ok = eng.submit(FillRequest(fill_price="54.16", side="sell"))
        self.assertNotIsInstance(ok, NeedConfirm)
        self.assertEqual(eng.state.position, -100)


class TestNear(unittest.TestCase):
    def test_near_asks(self):
        eng = Engine(Config(), State(base="53.70", initial_shares=2500, position=2500))
        sell1 = sell_level("53.70", Config())
        px = str(round(float(sell1) - 0.01, 2))
        result = eng.submit(FillRequest(fill_price=px))
        self.assertIsInstance(result, NeedConfirm)
        self.assertEqual(result.reason, "near")

    def test_crossed_does_not_ask(self):
        eng = Engine(Config(), State(base="53.70", initial_shares=2500, position=2500))
        result = eng.submit(FillRequest(fill_price="54.16"))
        self.assertNotIsInstance(result, NeedConfirm)
        self.assertEqual(result.fills[0].side, "sell")


class TestFeeRates(unittest.TestCase):
    def test_builtin_defaults(self):
        cfg = Config()
        self.assertEqual(cfg.buy_fee_rate, "0.00008")
        self.assertEqual(cfg.sell_fee_rate, "0.00008")
        self.assertEqual(cfg.stamp_tax_rate, "0.0005")

    def test_stamp_is_charged_on_sell_only(self):
        cfg = Config()
        no_stamp = Config(stamp_tax_rate="0")
        self.assertEqual(initial_net_cash(100, "53.75", cfg), initial_net_cash(100, "53.75", no_stamp))
        self.assertEqual(initial_net_cash(100, "53.75", cfg), D("-5375.4300"))
        self.assertNotEqual(initial_net_cash(-100, "53.75", cfg), initial_net_cash(-100, "53.75", no_stamp))
        self.assertEqual(initial_net_cash(-100, "53.75", cfg), D("5371.8825"))

        eng = Engine(Config(stamp_tax_rate="0.002"), State(base="53.75", initial_shares=0, position=0))
        buy = eng.submit(FillRequest(fill_price="53.32", side="buy"))
        self.assertEqual(buy.fills[0].fee, "0.4266")

    def test_set_fee_rates_affects_later_trades_only_and_undoes(self):
        eng = Engine(Config(), State(base="53.75", initial_shares=0, position=0))
        buy = eng.submit(FillRequest(fill_price="53.32", side="buy"))
        self.assertEqual(buy.fills[0].fee, "0.4266")
        changed = eng.set_fee_rates(buy_fee_rate="0.0001", sell_fee_rate="0.0002", stamp_tax_rate="0.001")
        self.assertEqual(changed.note, "改费用 买入 0.8 → 1，卖出 0.8 → 2，印花税 5 → 10")
        self.assertEqual(eng.fills[0].fee, "0.4266")
        same = eng.set_fee_rates(buy_fee_rate="0.000100", sell_fee_rate="0.0002", stamp_tax_rate="0.0010")
        self.assertEqual(same.fills, [])

        sell_price = eng.levels().sell1
        sell = eng.submit(FillRequest(fill_price=sell_price, side="sell"))
        stamped = sell_fee_cash(100, sell_price, D(eng.config.sell_fee_rate) + D(eng.config.stamp_tax_rate))[1]
        sell_only = sell_fee_cash(100, sell_price, eng.config.sell_fee_rate)[1]
        self.assertEqual(sell.fills[0].fee, stamped)
        self.assertNotEqual(stamped, sell_only)

        buy_price = eng.levels().buy1
        later = eng.submit(FillRequest(fill_price=buy_price, side="buy"))
        self.assertEqual(later.fills[0].fee, buy_fee_cash(100, buy_price, eng.config.buy_fee_rate)[1])
        self.assertNotEqual(
            later.fills[0].fee,
            buy_fee_cash(100, buy_price, D(eng.config.buy_fee_rate) + D(eng.config.stamp_tax_rate))[1],
        )

        eng.undo_batch(3)
        self.assertEqual(eng.config.buy_fee_rate, "0.00008")
        self.assertEqual(eng.config.sell_fee_rate, "0.00008")
        self.assertEqual(eng.config.stamp_tax_rate, "0.0005")
        self.assertEqual([f.kind for f in eng.fills], ["grid"])
        self.assertEqual(eng.fills[0].fee, "0.4266")

    def test_invalid_fee_rates_do_not_change_the_book(self):
        eng = Engine(Config(), State(base="53.75", initial_shares=0, position=0))
        before = eng.to_dict()
        for kwargs in (
            {"buy_fee_rate": "-0.1"},
            {"sell_fee_rate": "1"},
            {"stamp_tax_rate": ""},
            {"sell_fee_rate": "0.6", "stamp_tax_rate": "0.5"},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    eng.set_fee_rates(**kwargs)
                self.assertEqual(eng.to_dict(), before)


if __name__ == "__main__":
    unittest.main()
