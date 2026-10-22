"""Regression tests for configurable gold purities and desktop product entry."""
import sqlite3
import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path
from gold_accounting import Ledger, calculate_transaction, describe_calculation


class PurityTests(unittest.TestCase):
    def test_custom_ratio_and_defaults(self):
        result = calculate_transaction('in', 'used', '10', '100', purity='۸۰۰', purchase_purity='۷۲۰')
        self.assertEqual(result.stock_weight, D('10'))
        self.assertEqual(result.total, D('900'))
        self.assertEqual(calculate_transaction('in', 'used', '10', '100').stock_weight, D('10'))
        self.assertIn('800 × 720', describe_calculation(result, 'in', 'used'))

    def test_purchase_settlement_is_separate_from_physical_assets(self):
        ledger = Ledger(':memory:')
        self.addCleanup(ledger.close)
        result = ledger.add('in', 'used', '10', '5000000')
        self.assertEqual(result.billed_weight, D('9.8'))
        self.assertEqual(result.total, D('49000000'))
        self.assertEqual(ledger.balances()['used'], D('10'))
        self.assertEqual(ledger.gold_assets()['stock'], D('10'))
        row = ledger.rows('in')[0]
        self.assertEqual(D(row['billed_weight']), D('9.8'))
        self.assertEqual(D(row['stock_weight']), D('10'))
        self.assertIn('وزن افزوده به موجودی: 10', describe_calculation(result, 'in', 'used'))
        with self.assertRaises(ValueError):
            ledger.add('out', 'used', '10.01', '5000000')
        ledger.add('out', 'used', '10', '5000000')
        self.assertEqual(ledger.balances()['used'], 0)

    def test_invalid_purities(self):
        for field in ('purity', 'purchase_purity'):
            for value in ('0', '-1', '1001', 'NaN', 'abc', ''):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    calculate_transaction('in', 'used', '10', '100', **{field: value})

    def test_persistence_edit_and_product_isolation(self):
        ledger = Ledger(':memory:')
        self.addCleanup(ledger.close)
        ledger.add('in', 'used', '10', '100', purity='800', purchase_purity='720',
                   product_code='A1', product_title='گردنبند')
        row = ledger.rows('in')[0]
        self.assertEqual(row['purity'], '800')
        self.assertEqual(row['purchase_purity'], '720')
        self.assertEqual(row['product_title'], 'گردنبند')
        ledger.update(row['id'], 'used', '10', '100')
        self.assertEqual(ledger.get(row['id'])['stock_weight'], '10')
        ledger.add('in', 'used', '20', '100', product_code='B2', product_title='انگشتر')
        with self.assertRaises(ValueError):
            ledger.add('out', 'used', '11', '100', product_code='A1', purity='800', purchase_purity='720')
        ledger.add('out', 'used', '5', '100', product_code='A1', purity='800', purchase_purity='720')
        with self.assertRaises(ValueError):
            ledger.update(row['id'], 'used', '4', '100', purchase_purity='100')
        self.assertEqual(ledger.get(row['id'])['purchase_purity'], '720')
        self.assertEqual(ledger.get(row['id'])['stock_weight'], '10')

    def test_migration_does_not_recalculate(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'old.db'
            with sqlite3.connect(path) as con:
                con.execute('CREATE TABLE transactions (id INTEGER PRIMARY KEY, created_at TEXT, direction TEXT, kind TEXT, weight TEXT, price TEXT, making_rate TEXT, selling_rate TEXT, total TEXT)')
                con.execute("INSERT INTO transactions VALUES (1,'2026-01-01','in','used','10','100','0','0','1000')")
            ledger = Ledger(path)
            try:
                row = ledger.get(1)
                self.assertEqual((row['purity'], row['purchase_purity']), ('750', '735'))
                ledger.update(1, 'used', '10', '100', product_title='قدیمی')
                row = ledger.get(1)
                self.assertEqual((row['stock_weight'], row['total'], row['calculation_version']), ('10', '1000', 'legacy'))
            finally:
                ledger.close()


if __name__ == '__main__':
    unittest.main()
