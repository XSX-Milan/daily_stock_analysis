# -*- coding: utf-8 -*-

import unittest
from unittest.mock import Mock, patch

import pandas as pd

from src.services.sector_scanner_service import SectorScannerService


class SectorScannerServiceTestCase(unittest.TestCase):
    def test_scan_sectors_respects_max_universe_bound(self):
        data_fetcher = Mock()
        data_fetcher.get_sector_rankings.return_value = (
            [{"name": "SectorA"}, {"name": "SectorB"}, {"name": "SectorC"}],
            [],
        )

        sector_frames = {
            "SectorA": pd.DataFrame({"代码": ["000001", "000002", "000003", "000004"]}),
            "SectorB": pd.DataFrame({"代码": ["000005", "000006", "000007", "000008"]}),
            "SectorC": pd.DataFrame({"代码": ["000009", "000010", "000011", "000012"]}),
        }

        mock_ak = Mock()
        mock_ak.stock_board_industry_cons_em.side_effect = lambda symbol: sector_frames[
            symbol
        ]

        with patch(
            "src.services.sector_scanner_service.importlib.import_module",
            return_value=mock_ak,
        ):
            service = SectorScannerService(
                data_fetcher=data_fetcher, top_n=3, max_universe=5
            )
            scanned = service.scan_sectors()

        self.assertEqual(
            scanned,
            [
                ("SectorA", ["000001", "000002", "000003"]),
                ("SectorB", ["000005", "000006"]),
            ],
        )
        total_codes = sum(len(codes) for _, codes in scanned)
        self.assertLessEqual(total_codes, 5)

    def test_scan_sectors_continues_when_one_sector_errors(self):
        data_fetcher = Mock()
        data_fetcher.get_sector_rankings.return_value = (
            [{"name": "Good1"}, {"name": "Bad"}, {"name": "Good2"}],
            [],
        )

        def _sector_df(symbol: str) -> pd.DataFrame:
            if symbol == "Bad":
                raise RuntimeError("boom")
            if symbol == "Good1":
                return pd.DataFrame({"代码": ["600001", "600002"]})
            return pd.DataFrame({"代码": ["600003", "600004"]})

        mock_ak = Mock()
        mock_ak.stock_board_industry_cons_em.side_effect = _sector_df

        with patch(
            "src.services.sector_scanner_service.importlib.import_module",
            return_value=mock_ak,
        ):
            service = SectorScannerService(
                data_fetcher=data_fetcher, top_n=2, max_universe=10
            )
            scanned = service.scan_sectors()

        self.assertEqual(
            scanned, [("Good1", ["600001", "600002"]), ("Good2", ["600003", "600004"])]
        )

    def test_get_sector_stocks_filters_to_a_share_codes(self):
        data_fetcher = Mock()
        mock_ak = Mock()
        mock_ak.stock_board_industry_cons_em.return_value = pd.DataFrame(
            {"代码": ["600519", "AAPL", "00700", " 000001 ", 123456]}
        )

        with patch(
            "src.services.sector_scanner_service.importlib.import_module",
            return_value=mock_ak,
        ):
            service = SectorScannerService(
                data_fetcher=data_fetcher, top_n=10, max_universe=50
            )
            codes = service.get_sector_stocks("AnySector", limit=2)

        self.assertEqual(codes, ["600519", "000001"])

    def test_get_all_scan_codes_deduplicates_across_sectors(self):
        data_fetcher = Mock()
        data_fetcher.get_sector_rankings.return_value = (
            [{"name": "S1"}, {"name": "S2"}],
            [],
        )

        sector_frames = {
            "S1": pd.DataFrame({"代码": ["000001", "000002", "000003"]}),
            "S2": pd.DataFrame({"代码": ["000003", "000004", "000002"]}),
        }
        mock_ak = Mock()
        mock_ak.stock_board_industry_cons_em.side_effect = lambda symbol: sector_frames[
            symbol
        ]

        with patch(
            "src.services.sector_scanner_service.importlib.import_module",
            return_value=mock_ak,
        ):
            service = SectorScannerService(
                data_fetcher=data_fetcher, top_n=3, max_universe=20
            )
            all_codes = service.get_all_scan_codes()

        self.assertEqual(all_codes, ["000001", "000002", "000003", "000004"])

    def test_get_sector_stocks_overseas_fallback_returns_without_provider_lookup(self):
        service = SectorScannerService(data_fetcher=Mock(), top_n=10, max_universe=50)

        with patch(
            "src.services.sector_scanner_service.importlib.import_module",
            side_effect=RuntimeError("provider import should be skipped"),
        ):
            codes = service.get_sector_stocks("Tech", limit=3, market="US")

        self.assertEqual(codes, ["AAPL", "MSFT", "NVDA"])

    def test_get_sector_stocks_overseas_non_fallback_still_uses_provider_metadata(self):
        service = SectorScannerService(data_fetcher=Mock(), top_n=10, max_universe=50)
        mock_yf = Mock()

        def _ticker(symbol: str) -> Mock:
            ticker = Mock()
            if symbol == "AAPL":
                ticker.info = {"sector": "AI Infra", "industry": "Semiconductors"}
            else:
                ticker.info = {"sector": "Utilities", "industry": "Power"}
            return ticker

        mock_yf.Ticker.side_effect = _ticker

        with (
            patch.object(
                service, "_build_market_candidates", return_value=["AAPL", "MSFT"]
            ),
            patch(
                "src.services.sector_scanner_service.importlib.import_module",
                return_value=mock_yf,
            ),
        ):
            codes = service.get_sector_stocks("AI Infra", limit=2, market="US")

        self.assertEqual(codes, ["AAPL"])
        mock_yf.Ticker.assert_any_call("AAPL")

    def test_alias_metadata_collapses_to_canonical_key_and_display_label(self):
        tech_meta = SectorScannerService._normalize_sector_metadata("Tech")
        zh_tech_meta = SectorScannerService._normalize_sector_metadata("科技")

        self.assertEqual(tech_meta["canonical_key"], "technology")
        self.assertEqual(zh_tech_meta["canonical_key"], "technology")
        self.assertEqual(tech_meta["display_label"], "Technology")
        self.assertEqual(zh_tech_meta["display_label"], "Technology")
        self.assertIn("tech", tech_meta["aliases"])
        self.assertIn("technology", zh_tech_meta["aliases"])
        self.assertEqual(tech_meta["raw_provider_label"], "Tech")
        self.assertEqual(zh_tech_meta["raw_provider_label"], "科技")

    def test_communication_services_aliases_collapse_to_same_canonical_metadata(self):
        spaced_alias_meta = SectorScannerService._normalize_sector_metadata(
            "Communication Services"
        )
        provider_alias_meta = SectorScannerService._normalize_sector_metadata(
            "Internet Content & Information"
        )
        zh_alias_meta = SectorScannerService._normalize_sector_metadata("通信服务")

        self.assertEqual(spaced_alias_meta["canonical_key"], "communicationservices")
        self.assertEqual(provider_alias_meta["canonical_key"], "communicationservices")
        self.assertEqual(zh_alias_meta["canonical_key"], "communicationservices")
        self.assertEqual(spaced_alias_meta["display_label"], "Communication Services")
        self.assertEqual(provider_alias_meta["display_label"], "Communication Services")
        self.assertEqual(zh_alias_meta["display_label"], "Communication Services")
        self.assertIn("communicationservices", spaced_alias_meta["aliases"])
        self.assertIn("internetcontent&information", provider_alias_meta["aliases"])
        self.assertGreaterEqual(len(zh_alias_meta["aliases"]), 2)
        self.assertEqual(
            provider_alias_meta["raw_provider_label"], "Internet Content & Information"
        )

    def test_fallback_alias_lookup_uses_canonical_group(self):
        codes_from_en_alias = SectorScannerService._get_overseas_fallback_codes(
            "Tech", "US"
        )
        codes_from_zh_alias = SectorScannerService._get_overseas_fallback_codes(
            "科技", "US"
        )

        self.assertEqual(codes_from_en_alias, codes_from_zh_alias)
        self.assertGreater(len(codes_from_en_alias), 0)

    def test_provider_unmatched_metadata_keeps_raw_label(self):
        matched = SectorScannerService._match_sector_metadata("Technology", "Utilities")

        self.assertFalse(matched["matched"])
        self.assertEqual(matched["canonical_key"], "technology")
        self.assertEqual(matched["display_label"], "Technology")
        self.assertIn("tech", matched["aliases"])
        self.assertEqual(matched["raw_provider_label"], "Utilities")

    def test_unknown_sector_fallback_and_match_fail_safe(self):
        unknown_codes = SectorScannerService._get_overseas_fallback_codes(
            "Unknown Sector",
            "US",
        )
        is_match = SectorScannerService._is_sector_match(
            "Unknown Sector",
            ["Tech", "Semiconductors"],
        )

        self.assertEqual(unknown_codes, [])
        self.assertFalse(is_match)


if __name__ == "__main__":
    unittest.main()
