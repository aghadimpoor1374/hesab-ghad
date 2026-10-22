"""جستجو، ساعت داخلی و کلید مدیریت محلی حساب قدیم؛ مستقل از رابط گرافیکی."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import hmac
import re
import secrets
import sqlite3
import time

from gold_accounting import TRANSLATION, jalali_timestamp, number, product_text

APP_ZONE = timezone(timedelta(hours=3, minutes=30))


def parse_jalali_date(value):
    text = str(value).translate(TRANSLATION).strip().replace("-", "/")
    match = re.fullmatch(r"([0-9]{4})/([0-9]{1,2})/([0-9]{1,2})", text)
    if not match:
        raise ValueError("تاریخ شمسی را مانند ۱۴۰۵/۰۱/۰۱ وارد کنید.")
    jy, jm, jd = map(int, match.groups())
    if not 1200 <= jy <= 1600 or not 1 <= jm <= 12 or not 1 <= jd <= 31:
        raise ValueError("تاریخ شمسی نامعتبر است؛ سال باید بین ۱۲۰۰ تا ۱۶۰۰ باشد.")
    # نوروز را با تبدیل معکوسِ همان الگوریتم سوابق پیدا می‌کنیم تا دو تقویم ناسازگار نشوند.
    start = next((datetime(jy + 621, 3, day) for day in range(19, 23)
                  if jalali_timestamp(datetime(jy + 621, 3, day)).startswith(f"{jy:04d}/01/01")), None)
    if start is None:
        raise ValueError("تاریخ خارج از محدوده پشتیبانی است.")
    offset = (jm - 1) * 31 if jm <= 6 else 186 + (jm - 7) * 30
    result = start + timedelta(days=offset + jd - 1)
    if jalali_timestamp(result)[:10] != f"{jy:04d}/{jm:02d}/{jd:02d}":
        raise ValueError("این روز در تقویم شمسی وجود ندارد.")
    return result.date()


def parse_clock(value, end=False):
    text = str(value).translate(TRANSLATION).strip()
    if not re.fullmatch(r"[0-9]{1,2}:[0-9]{2}(:[0-9]{2})?", text):
        raise ValueError("ساعت را به شکل ۰۹:۳۰ یا ۰۹:۳۰:۰۰ وارد کنید.")
    parts = list(map(int, text.split(":")))
    hour, minute = parts[:2]
    second = parts[2] if len(parts) == 3 else (59 if end else 0)
    if hour > 23 or minute > 59 or second > 59:
        raise ValueError("ساعت باید بین ۰۰:۰۰:۰۰ تا ۲۳:۵۹:۵۹ باشد.")
    return hour * 3600 + minute * 60 + second


def jalali_moment(date, clock):
    day = parse_jalali_date(date)
    seconds = parse_clock(clock)
    return datetime.combine(day, datetime.min.time(), APP_ZONE) + timedelta(seconds=seconds)


def validate_search(filters):
    allowed = {"date", "time_from", "time_to", "weight_min", "weight_max", "document_no", "direction", "kind", "product_code", "product_title"}
    if set(filters) - allowed:
        raise ValueError("فیلتر ناشناخته است.")
    result = {}
    for key, value in filters.items():
        if value is None or str(value).strip() == "":
            continue
        if key in ('product_code', 'product_title'):
            result[key] = product_text(value)
        elif key == "date":
            result[key] = jalali_timestamp(parse_jalali_date(value))[:10]
        elif key in ("time_from", "time_to"):
            result[key] = parse_clock(value, end=key == "time_to")
        elif key in ("weight_min", "weight_max"):
            result[key] = number(value, "وزن جستجو", allow_zero=True)
        elif key == "document_no":
            text = str(value).translate(TRANSLATION).strip()
            if not re.fullmatch(r"[0-9]{1,18}", text) or int(text) < 1:
                raise ValueError("شماره سند باید یک عدد صحیح مثبت باشد.")
            result[key] = int(text)
        elif key == "direction":
            if value not in ("in", "out"):
                raise ValueError("جهت تراکنش نامعتبر است.")
            result[key] = value
        elif key == "kind":
            if value not in ("new", "used"):
                raise ValueError("نوع طلا نامعتبر است.")
            result[key] = value
    for low, high in (("time_from", "time_to"), ("weight_min", "weight_max")):
        if low in result and high in result and result[low] > result[high]:
            raise ValueError("ابتدای بازه نباید از انتهای آن بیشتر باشد.")
    return result


def search_transactions(ledger, **filters):
    """فیلترها با AND ترکیب می‌شوند؛ وزن، وزن اولیه و بازه‌ها شامل دو سرند.

    بدون فیلتر تاریخ، همه روزها بررسی می‌شوند. پیش‌فرض امروز در رابط اعمال می‌شود.
    ساعت ناموجود سوابق قدیمی با ساعت فرضی جایگزین نمی‌شود.
    """
    wanted = validate_search(filters)
    clauses, parameters = [], []
    for key in ("document_no", "direction", "kind"):
        if key in wanted:
            clauses.append(f"{key} = ?")
            parameters.append(wanted[key])
    query = "SELECT * FROM transactions"
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY id DESC"
    result = []
    for row in ledger.connection.execute(query, parameters):
        if 'product_code' in wanted and product_text(row['product_code'] or '') != wanted['product_code']:
            continue
        if 'product_title' in wanted and wanted['product_title'] not in product_text(row['product_title'] or ''):
            continue
        if "date" in wanted or "time_from" in wanted or "time_to" in wanted:
            try:
                stamp = row["created_at_jalali"] or jalali_timestamp(row["created_at"])
                date, *clock = stamp.split()
                if "date" in wanted and date != wanted["date"]:
                    continue
                if "time_from" in wanted or "time_to" in wanted:
                    if not clock:
                        continue
                    seconds = parse_clock(clock[0])
                    if seconds < wanted.get("time_from", 0) or seconds > wanted.get("time_to", 86399):
                        continue
            except (ValueError, TypeError):
                continue
        weight = Decimal(row["weight"])
        if "weight_min" in wanted and weight < wanted["weight_min"]:
            continue
        if "weight_max" in wanted and weight > wanted["weight_max"]:
            continue
        result.append(row)
    return result


class ApplicationClock:
    """ساعت برنامه، نه ساعت سیستم‌عامل. کلید مدیریت با PBKDF2 ذخیره می‌شود.

    در هر اجرا از monotonic استفاده می‌شود. بین اجراها گذر زمان سیستم محاسبه
    می‌شود و آخرین زمان ذخیره‌شده مانع عقب‌رفت تصادفی می‌شود. این راهکار جای
    ساعت امن سخت‌افزاری/سرور لایسنس و محافظت در برابر مالک فایل SQLite نیست.
    """
    ROUNDS = 240_000

    def __init__(self, connection, wall_time=None, monotonic=None):
        self.connection = connection
        self.wall_time = wall_time or time.time
        self.monotonic = monotonic or time.monotonic
        with connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS application_settings (
                id INTEGER PRIMARY KEY CHECK(id = 1), clock_base REAL NOT NULL,
                wall_base REAL NOT NULL, last_seen REAL NOT NULL,
                license_salt TEXT NOT NULL, license_hash TEXT NOT NULL,
                failed_attempts INTEGER NOT NULL DEFAULT 0,
                locked_until REAL NOT NULL DEFAULT 0)""")
            connection.execute("""CREATE TABLE IF NOT EXISTS administration_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL,
                recorded_at_utc TEXT NOT NULL, old_value TEXT, new_value TEXT)""")
        self._base = self._mono = None
        self._load()

    @property
    def initialized(self):
        return self._base is not None

    def _load(self):
        row = self.connection.execute("SELECT * FROM application_settings WHERE id = 1").fetchone()
        if row:
            self._base = max(row["last_seen"], row["clock_base"] + max(0, self.wall_time() - row["wall_base"]))
            self._mono = self.monotonic()

    @staticmethod
    def generate_license():
        return "HG-" + "-".join(secrets.token_hex(4).upper() for _ in range(4))

    @classmethod
    def _hash(cls, key, salt):
        return hashlib.pbkdf2_hmac("sha256", key.strip().encode("utf-8"), bytes.fromhex(salt), cls.ROUNDS).hex()

    def _audit(self, action, old, new):
        self.connection.execute("""INSERT INTO administration_audit
            (action, recorded_at_utc, old_value, new_value) VALUES (?, ?, ?, ?)""",
            (action, datetime.now(timezone.utc).isoformat(timespec="seconds"), old, new))

    def initialize(self, date, clock, license_key=None):
        moment = jalali_moment(date, clock)
        key = license_key or self.generate_license()
        if len(key.strip()) < 24:
            raise ValueError("کلید مدیریت باید دست‌کم ۲۴ نویسه داشته باشد.")
        salt = secrets.token_hex(16)
        digest = self._hash(key, salt)
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            if self.connection.execute("SELECT 1 FROM application_settings WHERE id = 1").fetchone():
                raise ValueError("تنظیم اولیه قبلاً انجام شده؛ تغییر ساعت فقط با کلید مدیریت مجاز است.")
            self.connection.execute("""INSERT INTO application_settings
                (id, clock_base, wall_base, last_seen, license_salt, license_hash)
                VALUES (1, ?, ?, ?, ?, ?)""",
                (moment.timestamp(), self.wall_time(), moment.timestamp(), salt, digest))
            self._audit("initial_setup", None, jalali_timestamp(moment))
        self._load()
        return key

    def now(self):
        if not self.initialized:
            raise ValueError("ابتدا تاریخ و ساعت برنامه را تنظیم کنید.")
        elapsed = max(0, self.monotonic() - self._mono)
        return datetime.fromtimestamp(self._base + elapsed, APP_ZONE)

    def timestamps(self):
        moment = self.now()
        return moment.isoformat(sep=" ", timespec="seconds"), jalali_timestamp(moment)

    def checkpoint(self):
        if not self.initialized:
            return
        moment = self.now().timestamp()
        with self.connection:
            self.connection.execute("""UPDATE application_settings SET
                clock_base = ?, wall_base = ?, last_seen = ? WHERE id = 1""",
                (moment, self.wall_time(), moment))

    def authorize(self, key):
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            row = self.connection.execute("SELECT * FROM application_settings WHERE id = 1").fetchone()
            if row is None:
                raise ValueError("تنظیم اولیه انجام نشده است.")
            now = max(self.wall_time(), self.now().timestamp())
            if now < row["locked_until"]:
                raise ValueError("ورود مدیریت موقتاً قفل است؛ یک دقیقه بعد دوباره تلاش کنید.")
            valid = hmac.compare_digest(self._hash(str(key), row["license_salt"]), row["license_hash"])
            attempts = 0 if valid else row["failed_attempts"] + 1
            locked_until = now + 60 if attempts >= 5 else 0
            self.connection.execute("""UPDATE application_settings SET failed_attempts = ?,
                locked_until = ? WHERE id = 1""", (0 if attempts >= 5 else attempts, locked_until))
            if not valid:
                self._audit("authorization_failed", None, None)
        # خطا بیرون از تراکنش است تا شمارنده تلاش ناموفق rollback نشود.
        if not valid:
            raise ValueError("کلید مدیریت معتبر نیست.")
        return True

    def change_time(self, date, clock, key):
        moment = jalali_moment(date, clock)
        self.authorize(key)
        old = jalali_timestamp(self.now())
        with self.connection:
            self.connection.execute("""UPDATE application_settings SET
                clock_base = ?, wall_base = ?, last_seen = ? WHERE id = 1""",
                (moment.timestamp(), self.wall_time(), moment.timestamp()))
            self._audit("clock_changed", old, jalali_timestamp(moment))
        self._load()

    def backup(self, path, key):
        self.authorize(key)
        self.checkpoint()
        # فقط رابط اجازه انتخاب مسیری متفاوت با پایگاه داده در حال استفاده را می‌دهد.
        current = self.connection.execute("PRAGMA database_list").fetchone()[2]
        from pathlib import Path
        if current and Path(current).resolve() == Path(path).resolve():
            raise ValueError("مسیر پشتیبان باید با پایگاه داده اصلی متفاوت باشد.")
        with sqlite3.connect(str(path)) as target:
            self.connection.backup(target)
        with self.connection:
            self._audit("backup_created", None, str(path))
