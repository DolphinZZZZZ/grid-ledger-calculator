import tempfile
import unittest

from grid_ledger import book
from grid_ledger.engine import Config, Engine, FillRequest, State
from grid_ledger.gui import PriceBuffer, format_tape_applied


class TestPriceBuffer(unittest.TestCase):
    def test_digits_and_dot(self):
        b = PriceBuffer()
        b.press("5")
        b.press("3")
        b.press(".")
        b.press(".")
        b.press("3")
        b.press("2")
        self.assertEqual(b.price(), "53.32")

    def test_fresh_replaces(self):
        b = PriceBuffer()
        b.set("53.32", fresh=True)
        b.press("9")
        self.assertEqual(b.text, "9")


class TestTape(unittest.TestCase):
    def test_applied_mentions_gain(self):
        eng = Engine(Config(), State(base="53.75", initial_shares=0, position=0))
        r = eng.submit(FillRequest(fill_price="53.75", side="sell", qty=3400, opening=True, force=True))
        text = format_tape_applied(eng, r)
        self.assertIn("建仓", text)
        self.assertIn("基准 53.75", text)


class TestGuiSmoke(unittest.TestCase):
    def _with_tmp_books(self):
        old = book.BOOKS
        tmp = tempfile.TemporaryDirectory()
        book.set_books_dir(tmp.name)
        return old, tmp

    def _restore_books(self, old, tmp):
        book.set_books_dir(old)
        tmp.cleanup()

    def test_build_window(self):
        try:
            import tkinter as tk
        except Exception:
            self.skipTest("no tkinter")
        from grid_ledger.gui import App

        try:
            root = tk.Tk()
        except Exception:
            self.skipTest("no display")
        root.withdraw()
        try:
            app = App(root)
            self.assertIn("init", app.stat)
            app._refresh()
            if app.engine:
                self.assertTrue(app.engine.config.allow_short)
                self.assertTrue(app.engine.config.allow_net_buy_over_zero)
        finally:
            root.destroy()

    def test_pad_right_tape_bottom(self):
        try:
            import tkinter as tk
        except Exception:
            self.skipTest("no tkinter")
        from grid_ledger.gui import App

        try:
            root = tk.Tk()
        except Exception:
            self.skipTest("no display")
        try:
            app = App(root)
            root.update()
            self.assertTrue(app.pad.winfo_ismapped())
            self.assertTrue(app.tape.winfo_ismapped())
            self.assertGreater(app.pad.winfo_rootx(), app.lcd.winfo_rootx())
            self.assertGreater(app.tape.winfo_rooty(), app.pad.winfo_rooty())
            self.assertGreater(app.tape.winfo_height(), 80)
        finally:
            root.destroy()

    def test_calc_window_alongside_ledger(self):
        try:
            import tkinter as tk
        except Exception:
            self.skipTest("no tkinter")
        from grid_ledger.gui import App

        try:
            root = tk.Tk()
        except Exception:
            self.skipTest("no display")
        old, tmp = self._with_tmp_books()
        try:
            book.create("实盘", base="53.75", shares=0)
            app = App(root)
            root.update()
            before = (
                app.engine.state.base,
                app.engine.state.position,
                app.engine.state.buy_count,
                app.engine.state.sell_count,
                len(app.engine.fills),
                app.engine.config.up_pct,
                app.engine.config.down_pct,
            )
            app._open_calc()
            root.update()
            self.assertIsNotNone(app._calc_win)
            calc = app._calc_win.win
            self.assertTrue(calc.winfo_exists())
            self.assertIsNot(calc, root)
            self.assertTrue(app.pad.winfo_ismapped())
            self.assertTrue(app.tape.winfo_ismapped())
            app._calc_win.start_var.set("53.75")
            app._calc_win.up_var.set("0.85")
            app._calc_win.down_var.set("0.8")
            app._calc_win.n_var.set("5")
            app._calc_win._set_side("sell")
            app._calc_win._compute()
            root.update()
            self.assertEqual(app._calc_win.side_var.get(), "sell")
            self.assertEqual(app._calc_win.stop_var.get(), "56.07")
            self.assertEqual(app._calc_win.avg_var.get(), "55.14")
            self.assertNotIn("买入价", app._calc_win.table.get("1.0", "end"))
            app._calc_win._set_side("buy")
            root.update()
            self.assertEqual(app._calc_win.side_var.get(), "buy")
            self.assertEqual(app._calc_win.stop_var.get(), "51.63")
            self.assertEqual(app._calc_win.avg_var.get(), "52.47")
            self.assertNotIn("卖出价", app._calc_win.table.get("1.0", "end"))
            self.assertEqual(
                (
                    app.engine.state.base,
                    app.engine.state.position,
                    app.engine.state.buy_count,
                    app.engine.state.sell_count,
                    len(app.engine.fills),
                    app.engine.config.up_pct,
                    app.engine.config.down_pct,
                ),
                before,
            )
            first = calc
            app._open_calc()
            root.update()
            self.assertIsNone(app._calc_win)
            self.assertFalse(first.winfo_exists())
            self.assertTrue(app.pad.winfo_ismapped())
        finally:
            try:
                root.destroy()
            except Exception:
                pass
            self._restore_books(old, tmp)

    def test_calc_remembers_inputs_after_close(self):
        try:
            import tkinter as tk
        except Exception:
            self.skipTest("no tkinter")
        from grid_ledger.gui import App

        try:
            root = tk.Tk()
        except Exception:
            self.skipTest("no display")
        old, tmp = self._with_tmp_books()
        try:
            app = App(root)
            root.update()
            book_defaults = app._calc_defaults()
            app._open_calc()
            root.update()
            app._calc_win.start_var.set("10.00")
            app._calc_win.up_var.set("2")
            app._calc_win.down_var.set("1.2")
            app._calc_win.n_var.set("8")
            app._calc_win._set_side("buy")
            root.update()
            self.assertNotEqual(app._calc_win.start_var.get(), book_defaults["start"])
            app._open_calc()
            root.update()
            self.assertIsNone(app._calc_win)
            app._open_calc()
            root.update()
            self.assertEqual(app._calc_win.start_var.get(), "10.00")
            self.assertEqual(app._calc_win.up_var.get(), "2")
            self.assertEqual(app._calc_win.down_var.get(), "1.2")
            self.assertEqual(app._calc_win.n_var.get(), "8")
            self.assertEqual(app._calc_win.side_var.get(), "buy")
            self.assertEqual(app._calc_win.stop_var.get(), "9.08")
        finally:
            try:
                root.destroy()
            except Exception:
                pass
            self._restore_books(old, tmp)

    def test_calc_state_survives_app_restart(self):
        try:
            import tkinter as tk
        except Exception:
            self.skipTest("no tkinter")
        from grid_ledger.gui import App

        try:
            root = tk.Tk()
        except Exception:
            self.skipTest("no display")
        old, tmp = self._with_tmp_books()
        try:
            app = App(root)
            root.update()
            app._open_calc()
            root.update()
            app._calc_win.start_var.set("10.00")
            app._calc_win.up_var.set("2")
            app._calc_win.down_var.set("1.2")
            app._calc_win.n_var.set("8")
            app._calc_win._set_side("buy")
            root.update()
            app._open_calc()
            root.update()
            root.destroy()
            root = tk.Tk()
            app = App(root)
            root.update()
            app._open_calc()
            root.update()
            self.assertEqual(app._calc_win.start_var.get(), "10.00")
            self.assertEqual(app._calc_win.up_var.get(), "2")
            self.assertEqual(app._calc_win.down_var.get(), "1.2")
            self.assertEqual(app._calc_win.n_var.get(), "8")
            self.assertEqual(app._calc_win.side_var.get(), "buy")
            self.assertEqual(app._calc_win.stop_var.get(), "9.08")
        finally:
            try:
                root.destroy()
            except Exception:
                pass
            self._restore_books(old, tmp)


if __name__ == "__main__":
    unittest.main()

