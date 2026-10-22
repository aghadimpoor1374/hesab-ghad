"""رابط جستجو، راه‌اندازی اولیه و گزارش‌های حساب قدیم."""
from datetime import datetime
from decimal import Decimal
from pathlib import Path
import sqlite3
import tempfile
import tkinter as tk
from tkinter import filedialog
from gold_widgets import messagebox, simpledialog
import gold_widgets as ttk
from gold_widgets import TkLabel

from gold_accounting import display, money
from gold_services import APP_ZONE, ApplicationClock, jalali_timestamp, validate_search
from gold_reports import export_pdf, send_to_printer


def document_range(rows, start='', end=''):
    """Inclusive document-number bounds, independent of invoice numbers."""
    def bound(value):
        value = str(value).strip()
        if not value:
            return None
        if not value.isdecimal() or int(value) < 1:
            raise ValueError('شماره سند باید عدد صحیح مثبت باشد.')
        return int(value)
    low, high = bound(start), bound(end)
    if low is not None and high is not None and low > high:
        raise ValueError('شماره سند ابتدا نباید بزرگ‌تر از انتها باشد.')
    selected = [row for row in rows if
                (low is None or (row['document_no'] is not None and row['document_no'] >= low)) and
                (high is None or (row['document_no'] is not None and row['document_no'] <= high))]
    description = ' | '.join(text for text in (
        f'از سند: {low}' if low is not None else '',
        f'تا سند: {high}' if high is not None else '') if text)
    if description and not selected:
        raise ValueError('در بازه انتخاب‌شده و فیلترهای برگه فعال، سندی وجود ندارد.')
    return selected, description


class DesktopFeatures:
    def __init__(self, root, ledger, database):
        self.root, self.ledger, self.database = root, ledger, database
        self.clock = ApplicationClock(ledger.connection)
        self.active_filters = {}
        self.report_context = None
        self.locate_document = None
        self.search_tree = None
        self.follow_today = True
        self.timer = None
        self.ticks = 0
        self.last_day = None
        self.print_directory = tempfile.TemporaryDirectory(prefix="hesab-ghadim-print-")
        self.style()

    def style(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        self.root.configure(background="#edf2f3")
        style.configure(".", font=("Tahoma", 10), background="#edf2f3", foreground="#233c43")
        style.configure("TFrame", background="#edf2f3")
        style.configure("TLabel", background="#edf2f3", padding=2)
        style.configure("TLabelframe", background="#edf2f3", bordercolor="#d1dcdf")
        style.configure("TLabelframe.Label", background="#edf2f3", foreground="#1b655f")
        style.configure("TButton", padding=(8, 3), borderwidth=0, background="#dde7e9")
        style.map("TButton", background=[("active", "#ccdedd")])
        style.configure("Accent.TButton", background="#176b60", foreground="white")
        style.map("Accent.TButton", background=[("active", "#0e5149")])
        style.configure("TEntry", padding=2, fieldbackground="white")
        style.configure("TCombobox", padding=2, fieldbackground="white")
        style.configure("TNotebook", background="#edf2f3", borderwidth=0)
        style.configure("TNotebook.Tab", padding=(14, 4), background="#dde7e9")
        style.map("TNotebook.Tab", background=[("selected", "#176b60")],
                  foreground=[("selected", "white")])
        style.configure("Treeview", rowheight=25, font=("Tahoma", 9), fieldbackground="white", background="white")
        style.configure("Treeview.Heading", font=("Tahoma", 9, "bold"), padding=3,
                        background="#dce7e7", foreground="#163e45")
        style.map("Treeview", background=[("selected", "#176b60")], foreground=[("selected", "white")])

    def prepare(self):
        if not self.clock.initialized and not self.initial_setup():
            return False
        self.ledger.timestamp_source = self.clock.timestamps
        self.build_header()
        self.tick()
        return True

    def save_license(self, key, parent, acknowledged):
        path = filedialog.asksaveasfilename(parent=parent, title="نگهداری کلید مدیریت در محل امن",
                                          defaultextension=".txt", initialfile="hesab-ghadim-admin-key.txt",
                                          filetypes=[("متن", "*.txt")])
        if not path:
            return
        try:
            Path(path).write_text("حساب قدیم — کلید مدیریت محلی\n" + key +
                                  "\nاین کلید را محرمانه و جدا از فایل داده نگهداری کنید.\n", encoding="utf-8")
            acknowledged.set(True)
        except OSError as error:
            messagebox.showerror("ذخیره نشد", str(error), parent=parent)

    def initial_setup(self):
        window = tk.Toplevel(self.root)
        window.title("حساب قدیم | راه‌اندازی اولیه")
        window.resizable(False, False)
        body = ttk.Frame(window, padding=24)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="به حساب قدیم خوش آمدید", font=("Tahoma", 17, "bold"), anchor="e").pack(fill="x")
        ttk.Label(body, text="تاریخ و ساعت داخلی را یک‌بار تنظیم کنید؛ پس از ثبت، فقط با کلید مدیریت تغییر می‌کند.\n"
                  "این تنظیم ساعت ویندوز را تغییر نمی‌دهد. منطقه زمانی برنامه: UTC+03:30",
                  justify="right", anchor="e").pack(fill="x", pady=12)
        now = datetime.now(APP_ZONE)
        date = tk.StringVar(value=jalali_timestamp(now)[:10])
        clock = tk.StringVar(value=now.strftime("%H:%M:%S"))
        for label, variable in (("تاریخ شمسی (سال/ماه/روز)", date), ("ساعت (ساعت:دقیقه:ثانیه)", clock)):
            row = ttk.Frame(body)
            row.pack(fill="x", pady=5)
            ttk.Label(row, text=label, width=30, anchor="e").pack(side="right")
            ttk.Entry(row, textvariable=variable, justify="right", width=26).pack(side="right", padx=8)
        key = self.clock.generate_license()
        ttk.Label(body, text="کلید مدیریت محلی شما — قابل بازیابی خودکار نیست", anchor="e").pack(fill="x", pady=(16, 5))
        key_entry = ttk.Entry(body, justify="center", width=56)
        key_entry.insert(0, key)
        key_entry.configure(state="readonly")
        key_entry.pack(fill="x")
        acknowledged = tk.BooleanVar(value=False)
        ttk.Button(body, text="ذخیره کلید در فایل امن…", command=lambda: self.save_license(key, window, acknowledged)).pack(anchor="e", pady=8)
        ttk.Checkbutton(body, text="کلید را در محل امن نگهداری کرده‌ام.", variable=acknowledged).pack(anchor="e")
        ttk.Label(body, text="کلید فقط برای مدیریت همین نصب است؛ لایسنس تجاری یا متصل به سرور نیست.\n"
                  "سوابق قبلی بدون تغییر باقی می‌مانند.", anchor="e", justify="right").pack(fill="x", pady=10)

        def finish():
            if not acknowledged.get():
                messagebox.showwarning("نگهداری کلید", "ابتدا کلید مدیریت را ذخیره و گزینه تأیید را فعال کنید.", parent=window)
                return
            if not messagebox.askyesno("تأیید تنظیم غیرقابل‌ویرایش",
                                      f"تاریخ {date.get()} و ساعت {clock.get()} ثبت و قفل شود؟", parent=window):
                return
            try:
                self.clock.initialize(date.get(), clock.get(), key)
                window.destroy()
            except (ValueError, sqlite3.Error) as error:
                messagebox.showerror("تنظیم انجام نشد", str(error), parent=window)

        ttk.Button(body, text="ثبت و قفل تنظیمات اولیه", style="Accent.TButton", command=finish).pack(anchor="e", pady=8)
        window.grab_set()
        self.root.wait_window(window)
        return self.clock.initialized

    def build_header(self):
        header = tk.Frame(self.root, background="#163e45", padx=20, pady=13)
        header.pack(fill="x")
        TkLabel(header, text="حساب قدیم", background="#163e45", foreground="#e4c178",
                 font=("Tahoma", 23, "bold")).pack(side="right", padx=(14, 0))
        self.clock_text = tk.StringVar()
        TkLabel(header, textvariable=self.clock_text, background="#163e45", foreground="#e1eded",
                 font=("Tahoma", 10), justify="right").pack(side="right", padx=15)
        self.printer_icon = tk.PhotoImage(width=19, height=19)
        for color, rect in (("#163e45", (4, 1, 15, 6)), ("#163e45", (1, 6, 18, 14)),
                            ("white", (5, 10, 14, 18)), ("#163e45", (6, 13, 13, 14)),
                            ("#163e45", (6, 15, 13, 16)), ("#e4c178", (14, 8, 16, 10))):
            self.printer_icon.put(color, to=rect)
        from gold_invoices import invoice_dialog, invoice_archive
        ttk.Button(header, text="آرشیو فاکتورها", command=lambda: invoice_archive(self)).pack(side="left", padx=4)
        ttk.Button(header, text="فاکتور", command=lambda: invoice_dialog(self)).pack(side="left", padx=4)
        ttk.Button(header, text="مدیریت قفل‌شده", command=self.admin_dialog).pack(side="left", padx=4)
        ttk.Button(header, text="ذخیره PDF", command=self.save_pdf).pack(side="left", padx=4)
        ttk.Button(header, text="چاپ", image=self.printer_icon, compound="right", command=self.print_report).pack(side="left", padx=4)
        range_frame = ttk.Frame(self.root, padding=(12, 4))
        range_frame.pack(fill="x")
        self.report_document_from = tk.StringVar()
        self.report_document_to = tk.StringVar()
        for label, variable in (("از شماره سند", self.report_document_from),
                                ("تا شماره سند", self.report_document_to)):
            ttk.Label(range_frame, text=label).pack(side="right", padx=4)
            ttk.Entry(range_frame, textvariable=variable, width=12).pack(side="right", padx=4)
        ttk.Label(range_frame, text="بازه PDF و چاپِ برگه فعال؛ خالی = بدون محدودیت (شماره سند، نه فاکتور)").pack(side="right", padx=8)
        ttk.Button(range_frame, text="پاک کردن بازه", command=lambda: (
            self.report_document_from.set(''), self.report_document_to.set(''))).pack(side="right")

    def build_overview(self):
        frame = ttk.Frame(self.root, padding=(12, 12, 12, 0))
        frame.pack(fill="x")
        self.card_values = {}
        for index, (key, title) in enumerate((("total", "دارایی طلایی حسابداری"), ("profit", "سود طلایی مستقل"),
                                              ("used", "موجودی دست‌دوم قابل‌فروش"), ("new", "موجودی نو قابل‌فروش"))):
            frame.columnconfigure(index, weight=1, uniform="card")
            card = tk.Frame(frame, background="white", padx=10, pady=4, highlightthickness=1, highlightbackground="#dce5e5")
            card.grid(row=0, column=index, sticky="nsew", padx=4)
            TkLabel(card, text=title, background="white", foreground="#567078", font=("Tahoma", 10)).pack(anchor="e")
            value = tk.StringVar(value="—")
            self.card_values[key] = value
            TkLabel(card, textvariable=value, background="white", foreground="#176b60", font=("Tahoma", 14, "bold")).pack(anchor="e", pady=(3, 0))
        self.asset_details = tk.StringVar()
        ttk.Label(self.root, textvariable=self.asset_details, anchor="e", padding=(20, 8)).pack(fill="x")

    def update_overview(self):
        balances, assets = self.ledger.balances(), self.ledger.gold_assets()
        for key, value in {**balances, "total": assets["total"], "profit": assets["profit"]}.items():
            self.card_values[key].set(display(value) + " گرم")
        volumes = self.ledger.trade_volumes()
        volume_text = '    |    '.join(
            f"{title}: حجم خرید {display(volumes[kind]['in'])} / حجم فروش {display(volumes[kind]['out'])} گرم"
            for kind, title in [('new', 'طلای نو'), ('used', 'دست دوم')])
        self.asset_details.set(volume_text + '\n' + f"موجودی قابل‌فروش: {display(assets['stock'])} گرم    |    "
                               f"موجودی + سود: {display(assets['inventory_total'])} گرم    |    "
                               f"خروج حساب‌شده: {display(assets['sold'])} گرم    •    مبالغ: تومان")

    def tick(self):
        self.clock_text.set(jalali_timestamp(self.clock.now()) + "\nساعت داخلی • قفل مدیریت فعال")
        day = jalali_timestamp(self.clock.now())[:10]
        if day != self.last_day and self.search_tree is not None and self.follow_today:
            self.search_vars["date"].set(day)
            self.active_filters["date"] = day
            self.refresh_search()
        self.last_day = day
        self.ticks += 1
        if self.ticks % 30 == 0:
            try:
                self.clock.checkpoint()
            except sqlite3.Error:
                self.clock_text.set("خطا در ذخیره ساعت؛ دسترسی به فایل داده را بررسی کنید.")
        self.timer = self.root.after(1000, self.tick)

    def build_search(self, notebook):
        self.search_tab = ttk.Frame(notebook, padding=12)
        notebook.add(self.search_tab, text="جستجو و گزارش‌ها")
        filters = ttk.LabelFrame(self.search_tab, text="جستجوی پیشرفته — فیلترهای خالی نادیده گرفته می‌شوند", padding=12)
        filters.pack(fill="x")
        for col in (0, 2, 4):
            filters.columnconfigure(col, weight=1)
        self.search_vars = {}
        fields = (("date", "تاریخ شمسی"), ("time_from", "از ساعت"), ("time_to", "تا ساعت"),
                  ("document_no", "شماره سند"), ("weight_min", "از وزن اولیه (گرم)"), ("weight_max", "تا وزن اولیه (گرم)"))
        for index, (key, label) in enumerate(fields):
            row, col = index // 3, 4 - (index % 3) * 2
            variable = tk.StringVar(value=jalali_timestamp(self.clock.now())[:10] if key == "date" else "")
            self.search_vars[key] = variable
            entry = ttk.Entry(filters, textvariable=variable, justify="right", width=18)
            entry.grid(row=row, column=col, sticky="ew", padx=6, pady=5)
            entry.bind("<Return>", lambda _event: self.apply_search())
            ttk.Label(filters, text=label, anchor="e").grid(row=row, column=col + 1, sticky="e", padx=3)
            if key == "date":
                self.date_entry = entry
        self.date_enabled = tk.BooleanVar(value=True)
        ttk.Checkbutton(filters, text="محدود به تاریخ بالا", variable=self.date_enabled,
                        command=lambda: self.date_entry.configure(state="normal" if self.date_enabled.get() else "disabled")).grid(row=2, column=4, columnspan=2, sticky="e", pady=6)
        self.search_direction = tk.StringVar(value="همه جهت‌ها")
        self.search_kind = tk.StringVar(value="همه طلاها")
        ttk.Combobox(filters, textvariable=self.search_direction, values=("همه جهت‌ها", "ورود", "خروج"), state="readonly", justify="right").grid(row=2, column=2, columnspan=2, sticky="ew", padx=6)
        ttk.Combobox(filters, textvariable=self.search_kind, values=("همه طلاها", "طلای نو", "دست‌دوم"), state="readonly", justify="right").grid(row=2, column=0, columnspan=2, sticky="ew", padx=6)
        actions = ttk.Frame(filters)
        actions.grid(row=3, column=0, columnspan=6, sticky="e", pady=(8, 0))
        ttk.Button(actions, text="جستجو", style="Accent.TButton", command=self.apply_search).pack(side="right", padx=4)
        ttk.Button(actions, text="بازنشانی: امروز", command=self.reset_search).pack(side="right", padx=4)
        ttk.Label(actions, text="برای سند قدیمی، محدودیت تاریخ را بردارید. ساعت: ۰۹:۳۰ یا ۰۹:۳۰:۰۰", anchor="e").pack(side="right", padx=10)
        self.search_status = tk.StringVar()
        ttk.Label(self.search_tab, textvariable=self.search_status, anchor="e", padding=8).pack(fill="x")
        bar = ttk.Frame(self.search_tab)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Button(bar, text="جزئیات سند", command=self.show_details).pack(side="right", padx=4)
        ttk.Button(bar, text="رفتن به سند برای ویرایش / حذف", command=self.go_to_document).pack(side="right", padx=4)
        table = ttk.Frame(self.search_tab)
        table.pack(fill="both", expand=True)
        columns = ("document", "date", "direction", "kind", "weight", "stock", "price", "total", "updated")
        self.search_tree = ttk.Treeview(table, columns=columns, show="headings", selectmode="browse")
        for key, text, width in zip(columns,
                ("شماره سند", "تاریخ و ساعت ثبت (شمسی)", "جهت", "نوع طلا", "وزن اولیه (گرم)", "وزن حساب‌شده (گرم)", "قیمت هر گرم (تومان)", "مبلغ کل (تومان)", "آخرین ویرایش"),
                (95, 200, 65, 85, 130, 145, 160, 170, 195)):
            self.search_tree.heading(key, text=text)
            self.search_tree.column(key, width=width, minwidth=60, anchor="e", stretch=False)
        self.search_tree.tag_configure("in", background="#f0f8f5")
        self.search_tree.tag_configure("out", background="#fff8eb")
        vertical = ttk.Scrollbar(table, orient="vertical", command=self.search_tree.yview)
        horizontal = ttk.Scrollbar(table, orient="horizontal", command=self.search_tree.xview)
        self.search_tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        self.search_tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")

        def double_click(event):
            if self.search_tree.identify_region(event.x, event.y) == "cell":
                item = self.search_tree.identify_row(event.y)
                if item:
                    self.search_tree.selection_set(item)
                    self.show_details()
        self.search_tree.bind("<Double-1>", double_click)
        self.reset_search()

    def collect_filters(self):
        result = {key: variable.get().strip() for key, variable in self.search_vars.items()}
        if not self.date_enabled.get():
            result.pop("date")
        elif not result["date"]:
            raise ValueError("تاریخ را وارد کنید یا محدودیت تاریخ را بردارید.")
        result["direction"] = {"ورود": "in", "خروج": "out"}.get(self.search_direction.get(), "")
        result["kind"] = {"طلای نو": "new", "دست‌دوم": "used"}.get(self.search_kind.get(), "")
        validate_search(result)
        return result

    def apply_search(self):
        try:
            filters = self.collect_filters()
            self.active_filters = filters
            self.follow_today = False
            self.refresh_search()
        except (ValueError, sqlite3.Error) as error:
            messagebox.showerror("جستجو انجام نشد", str(error), parent=self.root)

    def reset_search(self):
        for key, variable in self.search_vars.items():
            variable.set(jalali_timestamp(self.clock.now())[:10] if key == "date" else "")
        self.date_enabled.set(True)
        self.date_entry.configure(state="normal")
        self.search_direction.set("همه جهت‌ها")
        self.search_kind.set("همه طلاها")
        self.active_filters = self.collect_filters()
        self.follow_today = True
        self.refresh_search()

    def refresh_search(self):
        if self.search_tree is None:
            return
        rows = self.ledger.search(**self.active_filters)
        self.search_tree.delete(*self.search_tree.get_children())
        for row in rows:
            self.search_tree.insert("", "end", iid=str(row["id"]), tags=(row["direction"],), values=(
                row["document_no"], row["created_at_jalali"] or row["created_at"],
                "ورود" if row["direction"] == "in" else "خروج", "نو" if row["kind"] == "new" else "دست‌دوم",
                display(Decimal(row["weight"])), display(Decimal(row["stock_weight"])),
                display(Decimal(row["price"])), display(Decimal(row["total"])), row["updated_at_jalali"] or "—"))
        self.search_status.set(f"نتیجه: {len(rows)} سند    |    " + self.filter_description())

    def filter_description(self):
        labels = {"date": "تاریخ", "time_from": "از ساعت", "time_to": "تا ساعت", "weight_min": "از وزن اولیه",
                  "weight_max": "تا وزن اولیه", "document_no": "سند", "direction": "جهت", "kind": "نوع طلا"}
        translations = {"in": "ورود", "out": "خروج", "new": "نو", "used": "دست‌دوم"}
        return " | ".join(f"{labels[key]}: {translations.get(value, value)}" for key, value in self.active_filters.items() if value) or "همه اسناد، بدون فیلتر"

    def selected_search_row(self):
        selection = self.search_tree.selection()
        if not selection:
            raise ValueError("ابتدا یک سند از نتایج انتخاب کنید.")
        return self.ledger.get(int(selection[0]))

    def go_to_document(self):
        try:
            row = self.selected_search_row()
            if self.locate_document:
                self.locate_document(row)
        except ValueError as error:
            messagebox.showwarning("انتخاب سند", str(error), parent=self.root)

    def show_details(self):
        try:
            row = self.selected_search_row()
        except ValueError as error:
            messagebox.showwarning("انتخاب سند", str(error), parent=self.root)
            return
        def fmt(key):
            return display(Decimal(row[key])) if row[key] is not None else "—"
        lines = [f"سند {row['document_no']} — {'ورود' if row['direction'] == 'in' else 'خروج'} {'طلای نو' if row['kind'] == 'new' else 'دست‌دوم'}",
                 f"ثبت: {row['created_at_jalali'] or row['created_at']}", f"آخرین ویرایش: {row['updated_at_jalali'] or '—'}"]
        for key, label, unit in (("weight", "وزن اولیه", "گرم"), ("stock_weight", "وزن حساب‌شده", "گرم"),
                ("billed_weight", "فروش با اجرت", "گرم"), ("gold_profit", "سود طلایی", "گرم"),
                ("price", "قیمت هر گرم", "تومان"), ("base_amount", "قیمت خام", "تومان"),
                ("making_rate", "اجرت ساخت", "درصد"), ("making_amount", "مبلغ اجرت ساخت", "تومان"),
                ("selling_rate", "اجرت فروش", "درصد"), ("selling_amount", "مبلغ اجرت فروش", "تومان"),
                ("tax_rate", "مالیات روی اجرت‌ها", "درصد"), ("tax_amount", "مبلغ مالیات", "تومان"),
                ("total", "مبلغ کل", "تومان")):
            lines.append(f"{label}: {fmt(key)} {unit}")
        messagebox.showinfo("جزئیات سند — حساب قدیم", "\n".join(lines), parent=self.root)

    def current_report(self):
        if self.report_context:
            return self.report_context()
        return self.ledger.search(**self.active_filters), "گزارش جستجو", self.filter_description()

    def write_report(self, path):
        rows, title, filters = self.current_report()
        start = getattr(self, 'report_document_from', None)
        end = getattr(self, 'report_document_to', None)
        rows, description = document_range(rows, start.get() if start else '', end.get() if end else '')
        if description:
            filters += ' | ' + description
        return export_pdf(path, rows, title, filters, jalali_timestamp(self.clock.now()))

    def save_pdf(self):
        path = filedialog.asksaveasfilename(parent=self.root, title="ذخیره گزارش حساب قدیم",
                                          defaultextension=".pdf", initialfile="hesab-ghadim-report.pdf",
                                          filetypes=[("PDF", "*.pdf")])
        if not path:
            return
        try:
            self.write_report(path)
            messagebox.showinfo("گزارش آماده شد", f"گزارش برگه فعال ذخیره شد:\n{path}", parent=self.root)
        except Exception as error:
            messagebox.showerror("خطای PDF", str(error), parent=self.root)

    def print_report(self):
        if not messagebox.askyesno("چاپ گزارش", "گزارش برگه فعال به چاپگر پیش‌فرض ارسال شود؟\nدر برگه جستجو، فقط نتایج آخرین جستجوی اعمال‌شده چاپ می‌شوند.", parent=self.root):
            return
        try:
            path = Path(self.print_directory.name) / f"report-{self.ticks}.pdf"
            self.write_report(path)
            send_to_printer(path)
            messagebox.showinfo("چاپ", "درخواست چاپ به سیستم‌عامل ارسال شد.", parent=self.root)
        except Exception as error:
            messagebox.showerror("چاپ انجام نشد", str(error) + "\nمی‌توانید از دکمه «ذخیره PDF» استفاده کنید.", parent=self.root)

    def admin_dialog(self):
        key = simpledialog.askstring("ورود مدیریت", "کلید مدیریت محلی را وارد کنید:", show="*", parent=self.root)
        if key is None:
            return
        try:
            self.clock.authorize(key)
        except (ValueError, sqlite3.Error) as error:
            messagebox.showerror("دسترسی مجاز نیست", str(error), parent=self.root)
            return
        window = tk.Toplevel(self.root)
        window.title("حساب قدیم | مدیریت")
        window.transient(self.root)
        body = ttk.Frame(window, padding=22)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="تنظیمات مدیریتی", anchor="e", font=("Tahoma", 15, "bold")).pack(fill="x")
        ttk.Label(body, text="تغییر ساعت فقط روی ثبت‌های بعدی اثر دارد؛ تاریخ و مبالغ اسناد قبلی عوض نمی‌شود.",
                  anchor="e").pack(fill="x", pady=10)
        date = tk.StringVar(value=jalali_timestamp(self.clock.now())[:10])
        clock = tk.StringVar(value=self.clock.now().strftime("%H:%M:%S"))
        for label, variable in (("تاریخ شمسی", date), ("ساعت", clock)):
            row = ttk.Frame(body)
            row.pack(fill="x", pady=5)
            ttk.Label(row, text=label, anchor="e", width=14).pack(side="right")
            ttk.Entry(row, textvariable=variable, justify="right", width=25).pack(side="right")

        def change_time():
            if not messagebox.askyesno("تغییر ساعت داخلی", "زمان برنامه با مجوز مدیریت تغییر کند؟ این تغییر در رویدادهای مدیریتی ثبت می‌شود.", parent=window):
                return
            try:
                self.clock.change_time(date.get(), clock.get(), key)
                if self.follow_today:
                    self.reset_search()
                window.destroy()
                messagebox.showinfo("انجام شد", "ساعت داخلی تغییر کرد؛ اسناد قبلی دست‌نخورده‌اند.", parent=self.root)
            except (ValueError, sqlite3.Error) as error:
                messagebox.showerror("تغییر انجام نشد", str(error), parent=window)

        def backup():
            path = filedialog.asksaveasfilename(parent=window, title="پشتیبان پایگاه داده", defaultextension=".sqlite3",
                                              initialfile="hesab-ghadim-backup.sqlite3", filetypes=[("SQLite", "*.sqlite3")])
            if path:
                try:
                    self.clock.backup(path, key)
                    messagebox.showinfo("پشتیبان", "پشتیبان کامل داده‌ها و تنظیمات ذخیره شد.", parent=window)
                except (ValueError, sqlite3.Error, OSError) as error:
                    messagebox.showerror("پشتیبان انجام نشد", str(error), parent=window)
        ttk.Button(body, text="ثبت ساعت با مجوز مدیریت", command=change_time, style="Accent.TButton").pack(anchor="e", pady=10)
        ttk.Button(body, text="تهیه پشتیبان کامل…", command=backup).pack(anchor="e", pady=6)
        ttk.Label(body, text="کلید مدیریت در این پنجره نمایش داده نمی‌شود.\nبرای بستن دسترسی، این پنجره را ببندید.", anchor="e", justify="right").pack(fill="x", pady=8)
        window.grab_set()

    def shutdown(self):
        if self.timer is not None:
            self.root.after_cancel(self.timer)
        self.clock.checkpoint()
        self.print_directory.cleanup()
