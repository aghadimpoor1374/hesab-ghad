import unittest
from datetime import datetime
from decimal import Decimal
from gold_accounting import Ledger
from gold_customers import customers

class CustomerTests(unittest.TestCase):
    def test_customer_history(self):
        ledger = Ledger(':memory:', timestamp_source=lambda: ('2026-01-20 10:00:00', '1404/10/30'))
        self.addCleanup(ledger.close)
        ledger.add('in', 'used', '10', '100', customer_name='علی', bank_card='۱۲۳۴۵۶۷۸۹۰۱۲۳۴۵۶', national_image=b'image')
        ledger.add('out', 'used', '2', '100', customer_name='علی', customer_phone='۰۹۱۲۱۲۳۴۵۶۷')
        summary = customers(ledger, datetime(2026, 1, 21))[0]
        self.assertEqual(summary['weight'], Decimal(2))
        self.assertEqual(summary['total'], Decimal(200))
        self.assertEqual(summary['phone'], '09121234567')
        self.assertEqual(customers(ledger, datetime(2026, 3, 21))[0]['weight'], 0)
        row = ledger.rows('in')[0]
        ledger.update(row['id'], 'used', '10', '100', customer_name='احمد')
        self.assertEqual(ledger.get(row['id'])['national_image'], b'image')
        self.assertEqual(ledger.get(row['id'])['bank_card'], '1234567890123456')

    def test_validation(self):
        ledger = Ledger(':memory:')
        self.addCleanup(ledger.close)
        with self.assertRaises(ValueError):
            ledger.add('in', 'used', '1', '100', customer_phone='123')
        self.assertEqual(ledger.rows('in'), [])
