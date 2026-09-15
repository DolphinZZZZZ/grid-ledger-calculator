import unittest

from grid_ledger.calc import MAX_TRIGGERS, project
from grid_ledger.engine import Config, Engine, FillRequest, State, _walk_n
from grid_ledger.money import D, round_price


class TestProject(unittest.TestCase):
    def test_sell_five_grids(self):
        p = project("53.75", "5", "0.85", "sell")
        self.assertEqual(p.side, "sell")
        self.assertEqual(p.start, "53.7500")
        self.assertEqual(p.n, 5)
        self.assertEqual(p.prices, ("54.2069", "54.6677", "55.1324", "55.6010", "56.0736"))
        self.assertEqual(p.stop, "56.0736")
        self.assertEqual(p.avg, "55.1363")

    def test_buy_five_grids(self):
        p = project("53.75", "5", "0.8", "buy")
        self.assertEqual(p.side, "buy")
        self.assertEqual(p.prices, ("53.3200", "52.8934", "52.4703", "52.0505", "51.6341"))
        self.assertEqual(p.stop, "51.6341")
        self.assertEqual(p.avg, "52.4737")

    def test_matches_engine_walk(self):
        start, n = "53.70", 3
        cfg = Config()
        sells = project(start, n, cfg.up_pct, "sell")
        buys = project(start, n, cfg.down_pct, "buy")
        self.assertEqual(list(sells.prices), _walk_n(start, "sell", n, cfg, None))
        self.assertEqual(list(buys.prices), _walk_n(start, "buy", n, cfg, None))

    def test_stepwise_not_closed_form(self):
        p = project("0.50", 2, "0.85", "sell")
        self.assertEqual(p.prices, ("0.5043", "0.5086"))
        closed = str(round_price(D("0.50") * (D("1.0085") ** 2)))
        self.assertEqual(closed, "0.5085")
        self.assertEqual(p.stop, "0.5086")

    def test_start_not_in_average(self):
        p = project("53.75", 1, "0.85", "sell")
        self.assertEqual(p.prices, ("54.2069",))
        self.assertEqual(p.avg, "54.2069")
        p = project("53.75", 1, "0.8", "buy")
        self.assertEqual(p.prices, ("53.3200",))
        self.assertEqual(p.avg, "53.3200")

    def test_strips_percent_and_rounds_start(self):
        p = project("53.754", 1, "0.85%", "sell")
        self.assertEqual(p.start, "53.7540")
        self.assertEqual(p.display_places, 3)
        self.assertEqual(p.step_pct, "0.85")

    def test_rejects_bad_inputs(self):
        with self.assertRaises(ValueError):
            project("0", 1, "0.85", "sell")
        with self.assertRaises(ValueError):
            project("53.75", 0, "0.85", "sell")
        with self.assertRaises(ValueError):
            project("53.75", "1.5", "0.85", "sell")
        with self.assertRaises(ValueError):
            project("53.75", 1, "0", "sell")
        with self.assertRaises(ValueError):
            project("53.75", 1, "100", "buy")
        with self.assertRaises(ValueError):
            project("53.75", 1, "0.85", "both")
        with self.assertRaises(ValueError):
            project("53.75", MAX_TRIGGERS + 1, "0.85", "sell")

    def test_sell_ignores_down_step(self):
        p = project("53.75", 1, "0.85", "sell")
        self.assertEqual(p.stop, "54.2069")

    def test_does_not_touch_engine(self):
        eng = Engine(Config(), State(base="53.75", initial_shares=0, position=0))
        eng.submit(FillRequest(fill_price="53.75", side="sell", qty=100, opening=True, force=True))
        before = (eng.state.base, eng.state.position, len(eng.fills), eng.config.up_pct)
        project("10.00", 8, "1", "sell")
        self.assertEqual(
            (eng.state.base, eng.state.position, len(eng.fills), eng.config.up_pct),
            before,
        )


if __name__ == "__main__":
    unittest.main()
