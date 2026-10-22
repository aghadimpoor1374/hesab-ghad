import unittest
from decimal import Decimal as D
from gold_accounting import Ledger


class PurchaseBasisProfitTests(unittest.TestCase):
    def test_fifo_purchase_basis(self):
        ledger = Ledger(':memory:')
        ledger.add('in', 'used', '3.51', '100', purity='750', purchase_purity='727')
        sale = ledger.add('out', 'used', '3.51', '100', selling_rate='3')
        self.assertEqual(sale.gold_profit, D('3.51') * D('1.03') - D('3.51') * D('727') / D('750'))
        self.assertEqual(ledger.gold_assets()['profit'], sale.gold_profit)
        self.assertEqual(ledger.balances()['used'], D(0))

if __name__ == '__main__':
    unittest.main()
