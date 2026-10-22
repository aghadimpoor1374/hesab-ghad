import unittest
from decimal import Decimal
from gold_accounting import Ledger
from gold_special import SpecialLedger


class SpecialTests(unittest.TestCase):
    def setUp(self):
        self.ledger = Ledger(':memory:')
        self.s = SpecialLedger(self.ledger.connection)
        self.p = self.s.party('customer', 'آزمایش')

    def tearDown(self):
        self.ledger.close()

    def test_parsian_modes(self):
        a = self.s.quote('parsian', 3, weight='0.5', rate='6000000', fee=7)
        b = self.s.quote('parsian', 3, weight='1.5', mode='total', rate='6000000', fee=7)
        self.assertEqual(a, b)
        self.assertEqual(a['buy'], Decimal('8700000'))
        self.assertEqual(a['sell'], Decimal('9630000'))

    def test_coin_balance_and_oversell(self):
        self.s.trade('in', 'emami86', self.p, quantity=2, rate=100)
        self.s.trade('out', 'emami86', self.p, quantity=1, rate=150)
        self.assertEqual(self.s.stock('emami86')[0], 1)
        self.assertEqual(self.s.balance(self.p)[0], -50)
        with self.assertRaises(ValueError):
            self.s.trade('out', 'emami86', self.p, quantity=2, rate=150)
        self.assertEqual(self.s.stock('emami86')[0], 1)

    def test_melted(self):
        self.s.trade('in', 'melted', self.p, settlement='gold', quantity=1, weight=10, purity=735, rate=100)
        self.assertEqual(self.s.stock('melted')[2], Decimal('9.8'))
        self.assertEqual(self.s.balance(self.p), (Decimal(0), Decimal('-9.8')))
        self.s.trade('out', 'melted', self.p, settlement='paid', quantity=1, weight=5, purity=735, rate=100)
        self.assertEqual(self.s.stock('melted')[1:], (Decimal(5), Decimal('4.9')))

    def test_manual_accounts(self):
        self.s.post_account(self.p, '100', '2', 'مانده اولیه')
        self.s.post_account(self.p, '-50', '-1', 'دریافت')
        self.assertEqual(self.s.balance(self.p), (Decimal(50), Decimal(1)))

    def test_invalid(self):
        for value in ('NaN', '-1', 'Infinity'):
            with self.assertRaises(ValueError):
                self.s.quote('emami86', value)
        with self.assertRaises(ValueError):
            self.s.quote('melted', 1, weight=10, purity=1001)
        with self.assertRaises(ValueError):
            self.s.quote('parsian', '1.5', weight=1)

    def test_parsian_weight_guard(self):
        self.s.trade('in', 'parsian', self.p, quantity=2, weight=1, rate=100)
        with self.assertRaises(ValueError):
            self.s.trade('out', 'parsian', self.p, quantity=1, weight=3, rate=100)

    def test_no_legacy_mutation(self):
        before = list(self.ledger.connection.execute('SELECT * FROM transactions'))
        self.s.trade('in', 'melted', self.p, quantity=1, weight=10, purity=735, rate=100)
        self.assertEqual(before, list(self.ledger.connection.execute('SELECT * FROM transactions')))

if __name__ == '__main__':
    unittest.main()
