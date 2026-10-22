import sqlite3
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal as D
from unittest.mock import patch
from pathlib import Path

from gold_accounting import (
    Ledger, calculate, calculate_transaction, describe_calculation, display, monetary_title,
    number, transaction_rates, current_timestamps, jalali_timestamp,
)


class GoldTests(unittest.TestCase):
    def test_formula(self):
        result = calculate(D('10'), D('6000000'), D('10'), D('7'))
        self.assertEqual(result.base, D('60000000'))
        self.assertEqual(result.making, D('6000000'))
        self.assertEqual(result.selling, D('4620000'))
        self.assertEqual(result.total, D('70620000'))

    def test_tax_only_on_fees(self):
        result = calculate(D('10'), D('6000000'), D('10'), D('7'), D('10'))
        self.assertEqual(result.tax, D('1062000'))
        self.assertEqual(result.total, D('71682000'))
        no_fees = calculate(D('10'), D('6000000'), tax_rate=D('10'))
        self.assertEqual(no_fees.tax, 0)
        self.assertEqual(no_fees.total, D('60000000'))

    def test_new_entry_has_making_only(self):
        ledger = Ledger(':memory:')
        self.addCleanup(ledger.close)
        # مقادیر پنهان‌شده در ورود حتی در لایه ثبت هم نباید اعمال شوند.
        result = ledger.add('in', 'new', '10', '100', '10', 'bad', 'bad')
        self.assertEqual(result.total, D('1100'))
        self.assertEqual(result.selling, 0)
        self.assertEqual(result.tax, 0)
        row = ledger.rows('in')[0]
        self.assertEqual(row['selling_rate'], '0')
        self.assertEqual(row['tax_rate'], '0')
        self.assertEqual(row['tax_amount'], '0')
        self.assertEqual(transaction_rates('in', 'new', '10', 'bad', 'bad'),
                         (D('10'), D(0), D(0)))

    def test_sale_tax_saved_and_validated(self):
        ledger = Ledger(':memory:')
        self.addCleanup(ledger.close)
        ledger.add('in', 'new', '10', '100')
        result = ledger.add('out', 'new', '2', '100', '10', '5', '9')
        self.assertEqual(result.making, D('20'))
        self.assertEqual(result.selling, D('11'))
        self.assertEqual(result.tax, D('2.79'))
        self.assertEqual(result.total, D('233.79'))
        row = ledger.rows('out')[0]
        self.assertEqual(row['tax_rate'], '9')
        self.assertEqual(D(row['tax_amount']), D('2.79'))
        with self.assertRaises(ValueError):
            ledger.add('out', 'new', '1', '100', '10', '5', '-9')
        self.assertEqual(len(ledger.rows('out')), 1)

    def test_gold_assets_definition_and_separate_stock(self):
        ledger = Ledger(':memory:')
        self.addCleanup(ledger.close)
        ledger.add('in', 'new', '10', '100')
        ledger.add('in', 'used', '5', '100')
        ledger.add('out', 'new', '2', '100', '10', '5', '9')
        ledger.add('out', 'used', '1', '100')
        self.assertEqual(ledger.balances(), {'new': D('8'), 'used': D('4')})
        self.assertEqual(ledger.gold_assets(), {
            'stock': D('12'), 'sold': D('3'), 'profit': D('0'),
            'inventory_total': D('12'), 'billed_sold': D('3'), 'total': D('15')})

    def test_migrate_original_database_without_recalculating(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'old.sqlite3'
            with sqlite3.connect(path) as connection:
                connection.execute('''CREATE TABLE transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
                    direction TEXT NOT NULL, kind TEXT NOT NULL, weight TEXT NOT NULL,
                    price TEXT NOT NULL, making_rate TEXT NOT NULL,
                    selling_rate TEXT NOT NULL, total TEXT NOT NULL)''')
                connection.execute('''INSERT INTO transactions
                    (created_at, direction, kind, weight, price, making_rate, selling_rate, total)
                    VALUES ('2026-01-01', 'in', 'new', '10', '100', '10', '7', '1177.00')''')
            ledger = Ledger(path)
            try:
                row = ledger.rows('in')[0]
                self.assertEqual(row['id'], 1)
                self.assertEqual(row['total'], '1177.00')
                self.assertEqual(row['selling_rate'], '7')
                self.assertEqual(row['tax_rate'], '0')
                self.assertEqual(row['tax_amount'], '0')
                for key in ('base_amount', 'making_amount', 'selling_amount'):
                    self.assertIsNone(row[key])
                ledger.add('out', 'new', '1', '100', '10', '5', '9')
            finally:
                ledger.close()
            # اجرای دوباره مهاجرت باید بی‌خطر و اطلاعات مالیات ماندگار باشد.
            reopened = Ledger(path)
            try:
                self.assertEqual(len(reopened.rows('in')), 1)
                self.assertEqual(reopened.rows('out')[0]['tax_rate'], '9')
                self.assertEqual(reopened.balances()['new'], D('9'))
            finally:
                reopened.close()

    def test_new_entry_four_percent_breakdown_and_title(self):
        result = calculate_transaction('in', 'new', '۱۰', '۶۰۰۰۰۰۰', '۴', 'bad', 'bad')
        self.assertEqual(result.base, D('60000000'))
        self.assertEqual(result.making, D('2400000'))
        self.assertEqual(result.total, D('62400000'))
        text = describe_calculation(result, 'in', 'new')
        self.assertIn('قیمت طلای خام: 60,000,000 تومان', text)
        self.assertIn('اجرت ساخت: 2,400,000 تومان', text)
        self.assertIn('قیمت کل: 62,400,000 تومان', text)
        self.assertIn('قیمت ریالی ورود: 62,400,000 تومان', text)
        self.assertNotIn('اجرت فروش', text)
        self.assertNotIn('مالیات', text)
        self.assertEqual(monetary_title('in'), 'قیمت ریالی ورود')

    def test_new_sale_four_percent_sequence_and_title(self):
        result = calculate_transaction('out', 'new', '10', '6000000', '4', '7', '10')
        self.assertEqual(result.base, D('60000000'))
        self.assertEqual(result.making, D('2400000'))
        # اجرت فروش روی طلای خام + اجرت ساخت؛ مالیات فقط روی مجموع اجرت‌ها.
        self.assertEqual(result.selling, D('4368000'))
        self.assertEqual(result.tax, D('676800'))
        self.assertEqual(result.total, D('67444800'))
        text = describe_calculation(result, 'out', 'new')
        self.assertIn('قیمت اجرت فروش: 4,368,000 تومان', text)
        self.assertIn('مالیات بر ارزش افزوده اجرت‌ها: 676,800 تومان', text)
        self.assertIn('قیمت کل با احتساب مالیات بر ارزش افزوده: 67,444,800 تومان', text)
        self.assertIn('قیمت ریالی طلای فروخته‌شده: 67,444,800 تومان', text)
        self.assertEqual(monetary_title('out'), 'قیمت ریالی طلای فروخته‌شده')

    def test_used_description_preserves_weight_and_profit_details(self):
        result = calculate_transaction('out', 'used', '10', '100', selling_rate='5')
        text = describe_calculation(result, 'out', 'used')
        self.assertIn('وزن اولیه: 10 گرم', text)
        self.assertNotIn('تبدیل عیار', text)
        self.assertIn('فروش با اجرت: 10.5 گرم', text)
        self.assertIn('سود طلایی این فروش: 0.5 گرم', text)
        self.assertIn('قیمت ریالی طلای فروخته‌شده: 1,050 تومان', text)
        self.assertNotIn('مالیات', text)

    def test_price_components_persist_without_early_rounding(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'prices.sqlite3'
            first = Ledger(path)
            try:
                first.add('in', 'new', '10', '100')
                result = first.add('out', 'new', '.12345678', '12345.6789', '4', '7', '10')
                row = first.rows('out')[0]
                for key, amount in (('base_amount', result.base), ('making_amount', result.making),
                                    ('selling_amount', result.selling), ('tax_amount', result.tax),
                                    ('total', result.total)):
                    self.assertEqual(D(row[key]), amount)
                self.assertLess(result.making.as_tuple().exponent, -2)
                expected = dict(row)
            finally:
                first.close()
            reopened = Ledger(path)
            try:
                self.assertEqual(dict(reopened.rows('out')[0]), expected)
            finally:
                reopened.close()

    def test_upgrade_v3_preserves_existing_price_without_reconstruction(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'v3.sqlite3'
            with sqlite3.connect(path) as connection:
                connection.execute('''CREATE TABLE transactions (
                    id INTEGER PRIMARY KEY, created_at TEXT, direction TEXT, kind TEXT,
                    weight TEXT, price TEXT, making_rate TEXT, selling_rate TEXT, total TEXT,
                    tax_rate TEXT, tax_amount TEXT, stock_weight TEXT, billed_weight TEXT,
                    gold_profit TEXT, calculation_version TEXT)''')
                connection.execute('''INSERT INTO transactions VALUES
                    (1, '2026-01-01', 'in', 'new', '10', '100', '4', '0', '1040.00',
                     '0', '0', '10', '0', '0', '3')''')
            for _ in range(2):
                ledger = Ledger(path)
                try:
                    row = ledger.rows('in')[0]
                    self.assertEqual(row['total'], '1040.00')
                    self.assertEqual(row['stock_weight'], '10')
                    self.assertEqual(row['calculation_version'], '3')
                    for key in ('base_amount', 'making_amount', 'selling_amount'):
                        self.assertIsNone(row[key])
                    self.assertEqual(ledger.balances()['new'], D('10'))
                finally:
                    ledger.close()

    def test_persian_numbers(self):
        self.assertEqual(number('۱۲٬۳۴۵٫۶۷', 'عدد'), D('12345.67'))
        self.assertEqual(number('١٢.٥', 'عدد'), D('12.5'))

    def test_invalid_numbers(self):
        for text in ('', '-1', 'NaN', 'Infinity', '0', 'abc'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                number(text, 'عدد')
        self.assertEqual(number('0', 'اجرت', True), D(0))

    def test_ledger_and_insufficient_stock(self):
        ledger = Ledger(':memory:')
        self.addCleanup(ledger.close)
        ledger.add('in', 'new', '10', '100', '10', '7')
        ledger.add('in', 'used', '5', '100', '99', '99')
        ledger.add('out', 'new', '2.5', '120', '10', '7')
        self.assertEqual(ledger.balances(), {'new': D('7.5'), 'used': D('5')})
        self.assertEqual(D(ledger.rows('in')[0]['total']), D('490'))
        with self.assertRaises(ValueError):
            ledger.add('out', 'used', '6', '100')
        self.assertEqual(len(ledger.rows('out')), 1)
        ledger.add('out', 'used', '5', '100')
        self.assertEqual(ledger.balances()['used'], 0)

    def test_decimal_stock(self):
        ledger = Ledger(':memory:')
        self.addCleanup(ledger.close)
        ledger.add('in', 'new', '.1', '1')
        ledger.add('in', 'new', '.2', '1')
        ledger.add('out', 'new', '.3', '1')
        self.assertEqual(ledger.balances()['new'], 0)

    def test_used_example_and_no_double_counting(self):
        ledger = Ledger(':memory:')
        self.addCleanup(ledger.close)
        purchase = ledger.add('in', 'used', '۱۰', '100', 'bad', 'bad', 'bad')
        self.assertEqual(purchase.original_weight, D('10'))
        self.assertEqual(purchase.stock_weight, D('10'))
        self.assertEqual(purchase.total, D('980'))
        self.assertEqual(purchase.gold_profit, 0)
        self.assertEqual(ledger.balances()['used'], D('10'))
        self.assertEqual(ledger.gold_assets()['profit'], 0)
        # مبنای خروج هم وزن اولیه است، نه وزن تبدیل‌شده یا وزن با اجرت.
        preview = calculate_transaction('out', 'used', '10', '100', 'bad', '۵', 'bad')
        sale = ledger.add('out', 'used', '10', '100', 'bad', '۵', 'bad')
        self.assertEqual(preview, sale)
        self.assertEqual(sale.original_weight, D('10'))
        self.assertEqual(sale.stock_weight, D('10'))
        self.assertEqual(sale.billed_weight, D('10.5'))
        self.assertEqual(sale.gold_profit, D('.5'))
        self.assertEqual(sale.total, D('1050'))
        self.assertEqual(sale.making, 0)
        self.assertEqual(sale.tax, 0)
        self.assertEqual(ledger.balances()['used'], 0)
        self.assertEqual(ledger.gold_assets(), {
            'stock': D(0), 'sold': D('10'), 'profit': D('.5'),
            'inventory_total': D('.5'), 'billed_sold': D('10.5'), 'total': D('10.5')})
        row = ledger.rows('out')[0]
        self.assertEqual(D(row['weight']), D('10'))
        self.assertEqual(D(row['stock_weight']), D('10'))
        self.assertEqual(D(row['billed_weight']), D('10.5'))
        self.assertEqual(D(row['gold_profit']), D('.5'))
        self.assertEqual(row['calculation_version'], '6')

    def test_used_partial_sales_accumulate_profit(self):
        ledger = Ledger(':memory:')
        self.addCleanup(ledger.close)
        ledger.add('in', 'used', '10', '100')
        first = ledger.add('out', 'used', '4', '100', selling_rate='5')
        self.assertEqual(first.gold_profit, D('.2'))
        self.assertEqual(ledger.balances()['used'], D('6'))
        self.assertEqual(ledger.gold_assets()['inventory_total'], D('6.2'))
        second = ledger.add('out', 'used', '6', '100', selling_rate='10')
        self.assertEqual(second.gold_profit, D('.6'))
        self.assertEqual(ledger.balances()['used'], 0)
        self.assertEqual(ledger.gold_assets()['profit'], D('.8'))
        self.assertEqual(ledger.gold_assets()['total'], D('10.8'))
        self.assertEqual(ledger.gold_assets()['billed_sold'], D('10.8'))

    def test_used_profit_is_not_sellable_stock_and_failures_are_atomic(self):
        ledger = Ledger(':memory:')
        self.addCleanup(ledger.close)
        ledger.add('in', 'used', '10', '100')
        ledger.add('in', 'new', '100', '100')
        before = ledger.gold_assets()
        with self.assertRaises(ValueError):
            ledger.add('out', 'used', '10.00000001', '100', selling_rate='5')
        self.assertEqual(ledger.gold_assets(), before)
        self.assertEqual(len(ledger.rows('out')), 0)
        ledger.add('out', 'used', '10', '100', selling_rate='5')
        before = ledger.gold_assets()
        with self.assertRaises(ValueError):
            ledger.add('out', 'used', '.1', '100', selling_rate='5')
        self.assertEqual(ledger.gold_assets(), before)
        self.assertEqual(ledger.balances(), {'new': D('100'), 'used': D(0)})
        self.assertEqual(len(ledger.rows('out')), 1)

    def test_used_zero_fee_and_decimal_precision(self):
        ledger = Ledger(':memory:')
        self.addCleanup(ledger.close)
        ledger.add('in', 'used', '.1', '100')
        ledger.add('in', 'used', '.2', '100')
        sale = ledger.add('out', 'used', '.3', '100')
        self.assertEqual(sale.stock_weight, D('.3'))
        self.assertEqual(sale.billed_weight, D('.3'))
        self.assertEqual(sale.gold_profit, D('0'))
        self.assertEqual(ledger.balances()['used'], 0)
        smallest = ledger.add('in', 'used', '.00000001', '100')
        self.assertEqual(smallest.stock_weight, D('.00000001'))
        self.assertEqual(display(smallest.stock_weight), '0.00000001')
        ledger.add('out', 'used', '.00000001', '100')
        self.assertEqual(ledger.balances()['used'], 0)
        self.assertEqual(display(D('1000')), '1,000')
        self.assertEqual(display(D('0.00')), '0')

    def test_used_negative_fee_rejected_without_mutation(self):
        ledger = Ledger(':memory:')
        self.addCleanup(ledger.close)
        ledger.add('in', 'used', '10', '100')
        before = ledger.gold_assets()
        for rate in ('-1', 'NaN', 'bad'):
            with self.subTest(rate=rate), self.assertRaises(ValueError):
                ledger.add('out', 'used', '1', '100', selling_rate=rate)
        self.assertEqual(ledger.gold_assets(), before)
        self.assertEqual(len(ledger.rows('out')), 0)

    def test_used_weights_and_profit_persist(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'used.sqlite3'
            first = Ledger(path)
            try:
                first.add('in', 'used', '10', '100')
                first.add('out', 'used', '4', '120', selling_rate='5')
                expected_assets = first.gold_assets()
                expected_rows = [dict(row) for row in first.rows('out')]
            finally:
                first.close()
            for _ in range(2):
                reopened = Ledger(path)
                try:
                    self.assertEqual(reopened.gold_assets(), expected_assets)
                    self.assertEqual([dict(row) for row in reopened.rows('out')], expected_rows)
                    self.assertEqual(reopened.balances()['used'], D('6'))
                    self.assertEqual(reopened.gold_assets()['profit'], D('.2'))
                finally:
                    reopened.close()

    def test_migrate_used_legacy_preserves_weights_amounts_and_tax(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'legacy_used.sqlite3'
            with sqlite3.connect(path) as connection:
                connection.execute('''CREATE TABLE transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
                    direction TEXT NOT NULL, kind TEXT NOT NULL, weight TEXT NOT NULL,
                    price TEXT NOT NULL, making_rate TEXT NOT NULL,
                    selling_rate TEXT NOT NULL, total TEXT NOT NULL,
                    tax_rate TEXT NOT NULL, tax_amount TEXT NOT NULL)''')
                connection.executemany('''INSERT INTO transactions
                    (created_at, direction, kind, weight, price, making_rate, selling_rate,
                     total, tax_rate, tax_amount) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', [
                    ('2026-01-01', 'in', 'used', '10', '100', '0', '0', '1000', '0', '0'),
                    ('2026-01-02', 'out', 'used', '2', '100', '0', '0', '200', '0', '0'),
                    ('2026-01-03', 'in', 'new', '1', '100', '10', '0', '110', '0', '0'),
                    ('2026-01-04', 'out', 'new', '1', '100', '10', '5', '116.90', '9', '1.4'),
                ])
            first = Ledger(path)
            try:
                self.assertEqual(first.balances(), {'new': D(0), 'used': D('8')})
                self.assertEqual(first.gold_assets()['profit'], 0)
                self.assertEqual(first.gold_assets()['total'], D('11'))
                old_sale = first.rows('out')[1]
                self.assertEqual(old_sale['calculation_version'], 'legacy')
                self.assertEqual(old_sale['stock_weight'], '2')
                self.assertEqual(old_sale['billed_weight'], '2')
                self.assertEqual(old_sale['total'], '200')
                old_tax_sale = first.rows('out')[0]
                self.assertEqual(old_tax_sale['tax_rate'], '9')
                self.assertEqual(old_tax_sale['tax_amount'], '1.4')
                self.assertEqual(old_tax_sale['total'], '116.90')
                first.add('out', 'used', '2', '100', selling_rate='5')
                expected = first.gold_assets()
            finally:
                first.close()
            second = Ledger(path)
            try:
                self.assertEqual(second.gold_assets(), expected)
                self.assertEqual(second.balances()['used'], D('6'))
                self.assertEqual(second.gold_assets()['profit'], D('.1'))
            finally:
                second.close()

    def test_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'gold.sqlite3'
            first = Ledger(path)
            first.add('in', 'new', '3', '100')
            first.close()
            second = Ledger(path)
            try:
                self.assertEqual(second.balances()['new'], D('3'))
                self.assertEqual(len(second.rows('in')), 1)
            finally:
                second.close()


class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.ledger = Ledger(':memory:')
        self.addCleanup(self.ledger.close)

    def test_jalali_boundaries_and_leap_year(self):
        for gregorian, jalali in (
            ('2024-03-19', '1402/12/29'),
            ('2024-03-20', '1403/01/01'),
            ('2025-03-20', '1403/12/30'),
            ('2025-03-21', '1404/01/01'),
            ('2023-09-22', '1402/06/31'),
            ('2023-09-23', '1402/07/01'),
            ('2000-02-29', '1378/12/10'),
            ('2026-10-18', '1405/07/26'),
        ):
            with self.subTest(gregorian=gregorian):
                self.assertEqual(jalali_timestamp(gregorian), jalali)
        self.assertEqual(jalali_timestamp('2025-03-21 23:59:01+03:30'),
                         '1404/01/01 23:59:01')
        self.assertEqual(jalali_timestamp(datetime(2025, 3, 21, 0, 0, 1)),
                         '1404/01/01 00:00:01')

    def test_current_timestamp_and_new_document(self):
        gregorian, jalali = current_timestamps()
        self.assertIsNotNone(datetime.fromisoformat(gregorian).tzinfo)
        self.assertEqual(jalali, jalali_timestamp(gregorian))
        with patch('gold_accounting.current_timestamps', return_value=(
                '2025-03-21 12:34:56+03:30', '1404/01/01 12:34:56')):
            self.ledger.add('in', 'new', '10', '100')
        row = self.ledger.rows('in')[0]
        self.assertEqual(row['document_no'], 1001)
        self.assertEqual(row['created_at'], '2025-03-21 12:34:56+03:30')
        self.assertEqual(row['created_at_jalali'], '1404/01/01 12:34:56')
        self.assertIsNone(row['updated_at'])
        self.assertIsNone(row['updated_at_jalali'])

    def test_document_numbers_shared_between_directions_and_kinds(self):
        self.ledger.add('in', 'new', '10', '100')
        self.ledger.add('in', 'used', '10', '100')
        self.ledger.add('out', 'new', '1', '100')
        self.ledger.add('out', 'used', '1', '100')
        rows = self.ledger.connection.execute(
            'SELECT document_no FROM transactions ORDER BY id').fetchall()
        self.assertEqual([row[0] for row in rows], [1001, 1002, 1003, 1004])
        with self.assertRaises(ValueError):
            self.ledger.add('out', 'used', '100', '100')
        self.ledger.add('in', 'new', '1', '100')
        self.assertEqual(self.ledger.rows('in')[0]['document_no'], 1005)

    def test_edit_preserves_identity_and_creation_time_recalculates_amounts(self):
        self.ledger.add('in', 'new', '10', '100')
        self.ledger.add('out', 'new', '2', '100', '10', '5', '9')
        before = dict(self.ledger.rows('out')[0])
        with patch('gold_accounting.current_timestamps', return_value=(
                '2026-10-18 09:10:11+03:30', '1405/07/26 09:10:11')):
            row = self.ledger.update(before['id'], 'new', '3', '120', '4', '7', '10')
        for key in ('id', 'document_no', 'created_at', 'created_at_jalali'):
            self.assertEqual(row[key], before[key])
        expected = calculate_transaction('out', 'new', '3', '120', '4', '7', '10')
        for key, value in (('total', expected.total), ('base_amount', expected.base),
                           ('making_amount', expected.making), ('selling_amount', expected.selling),
                           ('tax_amount', expected.tax)):
            self.assertEqual(D(row[key]), value)
        self.assertEqual(row['updated_at'], '2026-10-18 09:10:11+03:30')
        self.assertEqual(row['updated_at_jalali'], '1405/07/26 09:10:11')
        self.assertEqual(self.ledger.balances()['new'], D('7'))
        self.assertEqual(len(self.ledger.rows('out')), 1)
        self.ledger.add('in', 'new', '1', '100')
        self.assertEqual(self.ledger.rows('in')[0]['document_no'], 1003)

    def test_edit_used_sale_and_delete_recompute_profit_without_double_counting(self):
        self.ledger.add('in', 'used', '10', '100')
        self.ledger.add('out', 'used', '10', '100', selling_rate='5')
        sale = self.ledger.rows('out')[0]
        edited = self.ledger.update(sale['id'], 'used', '4', '120', selling_rate='10')
        self.assertEqual(D(edited['stock_weight']), D('4'))
        self.assertEqual(D(edited['billed_weight']), D('4.4'))
        self.assertEqual(D(edited['gold_profit']), D('.4'))
        self.assertEqual(D(edited['total']), D('528'))
        self.assertEqual(self.ledger.balances()['used'], D('6'))
        self.assertEqual(self.ledger.gold_assets()['profit'], D('.4'))
        self.assertEqual(self.ledger.gold_assets()['inventory_total'], D('6.4'))
        self.ledger.delete(sale['id'])
        self.assertEqual(self.ledger.balances()['used'], D('10'))
        self.assertEqual(self.ledger.gold_assets()['profit'], D(0))
        self.assertEqual(self.ledger.gold_assets()['sold'], D(0))

    def test_edit_receipt_and_switch_kind(self):
        self.ledger.add('in', 'new', '10', '100', '4')
        row = self.ledger.rows('in')[0]
        edited = self.ledger.update(row['id'], 'used', '5', '120', 'bad', 'bad', 'bad')
        self.assertEqual(edited['direction'], 'in')
        self.assertEqual(D(edited['total']), D('588'))
        self.assertEqual(edited['making_rate'], '0')
        self.assertEqual(self.ledger.balances(), {'new': D(0), 'used': D('5')})
        self.ledger.delete(row['id'])
        self.assertEqual(self.ledger.balances(), {'new': D(0), 'used': D(0)})

    def test_edit_sale_kind_checks_separate_stock(self):
        self.ledger.add('in', 'new', '10', '100')
        self.ledger.add('out', 'new', '2', '100')
        row = dict(self.ledger.rows('out')[0])
        with self.assertRaises(ValueError):
            self.ledger.update(row['id'], 'used', '2', '100', selling_rate='5')
        self.assertEqual(dict(self.ledger.get(row['id'])), row)
        # خرید بعد از فروش هم نمی‌تواند پشتوانه آن فروش قدیمی باشد.
        self.ledger.add('in', 'used', '10', '100')
        with self.assertRaises(ValueError):
            self.ledger.update(row['id'], 'used', '2', '100', selling_rate='5')
        self.assertEqual(dict(self.ledger.get(row['id'])), row)

    def test_edit_and_delete_reject_negative_intermediate_stock_atomically(self):
        self.ledger.add('in', 'new', '10', '100')
        purchase = dict(self.ledger.rows('in')[0])
        self.ledger.add('out', 'new', '8', '100')
        self.ledger.add('in', 'new', '100', '100')
        assets = self.ledger.gold_assets()
        # هر دو تغییر مانده نهایی مثبت دارند، اما فروش میانی را بی‌پشتوانه می‌کنند.
        with self.assertRaisesRegex(ValueError, '1002'):
            self.ledger.update(purchase['id'], 'new', '5', '100')
        self.assertEqual(dict(self.ledger.get(purchase['id'])), purchase)
        self.assertEqual(self.ledger.gold_assets(), assets)
        with self.assertRaisesRegex(ValueError, '1002'):
            self.ledger.delete(purchase['id'])
        self.assertEqual(dict(self.ledger.get(purchase['id'])), purchase)
        self.assertEqual(self.ledger.gold_assets(), assets)
        self.assertFalse(self.ledger.connection.in_transaction)

    def test_sale_edit_cannot_use_profit_as_stock(self):
        self.ledger.add('in', 'used', '10', '100')
        self.ledger.add('out', 'used', '10', '100', selling_rate='5')
        sale = dict(self.ledger.rows('out')[0])
        with self.assertRaises(ValueError):
            self.ledger.update(sale['id'], 'used', '10.1', '100', selling_rate='5')
        self.assertEqual(dict(self.ledger.get(sale['id'])), sale)
        self.assertEqual(self.ledger.balances()['used'], 0)
        self.assertEqual(self.ledger.gold_assets()['profit'], D('.5'))

    def test_invalid_edit_and_missing_transactions_leave_no_changes(self):
        self.ledger.add('in', 'new', '10', '100')
        old = dict(self.ledger.rows('in')[0])
        for changes in (('new', '0', '100'), ('new', '10', '-1'),
                        ('bad', '10', '100'), ('new', '10', '100', '-1')):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.ledger.update(old['id'], *changes)
            self.assertEqual(dict(self.ledger.get(old['id'])), old)
        for operation in (lambda: self.ledger.update(999, 'new', '1', '100'),
                          lambda: self.ledger.delete(999), lambda: self.ledger.get(999)):
            with self.assertRaises(ValueError):
                operation()
        self.assertFalse(self.ledger.connection.in_transaction)

    def test_deleted_highest_document_never_reused_even_after_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'numbers.sqlite3'
            ledger = Ledger(path)
            try:
                ledger.add('in', 'new', '10', '100')
                ledger.add('in', 'used', '10', '100')
                ledger.delete(ledger.rows('in')[0]['id'])
            finally:
                ledger.close()
            ledger = Ledger(path)
            try:
                ledger.add('in', 'new', '1', '100')
                self.assertEqual(ledger.rows('in')[0]['document_no'], 1003)
                for row in ledger.rows('in'):
                    ledger.delete(row['id'])
            finally:
                ledger.close()
            ledger = Ledger(path)
            try:
                ledger.add('in', 'new', '1', '100')
                self.assertEqual(ledger.rows('in')[0]['document_no'], 1004)
            finally:
                ledger.close()

    def test_edit_metadata_and_deletion_persist(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'editing.sqlite3'
            ledger = Ledger(path)
            try:
                ledger.add('in', 'used', '10', '100')
                ledger.add('out', 'used', '2', '100', selling_rate='5')
                sale_id = ledger.rows('out')[0]['id']
                ledger.update(sale_id, 'used', '3', '120', selling_rate='10')
                expected = dict(ledger.get(sale_id))
                assets = ledger.gold_assets()
            finally:
                ledger.close()
            ledger = Ledger(path)
            try:
                self.assertEqual(dict(ledger.get(sale_id)), expected)
                self.assertEqual(ledger.gold_assets(), assets)
                ledger.delete(sale_id)
            finally:
                ledger.close()
            ledger = Ledger(path)
            try:
                self.assertEqual(ledger.rows('out'), [])
                self.assertEqual(ledger.gold_assets()['profit'], 0)
                self.assertEqual(ledger.balances()['used'], D('10'))
            finally:
                ledger.close()

    def test_migration_numbers_id_gaps_and_preserves_legacy_dates_and_amounts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'legacy.sqlite3'
            with sqlite3.connect(path) as connection:
                connection.execute('''CREATE TABLE transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
                    direction TEXT NOT NULL, kind TEXT NOT NULL, weight TEXT NOT NULL,
                    price TEXT NOT NULL, making_rate TEXT NOT NULL,
                    selling_rate TEXT NOT NULL, total TEXT NOT NULL)''')
                connection.executemany('INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', [
                    (4, '2025-03-21 11:12:13', 'in', 'new', '10', '100', '10', '7', '1177.00'),
                    (9, '2025-03-22', 'in', 'used', '10', '100', '0', '0', '1000'),
                ])
            for _ in range(2):
                ledger = Ledger(path)
                try:
                    rows = ledger.rows('in')
                    self.assertEqual([(r['id'], r['document_no']) for r in rows], [(9, 1002), (4, 1001)])
                    self.assertEqual(rows[1]['created_at'], '2025-03-21 11:12:13')
                    self.assertEqual(rows[1]['created_at_jalali'], '1404/01/01 11:12:13')
                    self.assertEqual(rows[0]['created_at_jalali'], '1404/01/02')
                    self.assertEqual(rows[1]['total'], '1177.00')
                    self.assertEqual(rows[0]['stock_weight'], '10')
                    self.assertIsNone(rows[1]['updated_at_jalali'])
                finally:
                    ledger.close()

    def test_no_op_legacy_edit_preserves_historical_values(self):
        self.ledger.add('in', 'new', '10', '100', '10')
        transaction_id = self.ledger.rows('in')[0]['id']
        with self.ledger.connection:
            self.ledger.connection.execute('''UPDATE transactions SET selling_rate = '7',
                total = '1177.00', base_amount = NULL, making_amount = NULL,
                selling_amount = NULL, calculation_version = 'legacy' WHERE id = ?''', (transaction_id,))
        before = dict(self.ledger.get(transaction_id))
        updated = self.ledger.update(transaction_id, 'new', '10.0', '100.00', '10.0', '7')
        for key, value in before.items():
            if key not in ('updated_at', 'updated_at_jalali'):
                self.assertEqual(updated[key], value)
        self.assertIsNotNone(updated['updated_at_jalali'])
        changed = self.ledger.update(transaction_id, 'new', '11', '100', '10')
        self.assertEqual(D(changed['total']), D('1210'))
        self.assertEqual(changed['calculation_version'], '6')
        self.assertEqual(changed['document_no'], before['document_no'])

    def test_no_op_legacy_used_edit_does_not_invent_profit_or_convert_stock(self):
        self.ledger.add('in', 'used', '10', '100')
        self.ledger.add('out', 'used', '2', '100')
        sale = self.ledger.rows('out')[0]
        with self.ledger.connection:
            self.ledger.connection.execute('''UPDATE transactions SET stock_weight = '2',
                billed_weight = '2', gold_profit = '0', total = '200.00',
                calculation_version = 'legacy', base_amount = NULL WHERE id = ?''', (sale['id'],))
        updated = self.ledger.update(sale['id'], 'used', '2', '100')
        self.assertEqual(updated['stock_weight'], '2')
        self.assertEqual(updated['total'], '200.00')
        self.assertEqual(updated['gold_profit'], '0')
        self.assertEqual(updated['calculation_version'], 'legacy')
        self.assertIsNone(updated['base_amount'])
        self.assertEqual(self.ledger.gold_assets()['profit'], 0)


if __name__ == '__main__':
    unittest.main()
