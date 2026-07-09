import unittest

from market_cell.features import FEATURE_VERSION, build_feature_snapshot
from market_cell.models import Candle


class FeatureSnapshotTests(unittest.TestCase):
    def test_builds_market_feature_snapshot(self):
        snapshot = build_feature_snapshot(
            [
                Candle("t1", 100, 102, 99, 101, 1000),
                Candle("t2", 101, 104, 100, 103, 1200),
                Candle("t3", 103, 106, 102, 105, 1400),
                Candle("t4", 105, 108, 104, 107, 2200),
            ]
        )

        self.assertEqual(FEATURE_VERSION, "market_features_v0.1")
        self.assertEqual(snapshot.candle_count, 4)
        self.assertAlmostEqual(snapshot.close_change_pct, 5.9406, places=4)
        self.assertAlmostEqual(snapshot.latest_volume_ratio, 1.8333, places=4)
        self.assertGreater(snapshot.average_range_pct, 0)
        self.assertLessEqual(snapshot.trend_efficiency, 1.0)

    def test_empty_snapshot_is_safe(self):
        snapshot = build_feature_snapshot([])

        self.assertEqual(snapshot.candle_count, 0)
        self.assertEqual(snapshot.latest_volume_ratio, 1)
        self.assertEqual(snapshot.trend_efficiency, 0)


if __name__ == "__main__":
    unittest.main()
