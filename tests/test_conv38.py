import unittest

from grid_ledger.engine import Config, Engine, FillRequest, State
from grid_ledger.money import D


class TestConv38(unittest.TestCase):
    def _run(self) -> Engine:
        eng = Engine(Config(), State(base="53.75", initial_shares=0, position=0))
        r = eng.submit(FillRequest(fill_price="53.75", side="sell", qty=3400, opening=True, force=True))
        self.assertEqual(r.fills[0].kind, "adjust")
        self.assertFalse(any(f.kind == "grid" for f in eng.fills))
        self.assertEqual(eng.state.position, -3400)
        self.assertEqual(eng.state.initial_shares, -3400)
        self.assertEqual(eng.state.opening_price, "53.7500")
        self.assertEqual(eng.state.sell_proceeds, "0.0000")
        self.assertEqual(eng.state.buy_count, 0)
        self.assertEqual(eng.state.sell_count, 0)
        self.assertEqual(D(eng.state.opening_cash), D("182644.0050"))
        self.assertEqual(D(eng.mark().occupied), D("-182644.0050"))

        r = eng.submit(FillRequest(fill_price="53.32", side="buy"))
        self.assertEqual(r.fills[0].trigger_price, "53.3200")
        self.assertEqual(r.fills[0].cash, "-5332.4266")
        self.assertEqual(eng.state.base, "53.3200")
        self.assertEqual(eng.state.position, -3300)
        self.assertEqual(eng.state.buy_count, 1)

        r = eng.submit(FillRequest(fill_price="52.88", trigger="52.89", side="buy"))
        self.assertEqual(r.fills[0].trigger_price, "52.8900")
        self.assertEqual(r.fills[0].fill_price, "52.8800")
        self.assertEqual(r.fills[0].cash, "-5288.4230")
        self.assertEqual(eng.state.base, "52.8900")
        self.assertEqual(eng.state.position, -3200)
        self.assertEqual(eng.state.buy_count, 2)

        r = eng.submit(FillRequest(fill_price="53.35"))
        self.assertEqual(r.fills[0].side, "sell")
        self.assertEqual(r.fills[0].trigger_price, "53.3396")
        self.assertEqual(r.fills[0].fill_price, "53.3500")
        self.assertEqual(r.fills[0].fee, "3.0943")
        self.assertEqual(r.fills[0].cash, "5331.9057")
        self.assertEqual(eng.state.base, "53.3396")
        self.assertEqual(eng.state.position, -3300)
        self.assertEqual(eng.state.sell_count, 1)
        self.assertEqual(eng.initial_base(), "53.7500")
        self.assertEqual(eng.state.base, "53.3396")
        return eng

    def test_state_and_gain(self):
        eng = self._run()
        lv = eng.levels()
        self.assertEqual((lv.buy2, lv.buy1, lv.base, lv.sell1, lv.sell2), ("52.4896", "52.9129", "53.3396", "53.7930", "54.2502"))
        mk = eng.mark("53.35")
        self.assertEqual(mk.net_cash, "177355.0611")
        self.assertEqual(mk.occupied, "-177355.0611")
        self.assertEqual(mk.hold, "1254.0050")
        self.assertEqual(mk.actual, "1300.0611")
        self.assertEqual(mk.gain, "46.0561")

    def test_52_88_infers_buy_without_trigger(self):
        eng = Engine(Config(), State(base="53.75", initial_shares=0, position=0))
        eng.submit(FillRequest(fill_price="53.75", side="sell", qty=3400, opening=True, force=True))
        eng.submit(FillRequest(fill_price="53.32", side="buy"))
        r = eng.submit(FillRequest(fill_price="52.88"))
        self.assertEqual(r.fills[0].side, "buy")
        self.assertEqual(r.fills[0].trigger_price, "52.8934")
        self.assertEqual(r.fills[0].fill_price, "52.8800")


if __name__ == "__main__":
    unittest.main()
