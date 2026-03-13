import unittest

from src.recommendation.market_utils import (
    detect_market_region,
    get_market_close_hour,
    get_market_indices,
)
from src.recommendation.models import MarketRegion


class MarketUtilsTestCase(unittest.TestCase):
    def test_detect_market_region_mixed_codes(self) -> None:
        self.assertEqual(detect_market_region("AAPL"), MarketRegion.US)
        self.assertEqual(detect_market_region("HK00700"), MarketRegion.HK)
        self.assertEqual(detect_market_region("600519"), MarketRegion.CN)

    def test_detect_market_region_fallbacks_to_cn_for_non_us_hk_codes(self) -> None:
        self.assertEqual(detect_market_region("SPX"), MarketRegion.CN)
        self.assertEqual(detect_market_region("000001"), MarketRegion.CN)

    def test_get_market_indices_matches_static_mapping(self) -> None:
        self.assertEqual(
            get_market_indices(MarketRegion.CN), ["000001", "399001", "399006"]
        )
        self.assertEqual(get_market_indices(MarketRegion.US), ["SPX", "DJI", "IXIC"])

        hk_indices = get_market_indices(MarketRegion.HK)
        self.assertEqual(len(hk_indices), 1)
        self.assertEqual(hk_indices, ["HSI"])

    def test_get_market_indices_returns_copy(self) -> None:
        indices = get_market_indices(MarketRegion.CN)
        indices.append("TEST")

        self.assertEqual(
            get_market_indices(MarketRegion.CN), ["000001", "399001", "399006"]
        )

    def test_get_market_close_hour(self) -> None:
        self.assertEqual(get_market_close_hour(MarketRegion.CN), 15)
        self.assertEqual(get_market_close_hour(MarketRegion.HK), 16)
        self.assertEqual(get_market_close_hour(MarketRegion.US), 16)


if __name__ == "__main__":
    unittest.main()
