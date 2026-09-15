import unittest

from grid_ledger.money import D, round_money, round_price


class TestMoney(unittest.TestCase):
    def test_half_up_not_banker(self):
        self.assertEqual(round_money("1.23445"), D("1.2345"))
        self.assertEqual(round_money("1.23435"), D("1.2344"))
        self.assertEqual(round_price("54.15645"), D("54.1565"))

    def test_fees_conv38(self):
        amount = round_money(D(100) * D("53.32"))
        fee = round_money(amount * D("0.00008"))
        self.assertEqual(amount, D("5332.00"))
        self.assertEqual(fee, D("0.4266"))

        amount = round_money(D(100) * D("52.88"))
        fee = round_money(amount * D("0.00008"))
        self.assertEqual(fee, D("0.4230"))

        amount = round_money(D(3400) * D("53.75"))
        fee = round_money(amount * D("0.00058"))
        self.assertEqual(amount, D("182750.00"))
        self.assertEqual(fee, D("105.9950"))

        amount = round_money(D(100) * D("53.35"))
        fee = round_money(amount * D("0.00058"))
        self.assertEqual(fee, D("3.0943"))


if __name__ == "__main__":
    unittest.main()
