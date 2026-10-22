"""Separate coin/melted inventory and explicit dual-unit settlement ledger.
Legacy stock and transactions are intentionally not reclassified.
"""
from decimal import Decimal, InvalidOperation
from datetime import datetime
import json
import sqlite3

COINS = {'emami86': 'امامی ۸۶', 'bahar86': 'بهار آزادی ۸۶',
         'half86': 'نیم بهار آزادی ۸۶', 'quarter86': 'ربع بهار آزادی ۸۶',
         'parsian': 'پارسیان', 'melted': 'آبشده'}


def number(value, positive=False):
    try:
        result = Decimal(str(value).replace(',', '').translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')))
    except (InvalidOperation, ValueError):
        raise ValueError('عدد معتبر وارد کنید.')
    if not result.is_finite() or result < 0 or (positive and result == 0):
        raise ValueError('عدد باید مثبت باشد.' if positive else 'عدد منفی مجاز نیست.')
    return result


class SpecialLedger:
    def __init__(self, connection):
        self.db = connection
        with self.db:
            self.db.execute('''CREATE TABLE IF NOT EXISTS special_parties (
                id INTEGER PRIMARY KEY, role TEXT NOT NULL, name TEXT NOT NULL,
                UNIQUE(role, name))''')
            self.db.execute('''CREATE TABLE IF NOT EXISTS special_trades (
                id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, direction TEXT NOT NULL,
                kind TEXT NOT NULL, quantity INTEGER NOT NULL, weight TEXT NOT NULL,
                purity TEXT NOT NULL, equivalent TEXT NOT NULL, total TEXT NOT NULL,
                party_id INTEGER NOT NULL, terms TEXT NOT NULL)''')
            self.db.execute('''CREATE TABLE IF NOT EXISTS special_accounts (
                id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, party_id INTEGER NOT NULL,
                toman TEXT NOT NULL, gold TEXT NOT NULL, note TEXT NOT NULL,
                trade_id INTEGER)''')

    def party(self, role, name):
        name = name.strip()
        if role not in ('customer', 'supplier') or not name:
            raise ValueError('نوع و نام طرف حساب الزامی است.')
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO special_parties(role,name) VALUES (?,?)', (role, name))
        return self.db.execute('SELECT id FROM special_parties WHERE role=? AND name=?', (role, name)).fetchone()[0]

    def quote(self, kind, quantity, weight='0', mode='each', rate='0', fee='0', purity='750'):
        if kind not in COINS or mode not in ('each', 'total'):
            raise ValueError('نوع معامله یا مبنای وزن نامعتبر است.')
        q = number(quantity, True)
        if q != q.to_integral_value():
            raise ValueError('تعداد باید عدد صحیح باشد.')
        r, f, p = number(rate), number(fee), number(purity, True)
        if p > 1000:
            raise ValueError('عیار نمی‌تواند بیشتر از ۱۰۰۰ باشد.')
        w = number(weight, kind in ('parsian', 'melted'))
        total_weight = w * q if mode == 'each' else w
        if kind == 'parsian':
            buy = total_weight * r * Decimal(725) / 750
            sell = total_weight * r * (1 + f / 100)
            p = Decimal(725)
        elif kind == 'melted':
            buy = sell = total_weight * p / 750 * r
        else:
            total_weight = Decimal(0)
            buy = sell = q * r
        eq = total_weight * p / 750 if kind in ('parsian', 'melted') else Decimal(0)
        return dict(quantity=int(q), weight=total_weight, purity=p, equivalent=eq, buy=buy, sell=sell)

    def stock(self, kind):
        quantity, weight, equivalent = 0, Decimal(0), Decimal(0)
        for row in self.db.execute('SELECT direction,quantity,weight,equivalent FROM special_trades WHERE kind=?', (kind,)):
            sign = 1 if row[0] == 'in' else -1
            quantity += sign * row[1]
            weight += sign * Decimal(row[2])
            equivalent += sign * Decimal(row[3])
        return quantity, weight, equivalent

    def post_account(self, party, toman, gold, note):
        # Signed: positive = receivable from party; negative = payable to party.
        try:
            t, g = Decimal(str(toman)), Decimal(str(gold))
        except InvalidOperation:
            raise ValueError('مانده نامعتبر است.')
        if not t.is_finite() or not g.is_finite() or not note.strip():
            raise ValueError('شرح و مقادیر معتبر الزامی است.')
        if not self.db.execute('SELECT 1 FROM special_parties WHERE id=?', (party,)).fetchone():
            raise ValueError('طرف حساب یافت نشد.')
        with self.db:
            self.db.execute('INSERT INTO special_accounts(created_at,party_id,toman,gold,note) VALUES (?,?,?,?,?)',
                            (datetime.now().isoformat(), party, str(t), str(g), note))

    def balance(self, party):
        rows = self.db.execute('SELECT toman,gold FROM special_accounts WHERE party_id=?', (party,))
        t = g = Decimal(0)
        for a, b in rows:
            t += Decimal(a)
            g += Decimal(b)
        return t, g

    def trade(self, direction, kind, party, settlement='toman', **terms):
        if direction not in ('in', 'out') or settlement not in ('toman', 'gold', 'paid'):
            raise ValueError('جهت یا روش تسویه نامعتبر است.')
        if not self.db.execute('SELECT 1 FROM special_parties WHERE id=?', (party,)).fetchone():
            raise ValueError('طرف حساب یافت نشد.')
        result = self.quote(kind, **terms)
        if settlement == 'gold' and kind not in ('parsian', 'melted'):
            raise ValueError('برای سکه‌های تعدادی تسویه طلایی تعریف نشده است.')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            q, w, eq = self.stock(kind)
            if direction == 'out':
                if kind == 'melted':
                    enough = w >= result['weight'] and eq >= result['equivalent']
                elif kind == 'parsian':
                    enough = q >= result['quantity'] and w >= result['weight'] and eq >= result['equivalent']
                else:
                    enough = q >= result['quantity']
                if not enough:
                    raise ValueError('موجودی کافی نیست؛ وزن، تعداد و عیار را بررسی کنید.')
            total = result['buy' if direction == 'in' else 'sell']
            stamp = datetime.now().isoformat()
            cur = self.db.execute('''INSERT INTO special_trades(created_at,direction,kind,quantity,weight,purity,equivalent,total,party_id,terms)
                VALUES (?,?,?,?,?,?,?,?,?,?)''', (stamp, direction, kind, result['quantity'], str(result['weight']),
                str(result['purity']), str(result['equivalent']), str(total), party, json.dumps(terms, ensure_ascii=False)))
            sign = 1 if direction == 'out' else -1
            t = total * sign if settlement == 'toman' else Decimal(0)
            g = result['equivalent'] * sign if settlement == 'gold' else Decimal(0)
            self.db.execute('''INSERT INTO special_accounts(created_at,party_id,toman,gold,note,trade_id)
                VALUES (?,?,?,?,?,?)''', (stamp, party, str(t), str(g), COINS[kind], cur.lastrowid))
        return result


def build_special_tabs(notebook, ledger, root):
    import tkinter as tk
    from tkinter import ttk, messagebox
    store = SpecialLedger(ledger.connection)
    page = ttk.Frame(notebook)
    trade_page = page
    notebook.add(page, text='سکه، آبشده و حساب دوگانه')
    canvas = tk.Canvas(page, highlightthickness=0)
    scroll = ttk.Scrollbar(page, orient='vertical', command=canvas.yview)
    canvas.configure(yscrollcommand=scroll.set)
    scroll.pack(side='right', fill='y')
    canvas.pack(side='left', fill='both', expand=True)
    content = ttk.Frame(canvas, padding=8)
    content_id = canvas.create_window((0, 0), window=content, anchor='nw')
    content.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>', lambda e: canvas.itemconfigure(content_id, width=e.width))
    page = content
    ttk.Label(page, text='موجودی این بخش مستقل از طلای نو و دست‌دوم است؛ معادل ۷۵۰ دوباره از آن‌ها کسر نمی‌شود.').pack(anchor='e')
    form = ttk.Frame(page)
    form.pack(fill='x')
    fields = {}

    def field(key, title, default, values=None):
        i = len(fields)
        row, col = divmod(i, 4)
        cell = ttk.Frame(form, padding=3)
        cell.grid(row=row, column=col, sticky='ew')
        form.columnconfigure(col, weight=1)
        ttk.Label(cell, text=title, anchor='e').pack(fill='x')
        var = tk.StringVar(value=default)
        widget = ttk.Combobox(cell, textvariable=var, values=values, state='readonly') if values else ttk.Entry(cell, textvariable=var, justify='right')
        widget.pack(fill='x')
        fields[key] = var

    field('kind', 'نوع', 'پارسیان', list(COINS.values()))
    field('direction', 'عملیات', 'خرید / ورود', ['خرید / ورود', 'فروش / خروج'])
    field('role', 'نوع طرف حساب', 'مشتری', ['مشتری', 'تأمین‌کننده'])
    field('name', 'نام کامل طرف حساب', '')
    field('quantity', 'تعداد (آبشده: ۱)', '1')
    field('weight', 'وزن واقعی به گرم', '0')
    field('mode', 'مبنای وزن ورودی', 'هر قطعه', ['هر قطعه', 'مجموع'])
    field('purity', 'عیار آبشده؛ پارسیان ثابت ۷۲۵', '750')
    field('rate', 'نرخ تومان: هر عدد سکه / هر گرم ۱۸ عیار', '0')
    field('fee', 'اجرت فروش پارسیان (درصد)', '0')
    field('settlement', 'ثبت مانده معامله', 'تومانی', ['تومانی', 'طلایی', 'تسویه‌شده'])
    preview = tk.StringVar()
    ttk.Label(page, textvariable=preview, anchor='e').pack(fill='x', pady=4)

    def args():
        return dict(quantity=fields['quantity'].get(), weight=fields['weight'].get(),
                    mode='each' if fields['mode'].get() == 'هر قطعه' else 'total',
                    rate=fields['rate'].get(), fee=fields['fee'].get(), purity=fields['purity'].get())

    def party():
        return store.party('customer' if fields['role'].get() == 'مشتری' else 'supplier', fields['name'].get())

    def kind():
        return next(k for k, v in COINS.items() if v == fields['kind'].get())

    def calculate():
        r = store.quote(kind(), **args())
        preview.set(f"وزن کل: {r['weight']:,.6f} | معادل ۷۵۰: {r['equivalent']:,.6f} | خرید: {r['buy']:,.0f} | فروش: {r['sell']:,.0f} تومان")
        return r

    def guarded(fn):
        def run():
            try:
                fn()
            except (ValueError, sqlite3.Error, InvalidOperation, OSError) as error:
                messagebox.showerror('خطا', str(error), parent=root)
        return run

    inventory = ttk.Treeview(page, columns=('name','q','w','eq'), show='headings', height=6)
    for key, title in [('name','نوع'),('q','تعداد'),('w','وزن واقعی'),('eq','معادل ۷۵۰')]:
        inventory.heading(key, text=title)
        inventory.column(key, width=150, anchor='e')
    balance_text = tk.StringVar()

    def refresh():
        inventory.delete(*inventory.get_children())
        for k, title in COINS.items():
            q, w, eq = store.stock(k)
            inventory.insert('', 'end', values=(title, '—' if k == 'melted' else q, f'{w:f}', f'{eq:f}'))
        p = party()
        t, g = store.balance(p)
        balance_text.set(f'مانده {fields["name"].get()}: {t:,.0f} تومان | {g:,.6f} گرم ۷۵۰ — مثبت: طلب ما؛ منفی: بدهی ما')
        history.delete(*history.get_children())
        for row in store.db.execute('SELECT created_at,toman,gold,note FROM special_accounts WHERE party_id=? ORDER BY id DESC', (p,)):
            history.insert('', 'end', values=tuple(row))

    def save():
        calculate()
        if not messagebox.askyesno('تأیید ثبت', preview.get() + '\nمعامله ثبت شود؟', parent=root):
            return
        store.trade('in' if fields['direction'].get() == 'خرید / ورود' else 'out', kind(), party(),
                    {'تومانی':'toman','طلایی':'gold','تسویه‌شده':'paid'}[fields['settlement'].get()], **args())
        refresh()

    buttons = ttk.Frame(page)
    buttons.pack(fill='x')
    ttk.Button(buttons, text='محاسبه', command=guarded(calculate)).pack(side='right')
    ttk.Button(buttons, text='ثبت معامله', command=guarded(save)).pack(side='right')
    ttk.Button(buttons, text='نمایش حساب و موجودی', command=guarded(refresh)).pack(side='right')
    def export():
        import csv
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(parent=root, defaultextension='.csv', filetypes=[('CSV', '*.csv')], initialfile='coins-melted-trades.csv')
        if not path:
            return
        rows = store.db.execute('''SELECT t.id,t.created_at,t.direction,t.kind,p.role,p.name,
            t.quantity,t.weight,t.purity,t.equivalent,t.total,t.terms
            FROM special_trades t JOIN special_parties p ON p.id=t.party_id ORDER BY t.id''')
        with open(path, 'w', encoding='utf-8-sig', newline='') as output:
            writer = csv.writer(output)
            writer.writerow(['شماره','تاریخ','جهت','نوع','نوع طرف','نام طرف','تعداد','وزن کل','عیار','معادل ۷۵۰','مبلغ تومان','جزئیات محاسبه'])
            for row in rows:
                values = list(row)
                values[3] = COINS[values[3]]
                writer.writerow([("'" + str(v)) if str(v).startswith(('=', '+', '-', '@')) else v for v in values])
    ttk.Button(buttons, text='خروجی معاملات CSV', command=guarded(export)).pack(side='right')
    inventory.pack(fill='x', pady=4)
    ttk.Label(page, textvariable=balance_text, anchor='e').pack(fill='x')
    ttk.Label(page, text='ثبت دستی مانده اولیه/تسویه: مثبت = افزایش طلب ما؛ منفی = افزایش بدهی ما. دریافت از مشتری با مقدار منفی ثبت شود.').pack(anchor='e')
    manual = ttk.Frame(page)
    manual.pack(fill='x')
    manual_vars = []
    for label in ('تومان با علامت', 'گرم ۷۵۰ با علامت', 'شرح الزامی'):
        ttk.Label(manual, text=label).pack(side='right')
        v = tk.StringVar(value='0' if len(manual_vars) < 2 else '')
        ttk.Entry(manual, textvariable=v, width=22).pack(side='right')
        manual_vars.append(v)

    def adjustment():
        store.post_account(party(), *(v.get() for v in manual_vars))
        refresh()
    ttk.Button(manual, text='ثبت حساب', command=guarded(adjustment)).pack(side='right')
    history = ttk.Treeview(page, columns=('date','toman','gold','note'), show='headings', height=5)
    for key, title in [('date','تاریخ'),('toman','تومان'),('gold','گرم ۷۵۰'),('note','شرح')]:
        history.heading(key, text=title)
        history.column(key, width=170, anchor='e')
    history.pack(fill='both', expand=True)
    for k, title in COINS.items():
        q, w, eq = store.stock(k)
        inventory.insert('', 'end', values=(title, '—' if k == 'melted' else q, str(w), str(eq)))

    def open_trade(selected_kind, direction):
        if selected_kind not in COINS or direction not in ('in', 'out'):
            raise ValueError('نوع یا جهت معامله نامعتبر است.')
        fields['kind'].set(COINS[selected_kind])
        fields['direction'].set('خرید / ورود' if direction == 'in' else 'فروش / خروج')
        preview.set('نوع و عملیات انتخاب شد؛ تعداد، وزن، عیار، نرخ و طرف حساب را بررسی و سپس محاسبه کنید.')
        notebook.select(trade_page)
        canvas.yview_moveto(0)

    return open_trade
