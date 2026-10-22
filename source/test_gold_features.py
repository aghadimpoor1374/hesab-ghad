"""آزمون‌های جستجو، ساعت قفل‌شده و گزارش حساب قدیم؛ بدون نیاز به نمایشگر."""
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from gold_accounting import Ledger, jalali_timestamp
from gold_services import ApplicationClock, jalali_moment, parse_clock, parse_jalali_date, validate_search
from gold_reports import export_pdf, send_to_printer


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.ledger = Ledger(':memory:')
        self.addCleanup(self.ledger.close)
        for direction, kind, weight, stamp in (
            ('in', 'new', '10', '1405/01/01 09:30:00'),
            ('in', 'used', '5', '1405/01/01 10:15:59'),
            ('out', 'new', '2', '1405/01/01 10:16:00'),
            ('in', 'new', '3', '1405/01/02 09:30:00'),
        ):
            self.ledger.timestamp_source = lambda stamp=stamp: (
                jalali_moment(*stamp.split()).isoformat(sep=' ', timespec='seconds'), stamp)
            self.ledger.add(direction, kind, weight, '100')

    def test_date_and_optional_filters_are_combined(self):
        self.assertEqual(len(self.ledger.search(date='۱۴۰۵/۱/۱')), 3)
        self.assertEqual(len(self.ledger.search()), 4)
        rows = self.ledger.search(date='1405/01/01', direction='in', kind='used',
                                  weight_min='۵', weight_max='۵', document_no='۱۰۰۲',
                                  time_from='10:15', time_to='10:15')
        self.assertEqual([row['document_no'] for row in rows], [1002])
        self.assertEqual(self.ledger.search(date='1405/01/02', document_no='1002'), [])

    def test_time_boundaries_and_weight_precision(self):
        rows = self.ledger.search(time_from='09:30', time_to='10:15')
        self.assertEqual([row['document_no'] for row in rows], [1004, 1002, 1001])
        self.assertEqual([row['document_no'] for row in self.ledger.search(weight_min='4.99', weight_max='5.01')], [1002])
        with self.assertRaises(ValueError):
            self.ledger.search(document_no='1 OR 1=1')

    def test_legacy_missing_time_is_not_invented(self):
        with self.ledger.connection:
            self.ledger.connection.execute("UPDATE transactions SET created_at = '2026-03-21', created_at_jalali = '1405/01/01' WHERE id = 1")
        self.assertEqual(len(self.ledger.search(date='1405/01/01')), 3)
        self.assertNotIn(1, [row['id'] for row in self.ledger.search(time_from='00:00', time_to='23:59')])

    def test_bad_filters_do_not_change_rows(self):
        for filters in ({'date': '1405/12/30'}, {'date': '1405/07/31'},
                        {'time_from': '24:00'}, {'time_from': '10:00', 'time_to': '09:00'},
                        {'weight_min': '6', 'weight_max': '5'}, {'weight_min': '-1'},
                        {'document_no': '0'}, {'direction': 'bad'}, {'kind': 'bad'}, {'other': 'x'}):
            with self.subTest(filters=filters), self.assertRaises(ValueError):
                self.ledger.search(**filters)
        self.assertEqual(len(self.ledger.search()), 4)

    def test_jalali_validation_and_clock(self):
        self.assertEqual(str(parse_jalali_date('۱۴۰۳/۱۲/۳۰')), '2025-03-20')
        self.assertEqual(str(parse_jalali_date('1404/01/01')), '2025-03-21')
        self.assertEqual(parse_clock('۰۹:۳۰'), 34200)
        self.assertEqual(parse_clock('09:30', end=True), 34259)
        self.assertEqual(validate_search({'date': '1405-1-1'})['date'], '1405/01/01')
        for value in ('1404/12/30', '1405/02/32', '1405/00/01', 'bad'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_jalali_date(value)


class ClockTests(unittest.TestCase):
    KEY = 'HG-12345678-12345678-12345678-12345678'

    def setUp(self):
        self.ledger = Ledger(':memory:')
        self.addCleanup(self.ledger.close)
        self.wall = 1_700_000_000.0
        self.mono = 100.0
        # کم‌کردن هزینه PBKDF2 فقط برای آزمون؛ مقدار واقعی جداگانه بررسی می‌شود.
        self.hash_patch = patch.object(ApplicationClock, 'ROUNDS', 1000)
        self.hash_patch.start()
        self.addCleanup(self.hash_patch.stop)
        self.clock = ApplicationClock(self.ledger.connection, lambda: self.wall, lambda: self.mono)

    def initialize(self):
        return self.clock.initialize('1405/01/01', '09:30:00', self.KEY)

    def test_first_run_and_persistent_lock(self):
        self.assertFalse(self.clock.initialized)
        with self.assertRaises(ValueError):
            self.clock.now()
        self.assertEqual(self.initialize(), self.KEY)
        with self.assertRaises(ValueError):
            self.initialize()
        row = self.ledger.connection.execute('SELECT * FROM application_settings').fetchone()
        self.assertNotEqual(row['license_hash'], self.KEY)
        self.assertNotIn(self.KEY, str(tuple(row)))
        self.assertTrue(self.clock.authorize(self.KEY))
        self.assertEqual(self.ledger.connection.execute('SELECT COUNT(*) FROM administration_audit').fetchone()[0], 1)

    def test_monotonic_clock_ignores_wall_change_during_session(self):
        self.initialize()
        first = self.clock.now()
        self.wall += 3600 * 24
        self.mono += 7
        self.assertEqual((self.clock.now() - first).total_seconds(), 7)
        self.wall -= 3600 * 48
        self.assertEqual((self.clock.now() - first).total_seconds(), 7)

    def test_checkpoint_and_restart_no_accidental_backward_time(self):
        self.initialize()
        self.mono += 90
        self.clock.checkpoint()
        expected = self.clock.now()
        self.wall -= 3600
        reopened = ApplicationClock(self.ledger.connection, lambda: self.wall, lambda: self.mono)
        self.assertEqual(reopened.now(), expected)
        self.wall += 3610
        reopened = ApplicationClock(self.ledger.connection, lambda: self.wall, lambda: self.mono)
        self.assertEqual((reopened.now() - expected).total_seconds(), 10)

    def test_wrong_key_attempts_persist_and_lock(self):
        self.initialize()
        for _ in range(5):
            with self.assertRaisesRegex(ValueError, 'معتبر نیست'):
                self.clock.authorize('wrong')
        with self.assertRaisesRegex(ValueError, 'قفل'):
            self.clock.authorize(self.KEY)
        self.assertEqual(self.ledger.connection.execute("SELECT COUNT(*) FROM administration_audit WHERE action = 'authorization_failed'").fetchone()[0], 5)
        self.mono += 61
        self.assertTrue(self.clock.authorize(self.KEY))

    def test_authorized_time_change_and_ledger_timestamps(self):
        self.initialize()
        self.ledger.timestamp_source = self.clock.timestamps
        self.ledger.add('in', 'new', '10', '100')
        before = dict(self.ledger.rows('in')[0])
        with self.assertRaises(ValueError):
            self.clock.change_time('1405/02/01', '12:00', 'wrong')
        self.clock.change_time('1405/02/01', '12:00', self.KEY)
        self.assertEqual(jalali_timestamp(self.clock.now()), '1405/02/01 12:00:00')
        self.assertEqual(dict(self.ledger.rows('in')[0]), before)
        self.ledger.update(before['id'], 'new', '9', '100')
        after = self.ledger.rows('in')[0]
        self.assertEqual(after['created_at_jalali'], before['created_at_jalali'])
        self.assertEqual(after['updated_at_jalali'], '1405/02/01 12:00:00')
        self.assertEqual(after['document_no'], before['document_no'])

    def test_backup_keeps_transactions_and_clock(self):
        self.initialize()
        self.ledger.add('in', 'new', '10', '100')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'backup.sqlite3'
            self.clock.backup(path, self.KEY)
            backup = Ledger(path)
            try:
                self.assertEqual(len(backup.rows('in')), 1)
                self.assertTrue(ApplicationClock(backup.connection).initialized)
            finally:
                backup.close()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'main.sqlite3'
            ledger = Ledger(path)
            try:
                clock = ApplicationClock(ledger.connection)
                clock.initialize('1405/01/01', '09:30', self.KEY)
                with self.assertRaises(ValueError):
                    clock.backup(path, self.KEY)
            finally:
                ledger.close()


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.ledger = Ledger(':memory:')
        self.addCleanup(self.ledger.close)
        self.ledger.add('in', 'new', '10', '100', '4')
        self.ledger.add('out', 'new', '2', '100', '4', '7', '10')
        self.ledger.add('in', 'used', '10', '100')
        self.ledger.add('out', 'used', '10', '100', '0', '5')

    def test_report_sums_use_recorded_values(self):
        from pypdf import PdfReader
        rows = self.ledger.search()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'totals.pdf'
            export_pdf(path, rows)
            text = ''.join(page.extract_text(extraction_mode='layout') for page in PdfReader(path).pages)
            self.assertIn('2,020', text)  # ورود: ۱۰۴۰ + ۹۸۰
            self.assertIn('1,274.82', text)  # جمع مبالغ خروج ثبت‌شده؛ بدون محاسبه مجدد

    def test_pdf_unicode_fonts_details_and_empty_report(self):
        from pypdf import PdfReader
        with tempfile.TemporaryDirectory() as directory:
            for name, rows in (('full', self.ledger.search()), ('empty', [])):
                path = Path(directory) / (name + '.pdf')
                export_pdf(path, rows, title='گزارش حساب قدیم', filter_text='فیلتر روزانه: ۱۴۰۵/۰۱/۰۱', generated_at='1405/01/01 12:00:00')
                reader = PdfReader(path)
                self.assertGreaterEqual(len(reader.pages), 1)
                self.assertTrue(any('/ToUnicode' in font.get_object() for font in reader.pages[0]['/Resources']['/Font'].get_object().values()))
                text = ''.join(page.extract_text(extraction_mode='layout') for page in reader.pages)
                self.assertIn('1405/01/01', text)
                self.assertIn('0.5' if rows else '0', text)

    def test_pdf_paginates_and_preserves_legacy_missing_breakdown(self):
        from pypdf import PdfReader
        row = dict(self.ledger.rows('in')[0])
        row.update(base_amount=None, making_amount=None, selling_amount=None, created_at_jalali='')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'many.pdf'
            export_pdf(path, [row] * 90)
            self.assertGreater(len(PdfReader(path).pages), 2)

    def test_unix_print_command_and_no_printer_failure(self):
        with patch('gold_reports.os.name', 'posix'), patch('gold_reports.shutil.which', side_effect=lambda name: '/usr/bin/lp' if name == 'lp' else None), patch('gold_reports.subprocess.run') as run:
            send_to_printer('/tmp/test.pdf')
            self.assertEqual(run.call_args.args[0], ['/usr/bin/lp', '/tmp/test.pdf'])
        with patch('gold_reports.os.name', 'posix'), patch('gold_reports.shutil.which', return_value=None):
            with self.assertRaises(RuntimeError):
                send_to_printer('/tmp/test.pdf')


if __name__ == '__main__':
    unittest.main()
