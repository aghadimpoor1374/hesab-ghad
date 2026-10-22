"""Run GUI routing checks with xvfb-run -a python -m unittest test_special_navigation."""
import os
import tempfile
import unittest
from unittest.mock import patch
import tkinter as tk
from tkinter import ttk
import gold_accounting
from gold_widgets import visual


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name == 'nt', 'Display required')
class NavigationTests(unittest.TestCase):
    def test_purchase_and_sale_route_to_special_form_without_posting(self):
        with tempfile.TemporaryDirectory() as folder:
            close_app = []

            def inspect(root):
                try:
                    root.update_idletasks()
                    notebook = next(w for w in descendants(root) if isinstance(w, ttk.Notebook))
                    selectors = [w for w in descendants(root) if isinstance(w, ttk.Combobox)
                                 and visual('طلای آبشده') in w.cget('values')]
                    self.assertEqual(len(selectors), 2)
                    for selector in selectors:
                        ancestor = selector
                        while str(ancestor) not in notebook.tabs():
                            ancestor = ancestor.master
                        title = notebook.tab(ancestor, 'text')
                        expected_direction = 'خرید / ورود' if visual('ورود') in title else 'فروش / خروج'
                        for choice, expected_kind in [('طلای آبشده', 'آبشده'), ('سکه', 'امامی ۸۶'), ('سکه پارسیان', 'پارسیان')]:
                            self.assertIn(visual(choice), selector.cget('values'))
                            notebook.select(ancestor)
                            selector.set(choice)
                            selector.event_generate('<<ComboboxSelected>>')
                            root.update_idletasks()
                            self.assertEqual(selector.get(), visual('طلای نو'))
                            self.assertEqual(notebook.tab(notebook.select(), 'text'), visual('سکه، آبشده و حساب دوگانه'))
                            special = root.nametowidget(notebook.select())
                            values = [w.get() for w in descendants(special) if isinstance(w, ttk.Combobox)]
                            self.assertIn(expected_kind, values)
                            self.assertIn(expected_direction, values)
                    import sqlite3
                    with sqlite3.connect(os.environ['HESAB_GHADIM_DATABASE']) as db:
                        self.assertEqual(db.execute('SELECT COUNT(*) FROM special_trades').fetchone()[0], 0)
                        self.assertEqual(db.execute('SELECT COUNT(*) FROM transactions').fetchone()[0], 0)
                finally:
                    close_app[0]()

            with patch.dict(os.environ, {'HESAB_GHADIM_DATABASE': os.path.join(folder, 'test.sqlite3')}):
                from gold_services import ApplicationClock
                ledger = gold_accounting.Ledger(os.environ['HESAB_GHADIM_DATABASE'])
                clock = ApplicationClock(ledger.connection)
                clock.initialize('1404/01/01', '12:00:00', clock.generate_license())
                ledger.close()
                with patch.object(tk.Tk, 'mainloop', inspect):
                    gold_accounting.main(license_setup=lambda root, close: close_app.append(close))


if __name__ == '__main__':
    unittest.main()
