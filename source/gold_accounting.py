"""حساب قدیم — حسابداری طلا با Python و Tkinter؛ مبالغ و وزن‌ها با Decimal."""
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from pathlib import Path
import sqlite3
import unicodedata


def product_text(value):
    return unicodedata.normalize('NFKC', str(value)).translate(
        str.maketrans('يك٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', 'یک01234567890123456789')
    ).strip().casefold()


TRANSLATION = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩٫", "01234567890123456789.")


def number(value, label, allow_zero=False):
    text = str(value).translate(TRANSLATION).replace(",", "").replace("٬", "").strip()
    try:
        result = Decimal(text)
    except InvalidOperation:
        raise ValueError(f"{label} را به صورت عدد وارد کنید.") from None
    if not result.is_finite() or result < 0 or (result == 0 and not allow_zero):
        raise ValueError(f"{label} باید {'صفر یا مثبت' if allow_zero else 'مثبت'} باشد.")
    if result > Decimal("1000000000000000") or result.as_tuple().exponent < -8:
        raise ValueError(f"{label}: حداکثر ۱۵ رقم صحیح و ۸ رقم اعشار وارد کنید.")
    return result


def money(value):
    with localcontext() as context:
        context.prec = 100
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def display(value):
    text = f"{value:,f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


@dataclass(frozen=True)
class Calculation:
    base: Decimal
    making: Decimal
    selling: Decimal
    tax: Decimal
    total: Decimal
    original_weight: Decimal = Decimal(0)
    stock_weight: Decimal = Decimal(0)
    billed_weight: Decimal = Decimal(0)
    gold_profit: Decimal = Decimal(0)
    purity: Decimal = Decimal(750)
    purchase_purity: Decimal = Decimal(735)


def calculate(weight, price, making_rate=Decimal(0), selling_rate=Decimal(0), tax_rate=Decimal(0)):
    with localcontext() as context:
        context.prec = 100
        base = weight * price
        making = base * making_rate / 100
        selling = (base + making) * selling_rate / 100
        tax = (making + selling) * tax_rate / 100
        # مالیات فقط روی مبالغ اجرت‌هاست؛ گرد کردن تنها در مبلغ نهایی است.
        return Calculation(base, making, selling, tax, money(base + making + selling + tax),
                           original_weight=weight, stock_weight=weight)


def transaction_rates(direction, kind, making_rate, selling_rate, tax_rate):
    if direction not in ("in", "out") or kind not in ("new", "used"):
        raise ValueError("نوع تراکنش نامعتبر است.")
    making = number(making_rate, "اجرت ساخت", True) if kind == "new" else Decimal(0)
    selling = number(selling_rate, "اجرت فروش", True) if direction == "out" else Decimal(0)
    tax = number(tax_rate, "مالیات", True) if kind == "new" and direction == "out" else Decimal(0)
    return making, selling, tax


def calculate_transaction(direction, kind, weight, price, making_rate="0", selling_rate="0", tax_rate="0", *, purity="750", purchase_purity="735"):
    purity = number(purity, "عیار اولیه")
    purchase_purity = number(purchase_purity, "عیار خرید")
    if purity > 1000 or purchase_purity > 1000:
        raise ValueError("عیار باید بیشتر از صفر و حداکثر ۱۰۰۰ باشد.")
    making, selling, tax = transaction_rates(direction, kind, making_rate, selling_rate, tax_rate)
    weight = number(weight, "وزن اولیه")
    price = number(price, "قیمت هر گرم")
    with localcontext() as context:
        context.prec = 100
        if kind == "new":
            return replace(calculate(weight, price, making, selling, tax),
                           gold_profit=(calculate(weight, price, making, selling, tax).selling / price
                                        if direction == 'out' else Decimal(0)),
                           billed_weight=weight if direction == "out" else Decimal(0),
                           purity=purity, purchase_purity=purchase_purity)
        stock_weight = weight * purchase_purity / purity
        if direction == "in":
            return replace(calculate(stock_weight, price), original_weight=weight,
                           stock_weight=weight, billed_weight=stock_weight,
                           purity=purity, purchase_purity=purchase_purity)
        billed_weight = weight * (1 + selling / 100)
        return replace(calculate(weight, price, selling_rate=selling),
                       stock_weight=weight, billed_weight=billed_weight,
                       gold_profit=(money(weight * price * selling / 100) / price),
                       purity=purity, purchase_purity=purchase_purity)


def jalali_timestamp(value):
    """تاریخ میلادی/ISO را بدون وابستگی جانبی به هجری شمسی تبدیل می‌کند.

    ساعت و منطقه زمانی همان ساعت ذخیره‌شده/سیستم است. تاریخ‌های قدیمی که
    ساعت ندارند، بدون ساختن ساعت فرضی تبدیل می‌شوند.
    """
    date_only = isinstance(value, str) and len(value.strip()) == 10
    moment = datetime.fromisoformat(value) if isinstance(value, str) else value
    year, month, day = moment.year, moment.month, moment.day
    month_days = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)
    leap_year = year + 1 if month > 2 else year
    days = (355666 + 365 * year + (leap_year + 3) // 4
            - (leap_year + 99) // 100 + (leap_year + 399) // 400
            + day + month_days[month - 1])
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm, jd = 1 + days // 31, 1 + days % 31
    else:
        jm, jd = 7 + (days - 186) // 30, 1 + (days - 186) % 30
    text = f"{jy:04d}/{jm:02d}/{jd:02d}"
    return text if date_only else f"{text} {moment:%H:%M:%S}"


def current_timestamps():
    moment = datetime.now().astimezone()
    return moment.isoformat(sep=" ", timespec="seconds"), jalali_timestamp(moment)


def monetary_title(direction):
    if direction == "in":
        return "قیمت ریالی ورود"
    if direction == "out":
        return "قیمت ریالی طلای فروخته‌شده"
    raise ValueError("نوع تراکنش نامعتبر است.")


def describe_calculation(result, direction, kind):
    """مبالغ ورودی و خروجی با همان واحد تومان نمایش داده می‌شوند."""
    title = monetary_title(direction)
    lines = [f"قیمت طلای خام: {display(money(result.base))} تومان"]
    if kind == "new":
        lines[0] += f"    |    اجرت ساخت: {display(money(result.making))} تومان"
    if direction == "out":
        lines.append(f"قیمت اجرت فروش: {display(money(result.selling))} تومان")
        if kind == "new":
            lines[-1] += f"    |    مالیات بر ارزش افزوده اجرت‌ها: {display(money(result.tax))} تومان"
    total_label = "قیمت کل با احتساب مالیات بر ارزش افزوده" if direction == "out" and kind == "new" else "قیمت کل"
    lines.append(f"{total_label}: {display(result.total)} تومان")
    lines.append(f"{title}: {display(result.total)} تومان")
    if kind == "used":
        weights = [f"وزن اولیه: {display(result.original_weight)} گرم"]
        if direction == 'in':
            weights.append(f"وزن مبنای پرداخت (وزن ÷ {display(result.purity)} × {display(result.purchase_purity)}): {display(result.billed_weight)} گرم")
        if direction == "in":
            weights.append(f"وزن افزوده به موجودی: {display(result.stock_weight)} گرم؛ وزن تبدیل‌شده فقط مبنای مبلغ پرداختی است.")
        if direction == "out":
            weights.append(f"فروش با اجرت: {display(result.billed_weight)} گرم    |    "
                           f"سود طلایی این فروش: {display(result.gold_profit)} گرم")
        lines = weights + lines
    return "\n".join(lines)


class Ledger:
    def __init__(self, path, timestamp_source=None):
        self.timestamp_source = timestamp_source or (lambda: current_timestamps())
        self.connection = sqlite3.connect(str(path))
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                direction TEXT NOT NULL CHECK(direction IN ('in', 'out')),
                kind TEXT NOT NULL CHECK(kind IN ('new', 'used')),
                weight TEXT NOT NULL,
                price TEXT NOT NULL,
                making_rate TEXT NOT NULL,
                selling_rate TEXT NOT NULL,
                total TEXT NOT NULL
            )
        """)
        # سوابق قدیمی بدون تغییر وزن و مبلغ حفظ می‌شوند؛ سود گذشته حدس زده نمی‌شود.
        definitions = {
            "supplier_id": "INTEGER",
            "tax_rate": "TEXT NOT NULL DEFAULT '0'",
            "tax_amount": "TEXT NOT NULL DEFAULT '0'",
            "stock_weight": "TEXT",
            "billed_weight": "TEXT NOT NULL DEFAULT '0'",
            "gold_profit": "TEXT NOT NULL DEFAULT '0'",
            "calculation_version": "TEXT NOT NULL DEFAULT 'legacy'",
            "base_amount": "TEXT",
            "making_amount": "TEXT",
            "selling_amount": "TEXT",
            "document_no": "INTEGER",
            "created_at_jalali": "TEXT",
            "updated_at": "TEXT",
            "updated_at_jalali": "TEXT",
            "product_id": "INTEGER",
            "product_code": "TEXT",
            "product_title": "TEXT",
            "purity": "TEXT NOT NULL DEFAULT '750'",
            "customer_name": "TEXT NOT NULL DEFAULT ''",
            "customer_phone": "TEXT NOT NULL DEFAULT ''",
            "bank_card": "TEXT NOT NULL DEFAULT ''",
            "national_image": "BLOB",
            "bank_image": "BLOB",
            "gold_fee_rate": "TEXT NOT NULL DEFAULT '0'",
            "purchase_purity": "TEXT NOT NULL DEFAULT '735'",
        }
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            self.connection.execute("CREATE TABLE IF NOT EXISTS suppliers (id INTEGER PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE, phone TEXT NOT NULL DEFAULT '')")
            columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(transactions)")}
            for column, definition in definitions.items():
                if column not in columns:
                    self.connection.execute(f"ALTER TABLE transactions ADD COLUMN {column} {definition}")
            self.connection.execute("""UPDATE transactions SET stock_weight = weight,
                billed_weight = CASE WHEN direction = 'out' THEN weight ELSE '0' END
                WHERE stock_weight IS NULL""")
            self.connection.execute("""CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL,
                code_key TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
                title_key TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('new', 'used'))
            )""")
            self.connection.execute("""CREATE INDEX IF NOT EXISTS transactions_product
                ON transactions(product_id)""")
            self.connection.execute("""CREATE TABLE IF NOT EXISTS ledger_counters (
                name TEXT PRIMARY KEY, value INTEGER NOT NULL)""")
            counter = self.connection.execute(
                "SELECT value FROM ledger_counters WHERE name = 'next_document_no'"
            ).fetchone()
            highest = self.connection.execute(
                "SELECT MAX(document_no) FROM transactions"
            ).fetchone()[0]
            next_no = max(1001, (highest or 1000) + 1, counter["value"] if counter else 1001)
            for row in self.connection.execute(
                "SELECT id FROM transactions WHERE document_no IS NULL ORDER BY id"
            ).fetchall():
                self.connection.execute("UPDATE transactions SET document_no = ? WHERE id = ?",
                                        (next_no, row["id"]))
                next_no += 1
            self.connection.execute(
                "INSERT OR REPLACE INTO ledger_counters (name, value) VALUES ('next_document_no', ?)",
                (next_no,))
            self.connection.execute("""CREATE UNIQUE INDEX IF NOT EXISTS transactions_document_no
                ON transactions(document_no)""")
            for row in self.connection.execute(
                "SELECT id, created_at FROM transactions WHERE created_at_jalali IS NULL"
            ).fetchall():
                try:
                    stamp = jalali_timestamp(row["created_at"])
                except (ValueError, TypeError):
                    # تاریخ ناخوانای قدیمی را با تاریخ امروز جایگزین نمی‌کنیم.
                    continue
                self.connection.execute("UPDATE transactions SET created_at_jalali = ? WHERE id = ?",
                                        (stamp, row["id"]))

    def create_product(self, code, title, kind):
        code, title = str(code).strip(), str(title).strip()
        if not code or not title or len(code) > 64 or len(title) > 160:
            raise ValueError("کد (حداکثر ۶۴ نویسه) و عنوان (حداکثر ۱۶۰ نویسه) الزامی است.")
        if kind not in ('new', 'used'):
            raise ValueError("نوع طلا نامعتبر است.")
        try:
            with self.connection:
                cursor = self.connection.execute(
                    'INSERT INTO products(code,code_key,title,title_key,kind) VALUES (?,?,?,?,?)',
                    (code, product_text(code), title, product_text(title), kind))
        except sqlite3.IntegrityError:
            raise ValueError("این کد محصول قبلاً ثبت شده است.") from None
        return self.get_product(cursor.lastrowid)

    def get_product(self, product_id):
        row = self.connection.execute('SELECT * FROM products WHERE id=?', (product_id,)).fetchone()
        if row is None:
            raise ValueError("محصول یافت نشد.")
        return row

    def product_balance(self, product_id):
        with localcontext() as context:
            context.prec = 100
            return sum((Decimal(row['stock_weight']) * (1 if row['direction'] == 'in' else -1)
                        for row in self.connection.execute(
                            'SELECT direction,stock_weight FROM transactions WHERE product_id=?',
                            (product_id,))), Decimal(0))

    def find_products(self, query='', kind=None, code=None):
        if kind is not None and kind not in ('new', 'used'):
            raise ValueError("نوع طلا نامعتبر است.")
        rows = self.connection.execute('SELECT * FROM products ORDER BY id DESC').fetchall()
        key = product_text(code if code is not None else query)
        matches = [row for row in rows if row['code_key'] == key] if key else []
        if code is not None or matches:
            rows = matches
        elif key:
            rows = [row for row in rows if key in row['title_key']]
        return [dict(row, balance=str(self.product_balance(row['id'])))
                for row in rows if kind is None or row['kind'] == kind]

    def _product_fields(self, product_id, kind):
        product = self.get_product(product_id)
        if product['kind'] != kind:
            raise ValueError("نوع طلا با محصول انتخاب‌شده یکسان نیست.")
        return dict(product_id=product['id'], product_code=product['code'], product_title=product['title'])

    def _resolve_product(self, code, title, kind, direction):
        matches = self.find_products(code=code)
        if matches:
            product = matches[0]
            if product['kind'] != kind:
                raise ValueError("نوع طلا با کد کالای ثبت‌شده یکسان نیست.")
            if title and product_text(title) != product_text(product['title']):
                raise ValueError("این کد برای عنوان کالای دیگری ثبت شده است.")
            return self._product_fields(product['id'], kind)
        if direction != 'in':
            raise ValueError("برای این کد کالا ابتدا ورود ثبت کنید.")
        if not title:
            raise ValueError("برای کد کالای جدید، نوع/عنوان کالا را وارد کنید.")
        cursor = self.connection.execute(
            'INSERT INTO products(code,code_key,title,title_key,kind) VALUES (?,?,?,?,?)',
            (code, product_text(code), title, product_text(title), kind))
        return self._product_fields(cursor.lastrowid, kind)

    def balances(self):
        with localcontext() as context:
            context.prec = 100
            result = {"new": Decimal(0), "used": Decimal(0)}
            for row in self.connection.execute("SELECT direction, kind, stock_weight FROM transactions"):
                result[row["kind"]] += Decimal(row["stock_weight"]) * (1 if row["direction"] == "in" else -1)
            return result

    def trade_volumes(self):
        volumes = {kind: {'in': Decimal(0), 'out': Decimal(0)} for kind in ('new', 'used')}
        for row in self.connection.execute('SELECT kind,direction,stock_weight FROM transactions'):
            volumes[row['kind']][row['direction']] += Decimal(row['stock_weight'])
        return volumes

    def gold_cost_summary(self):
        """FIFO cost in gold grams; tax excluded, physical stock untouched."""
        with localcontext() as context:
            context.prec = 100
            lots = {}
            sale_profits = {}
            purchase = fees = revenue = cost_sold = Decimal(0)
            for record in self.connection.execute('SELECT * FROM transactions ORDER BY id'):
                row = dict(record)
                key = (row['kind'], row['product_id'])
                queue = lots.setdefault(key, [])
                weight = Decimal(row['stock_weight'])
                if row['direction'] == 'in':
                    base = (Decimal(row['billed_weight']) if row['kind'] == 'used'
                            and row['calculation_version'] != 'legacy' else weight)
                    fee = Decimal(row['weight']) * Decimal(row['gold_fee_rate']) / 100
                    purchase += base + fee
                    fees += fee
                    queue.append([weight, base + fee])
                    continue
                remaining = weight
                basis = Decimal(0)
                for lot in queue:
                    take = min(remaining, lot[0])
                    if lot[0]:
                        allocated = lot[1] * take / lot[0]
                        basis += allocated
                        lot[1] -= allocated
                    lot[0] -= take
                    remaining -= take
                    if not remaining:
                        break
                if remaining:
                    raise ValueError('موجودی مرتبط برای محاسبه بهای تمام‌شده کافی نیست.')
                cost_sold += basis
                previous_revenue = revenue
                if row['calculation_version'] == 'legacy':
                    revenue += weight + Decimal(row['gold_profit'])
                else:
                    revenue += (Decimal(row['total']) - Decimal(row['tax_amount'])) / Decimal(row['price'])
                sale_profits[row['id']] = revenue - previous_revenue - basis
            inventory_cost = sum((lot[1] for queue in lots.values() for lot in queue), Decimal(0))
            return dict(sale_profits=sale_profits, purchase_cost=purchase, purchase_fees=fees, sale_revenue=revenue,
                        sold_cost=cost_sold, inventory_cost=inventory_cost,
                        net_profit=revenue - cost_sold, accounting_assets=inventory_cost + revenue)

    def gold_dashboard(self):
        """Display totals: purchase cost is not physical sellable stock."""
        with localcontext() as context:
            context.prec = 100
            new_weight = new_fee = sold = Decimal(0)
            for row in self.connection.execute(
                    'SELECT direction, kind, weight, stock_weight, gold_fee_rate FROM transactions'):
                if row['direction'] == 'out':
                    sold += Decimal(row['stock_weight'])
                elif row['kind'] == 'new':
                    weight = Decimal(row['weight'])
                    new_weight += weight
                    new_fee += weight * Decimal(row['gold_fee_rate']) / 100
            return dict(new_purchase_weight=new_weight, new_purchase_fee=new_fee,
                        new_purchase_with_fee=new_weight + new_fee, sold_weight=sold,
                        net_profit=self.gold_cost_summary()['net_profit'])

    def gold_assets(self):
        with localcontext() as context:
            context.prec = 100
            stock = sum(self.balances().values(), Decimal(0))
            sold = profit = billed_sold = Decimal(0)
            for row in self.connection.execute(
                "SELECT * FROM transactions WHERE direction = 'out'"
            ):
                sold += Decimal(row["stock_weight"])
                profit += (self._used_sale_profit(dict(row), row['id'])
                           if row['kind'] == 'used' and row['calculation_version'] != 'legacy'
                           else (Decimal(row['selling_amount'] or '0') / Decimal(row['price'])
                                 if row['kind'] == 'new' and row['calculation_version'] != 'legacy'
                                 else Decimal(row['gold_profit'])))
                billed_sold += Decimal(row["billed_weight"])
            # سود جدا از وزن کسرشده است؛ اگر فروش با اجرت را جمع کنیم دوباره شمرده می‌شود.
            summary = self.gold_cost_summary()
            profit = summary['net_profit']
            return {"stock": stock, "sold": sold, "profit": profit,
                    "inventory_total": summary['inventory_cost'] + profit, "billed_sold": billed_sold,
                    "total": summary['accounting_assets']}

    @staticmethod
    def _calculated_fields(direction, kind, weight, price, making_rate, selling_rate, tax_rate,
                           purity="750", purchase_purity="735", product_code="", product_title=""):
        product_code, product_title = str(product_code).strip(), str(product_title).strip()
        if len(product_code) > 64 or len(product_title) > 160:
            raise ValueError("کد کالا حداکثر ۶۴ و نوع/عنوان کالا حداکثر ۱۶۰ نویسه باشد.")
        rates = transaction_rates(direction, kind, making_rate, selling_rate, tax_rate)
        result = calculate_transaction(direction, kind, weight, price, *rates,
                                       purity=purity, purchase_purity=purchase_purity)
        fields = dict(zip(("making_rate", "selling_rate", "tax_rate"), map(str, rates)))
        fields.update(direction=direction, kind=kind, weight=str(result.original_weight),
                      price=str(number(price, "قیمت هر گرم")), total=str(result.total),
                      tax_amount=str(result.tax), stock_weight=str(result.stock_weight),
                      billed_weight=str(result.billed_weight), gold_profit=str(result.gold_profit),
                      calculation_version="6", purity=str(result.purity),
                      purchase_purity=str(result.purchase_purity), product_code=product_code,
                      product_title=product_title, base_amount=str(result.base),
                      making_amount=str(result.making), selling_amount=str(result.selling))
        return result, fields

    def _used_sale_profit(self, fields, before_id=None):
        """FIFO purchase settlement weight; physical stock remains unchanged."""
        lots = []
        query = "SELECT * FROM transactions"
        args = ()
        if before_id is not None:
            query += " WHERE id < ?"
            args = (before_id,)
        query += " ORDER BY id"
        with localcontext() as context:
            context.prec = 100
            for row in self.connection.execute(query, args):
                if row['kind'] != 'used' or row['product_id'] != fields.get('product_id'):
                    continue
                physical = Decimal(row['stock_weight'])
                if row['direction'] == 'in':
                    # Legacy documents have no reliable converted purchase basis.
                    paid = (Decimal(row['billed_weight'])
                            if row['calculation_version'] != 'legacy' else physical)
                    lots.append([physical, paid])
                else:
                    remaining = physical
                    for lot in lots:
                        used = min(remaining, lot[0])
                        if lot[0]:
                            lot[1] -= lot[1] * used / lot[0]
                        lot[0] -= used
                        remaining -= used
                        if not remaining:
                            break
            remaining = Decimal(fields['stock_weight'])
            basis = Decimal(0)
            for physical, paid in lots:
                used = min(remaining, physical)
                if physical:
                    basis += paid * used / physical
                remaining -= used
                if not remaining:
                    break
            if remaining:
                raise ValueError('موجودی خرید مرتبط برای محاسبه سود کافی نیست؛ کد کالای ورود و خروج را بررسی کنید.')
            return Decimal(fields['billed_weight']) - basis

    def get(self, transaction_id):
        row = self.connection.execute("SELECT * FROM transactions WHERE id = ?",
                                      (transaction_id,)).fetchone()
        if row is None:
            raise ValueError("تراکنش انتخاب‌شده وجود ندارد؛ فهرست را به‌روز کنید.")
        return row

    def _check_stock_history(self):
        # فقط مانده نهایی کافی نیست؛ اصلاح خرید قدیمی نباید فروش میانی را بی‌پشتوانه کند.
        with localcontext() as context:
            context.prec = 100
            balances = {"new": Decimal(0), "used": Decimal(0)}
            products = {}
            for row in self.connection.execute("""SELECT direction, kind, stock_weight, document_no, product_id
                    FROM transactions ORDER BY id"""):
                change = Decimal(row["stock_weight"]) * (1 if row["direction"] == "in" else -1)
                balances[row["kind"]] += change
                # سوابق بی‌کد یک مخزن مستقل‌اند؛ موجودی محصول دیگر قابل قرض‌گرفتن نیست.
                key = (row['kind'], row['product_id'])
                products[key] = products.get(key, Decimal(0)) + change
                if balances[row["kind"]] < 0 or products[key] < 0:
                    raise ValueError(f"موجودی سند {row['document_no']} در نوع طلا یا کد کالای انتخاب‌شده کافی نیست. "
                                     "کد کالای خروج باید دقیقاً با ورود یکسان باشد؛ موجودی کالای دیگر قابل استفاده نیست. "
                                     "اگر خرید بی‌کد بوده، خروج را نیز بی‌کد ثبت کنید. وزن پرداختی خرید مبنای موجودی نیست.")

    def add(self, direction, kind, weight, price, making_rate="0", selling_rate="0", tax_rate="0", *, product_id=None,
            purity="750", purchase_purity="735", product_code="", product_title="", gold_fee_rate="0", supplier_id=None, **customer):
        result, fields = self._calculated_fields(direction, kind, weight, price,
                                                 making_rate, selling_rate, tax_rate,
                                                 purity, purchase_purity, product_code, product_title)
        fields['supplier_id'] = self._supplier_id(supplier_id, direction, kind)
        fields['gold_fee_rate'] = str(number(gold_fee_rate, 'درصد اجرت طلایی', allow_zero=True)) if direction == 'in' else '0'
        from gold_customers import customer_fields
        fields.update(customer_fields(customer))
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            if product_id is None and fields['product_code']:
                fields.update(self._resolve_product(fields['product_code'], fields['product_title'], kind, direction))
                product_id = fields['product_id']
            if product_id is not None:
                fields.update(self._product_fields(product_id, kind))
                if direction == 'out' and result.stock_weight > self.product_balance(product_id):
                    raise ValueError("موجودی این محصول برای خروج کافی نیست.")
            if direction == "out" and result.stock_weight > self.balances()[kind]:
                raise ValueError("موجودی این نوع طلا برای خروج کافی نیست؛ ابتدا ورود ثبت کنید.")
            if direction == 'out' and kind == 'used':
                profit = self._used_sale_profit(fields)
                fields.update(gold_profit=str(profit), calculation_version='7')
                result = replace(result, gold_profit=profit)
            fields["document_no"] = self.connection.execute(
                "SELECT value FROM ledger_counters WHERE name = 'next_document_no'"
            ).fetchone()[0]
            fields["created_at"], fields["created_at_jalali"] = self.timestamp_source()
            self.connection.execute(
                f"INSERT INTO transactions ({', '.join(fields)}) VALUES ({', '.join('?' for _ in fields)})",
                tuple(fields.values()))
            self._check_stock_history()
            self.connection.execute("""UPDATE ledger_counters SET value = value + 1
                WHERE name = 'next_document_no'""")
        return result

    def update(self, transaction_id, kind, weight, price, making_rate="0", selling_rate="0", tax_rate="0", *,
               purity=None, purchase_purity=None, product_code=None, product_title=None, gold_fee_rate=None, supplier_id=None, **customer):
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            old = self.get(transaction_id)
            _, fields = self._calculated_fields(old["direction"], kind, weight, price,
                                                making_rate, selling_rate, tax_rate,
                                                old['purity'] if purity is None else purity,
                                                old['purchase_purity'] if purchase_purity is None else purchase_purity,
                                                (old['product_code'] or '') if product_code is None else product_code,
                                                (old['product_title'] or '') if product_title is None else product_title)
            if old['product_id'] is not None:
                self._product_fields(old['product_id'], kind)
            old_rates = transaction_rates(old["direction"], old["kind"], old["making_rate"],
                                          old["selling_rate"], old["tax_rate"])
            previous = dict(old)
            previous.update(zip(("making_rate", "selling_rate", "tax_rate"), map(str, old_rates)))
            changed = old["kind"] != kind or any(
                Decimal(previous[key]) != Decimal(fields[key])
                for key in ("weight", "price", "making_rate", "selling_rate", "tax_rate", "purity", "purchase_purity"))
            # ذخیره بدون تغییر ورودی‌ها نباید وزن یا مبلغ سوابق قدیمی را بازمحاسبه کند.
            if not changed:
                fields = {key: fields[key] for key in ('product_code', 'product_title')}
            if product_code is not None and fields.get('product_code') != (old['product_code'] or ''):
                if fields['product_code']:
                    fields.update(self._resolve_product(fields['product_code'], fields['product_title'], kind, old['direction']))
                else:
                    fields['product_id'] = None
            elif old['product_id'] is not None:
                if product_title is not None and product_text(product_title) != product_text(old['product_title'] or ''):
                    raise ValueError("عنوان کالای دارای کد را در این سند تغییر ندهید؛ برای کالای دیگر کد دیگری وارد کنید.")
                fields.update(self._product_fields(old['product_id'], kind))
            from gold_customers import customer_fields
            fields.update(customer_fields(customer))
            fields['supplier_id'] = self._supplier_id(old['supplier_id'] if supplier_id is None else supplier_id, old['direction'], kind)
            if gold_fee_rate is not None and old['direction'] == 'in':
                fields['gold_fee_rate'] = str(number(gold_fee_rate, 'درصد اجرت طلایی', allow_zero=True))
            fields["updated_at"], fields["updated_at_jalali"] = self.timestamp_source()
            assignments = ", ".join(f"{key} = ?" for key in fields)
            self.connection.execute(f"UPDATE transactions SET {assignments} WHERE id = ?",
                                    (*fields.values(), transaction_id))
            self._check_stock_history()
            updated = self.get(transaction_id)
        return updated

    def delete(self, transaction_id):
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            self.get(transaction_id)
            self.connection.execute("DELETE FROM transactions WHERE id = ?", (transaction_id,))
            self._check_stock_history()

    def rows(self, direction):
        return self.connection.execute(
            "SELECT * FROM transactions WHERE direction = ? ORDER BY id DESC", (direction,)
        ).fetchall()

    def search(self, **filters):
        from gold_services import search_transactions
        return search_transactions(self, **filters)

    def create_supplier(self, name, phone=''):
        name = str(name).strip()
        if not name or len(name) > 160:
            raise ValueError('نام بنکدار را وارد کنید (حداکثر ۱۶۰ حرف).')
        with self.connection:
            try:
                cursor = self.connection.execute('INSERT INTO suppliers(name,name_key,phone) VALUES (?,?,?)', (name, product_text(name), str(phone).strip()))
            except sqlite3.IntegrityError:
                raise ValueError('این بنکدار قبلاً ثبت شده است.') from None
        return cursor.lastrowid

    def suppliers(self):
        return self.connection.execute('SELECT * FROM suppliers ORDER BY name,id').fetchall()

    def _supplier_id(self, supplier_id, direction, kind):
        if supplier_id is None:
            return None
        if direction != 'in' or kind != 'new':
            raise ValueError('بنکدار فقط برای ورود طلای نو قابل انتخاب است.')
        if not self.connection.execute('SELECT 1 FROM suppliers WHERE id=?', (supplier_id,)).fetchone():
            raise ValueError('بنکدار یافت نشد.')
        return supplier_id

    def supplier_summary(self, supplier_id):
        with localcontext() as context:
            context.prec = 100
            purchased = fees = remaining = remaining_fee = Decimal(0)
            lots, records = {}, []
            for row in self.connection.execute("SELECT * FROM transactions WHERE kind='new' ORDER BY id"):
                queue = lots.setdefault(row['product_id'], [])
                weight = Decimal(row['stock_weight'])
                if row['direction'] == 'in':
                    fee = Decimal(row['weight']) * Decimal(row['gold_fee_rate']) / 100
                    queue.append([weight, fee, row['supplier_id']])
                    if row['supplier_id'] == supplier_id:
                        purchased += weight
                        fees += fee
                        records.append(dict(row))
                else:
                    left = weight
                    for lot in queue:
                        take = min(left, lot[0])
                        if lot[0]:
                            lot[1] -= lot[1] * take / lot[0]
                        lot[0] -= take
                        left -= take
                        if not left:
                            break
            for queue in lots.values():
                for weight, fee, owner in queue:
                    if owner == supplier_id:
                        remaining += weight
                        remaining_fee += fee
            return dict(purchased=purchased, fees=fees, remaining=remaining, remaining_fee=remaining_fee, records=records)

    def close(self):
        self.connection.close()


def main(license_setup=None):
    import tkinter as tk
    from gold_widgets import messagebox
    import gold_widgets as ttk

    from gold_features import DesktopFeatures

    root = tk.Tk()
    icon_path = Path(__file__).resolve().parent / 'assets' / 'app-icon.png'
    if icon_path.exists():
        root._app_icon = tk.PhotoImage(file=str(icon_path))
        root.iconphoto(True, root._app_icon)
    root.withdraw()
    root.title("حساب قدیم | حسابداری طلا")
    screen_width, screen_height = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f'{min(1280, screen_width - 40)}x{min(900, screen_height - 80)}')
    root.minsize(min(1000, screen_width - 40), min(620, screen_height - 80))
    import os
    database = Path(os.environ.get('HESAB_GHADIM_DATABASE',
                                  str(Path(__file__).resolve().with_name('gold_accounting.sqlite3'))))
    try:
        ledger = Ledger(database)
    except sqlite3.Error as error:
        messagebox.showerror("خطا", f"باز کردن فایل اطلاعات ممکن نشد:\n{error}")
        root.destroy()
        return

    try:
        features = DesktopFeatures(root, ledger, database)
        if not features.prepare():
            features.shutdown()
            ledger.close()
            root.destroy()
            return
    except (ValueError, sqlite3.Error) as error:
        messagebox.showerror("راه‌اندازی انجام نشد", str(error), parent=root)
        ledger.close()
        root.destroy()
        return
    features.build_overview()
    gold_cards = ttk.Frame(root, padding=8)
    gold_cards.pack(fill='x', padx=12)
    gold_cards.columnconfigure(0, weight=1)
    gold_cards.columnconfigure(1, weight=1)
    card_values = {}
    card_details = {}
    for column, (key, title) in enumerate((
            ('new_purchase_with_fee', 'وزن خرید طلای نو با اجرت'),
            ('net_profit', 'سود طلایی'))):
        card = ttk.LabelFrame(gold_cards, text=title, padding=10)
        card.grid(row=0, column=column, sticky='nsew', padx=5)
        card_values[key] = tk.StringVar(value='۰ گرم')
        card_details[key] = tk.StringVar()
        ttk.Label(card, textvariable=card_values[key], font=('Tahoma', 21, 'bold'),
                  foreground='#176875', anchor='e').pack(fill='x')
        ttk.Label(card, textvariable=card_details[key], anchor='e',
                  justify='right').pack(fill='x', pady=(6, 0))
    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True, padx=12, pady=8)
    from gold_customers import build_customer_tabs
    build_customer_tabs(notebook, ledger, root)
    from gold_special import build_special_tabs
    special_trade = build_special_tabs(notebook, ledger, root)
    views = []
    kinds = {"طلای نو": "new", "طلای دست‌دوم": "used"}
    special_choices = {'طلای آبشده': 'melted', 'سکه': 'emami86', 'سکه پارسیان': 'parsian'}

    cost_text = tk.StringVar()
    ttk.Label(root, textvariable=cost_text, anchor='e', justify='right', padding=10).pack(fill='x')

    def refresh():
        summary = ledger.gold_cost_summary()
        dashboard = ledger.gold_dashboard()
        for key, variable in card_values.items():
            variable.set(display(dashboard[key]) + ' گرم')
        card_details['new_purchase_with_fee'].set(
            'وزن خرید: ' + display(dashboard['new_purchase_weight']) + ' گرم | اجرت خرید: '
            + display(dashboard['new_purchase_fee']) + ' گرم\nمجموع خریدهای ثبت‌شده؛ نه موجودی فیزیکی باقی‌مانده')
        card_details['net_profit'].set(
            'وزن فروخته‌شده: ' + display(dashboard['sold_weight'])
            + ' گرم\nسود خالص فروش نو و دست‌دوم پس از کسر هزینه خرید و اجرت؛ بدون مالیات')
        cost_text.set(' | '.join(label + ': ' + display(summary[key]) + ' گرم' for key, label in (
            ('purchase_cost', 'کل هزینه خرید'), ('purchase_fees', 'اجرت پرداختی خرید'),
            ('inventory_cost', 'بهای موجودی باقی‌مانده'), ('sale_revenue', 'فروش بدون مالیات'),
            ('net_profit', 'سود خالص طلایی'), ('accounting_assets', 'دارایی طلایی حسابداری'))))
        features.update_overview()
        features.refresh_search()
        for direction, tree in views:
            tree.delete(*tree.get_children())
            for row in ledger.rows(direction):
                sign = "+" if direction == "in" else "−"
                tree.insert("", "end", iid=str(row["id"]), values=(
                    row["document_no"], row["created_at_jalali"] or f"{row['created_at']} (قدیمی)",
                    row["updated_at_jalali"] or "—",
                    display(Decimal(row["total"])),
                    display(money(Decimal(row["tax_amount"]))),
                    *(display(money(Decimal(row[key]))) if row[key] is not None else "—"
                      for key in ("selling_amount", "making_amount", "base_amount")),
                    display(Decimal(row["tax_rate"])),
                    display(Decimal(row["selling_rate"])),
                    display(Decimal(row["making_rate"])),
                    display(Decimal(row["price"])),
                    display(summary['sale_profits'].get(row['id'], Decimal(0))),
                    display(Decimal(row["billed_weight"])) if direction == "out" else "—",
                    sign + display(Decimal(row["stock_weight"])),
                    display(Decimal(row["weight"])),
                    "طلای نو" if row["kind"] == "new" else "دست‌دوم",
                    "قدیمی" if row["calculation_version"] == "legacy" else "جدید",
                    row['product_title'] or '—', row['product_code'] or '—',
                    row['purity'], row['purchase_purity'],
                    display(Decimal(row['gold_fee_rate'])),
                    display(Decimal(row['weight']) * Decimal(row['gold_fee_rate']) / 100),
                    display(Decimal(row['weight']) * (1 + Decimal(row['gold_fee_rate']) / 100)),
                ))

    def build_tab(direction, title):
        page = ttk.Frame(notebook, padding=4)
        notebook.add(page, text=title)
        panes = ttk.Panedwindow(page, orient="vertical")
        panes.pack(fill="both", expand=True)
        upper = ttk.Frame(panes, height=230)
        panes.add(upper, weight=1)
        canvas = tk.Canvas(upper, highlightthickness=0, background="#edf2f3", height=230)
        scroll = ttk.Scrollbar(upper, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        tab = ttk.Frame(canvas)
        content = canvas.create_window((0, 0), window=tab, anchor="nw")
        tab.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(content, width=event.width))
        form = ttk.LabelFrame(tab, text=f"ثبت {title}", padding=4)
        form.pack(fill="x")
        for column in (0, 2, 4):
            form.columnconfigure(column, weight=1)
        selected = tk.StringVar(value="طلای نو")
        previous_kind = ['طلای نو']
        selector = ttk.Combobox(form, textvariable=selected, values=[*kinds, *special_choices], state="readonly", justify="right")
        selector.grid(row=0, column=2, sticky="ew", padx=6, pady=1)
        ttk.Label(form, text="نوع طلا", anchor="e").grid(row=0, column=3, sticky="e")
        ttk.Label(form, text=("فروش بر اساس وزن واقعی + درصد سود؛ بدون تبدیل عیار" if direction == "out" else "تبدیل عیار فقط برای خرید دست‌دوم: وزن ÷ عیار اولیه × عیار خرید"), anchor="e").grid(
            row=0, column=0, columnspan=2, sticky="e", padx=10) 
        supplier_id = [None]
        supplier_label = tk.StringVar(value='بنکدار انتخاب نشده است')
        if direction == 'in':
            def open_supplier():
                from gold_suppliers import choose_supplier
                chosen = choose_supplier(root, ledger)
                if chosen is not None:
                    supplier_id[0] = chosen
                    supplier_label.set(next(row['name'] for row in ledger.suppliers() if row['id'] == chosen))
                    selected.set('طلای نو')
                    changed()
            supplier_bar = ttk.Frame(tab)
            supplier_bar.pack(fill='x', before=form)
            ttk.Button(supplier_bar, text='بنکداران / انتخاب پرونده خرید', command=open_supplier).pack(side='right')
            ttk.Label(supplier_bar, textvariable=supplier_label).pack(side='right', padx=10)
        fields = {}
        editing_id = None
        for index, (key, label) in enumerate([
            ("weight", "وزن (گرم)"), ("price", "قیمت لحظه‌ای هر گرم (تومان)"),
            ("making", "اجرت ساخت (درصد)"), ("selling", "اجرت فروش (درصد)"),
            ("tax", "مالیات روی اجرت‌ها (درصد)"),
            ("product_title", "نوع/عنوان کالا (مثلاً گردنبند)"), ("product_code", "کد کالا"),
            ("customer_name", "نام مشتری"), ("customer_phone", "شماره همراه مشتری"),
            ("bank_card", "شماره کارت مقصد خرید از مشتری"),
            ("purity", "عیار مبنای قیمت هر گرم"), ("purchase_purity", "عیار طلای خریداری‌شده"),
        ], start=1):
            defaults = {"making": "0", "selling": "0", "tax": "0", "purity": "750", "purchase_purity": "750"}
            variable = tk.StringVar(value=defaults.get(key, ""))
            wide = key in ('product_title', 'customer_name')
            entry = ttk.Entry(form, textvariable=variable, justify="right", width=30 if wide else 16)
            row_index, column_index = 1 + (index - 1) // 3, (4, 2, 0)[(index - 1) % 3]
            entry.grid(row=row_index, column=column_index, sticky="ew" if wide else "e", padx=4, pady=1)
            label_widget = ttk.Label(form, text=label, anchor="e")
            label_widget.grid(row=row_index, column=column_index + 1, sticky="e")
            fields[key] = (variable, entry, label_widget)
        if direction == 'out':
            linking = [False]
            def link_product(source):
                if linking[0]:
                    return
                value = fields[source][0].get().strip()
                if not value:
                    return
                kind = kinds[selected.get()]
                matches = ledger.find_products(kind=kind, **({'code': value} if source == 'product_code' else {'query': value}))
                if source == 'product_title':
                    matches = [p for p in matches if product_text(p['title']) == product_text(value)]
                if len(matches) == 1:
                    linking[0] = True
                    try:
                        target = 'product_title' if source == 'product_code' else 'product_code'
                        fields[target][0].set(matches[0]['title' if target == 'product_title' else 'code'])
                    finally:
                        linking[0] = False
            for key in ('product_code', 'product_title'):
                fields[key][0].trace_add('write', lambda *_, key=key: link_product(key))

        gold_fee_rate = tk.StringVar(value='0')
        if direction == 'in':
            fee_frame = ttk.Frame(tab)
            fee_frame.pack(fill='x')
            ttk.Label(fee_frame, text='اجرت طلایی (درصد)').pack(side='right')
            ttk.Entry(fee_frame, textvariable=gold_fee_rate, width=9, justify='right').pack(side='right')
            fee_weight = tk.StringVar()
            combined_weight = tk.StringVar()
            for label, variable in [('اجرت طلایی (گرم)', fee_weight), ('طلای موجود + اجرت طلایی (گرم؛ وزن همین ردیف)', combined_weight)]:
                ttk.Label(fee_frame, text=label).pack(side='right', padx=5)
                ttk.Entry(fee_frame, textvariable=variable, state='readonly', width=13).pack(side='right')
            def update_gold_fee(*_):
                try:
                    weight = number(fields['weight'][0].get(), 'وزن', allow_zero=True)
                    fee = weight * number(gold_fee_rate.get(), 'اجرت طلایی', allow_zero=True) / Decimal(100)
                    fee_weight.set(display(fee))
                    combined_weight.set(display(weight + fee))
                except ValueError:
                    fee_weight.set('')
                    combined_weight.set('')
            fields['weight'][0].trace_add('write', update_gold_fee)
            gold_fee_rate.trace_add('write', update_gold_fee)
            fields['making'][0].trace_add('write', lambda *_: gold_fee_rate.set(fields['making'][0].get()))
        price_display = tk.StringVar()
        ttk.Label(form, textvariable=price_display, anchor='e').grid(row=5, column=0, columnspan=6, sticky='e')
        def update_price(*_):
            try:
                value = number(fields['price'][0].get(), 'قیمت هر گرم')
                price_display.set(f"قیمت هر گرم طلای ۱۸ عیار: {value:,.0f} تومان".replace(',', '،'))
            except ValueError:
                price_display.set('')
        fields['price'][0].trace_add('write', update_price)
        def from_quote():
            from tkinter import simpledialog
            quote = simpledialog.askstring('تبدیل مظنه', 'مظنه را به تومان وارد کنید (تقسیم بر ۴٫۳۳۱۸):', parent=root)
            if quote is not None:
                try:
                    value = number(quote.replace('،', '').replace(',', ''), 'مظنه')
                    fields['price'][0].set(str(money(value / Decimal('4.3318'))))
                except ValueError as error:
                    messagebox.showerror('مظنه', str(error), parent=root)
        ttk.Button(form, text='ورود مظنه و محاسبه قیمت هر گرم', command=from_quote).grid(row=6, column=0, columnspan=6, sticky='e')
        result_text = tk.StringVar(value="برای مشاهده مبلغ نهایی، «محاسبه» را بزنید.")
        result_label = ttk.Label(tab, textvariable=result_text, anchor="e", justify="right", padding=3)
        result_label.pack(fill="x")

        def changed(_event=None):
            choice = selected.get()
            if choice in special_choices:
                selected.set(previous_kind[0])
                special_trade(special_choices[choice], direction)
                return
            previous_kind[0] = choice
            is_new = selected.get() == "طلای نو"
            if direction == 'in':
                fields['purchase_purity'][0].set('750' if is_new else '735')
            for key in ('purity', 'purchase_purity'):
                for widget in fields[key][1:]:
                    if direction == 'out':
                        widget.grid_remove()
                    else:
                        widget.grid()
            fields["weight"][2].configure(text="وزن واقعی (گرم)" if direction == 'out' else ("وزن (گرم)" if is_new else "وزن اولیه، قبل از تبدیل (گرم)"))
            fields["selling"][2].configure(text="اجرت فروش (درصد)" if is_new else "اجرت فروش وزنی (درصد)")
            for key in ("making", "selling", "tax"):
                _, entry, label_widget = fields[key]
                if (key == "making" and is_new) or (key == "selling" and direction == "out") or (key == "tax" and is_new and direction == "out"):
                    entry.grid()
                    label_widget.grid()
                else:
                    entry.grid_remove()
                    label_widget.grid_remove()
            result_text.set("برای مشاهده مبلغ نهایی، «محاسبه» را بزنید.")

        selector.bind("<<ComboboxSelected>>", changed)
        changed()
        for variable, _, _ in fields.values():
            variable.trace_add("write", lambda *_: result_text.set("مقادیر تغییر کرد؛ دوباره محاسبه کنید."))

        def values():
            rates = transaction_rates(
                direction, kinds[selected.get()], fields["making"][0].get(),
                fields["selling"][0].get(), fields["tax"][0].get(),
            )
            return (
                number(fields["weight"][0].get(), "وزن"),
                number(fields["price"][0].get(), "قیمت هر گرم"),
                *rates,
            )

        def extra_values():
            return {key: fields[key][0].get() for key in
                    ('purity', 'purchase_purity', 'product_code', 'product_title',
                     'customer_name', 'customer_phone', 'bank_card')} | attachments | ({'gold_fee_rate': gold_fee_rate.get(), 'supplier_id': supplier_id[0] if selected.get() == 'طلای نو' else None} if direction == 'in' else {})

        def calculation_options():
            return {key: fields[key][0].get() for key in ('purity', 'purchase_purity')}

        def result_description(result):
            return describe_calculation(result, direction, kinds[selected.get()])

        def show_result(result):
            result_text.set(result_description(result))

        def preview():
            try:
                show_result(calculate_transaction(direction, kinds[selected.get()], *values(), **calculation_options()))
            except ValueError as error:
                messagebox.showerror("بررسی اطلاعات", str(error), parent=root)

        def finish_edit():
            nonlocal editing_id
            editing_id = None
            form.configure(text=f"ثبت {title}")
            save_button.configure(text=f"ثبت {title}")
            cancel_button.configure(state="disabled")
            attachments.clear()
            for key in ('customer_name', 'customer_phone', 'bank_card'):
                fields[key][0].set('')
            fields["weight"][0].set("")
            fields["product_code"][0].set("")
            fields["product_title"][0].set("")

        def selected_row():
            selection = tree.selection()
            if not selection:
                raise ValueError("ابتدا یک تراکنش را از جدول انتخاب کنید.")
            return ledger.get(int(selection[0]))

        def load_edit(_event=None):
            nonlocal editing_id
            try:
                row = selected_row()
                if editing_id is not None and not messagebox.askyesno(
                    "تغییر انتخاب", "تغییرات ذخیره‌نشده فرم کنار گذاشته شود؟", parent=root
                ):
                    return
                attachments.clear()
                for key in ('customer_name', 'customer_phone', 'bank_card'):
                    fields[key][0].set(row[key] or '')
                editing_id = row["id"]
                supplier_id[0] = row['supplier_id']
                supplier_label.set(next((item['name'] for item in ledger.suppliers() if item['id'] == row['supplier_id']), 'تعیین‌نشده'))
                selected.set("طلای نو" if row["kind"] == "new" else "طلای دست‌دوم")
                changed()
                for key, column in (("weight", "weight"), ("price", "price"),
                                    ("making", "making_rate"), ("selling", "selling_rate"),
                                    ("tax", "tax_rate"), ("purity", "purity"),
                                    ("purchase_purity", "purchase_purity"),
                                    ("product_code", "product_code"), ("product_title", "product_title")):
                    fields[key][0].set(row[column] or "")
                gold_fee_rate.set(row['gold_fee_rate'] or '0')
                form.configure(text=f"ویرایش سند {row['document_no']} — {title}")
                save_button.configure(text=f"ذخیره ویرایش سند {row['document_no']}")
                cancel_button.configure(state="normal")
                result_text.set("مقادیر سند بارگذاری شد؛ پس از تغییر، «ذخیره ویرایش» را بزنید."
                                + ("\nبا تغییر وزن، قیمت یا درصدهای سند قدیمی، محاسبات با قواعد فعلی انجام می‌شود."
                                   if row["calculation_version"] == "legacy" else ""))
                fields["weight"][1].focus_set()
            except (ValueError, sqlite3.Error) as error:
                messagebox.showerror("ویرایش انجام نشد", str(error), parent=root)

        def remove_selected():
            try:
                row = selected_row()
                if not messagebox.askyesno(
                    "تأیید حذف", f"سند {row['document_no']} با مبلغ {display(Decimal(row['total']))} تومان حذف شود؟\n"
                    "موجودی و سود طلایی نیز اصلاح می‌شوند. این عملیات قابل بازگشت نیست.", parent=root
                ):
                    return
                ledger.delete(row["id"])
                if editing_id == row["id"]:
                    finish_edit()
                refresh()
                result_text.set(f"سند {row['document_no']} حذف و موجودی و سود به‌روز شد.")
            except (ValueError, sqlite3.Error) as error:
                messagebox.showerror("حذف انجام نشد", str(error), parent=root)

        def save():
            try:
                if direction == 'in' and selected.get() == 'طلای نو' and supplier_id[0] is None and editing_id is None:
                    raise ValueError('ابتدا از دکمه بنکداران، پرونده بنکدار را انتخاب کنید.')
                args = values()
                result = calculate_transaction(direction, kinds[selected.get()], *args, **calculation_options())
                if editing_id is None:
                    confirmation = f"{title} {selected.get()}\n{result_description(result)}\nثبت شود؟"
                else:
                    old = ledger.get(editing_id)
                    confirmation = (f"ویرایش سند {old['document_no']}\n{result_description(result)}\n"
                                    "شماره سند و زمان ثبت اولیه حفظ می‌شوند.\n"
                                    "در صورت تغییر ورودی‌ها، محاسبات طبق قواعد فعلی انجام می‌شود؛ "
                                    "در غیر این صورت مبلغ قبلی حفظ می‌شود.\nویرایش ذخیره شود؟")
                if not messagebox.askyesno("تأیید ثبت", confirmation, parent=root):
                    return
                if editing_id is None:
                    result = ledger.add(direction, kinds[selected.get()], *args, **extra_values())
                    finish_edit()
                    show_result(result)
                else:
                    row = ledger.update(editing_id, kinds[selected.get()], *args, **extra_values())
                    finish_edit()
                    result_text.set(f"سند {row['document_no']} ویرایش شد.\n"
                                    f"{monetary_title(direction)}: {display(Decimal(row['total']))} تومان\n"
                                    f"آخرین ویرایش: {row['updated_at_jalali']}")
                refresh()
                messagebox.showinfo("ذخیره شد", "تراکنش ذخیره و موجودی و سود به‌روز شد.", parent=root)
            except (ValueError, sqlite3.Error) as error:
                messagebox.showerror("ثبت انجام نشد", str(error), parent=root)

        attachments = {}
        def upload(key):
            from tkinter import filedialog
            from gold_customers import read_image
            path = filedialog.askopenfilename(parent=root, filetypes=[('تصویر', '*.png *.jpg *.jpeg *.webp')])
            if path:
                try:
                    attachments[key] = read_image(path)
                    messagebox.showinfo('مدرک', 'تصویر انتخاب شد؛ با ذخیره سند ثبت می‌شود.', parent=root)
                except (ValueError, OSError) as error:
                    messagebox.showerror('مدرک', str(error), parent=root)
        buttons = ttk.Frame(form)
        if direction == 'in':
            ttk.Button(buttons, text='عکس کارت ملی', command=lambda: upload('national_image')).pack(side='right')
            ttk.Button(buttons, text='عکس کارت بانکی', command=lambda: upload('bank_image')).pack(side='right')
        buttons.grid(row=8, column=0, columnspan=4, sticky="e", pady=8)
        ttk.Button(buttons, text="محاسبه", command=preview).pack(side="right", padx=5)
        save_button = ttk.Button(buttons, text=f"ثبت {title}", command=save, style="Accent.TButton")
        save_button.pack(side="right", padx=5)
        cancel_button = ttk.Button(buttons, text="لغو ویرایش / ثبت جدید", state="disabled", command=finish_edit)
        cancel_button.pack(side="right", padx=5)
        table_frame = ttk.Frame(panes, height=220)
        actions = ttk.Frame(table_frame)
        actions.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, 4))
        ttk.Button(actions, text="ویرایش سند انتخاب‌شده", command=load_edit).pack(side="right", padx=5)
        ttk.Button(actions, text="حذف سند انتخاب‌شده", command=remove_selected).pack(side="right", padx=5)
        ttk.Label(actions, text="ابتدا یک ردیف جدول را انتخاب کنید؛ ثبت زمان با ساعت داخلی قفل‌شده است.",
                  anchor="e").pack(side="right", padx=5)
        panes.add(table_frame, weight=1)
        # Keep both panes visible even on shorter displays.
        def fit_panes(event=None):
            height = panes.winfo_height()
            if height < 80:
                return
            minimum = min(145, max(30, height // 3))
            maximum = max(minimum, height - minimum - 8)
            if not getattr(panes, '_sash_initialized', False):
                position = max(minimum, min(maximum, int(height * 0.48)))
                panes._sash_initialized = True
            else:
                position = max(minimum, min(maximum, panes.sashpos(0)))
            panes.sashpos(0, position)
        panes.bind('<Configure>', fit_panes)
        panes.bind('<Map>', lambda event: panes.after_idle(fit_panes))
        panes.bind('<ButtonRelease-1>', lambda event: panes.after_idle(fit_panes))
        columns = ("document", "date", "updated", "total", "tax_amount", "selling_amount", "making_amount", "base_amount",
                   "tax_rate", "selling", "making", "price", "profit",
                   "billed_weight", "stock_weight", "weight", "kind", "version",
                   "product_title", "product_code", "purity", "purchase_purity", "gold_fee_rate", "gold_fee_weight", "weight_with_fee")
        tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse",
                            displaycolumns=tuple(column for column in columns
                                                 if direction != 'out' or column != 'purchase_purity'))
        headings = ("شماره سند", "تاریخ و ساعت ثبت (شمسی)", "آخرین ویرایش (شمسی)",
                    f"{monetary_title(direction)} (تومان)", "مالیات ارزش افزوده (تومان)",
                    "اجرت فروش (تومان)", "اجرت ساخت (تومان)", "قیمت طلای خام (تومان)",
                    "مالیات ٪", "اجرت فروش ٪", "اجرت ساخت ٪", "قیمت هر گرم (تومان)",
                    "سود خالص FIFO (گرم)", "فروش با اجرت (گرم)", "تغییر موجودی (گرم)", "وزن اولیه (گرم)",
                    "نوع طلا", "روش محاسبه", "نوع/عنوان کالا", "کد کالا", "عیار اولیه", "عیار خرید")
        widths = (95, 210, 210, 300, 210, 170, 170, 180, 80, 95, 95, 170, 130, 145, 145, 125, 90, 95, 170, 110, 100, 100)
        headings += ('اجرت طلایی ٪', 'اجرت طلایی (گرم)', 'وزن محصول + اجرت طلایی (گرم)')
        widths += (110, 160, 240)
        for column, heading, width in zip(columns, headings, widths):
            tree.heading(column, text=heading)
            tree.column(column, width=width, minwidth=55, anchor="e")
        vertical = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        horizontal = ttk.Scrollbar(table_frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(1, weight=1)
        tree.grid(row=1, column=0, sticky="nsew")
        vertical.grid(row=1, column=1, sticky="ns")
        horizontal.grid(row=2, column=0, sticky="ew")
        # برچسب‌های بالای جدول هنگام دوبارکلیک نباید سند قبلی را وارد ویرایش کنند.
        def double_click(event):
            if tree.identify_region(event.x, event.y) == "cell":
                item = tree.identify_row(event.y)
                if item:
                    tree.selection_set(item)
                    load_edit()
        def open_table():
            window = tk.Toplevel(root)
            window.title(f"جدول تراکنش‌های {title}")
            window.geometry("1200x600")
            window.minsize(700, 350)
            full = ttk.Treeview(window, columns=columns, show="headings", selectmode="browse")
            for column, heading, width in zip(columns, headings, widths):
                full.heading(column, text=heading)
                full.column(column, width=width, minwidth=55, anchor="e")
            for item in tree.get_children():
                full.insert("", "end", iid=item, values=tree.item(item, "values"))
            sy = ttk.Scrollbar(window, orient="vertical", command=full.yview)
            sx = ttk.Scrollbar(window, orient="horizontal", command=full.xview)
            full.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
            window.rowconfigure(0, weight=1)
            window.columnconfigure(0, weight=1)
            full.grid(row=0, column=0, sticky="nsew")
            sy.grid(row=0, column=1, sticky="ns")
            sx.grid(row=1, column=0, sticky="ew")
            def edit_full(event):
                item = full.identify_row(event.y)
                if item and full.identify_region(event.x, event.y) == "cell":
                    tree.selection_set(item)
                    window.destroy()
                    load_edit()
            full.bind("<Double-1>", edit_full)
        ttk.Button(actions, text="باز کردن جدول در پنجره بزرگ", command=open_table).pack(side="right", padx=5)
        tree.bind("<Double-1>", double_click)
        views.append((direction, tree))
        return page

    incoming_tab = build_tab("in", "ورود")
    outgoing_tab = build_tab("out", "خروج")
    features.build_search(notebook)

    def report_context():
        active = notebook.select()
        if active == str(incoming_tab):
            return ledger.rows("in"), "گزارش اسناد ورود", "همه اسناد ورود، بدون محدودیت تاریخ"
        if active == str(outgoing_tab):
            return ledger.rows("out"), "گزارش اسناد خروج", "همه اسناد خروج، بدون محدودیت تاریخ"
        return ledger.search(**features.active_filters), "گزارش نتایج جستجو", features.filter_description()

    def locate_document(row):
        notebook.select(incoming_tab if row["direction"] == "in" else outgoing_tab)
        tree = next(tree for direction, tree in views if direction == row["direction"])
        tree.selection_set(str(row["id"]))
        tree.focus(str(row["id"]))
        tree.see(str(row["id"]))

    features.report_context = report_context
    features.locate_document = locate_document
    root.bind("<F5>", lambda _event: refresh())
    refresh()
    ttk.Label(root, text="سود طلایی یک مانده حسابداری جداست، نه طلای فیزیکی قابل‌فروش؛ فقط پس از ثبت خروج اضافه می‌شود.\n"
              "دارایی حسابداری = بهای موجودی باقی‌مانده + فروش بدون مالیات؛ سود خالص = فروش منهای هزینه FIFO همان کالا.\n"
              "واحد مبالغ تومان است؛ تبدیل به ریال انجام نمی‌شود. جزئیات ناموجود سوابق قدیمی: —",
              anchor="e", justify="right", padding=10).pack(fill="x")

    def close():
        try:
            features.shutdown()
        except sqlite3.Error as error:
            messagebox.showerror("خطای ذخیره ساعت", str(error), parent=root)
            return False
        ledger.close()
        root.destroy()
        return True

    root.protocol("WM_DELETE_WINDOW", close)
    if license_setup is not None:
        license_setup(root, close)
    root.deiconify()
    root.mainloop()


if __name__ == "__main__":
    main()
