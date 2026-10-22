"""آزمون اختیاری رابط واقعی؛ نیازمند Tk و نمایشگر (یا Xvfb)."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    import tkinter as tk
    from tkinter import ttk
except ImportError:
    tk = ttk = None

from gold_accounting import Ledger, main
from gold_services import ApplicationClock


@unittest.skipUnless(tk is not None, 'Tk is required to import the widget module')
class PersianTextTests(unittest.TestCase):
    def test_mode_selection_and_override(self):
        from gold_widgets import text_mode
        for platform, expected in (('win32', 'native'), ('darwin', 'native'), ('linux', 'manual')):
            with self.subTest(platform=platform), patch('gold_widgets.sys.platform', platform), \
                 patch.dict(os.environ, {'HESAB_GHADIM_TEXT_MODE': 'auto'}):
                self.assertEqual(text_mode(), expected)
                with patch.dict(os.environ, {'HESAB_GHADIM_TEXT_MODE': 'invalid'}):
                    self.assertEqual(text_mode(), expected)
                for override in ('native', 'manual'):
                    with patch.dict(os.environ, {'HESAB_GHADIM_TEXT_MODE': override}):
                        self.assertEqual(text_mode(), override)

    def test_native_keeps_logical_letters_and_is_idempotent(self):
        from gold_widgets import visual
        text = 'حساب قدیم\nPDF گزارش ۱۴۰۵/۰۱/۰۱\nHG-ABCD-1234'
        with patch.dict(os.environ, {'HESAB_GHADIM_TEXT_MODE': 'native'}):
            result = visual(text)
            self.assertEqual(result, '\u200fحساب قدیم\n\u200fPDF گزارش ۱۴۰۵/۰۱/۰۱\nHG-ABCD-1234')
            self.assertEqual(visual(result), result)
            self.assertEqual(visual(1002), '1002')

    def test_manual_preserves_mixed_tokens_and_shaped_lines(self):
        from gold_widgets import visual
        with patch.dict(os.environ, {'HESAB_GHADIM_TEXT_MODE': 'manual'}):
            self.assertEqual(visual('حساب قدیم'), 'ﻢﯾﺪﻗ ﺏﺎﺴﺣ')
            for text, tokens in (
                ('تاریخ 1405/01/02 13:30:45 ثبت شد', ('1405/01/02 13:30:45',)),
                ('تاریخ ۱۴۰۵/۰۱/۰۲ ۱۳:۳۰:۴۵ ثبت شد', ('۱۴۰۵/۰۱/۰۲ ۱۳:۳۰:۴۵',)),
                ('منطقه زمانی: UTC+03:30', ('UTC+03:30',)),
                ('کلید HG-ABCD-1234 و گزارش PDF', ('HG-ABCD-1234', 'PDF')),
                ('وزن 12.50 گرم؛ مبلغ 1,234 تومان', ('12.50', '1,234')),
            ):
                with self.subTest(text=text):
                    result = visual(text)
                    for token in tokens:
                        self.assertIn(token, result)
                    self.assertEqual(visual(result), result)
                    self.assertFalse(any(c in result for c in '\u202a\u202c'))
            shaped = visual('حساب قدیم')
            self.assertEqual(visual(shaped + '\nورود مدیریت'), shaped + '\n' + visual('ورود مدیریت'))


@unittest.skipUnless(tk is not None and (os.name == 'nt' or os.environ.get('DISPLAY')),
                     'Tk and a display are required')
class DesktopTests(unittest.TestCase):
    def test_persian_display_keeps_logical_values(self):
        import gold_widgets as widgets
        root = tk.Tk()
        root.withdraw()
        try:
            source = tk.StringVar(root, value='طلای نو')
            combo = widgets.Combobox(root, textvariable=source,
                                     values=('طلای نو', 'طلای دست‌دوم'), state='readonly')
            label = widgets.Label(root, textvariable=source)
            tree = widgets.Treeview(root, columns=('kind',), show='headings')
            tree.heading('kind', text='نوع طلا')
            tree.insert('', 'end', iid='1', text='عنوان محصول', values=('طلای نو',))
            notebook = widgets.Notebook(root)
            first, second = widgets.Frame(notebook), widgets.Frame(notebook)
            notebook.add(first, text='ورود طلا')
            notebook.insert(0, second, text='خروج طلا')
            self.assertEqual(notebook.tab(first, 'text'), widgets.visual('ورود طلا'))
            self.assertEqual(notebook.tab(second, 'text'), widgets.visual('خروج طلا'))
            notebook.tab(first, text='جستجوی اسناد')
            self.assertEqual(notebook.tab(first, 'text'), widgets.visual('جستجوی اسناد'))
            root.update()
            self.assertEqual(source.get(), 'طلای نو')
            self.assertEqual(combo.get(), widgets.visual('طلای نو'))
            combo.current(1)
            root.update()
            self.assertEqual(source.get(), 'طلای دست‌دوم')
            self.assertEqual(root.getvar(label.cget('textvariable')),
                             widgets.visual('طلای دست‌دوم'))
            source.set('طلای نو')
            self.assertEqual(combo.current(), 0)
            self.assertEqual(tree.heading('kind', 'text'), widgets.visual('نوع طلا'))
            self.assertEqual(tree.item('1', 'values'), (widgets.visual('طلای نو'),))
            self.assertEqual(tree.item('1', 'text'), widgets.visual('عنوان محصول'))
            tree.item('1', text='عنوان جدید', values=('طلای دست‌دوم',))
            self.assertEqual(tree.item('1', 'text'), widgets.visual('عنوان جدید'))
            self.assertEqual(tree.set('1', 'kind'), widgets.visual('طلای دست‌دوم'))
            tree.set('1', 'kind', 'طلای نو')
            self.assertEqual(tree.set('1', 'kind'), widgets.visual('طلای نو'))
            combo.set('طلای دست‌دوم')
            self.assertEqual(source.get(), 'طلای دست‌دوم')
            label.destroy()
            combo.destroy()
            source.set('بدون خطا پس از بستن')
        finally:
            root.destroy()

    def test_first_setup_and_authorized_admin_window(self):
        from gold_widgets import visual
        from gold_features import DesktopFeatures
        root = tk.Tk()
        root.withdraw()
        ledger = Ledger(':memory:')
        feature = DesktopFeatures(root, ledger, ':memory:')
        keys, errors = [], []
        root.report_callback_exception = lambda kind, error, trace: errors.append(error)

        def widgets(parent):
            for child in parent.winfo_children():
                yield child
                yield from widgets(child)

        def finish_setup():
            try:
                entries = [w for w in widgets(root) if isinstance(w, ttk.Entry)]
                keys.append(entries[-1].get())
                for entry, value in zip(entries, ('1405/01/01', '12:00:00')):
                    entry.delete(0, 'end')
                    entry.insert(0, value)
                next(w for w in widgets(root) if isinstance(w, ttk.Checkbutton)).invoke()
                next(w for w in widgets(root) if isinstance(w, ttk.Button)
                     and w.cget('text') == visual('ثبت و قفل تنظیمات اولیه')).invoke()
            except BaseException as error:
                errors.append(error)
                for window in root.winfo_children():
                    if isinstance(window, tk.Toplevel):
                        window.destroy()

        try:
            root.after(100, finish_setup)
            with patch('tkinter.messagebox.askyesno', return_value=True), \
                 patch('tkinter.messagebox.showinfo'), patch('tkinter.messagebox.showerror') as error_dialog:
                self.assertTrue(feature.prepare())
                if errors:
                    raise errors[0]
                self.assertTrue(feature.clock.initialized)
                ledger.timestamp_source = feature.clock.timestamps
                notebook = ttk.Notebook(root)
                notebook.pack(fill='both', expand=True)
                feature.build_overview()
                feature.build_search(notebook)
                ledger.add('in', 'new', '10', '100')
                original_stamp = ledger.get(1)['created_at_jalali']
                with patch('tkinter.simpledialog.askstring', return_value=keys[0]):
                    feature.admin_dialog()
                admin_window = next(w for w in root.winfo_children() if isinstance(w, tk.Toplevel))
                entries = [w for w in widgets(admin_window) if isinstance(w, ttk.Entry)]
                for entry, value in zip(entries, ('1405/01/02', '13:30:00')):
                    entry.delete(0, 'end')
                    entry.insert(0, value)
                next(w for w in widgets(root) if isinstance(w, ttk.Button)
                     and w.cget('text') == visual('ثبت ساعت با مجوز مدیریت')).invoke()
                self.assertTrue(feature.clock.timestamps()[1].startswith('1405/01/02 13:30:'))
                self.assertEqual(ledger.get(1)['created_at_jalali'], original_stamp)
                if errors:
                    raise errors[0]
                error_dialog.assert_not_called()
        finally:
            feature.shutdown()
            ledger.close()
            root.destroy()

    def test_main_search_edit_delete_and_pdf(self):
        from gold_widgets import visual
        from gold_features import DesktopFeatures
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / 'test.sqlite3')
            clock = ApplicationClock(ledger.connection)
            clock.initialize('1405/01/01', '12:00:00')
            ledger.timestamp_source = clock.timestamps
            ledger.add('in', 'new', '10', '100', '4')
            ledger.add('out', 'new', '2', '100', '4', '7', '10')
            ledger.add('in', 'used', '10', '100')
            root = tk.Tk()
            instances, errors = [], []
            root.report_callback_exception = lambda kind, error, trace: errors.append(error)
            original_init = DesktopFeatures.__init__

            def capture(instance, *args):
                original_init(instance, *args)
                instances.append(instance)

            def widgets(parent):
                for child in parent.winfo_children():
                    yield child
                    yield from widgets(child)

            def button(parent, text):
                return next(w for w in widgets(parent)
                            if isinstance(w, ttk.Button) and w.cget('text') == visual(text))

            def exercise():
                try:
                    feature = instances[0]
                    self.assertEqual(len(feature.search_tree.get_children()), 3)
                    self.assertEqual(feature.card_values['new'].get(), '8 گرم')
                    notebook = next(w for w in widgets(root) if isinstance(w, ttk.Notebook))
                    notebook.select(feature.search_tab)
                    feature.date_enabled.set(False)
                    feature.search_vars['document_no'].set('1002')
                    feature.apply_search()
                    self.assertEqual(len(feature.search_tree.get_children()), 1)
                    rows, _, _ = feature.current_report()
                    self.assertEqual(rows[0]['document_no'], 1002)
                    feature.search_tree.selection_set('2')
                    feature.go_to_document()
                    outgoing = root.nametowidget(notebook.select())
                    button(outgoing, 'ویرایش سند انتخاب‌شده').invoke()
                    weight_entry = next(w for w in widgets(outgoing)
                                        if isinstance(w, ttk.Entry) and w.get() == '2')
                    weight_entry.delete(0, 'end')
                    weight_entry.insert(0, '3')
                    button(outgoing, 'ذخیره ویرایش سند 1002').invoke()
                    self.assertEqual(ledger.get(2)['weight'], '3')
                    self.assertEqual(feature.card_values['new'].get(), '7 گرم')
                    # refresh clears selection; select the same document explicitly.
                    tree = next(w for w in widgets(outgoing) if isinstance(w, ttk.Treeview))
                    tree.selection_set('2')
                    button(outgoing, 'حذف سند انتخاب‌شده').invoke()
                    self.assertEqual(len(ledger.rows('out')), 0)
                    self.assertEqual(feature.card_values['new'].get(), '10 گرم')
                    notebook.select(feature.search_tab)
                    feature.reset_search()
                    path = Path(directory) / 'gui-report.pdf'
                    feature.write_report(path)
                    self.assertTrue(path.read_bytes().startswith(b'%PDF'))
                except BaseException as error:
                    errors.append(error)
                finally:
                    instances[0].shutdown()
                    ledger.close()
                    root.destroy()

            root.after(300, exercise)
            with patch('tkinter.Tk', return_value=root), patch('gold_accounting.Ledger', return_value=ledger), \
                 patch.object(DesktopFeatures, '__init__', capture), \
                 patch('tkinter.messagebox.askyesno', return_value=True), \
                 patch('tkinter.messagebox.showinfo'), patch('tkinter.messagebox.showerror') as error_dialog:
                main()
                if errors:
                    raise errors[0]
                error_dialog.assert_not_called()


if __name__ == '__main__':
    unittest.main()
