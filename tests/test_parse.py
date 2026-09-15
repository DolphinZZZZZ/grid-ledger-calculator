import unittest

from grid_ledger.parse import parse


class TestParse(unittest.TestCase):
    def test_bsuffix(self):
        p = parse("53.32b")
        self.assertEqual(p.op, "fill")
        self.assertEqual(p.fill_price, "53.3200")
        self.assertEqual(p.side, "buy")

    def test_plain_price(self):
        p = parse("52.88")
        self.assertEqual(p.op, "fill")
        self.assertEqual(p.fill_price, "52.8800")
        self.assertIsNone(p.side)

    def test_trigger_and_fill(self):
        p = parse("57.08触发57.12")
        self.assertEqual(p.fill_price, "57.0800")
        self.assertEqual(p.trigger, "57.1200")

    def test_trigger_qty_not_price(self):
        p = parse("2.触发网格53.75成交3400股")
        self.assertEqual(p.trigger, "53.7500")
        self.assertEqual(p.fill_price, "53.7500")
        self.assertEqual(p.qty, 3400)

    def test_opening(self):
        p = parse("初始：53.75卖出3400股")
        self.assertTrue(p.opening)
        self.assertEqual(p.side, "sell")
        self.assertEqual(p.fill_price, "53.7500")
        self.assertEqual(p.qty, 3400)

    def test_opening_at(self):
        p = parse("建仓 卖出 3400 @53.75")
        self.assertTrue(p.opening)
        self.assertEqual(p.side, "sell")
        self.assertEqual(p.fill_price, "53.7500")
        self.assertEqual(p.qty, 3400)

    def test_actual_fill(self):
        p = parse("按照成交52.88")
        self.assertEqual(p.fill_price, "52.8800")
        self.assertTrue(p.force)

    def test_sell_qty(self):
        p = parse("58.73成交500股")
        self.assertEqual(p.fill_price, "58.7300")
        self.assertEqual(p.qty, 500)

    def test_undo(self):
        self.assertEqual(parse("撤回").op, "undo")
        self.assertEqual(parse("撤回2").undo_n, 2)

    def test_keep_one(self):
        p = parse("错误，只触发了一格，成交价为57.9")
        self.assertEqual(p.op, "keep_one")
        self.assertEqual(p.fill_price, "57.9000")

    def test_pending_choice(self):
        p = parse("1", pending_keys={"1", "2"})
        self.assertEqual(p.op, "confirm")
        p = parse("53", pending_keys={"1", "2"})
        self.assertEqual(p.op, "fill")
        self.assertEqual(p.fill_price, "53.0000")

    def test_set_initial(self):
        p = parse("初始持仓是-3400")
        self.assertEqual(p.op, "set")
        self.assertEqual(p.set_key, "initial_shares")
        self.assertEqual(p.set_val, "-3400")

    def test_cancel_limit(self):
        p = parse("取消净买入卖出限制")
        self.assertEqual(p.op, "set")
        self.assertEqual(p.set_key, "allow_net_buy_over_zero")


if __name__ == "__main__":
    unittest.main()
