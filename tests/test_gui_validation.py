import copy
import tempfile
import unittest
from unittest.mock import patch

from grid_ledger import book
from grid_ledger.calc import project
from grid_ledger.engine import Engine
from grid_ledger.gui import App, NewBookDialog


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


class TestGuiValidation(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.tk = tk
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display")
        self.root.withdraw()
        self.old = book.BOOKS
        self.tmp = tempfile.TemporaryDirectory()
        book.set_books_dir(self.tmp.name)
        book.create("测试", "53.755", 0)
        self.popup_patch = patch("grid_ledger.gui.messagebox.showerror")
        self.popup = self.popup_patch.start()
        self.app = App(self.root)
        self.root.update_idletasks()

    def tearDown(self):
        self.popup_patch.stop()
        try:
            self.root.destroy()
        except self.tk.TclError:
            pass
        book.set_books_dir(self.old)
        self.tmp.cleanup()

    def test_invalid_trade_popup_keeps_every_input(self):
        self.app.buf.set("0")
        self.app.trigger_var.set("53.32")
        self.app.qty_var.set("100")
        before = copy.deepcopy(self.app.engine.to_dict())
        saved = book.book_path("测试").read_bytes()
        with patch.object(Engine, "_commit_batch") as commit:
            self.app._go("buy")
            commit.assert_not_called()
        self.popup.assert_called_once()
        self.assertEqual(self.app.buf.text, "0")
        self.assertEqual(self.app.trigger_var.get(), "53.32")
        self.assertEqual(self.app.qty_var.get(), "100")
        self.assertEqual(self.app.engine.to_dict(), before)
        self.assertEqual(book.book_path("测试").read_bytes(), saved)

    def test_invalid_command_is_not_cleared(self):
        for text in ("53.32买入-100股", "改基准价 0", "set down 101", "53.32成交100.5股",
                     "初始持仓1.5", "成交价53.75.5", "53.32成交NaN股"):
            with self.subTest(text=text):
                self.popup.reset_mock()
                self.app.cmd_var.set(text)
                self.app._run_cmd()
                self.popup.assert_called_once()
                self.assertEqual(self.app.cmd_var.get(), text)

    def test_invalid_calculator_input_does_not_enter_grid_math(self):
        self.app._open_calc()
        calc = self.app._calc_win
        calc.start_var.set("53.755")
        calc.n_var.set("1.5")
        with patch("grid_ledger.calc._walk_n") as walk:
            calc._compute()
            walk.assert_not_called()
        self.popup.assert_called_once()
        self.assertEqual(calc.start_var.get(), "53.755")
        self.assertEqual(calc.n_var.get(), "1.5")
        self.assertEqual(calc.stop_var.get(), "—")
        calc.n_var.set("5")
        calc._compute()
        self.assertEqual(calc.stop_var.get(), "56.079")
        self.assertEqual(calc.avg_var.get(), "55.141")
        self.assertEqual(calc.err_var.get(), "")

    def test_two_and_three_decimal_display(self):
        self.app._open_calc()
        calc = self.app._calc_win
        for start, stop, avg in [("53.75", "56.07", "55.14"), ("53.755", "56.079", "55.141")]:
            calc.start_var.set(start)
            calc._compute()
            self.assertEqual(calc.stop_var.get(), stop)
            self.assertEqual(calc.avg_var.get(), avg)
        self.assertEqual(self.app.lv["base"].cget("text"), "53.755")
        self.assertEqual(self.app.lv["sell1"].cget("text"), "54.212")

    def test_selected_price_and_calc_defaults_keep_hidden_fourth_decimal(self):
        self.app._use_level("sell1")
        self.assertEqual(self.app.buf.text, "54.212")
        self.assertEqual(self.app.buf.price(), "54.2119")
        self.app._go("sell")
        self.assertEqual(self.app.engine.state.base, "54.2119")
        self.app._open_calc()
        calc = self.app._calc_win
        self.assertEqual(calc.start_var.get(), "54.212")
        self.assertEqual(calc.snapshot()["start"], "54.2119")
        expected = project("54.2119", 5, "0.85", "sell", places=3)
        self.assertEqual(calc.stop_var.get(), self.app.engine.format_price(expected.stop))
        calc._close()
        self.app._open_calc()
        calc = self.app._calc_win
        self.assertEqual(calc.snapshot()["start"], "54.2119")
        calc.start_var.set("54.212")
        self.assertEqual(calc.snapshot()["start"], "54.212")

    def test_parent_close_saves_uncomputed_input(self):
        self.app._open_calc()
        calc = self.app._calc_win
        calc.start_var.set("10.123")
        calc.up_var.set("2")
        calc.down_var.set("1.2")
        calc.n_var.set("8")
        self.app._on_close()
        saved = book.load_calc_state()
        self.assertEqual(saved["start"], "10.123")
        self.assertEqual(saved["n"], "8")
        self.root = self.tk.Tk()
        self.root.withdraw()
        self.app = App(self.root)
        self.app._open_calc()
        self.assertEqual(self.app._calc_win.start_var.get(), "10.123")
        self.assertEqual(self.app._calc_win.up_var.get(), "2")
        self.assertEqual(self.app._calc_win.n_var.get(), "8")

    def test_invalid_calculator_input_survives_reopening(self):
        self.app._open_calc()
        for raw in ("1e999", "0", "bad"):
            calc = self.app._calc_win
            calc.start_var.set(raw)
            calc._close()
            self.app._open_calc()
            calc = self.app._calc_win
            self.assertEqual(calc.start_var.get(), raw)
            self.assertEqual(calc.stop_var.get(), "—")

    def test_invalid_quantity_conversion_keeps_input(self):
        self.app.buf.set("100.5")
        self.app._to_qty()
        self.popup.assert_called_once()
        self.assertEqual(self.app.buf.text, "100.5")
        self.assertEqual(self.app.qty_var.get(), "100")

    def _run_modal_action(self, action, open_dialog):
        errors = []

        def interact():
            win = next(w for w in self.root.winfo_children() if isinstance(w, self.tk.Toplevel))
            try:
                action(win)
            except Exception as error:
                errors.append(error)
            finally:
                if win.winfo_exists():
                    win.destroy()

        self.root.after(30, interact)
        result = open_dialog()
        if errors:
            raise errors[0]
        return result

    def test_new_book_invalid_lot_leaves_dialog_and_fields(self):
        def action(win):
            entries = [w for w in descendants(win) if isinstance(w, self.tk.Entry)]
            entries[4].delete(0, "end")
            entries[4].insert(0, "-100")
            button = next(w for w in descendants(win) if isinstance(w, self.tk.Button) and w.cget("text") == "创建")
            button.invoke()
            self.popup.assert_called_once()
            self.assertTrue(win.winfo_exists())
            self.assertEqual(entries[4].get(), "-100")
            self.assertEqual(book.list_books(), ["测试"])

        dialog = self._run_modal_action(action, lambda: NewBookDialog(self.root))
        self.assertIsNone(dialog.result)

    def test_step_dialog_keeps_invalid_value_then_accepts_correction(self):
        def action(win):
            entry = next(w for w in descendants(win) if isinstance(w, self.tk.Entry))
            button = next(w for w in descendants(win) if isinstance(w, self.tk.Button) and w.cget("text") == "确定")
            entry.delete(0, "end")
            entry.insert(0, "101")
            button.invoke()
            self.popup.assert_called_once()
            self.assertTrue(win.winfo_exists())
            self.assertEqual(entry.get(), "101")
            self.assertEqual(self.app.engine.config.down_pct, "0.8")
            entry.delete(0, "end")
            entry.insert(0, "0.7")
            button.invoke()

        self._run_modal_action(action, lambda: self.app._edit_step("down"))
        self.assertEqual(self.app.engine.config.down_pct, "0.7")


if __name__ == "__main__":
    unittest.main()
