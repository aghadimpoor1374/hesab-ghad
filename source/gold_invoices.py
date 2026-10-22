"""Independent, immutable invoice snapshots and printable Persian HTML."""
import json
from html import escape
from pathlib import Path
from decimal import Decimal
from gold_accounting import display, jalali_timestamp

NOTICE = 'مشتری گرامی جنس فروخته شده ، در هنگام تعویض و یا فروش ، اجرت آن کسر و طلا به نرخ روز خریداری میگردد'

class Invoices:
    def __init__(self, ledger):
        self.ledger = ledger
        self.db = ledger.connection
        with self.db:
            self.db.execute('CREATE TABLE IF NOT EXISTS gallery_profile (id INTEGER PRIMARY KEY CHECK(id=1), name TEXT, address TEXT, phone TEXT)')
            self.db.execute('CREATE TABLE IF NOT EXISTS invoices (number INTEGER PRIMARY KEY, snapshot TEXT NOT NULL)')

    def profile(self):
        row = self.db.execute('SELECT * FROM gallery_profile WHERE id=1').fetchone()
        return dict(row) if row else None

    def save_profile(self, name, address, phone):
        if not all(str(x).strip() for x in (name, address, phone)):
            raise ValueError('نام گالری، آدرس و تلفن را وارد کنید.')
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO gallery_profile VALUES(1,?,?,?)', (name.strip(), address.strip(), phone.strip()))

    def issue(self, ids, customer, phone='', national_id=''):
        if not ids or len(set(ids)) != len(ids):
            raise ValueError('شماره سندهای فروش را بدون تکرار وارد کنید.')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            profile = self.profile()
            if not profile:
                raise ValueError('ابتدا مشخصات گالری را تنظیم کنید.')
            rows = [dict(self.ledger.get(i)) for i in ids]
            if any(r['direction'] != 'out' for r in rows):
                raise ValueError('فاکتور فقط برای اسناد فروش صادر می‌شود.')
            if len({r['price'] for r in rows}) != 1:
                raise ValueError('قیمت هر گرم در ردیف‌های فاکتور باید یکسان باشد.')
            number = self.db.execute('SELECT COALESCE(MAX(number),999)+1 FROM invoices').fetchone()[0]
            created, _ = self.ledger.timestamp_source()
            data = dict(profile=profile, rows=rows, customer=customer, phone=phone,
                        national_id=national_id, created=created, number=number)
            # Images are retained in the original documents, not duplicated into invoices.
            for row in rows:
                row.pop('national_image', None)
                row.pop('bank_image', None)
            self.db.execute('INSERT INTO invoices VALUES(?,?)', (number, json.dumps(data, ensure_ascii=False)))
        return number

    def export(self, number, path):
        row = self.db.execute('SELECT snapshot FROM invoices WHERE number=?', (number,)).fetchone()
        if not row:
            raise ValueError('فاکتور پیدا نشد.')
        return export_invoice_pdf(json.loads(row[0]), path)

    def export_html(self, number, path):
        row = self.db.execute('SELECT snapshot FROM invoices WHERE number=?', (number,)).fetchone()
        if not row:
            raise ValueError('فاکتور پیدا نشد.')
        d = json.loads(row[0]); p = d['profile']
        e = lambda x: escape(str(x))
        lines = []
        total = Decimal(0)
        for index, r in enumerate(d['rows'], 1):
            weight = Decimal(r['weight']); grams = int(weight); soot = (weight-grams)*1000
            total += Decimal(r['total'])
            purity = '750/18' if Decimal(r['purity']) == 750 else r['purity']
            cells = [index, r['product_title'] or ('طلای نو' if r['kind']=='new' else 'طلای دست دوم'), purity,
                     f'{grams} گرم و {display(soot)} سوت', display(Decimal(r['total']))]
            lines.append('<tr>'+''.join('<td>'+e(c)+'</td>' for c in cells)+'</tr>')
        html = f'''<!doctype html><html lang="fa" dir="rtl"><meta charset="utf-8">
<title>فاکتور {number}</title><style>body{{font-family:Tahoma,sans-serif;margin:35px;line-height:2}}h1{{text-align:center}}table{{width:100%;border-collapse:collapse}}td,th{{border:1px solid #555;padding:10px}}@media print{{button{{display:none}}}}</style>
<button onclick="window.print()">چاپ / ذخیره PDF</button><h1>{e(p['name'])}</h1>
<p>شماره فاکتور: {number} — تاریخ و ساعت: {e(jalali_timestamp(d['created']))}</p>
<p>نام مشتری: {e(d['customer'])} — همراه: {e(d['phone'])} — کد ملی: {e(d['national_id'])}</p>
<p>قیمت هر گرم طلای ۱۸ عیار: {e(display(Decimal(d['rows'][0]['price'])))} تومان</p>
<table><tr><th>ردیف</th><th>شرح کالا</th><th>عیار</th><th>وزن طلا (گرم و سوت)</th><th>مبلغ (تومان)</th></tr>{''.join(lines)}</table>
<p>جمع کل: {e(display(total))} تومان</p><p>{NOTICE}</p><footer>{e(p['address'])} — تلفن: {e(p['phone'])}</footer></html>'''
        Path(path).write_text(html, encoding='utf-8')


def export_invoice_pdf(data, path):
    """A5 landscape invoice, matching the gallery's printed stationery."""
    import arabic_reshaper
    from bidi.algorithm import get_display
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A5, landscape
    from reportlab.lib import colors
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    font = 'HesabInvoice'
    if font not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(font, str(Path(__file__).resolve().parent / 'assets' / 'DejaVuSans.ttf')))
    c = canvas.Canvas(str(path), pagesize=landscape(A5))
    c.setTitle(f"Invoice {data['number']}")
    gold = colors.HexColor('#b49b54')
    def txt(value, x, y, size=9, align='right'):
        c.setFont(font, size)
        c.setFillColor(colors.HexColor('#302b23'))
        shaped = get_display(arabic_reshaper.reshape(str(value)))
        {'right':c.drawRightString, 'center':c.drawCentredString, 'left':c.drawString}[align](x,y,shaped)
    def wrapped(value, width, size=9):
        lines=[]; line=''
        for word in str(value).split():
            trial=(line+' '+word).strip()
            if line and pdfmetrics.stringWidth(get_display(arabic_reshaper.reshape(trial)),font,size)>width:
                lines.append(line); line=word
            else: line=trial
        return lines+[line]
    rows=data['rows']; groups=[rows[i:i+4] for i in range(0,len(rows),4)]
    total=sum((Decimal(r['total']) for r in rows),Decimal(0))
    logo=Path(__file__).resolve().parent/'gallery-logo.png'
    if not logo.exists(): logo=Path(__file__).resolve().parent/'assets'/'gallery-logo.png'
    for page, group in enumerate(groups,1):
        c.setStrokeColor(gold);c.setLineWidth(.8)
        c.rect(13,13,568,394);c.rect(18,18,558,384)
        if logo.exists():
            c.drawImage(str(logo),253,330,width=90,height=76,preserveAspectRatio=True,anchor='c',mask='auto')
        else:
            txt('طلای قدیم پور',298,367,16,'center')
        txt('شماره: '+str(data['number']),145,380)
        txt('تاریخ: '+jalali_timestamp(data['created']),220,358,8)
        txt('نام خریدار: '+data['customer'],564,380)
        txt('قیمت روز: '+display(Decimal(rows[0]['price']))+' تومان',564,358,8)
        txt('همراه: '+data.get('phone',''),564,341,8)
        txt('کد ملی خریدار: '+data.get('national_id',''),564,328,8)
        docs='، '.join(str(r.get('document_no','')) for r in group)
        txt('سند فروش: '+docs,215,338,8)
        # Visual order left to right: amount, grams, soot, purity, description.
        xs=[28,177,232,287,352,566]; top=322; head=289; bottom=119
        c.setFillColor(colors.HexColor('#dfce94'));c.rect(28,head,538,33,fill=1,stroke=0)
        c.setStrokeColor(gold); c.rect(28,bottom,538,top-bottom)
        for x in [177,287,352]:c.line(x,bottom,x,top)
        c.line(232,bottom,232,306);c.line(177,306,287,306);c.line(28,head,566,head)
        for label,x,y in [('مبلغ (تومان)',102,301),('وزن طلا',232,311),('گرم',204,293),('سوت',259,293),('عیار',319,301),('شرح کالا',459,301)]:txt(label,x,y,10,'center')
        for i,row in enumerate(group):
            y=269-i*39; weight=Decimal(row['weight']); grams=int(weight)
            title=row.get('product_title') or ('طلای نو' if row['kind']=='new' else 'طلای دست دوم')
            for j,line in enumerate(wrapped(title,200)[:2]):txt(line,558,y-j*14)
            txt('750/18' if Decimal(row['purity'])==750 else row['purity'],319,y,9,'center')
            txt(display(grams),204,y,9,'center');txt(display((weight-grams)*1000),259,y,9,'center')
            txt(display(Decimal(row['total'])),102,y,9,'center')
        txt('جمع مبلغ: '+display(total)+' تومان',340,98,11)
        txt('مهر و امضا',112,98,9,'center')
        txt('www.ghadimpourgold.ir',563,103,8)
        txt('021-44535901',563,89,9)
        txt('تهرانسر - خیابان گیتی نما - پاساژ سینا - پلاک 5',563,73,8)
        for j,line in enumerate(wrapped(NICE_NOTICE,525,8)):txt(line,298,49-j*12,8,'center')
        if len(groups)>1:txt(f'{page} / {len(groups)}',32,23,7,'left')
        c.showPage()
    c.save()
    return Path(path)


NICE_NOTICE = 'مشتری گرامی جنس فروخته شده، در هنگام تعویض و یا فروش، اجرت آن کسر و طلا به نرخ روز خریداری میگردد'


def invoice_dialog(app):
    from tkinter import simpledialog, messagebox, filedialog
    import webbrowser
    store = Invoices(app.ledger)
    try:
        profile = store.profile()
        if not profile or messagebox.askyesno('مشخصات گالری', 'مشخصات گالری تغییر کند؟', parent=app.root):
            values = []
            for key, label, default in [('name','نام گالری','طلای قدیم پور'), ('address','آدرس فروشگاه',''), ('phone','تلفن فروشگاه','')]:
                value = simpledialog.askstring('مشخصات گالری', label, initialvalue=(profile or {}).get(key, default), parent=app.root)
                if value is None: return
                values.append(value)
            store.save_profile(*values)
        existing = simpledialog.askstring('فاکتور', 'برای بازچاپ، شماره فاکتور را وارد کنید؛ برای صدور جدید خالی بگذارید.', parent=app.root)
        if existing is None: return
        if existing.strip():
            number = int(existing)
        else:
            documents = simpledialog.askstring('صدور فاکتور', 'شماره سندهای فروش (با ویرگول جدا کنید):', parent=app.root)
            if not documents: return
            ids = []
            for doc in documents.replace('،', ',').split(','):
                row = app.ledger.connection.execute('SELECT id FROM transactions WHERE document_no=?', (int(doc.strip()),)).fetchone()
                if not row: raise ValueError('شماره سند پیدا نشد.')
                ids.append(row[0])
            first = app.ledger.get(ids[0])
            values = []
            for label, default in [('نام مشتری', first['customer_name']), ('شماره همراه', first['customer_phone']), ('کد ملی', '')]:
                value = simpledialog.askstring('مشخصات مشتری', label, initialvalue=default, parent=app.root)
                if value is None: return
                values.append(value)
            number = store.issue(ids, *values)
            messagebox.showinfo('ثبت فاکتور', f'فاکتور شماره {number} ثبت شد. شماره آن مستقل از سند است.', parent=app.root)
        path = filedialog.asksaveasfilename(parent=app.root, initialfile=f'invoice-{number}.pdf', defaultextension='.pdf', filetypes=[('PDF','*.pdf')])
        if path:
            store.export(number, path)
            import os
            if os.name == 'nt':
                os.startfile(str(Path(path).resolve()))
            else:
                webbrowser.open(Path(path).resolve().as_uri())
            if messagebox.askyesno('چاپ فاکتور', 'فاکتور PDF ذخیره شد. به چاپگر پیش‌فرض ارسال شود؟', parent=app.root):
                from gold_reports import send_to_printer
                send_to_printer(path)
    except (ValueError, OSError, RuntimeError) as error:
        messagebox.showerror('فاکتور', str(error), parent=app.root)


def invoice_archive(app):
    import tkinter as tk
    import gold_widgets as ttk
    from tkinter import filedialog, messagebox
    store = Invoices(app.ledger)
    window = tk.Toplevel(app.root)
    window.title('آرشیو فاکتورها')
    window.geometry('850x450')
    tree = ttk.Treeview(window, columns=('number', 'date', 'customer', 'phone', 'total'), show='headings')
    for key, title in zip(tree['columns'], ('شماره فاکتور', 'تاریخ', 'مشتری', 'همراه', 'مبلغ تومان')):
        tree.heading(key, text=title)
        tree.column(key, width=150)
    tree.pack(fill='both', expand=True)
    def refresh():
        tree.delete(*tree.get_children())
        for row in store.db.execute('SELECT number,snapshot FROM invoices ORDER BY number DESC'):
            data = json.loads(row['snapshot'])
            total = sum((Decimal(r['total']) for r in data['rows']), Decimal(0))
            tree.insert('', 'end', iid=str(row['number']), values=(row['number'], jalali_timestamp(data['created']), data['customer'], data['phone'], display(total)))
    def export():
        if not tree.selection():
            return
        number = int(tree.selection()[0])
        path = filedialog.asksaveasfilename(parent=window, initialfile=f'invoice-{number}.pdf', defaultextension='.pdf', filetypes=[('PDF', '*.pdf')])
        if path:
            try:
                store.export(number, path)
                import webbrowser
                webbrowser.open(Path(path).resolve().as_uri())
            except (ValueError, OSError, RuntimeError) as error:
                messagebox.showerror('فاکتور', str(error), parent=window)
    ttk.Button(window, text='به‌روزرسانی', command=refresh).pack(side='right')
    ttk.Button(window, text='نمایش / PDF / چاپ', command=export).pack(side='right')
    tree.bind('<Double-1>', lambda event: export())
    refresh()
