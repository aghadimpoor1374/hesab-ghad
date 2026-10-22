import unittest
from decimal import Decimal as D
from gold_accounting import Ledger

class SuppliersTest(unittest.TestCase):
    def test_fifo_and_preservation(self):
        ledger = Ledger(':memory:')
        a = ledger.create_supplier('الف')
        b = ledger.create_supplier('ب')
        ledger.add('in', 'new', '100', '1000', gold_fee_rate='10', supplier_id=a)
        ledger.add('in', 'new', '50', '1000', gold_fee_rate='20', supplier_id=b)
        ledger.add('out', 'new', '120', '1000')
        self.assertEqual(ledger.supplier_summary(a)['remaining'], D(0))
        self.assertEqual(ledger.supplier_summary(b)['remaining'], D(30))
        self.assertEqual(ledger.supplier_summary(b)['remaining_fee'], D(6))
        self.assertEqual(ledger.supplier_summary(a)['fees'], D(10))
        row = ledger.rows('in')[-1]
        ledger.update(row['id'], 'new', '100', '1000')
        self.assertEqual(ledger.get(row['id'])['supplier_id'], a)
        with self.assertRaises(ValueError):
            ledger.add('in', 'new', '5', '1000', supplier_id=999)
        ledger.close()

    def test_unassigned(self):
        ledger = Ledger(':memory:')
        ledger.add('in', 'new', '10', '1000', gold_fee_rate='5')
        self.assertEqual(ledger.supplier_summary(None)['fees'], D('0.5'))
        ledger.close()

if __name__ == '__main__':
    unittest.main()
