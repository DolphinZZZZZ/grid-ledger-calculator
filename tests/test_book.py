import tempfile
import unittest
from grid_ledger import book
from grid_ledger.cli import run_line
from grid_ledger.engine import Config, Engine, FillRequest, State
from grid_ledger.money import D


class TestBookRoundtrip(unittest.TestCase):
    def setUp(self):
        self._old = book.BOOKS
        self.tmp = tempfile.TemporaryDirectory()
        book.set_books_dir(self.tmp.name)

    def tearDown(self):
        book.set_books_dir(self._old)
        self.tmp.cleanup()

    def test_save_load_gain(self):
        eng = Engine(Config(), State(base="53.75", initial_shares=0, position=0))
        eng.submit(FillRequest(fill_price="53.75", side="sell", qty=3400, opening=True, force=True))
        eng.submit(FillRequest(fill_price="53.32", side="buy"))
        eng.submit(FillRequest(fill_price="52.88"))
        eng.submit(FillRequest(fill_price="53.35"))
        book.save("实盘", eng)
        name, loaded = book.load("实盘")
        self.assertEqual(name, "实盘")
        mk = loaded.mark("53.35")
        self.assertEqual(mk.gain, "46.0561")
        self.assertEqual(loaded.state.base, "53.3430")
        self.assertEqual(len(loaded.fills), 4)

    def test_cli_lines(self):
        book.create("实盘", base="53.75", shares=-3400, opening_price="53.75")
        name, eng = book.load("实盘")
        out, eng, _ = run_line(name, eng, "53.32b")
        self.assertIn("53.32", out)
        out, eng, _ = run_line(name, eng, "52.88")
        self.assertIn("52.89", out)
        out, eng, _ = run_line(name, eng, "53.35")
        self.assertIn("46.06", out)
        self.assertEqual(D(eng.mark().gain), D("46.0561"))

    def test_set_initial_via_cli(self):
        book.create("实盘", base="53.75", shares=-3400, opening_price="53.75")
        name, eng = book.load("实盘")
        out, eng, _ = run_line(name, eng, "53.32b")
        out, eng, _ = run_line(name, eng, "初始持仓是-3000")
        self.assertEqual(eng.state.initial_shares, -3000)
        self.assertEqual(eng.state.position, -3300)
        self.assertEqual(eng.state.net_bought(), -300)
        self.assertIn("初始持仓", out)

    def test_duplicate_and_rename_slots(self):
        book.create("甲", base="53.75", shares=-3400, opening_price="53.75")
        name, eng = book.load("甲")
        run_line(name, eng, "53.32b")
        book.save("甲", eng)
        book.duplicate("甲", "乙")
        self.assertTrue(book.exists("甲"))
        self.assertTrue(book.exists("乙"))
        _, b = book.load("乙")
        self.assertEqual(b.state.position, -3300)
        slots = book.list_slots()
        names = [s["name"] for s in slots]
        self.assertIn("甲", names)
        self.assertIn("乙", names)
        self.assertTrue(any(s.get("saved_at") for s in slots))
        book.set_current("甲")
        book.rename("甲", "丙")
        self.assertFalse(book.exists("甲"))
        self.assertTrue(book.exists("丙"))
        self.assertEqual(book.current_name(), "丙")

    def test_calc_state_roundtrip_not_a_book(self):
        self.assertIsNone(book.load_calc_state())
        saved = {"side": "buy", "start": "10.00", "up": "2", "down": "1.2", "n": "8"}
        book.save_calc_state(saved)
        loaded = book.load_calc_state()
        self.assertEqual(loaded["side"], "buy")
        self.assertEqual(loaded["start"], "10.00")
        self.assertEqual(loaded["up"], "2")
        self.assertEqual(loaded["down"], "1.2")
        self.assertEqual(loaded["n"], "8")
        self.assertNotIn("_calc", book.list_books())
        book.create("实盘", base="53.75", shares=0)
        self.assertEqual(book.list_books(), ["实盘"])


if __name__ == "__main__":
    unittest.main()
