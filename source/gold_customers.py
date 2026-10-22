"""Local customer records; attachments remain inside the ledger backup."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
from pathlib import Path


def read_image(path):
    if Path(path).stat().st_size > 5 * 1024 * 1024:
        raise ValueError('حداکثر حجم تصویر ۵ مگابایت است.')
    data = Path(path).read_bytes()
    from PIL import Image
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format not in ('PNG', 'JPEG', 'WEBP'):
                raise ValueError('فرمت تصویر پشتیبانی نمی‌شود.')
            image.verify()
    except Exception as exc:
        raise ValueError('تصویر معتبر نیست.') from exc
    return data


def customer_fields(values):
    allowed = {'customer_name', 'customer_phone', 'bank_card', 'national_image', 'bank_image'}
    if set(values) - allowed:
        raise ValueError('فیلد مشتری نامعتبر است.')
    result = dict(values)
    for key in ('customer_name', 'customer_phone', 'bank_card'):
        if key in result:
            result[key] = str(result[key]).strip()
            if len(result[key]) > 160:
                raise ValueError('اطلاعات مشتری بیش از حد طولانی است.')
    for key, length in (('customer_phone', 11), ('bank_card', 16)):
        if key in result and result[key]:
            text = result[key].translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789'))
            text = text.replace(' ', '').replace('-', '')
            if not text.isascii() or not text.isdigit() or len(text) != length or (key == 'customer_phone' and not text.startswith('09')):
                raise ValueError('شماره همراه باید ۱۱ رقم با ۰۹ و شماره کارت ۱۶ رقم باشد.')
            result[key] = text
    for key in ('national_image', 'bank_image'):
        if key in result and result[key] is not None:
            if not isinstance(result[key], bytes) or len(result[key]) > 5 * 1024 * 1024:
                raise ValueError('حجم یا نوع مدرک نامعتبر است.')
    return result


def customers(ledger, now=None):
    limited = now is not None
    # Legacy timestamps without an offset are shop-local (Tehran).
    shop_timezone = timezone(timedelta(hours=3, minutes=30))
    def comparable(value):
        if value.tzinfo is None or value.utcoffset() is None:
            value = value.replace(tzinfo=shop_timezone)
        return value.astimezone(timezone.utc)
    now = comparable(now or datetime.now(shop_timezone))
    start = now - timedelta(days=30) if limited else None
    import json
    groups = {}
    covered = set()
    records = []
    if ledger.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='invoices'").fetchone():
        for item in ledger.connection.execute('SELECT snapshot FROM invoices ORDER BY number'):
            data = json.loads(item[0])
            for original in data['rows']:
                covered.add(original['id'])
                row = dict(original)
                row.update(customer_name=data['customer'], customer_phone=data['phone'], created_at=data['created'])
                records.append(row)
    records.extend(dict(row) for row in ledger.rows('out') if row['id'] not in covered)
    for row in records:
        if not row['customer_phone']:
            continue
        entry = groups.setdefault(row['customer_phone'], dict(name=row['customer_name'], phone=row['customer_phone'], weight=Decimal(0), total=Decimal(0), rows=[]))
        try:
            stamp = comparable(datetime.fromisoformat(row['created_at']))
        except ValueError:
            continue
        if stamp <= now and (start is None or start <= stamp):
            entry['weight'] += Decimal(row['weight'])
            entry['total'] += Decimal(row['total'])
            entry['rows'].append(row)
    return list(groups.values())


def build_customer_tabs(notebook, ledger, root):
    import gold_widgets as ttk
    from gold_widgets import messagebox
    from tkinter import filedialog, simpledialog
    from gold_accounting import display
    for archive, title in ((False, 'باشگاه مشتریان'), (True, 'آرشیو خرید از مشتری‌ها')):
        tab = ttk.Frame(notebook, padding=8)
        notebook.add(tab, text=title)
        ttk.Label(tab, text='باشگاه: همه فاکتورها و فروش‌های قبلی، بدون شمارش تکراری؛ شناسایی با همراه. مدارک محلی بدون رمزگذاری‌اند.').pack()
        cols = ('name', 'phone', 'weight', 'total')
        tree = ttk.Treeview(tab, columns=cols, show='headings')
        for col, label in zip(cols, ('نام مشتری', 'شماره همراه', 'وزن (گرم)', 'مبلغ (تومان)')):
            tree.heading(col, text=label)
        tree.pack(fill='both', expand=True)
        detail = ttk.Label(tab, text='', justify='right', anchor='e')
        detail.pack(fill='x')
        state = {}
        def refresh(tree=tree, archive=archive, state=state):
            tree.delete(*tree.get_children())
            state.clear()
            entries = [dict(row) for row in ledger.rows('in')] if archive else customers(ledger)
            for i, entry in enumerate(entries):
                state[str(i)] = entry
                tree.insert('', 'end', iid=str(i), values=(entry.get('customer_name', entry.get('name', '')) or 'ثبت نشده', entry.get('customer_phone', entry.get('phone', '')) or 'ثبت نشده', display(Decimal(entry['weight'])), display(Decimal(entry['total']))))
        def select(event=None, tree=tree, state=state, detail=detail, archive=archive):
            if not tree.selection():
                return
            entry = state[tree.selection()[0]]
            rows = [entry] if archive else entry['rows']
            detail.configure(text='\n'.join(f"سند {r['document_no']} | {r['created_at_jalali'] or r['created_at']} | {r['weight']} گرم | {r['total']} تومان | {r['product_title'] or 'بدون عنوان'} | کارت مقصد: {r['bank_card'] or '—'}" for r in rows) or 'در ۳۰ روز اخیر خریدی ثبت نشده است.')
        tree.bind('<<TreeviewSelect>>', select)
        ttk.Button(tab, text='به‌روزرسانی', command=refresh).pack()
        if archive:
            def edit_customer(tree=tree, state=state, refresh=refresh):
                if not tree.selection():
                    messagebox.showinfo('مشخصات مشتری', 'ابتدا یک سند را انتخاب کنید.', parent=root)
                    return
                entry = state[tree.selection()[0]]
                name = simpledialog.askstring('مشخصات مشتری', 'نام مشتری:', initialvalue=entry.get('customer_name') or '', parent=root)
                if name is None:
                    return
                phone = simpledialog.askstring('مشخصات مشتری', 'شماره همراه (اختیاری):', initialvalue=entry.get('customer_phone') or '', parent=root)
                if phone is None:
                    return
                try:
                    values = customer_fields(dict(customer_name=name, customer_phone=phone))
                    if not values['customer_name']:
                        raise ValueError('نام مشتری را وارد کنید.')
                    # Metadata only: never recalculate historical weights or amounts.
                    with ledger.connection:
                        ledger.connection.execute('UPDATE transactions SET customer_name=?, customer_phone=? WHERE id=? AND direction=?',
                                                  (values['customer_name'], values['customer_phone'], entry['id'], 'in'))
                    refresh()
                except ValueError as error:
                    messagebox.showerror('مشخصات مشتری', str(error), parent=root)
            ttk.Button(tab, text='ثبت / اصلاح نام و همراه مشتری', command=edit_customer).pack(side='right')
            def export(key, tree=tree, state=state):
                if not tree.selection():
                    return
                data = state[tree.selection()[0]][key]
                if not data:
                    messagebox.showinfo('مدرک', 'مدرکی برای این سند ثبت نشده است.', parent=root)
                    return
                from PIL import Image
                with Image.open(BytesIO(data)) as image:
                    suffix = {'JPEG': '.jpg', 'PNG': '.png', 'WEBP': '.webp'}[image.format]
                path = filedialog.asksaveasfilename(parent=root, defaultextension=suffix)
                if path:
                    Path(path).write_bytes(data)
            ttk.Button(tab, text='ذخیره تصویر کارت ملی', command=lambda export=export: export('national_image')).pack(side='right')
            ttk.Button(tab, text='ذخیره تصویر کارت بانکی', command=lambda export=export: export('bank_image')).pack(side='right')
        refresh()
