"""خروجی PDF راست‌به‌چپ و چاپ سیستم‌عامل؛ وابستگی‌ها فقط هنگام گزارش بارگذاری می‌شوند."""
from datetime import datetime
from decimal import Decimal
from pathlib import Path
import os
import shutil
import subprocess

from gold_accounting import display, jalali_timestamp, money


def export_pdf(path, rows, title="گزارش تراکنش‌ها", filter_text="", generated_at=None):
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import SimpleDocTemplate, LongTable, TableStyle, Spacer
    except ImportError as error:
        raise RuntimeError("برای PDF وابستگی‌های requirements.txt را نصب کنید.") from error
    font_path = Path(__file__).resolve().parent / "assets" / "DejaVuSans.ttf"
    if not font_path.exists():
        raise RuntimeError("فونت PDF پیدا نشد؛ پوشه assets را کنار برنامه قرار دهید.")
    font = "HesabGhadim"
    if font not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(font, str(font_path)))

    def rtl(value):
        return get_display(arabic_reshaper.reshape(str(value)))

    def amount(row, key, rounded=True):
        value = row[key]
        if value is None:
            return "—"
        value = Decimal(value)
        return display(money(value) if rounded else value)

    rows = list(rows)
    page_size = landscape(A4)
    width, height = page_size
    stamp = generated_at or jalali_timestamp(datetime.now().astimezone())
    # دو خط توضیح کوتاه؛ متن فیلتر بلند با خطوط مستقل در سربرگ نمایش داده می‌شود.
    filter_lines = []
    for part in filter_text.split(" | "):
        if part:
            filter_lines.append(part)
    header_height = 84 + 12 * len(filter_lines)
    document = SimpleDocTemplate(str(path), pagesize=page_size, rightMargin=22, leftMargin=22,
                                 topMargin=header_height, bottomMargin=38,
                                 title=f"حساب قدیم — {title}", author="حساب قدیم")
    headings = ("سند", "تاریخ و ساعت شمسی", "نوع / جهت", "وزن اولیه", "وزن حساب‌شده",
                "قیمت هر گرم", "ساخت ٪", "فروش ٪", "مالیات ٪", "مبلغ کل")
    widths = [43, 112, 77, 65, 71, 94, 42, 42, 44, width - 44 - 690]
    data = [[rtl(cell) for cell in reversed(headings)]]
    commands = [("FONTNAME", (0, 0), (-1, -1), font),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#163e45")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#c39b49"))]
    for index, row in enumerate(rows):
        values = [row["document_no"], row["created_at_jalali"] or row["created_at"],
                  ("نو" if row["kind"] == "new" else "دست‌دوم") + " / " + ("ورود" if row["direction"] == "in" else "خروج"),
                  amount(row, "weight", False), amount(row, "stock_weight", False),
                  amount(row, "price"), amount(row, "making_rate", False),
                  amount(row, "selling_rate", False), amount(row, "tax_rate", False), amount(row, "total")]
        # مقادیر بسیار بلند به چند خط شکسته می‌شوند تا هیچ عددی بریده نشود.
        cells = []
        for column, value in enumerate(values):
            text = str(value)
            if column not in (1, 2) and len(text) > 15:
                text = "\n".join(text[i:i + 13] for i in range(0, len(text), 13))
            cells.append("\n".join(rtl(line) for line in text.split("\n")))
        start = len(data)
        data.append(list(reversed(cells)))
        details = (f"خام: {amount(row, 'base_amount')}    |    اجرت ساخت: {amount(row, 'making_amount')}    |    "
                   f"اجرت فروش: {amount(row, 'selling_amount')}    |    مالیات اجرت‌ها: {amount(row, 'tax_amount')}")
        more = (f"وزن مبنای مبلغ: {amount(row, 'billed_weight', False)} گرم    |    "
                f"سود طلایی: {amount(row, 'gold_profit', False)} گرم    |    "
                f"ویرایش: {row['updated_at_jalali'] or '—'}    |    "
                f"روش محاسبه: {'قدیمی' if row['calculation_version'] == 'legacy' else 'جدید'}")
        product = ''
        if 'product_code' in row.keys() and (row['product_code'] or row['product_title'] or 'purity' in row.keys()):
            product = f"محصول: {row['product_code'] or '—'} — {row['product_title'] or '—'}"
            if 'purity' in row.keys():
                product += f" | عیار اولیه: {row['purity']} | عیار خرید: {row['purchase_purity']}"
            product = '\n'.join(rtl(product[i:i + 85]) for i in range(0, len(product), 85)) + '\n'
        data.append([product + rtl(details) + "\n" + rtl(more)] + [""] * 9)
        color = colors.HexColor("#f0f5f4" if index % 2 == 0 else "#ffffff")
        commands.extend([("SPAN", (0, start + 1), (-1, start + 1)),
                         ("NOSPLIT", (0, start), (-1, start + 1)),
                         ("BACKGROUND", (0, start), (-1, start + 1), color),
                         ("FONTSIZE", (0, start + 1), (-1, start + 1), 7),
                         ("LINEBELOW", (0, start + 1), (-1, start + 1), .3, colors.HexColor("#d8e3df"))])
    if not rows:
        data.append([rtl("هیچ سندی مطابق این جستجو یافت نشد.")] + [""] * 9)
        commands.append(("SPAN", (0, 1), (-1, 1)))
    table = LongTable(data, colWidths=list(reversed(widths)), repeatRows=1, hAlign="RIGHT")
    table.setStyle(TableStyle(commands))
    incoming = sum((Decimal(row["total"]) for row in rows if row["direction"] == "in"), Decimal(0))
    outgoing = sum((Decimal(row["total"]) for row in rows if row["direction"] == "out"), Decimal(0))

    def page(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#163e45"))
        canvas.setFont(font, 17)
        canvas.drawRightString(width - 22, height - 30, rtl("حساب قدیم"))
        canvas.setFont(font, 10)
        canvas.drawRightString(width - 22, height - 50, rtl(title))
        canvas.setFont(font, 8)
        canvas.drawRightString(width - 22, height - 66,
                              rtl(f"زمان گزارش: {stamp}    |    تعداد: {len(rows)}    |    وزن: گرم؛ مبلغ: تومان"))
        for index, line in enumerate(filter_lines):
            canvas.drawRightString(width - 22, height - 80 - index * 12, rtl(line))
        canvas.setFont(font, 7)
        canvas.drawRightString(width - 22, 23,
                              rtl(f"مجموع ورود: {display(money(incoming))} تومان    |    مجموع خروج: {display(money(outgoing))} تومان"))
        canvas.drawString(22, 23, rtl(f"صفحه {doc.page}"))
        canvas.restoreState()

    document.build([Spacer(1, 2), table], onFirstPage=page, onLaterPages=page)
    return Path(path)


def send_to_printer(path):
    path = str(Path(path).resolve())
    if os.name == "nt":
        try:
            os.startfile(path, "print")
        except OSError as error:
            raise RuntimeError("نرم‌افزار پیش‌فرض PDF یا چاپگر ویندوز را تنظیم کنید.") from error
        return
    command = shutil.which("lp") or shutil.which("lpr")
    if not command:
        raise RuntimeError("سرویس چاپ پیدا نشد. گزارش را PDF ذخیره و از PDF‌خوان چاپ کنید.")
    try:
        subprocess.run([command, path], check=True, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError("ارسال به چاپگر انجام نشد؛ اتصال و چاپگر پیش‌فرض را بررسی کنید.") from error
