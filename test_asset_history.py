import unittest

import pandas as pd

from asset_history import prepare_history


class AssetHistoryTests(unittest.TestCase):
    def test_deposits_and_withdrawals_do_not_count_as_operating_change(self):
        history = pd.DataFrame([
            {'date': '2026-01-03', 'total_assets': 1_300_000, 'net_flow': 200_000, 'currency': 'JPY', 'memo': '入金'},
            {'date': '2026-01-01', 'total_assets': 1_000_000, 'net_flow': 0, 'currency': 'JPY', 'memo': '基準'},
            {'date': '2026-01-05', 'total_assets': 1_250_000, 'net_flow': -80_000, 'currency': 'JPY', 'memo': '出金'},
        ])
        result = prepare_history(history)
        self.assertEqual(result['asset_change'].tolist(), [0, 300_000, 250_000])
        self.assertEqual(result['operating_change'].tolist(), [0, 100_000, 30_000])
        self.assertEqual(result['cumulative_operating_change'].tolist(), [0, 100_000, 130_000])

    def test_rejects_duplicate_date_and_mixed_currency(self):
        rows = pd.DataFrame([
            {'date': '2026-01-01', 'total_assets': 100, 'net_flow': 0, 'currency': 'JPY', 'memo': ''},
            {'date': '2026-01-01', 'total_assets': 200, 'net_flow': 0, 'currency': 'JPY', 'memo': ''},
        ])
        with self.assertRaises(ValueError):
            prepare_history(rows)
        rows.loc[1, 'date'] = '2026-01-02'
        rows.loc[1, 'currency'] = 'USD'
        with self.assertRaises(ValueError):
            prepare_history(rows)


if __name__ == '__main__':
    unittest.main()
