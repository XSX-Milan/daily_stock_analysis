import unittest

from src.recommendation.models import (
    CompositeScore,
    DimensionScore,
    MarketRegion,
    RecommendationPriority,
    ScoringWeights,
    StockRecommendation,
    WatchlistItem,
)


class RecommendationModelsTestCase(unittest.TestCase):
    def test_model_symbols_importable(self) -> None:
        self.assertIsNotNone(RecommendationPriority)
        self.assertIsNotNone(MarketRegion)
        self.assertIsNotNone(DimensionScore)
        self.assertIsNotNone(CompositeScore)
        self.assertIsNotNone(StockRecommendation)
        self.assertIsNotNone(ScoringWeights)
        self.assertIsNotNone(WatchlistItem)

    def test_scoring_weights_to_fractions(self) -> None:
        weights = ScoringWeights(technical=30, fundamental=25, sentiment=20, macro=15, risk=10)
        fractions = weights.to_fractions()

        self.assertEqual(fractions["technical"], 0.30)
        self.assertEqual(fractions["fundamental"], 0.25)
        self.assertEqual(fractions["sentiment"], 0.20)
        self.assertEqual(fractions["macro"], 0.15)
        self.assertEqual(fractions["risk"], 0.10)
        self.assertAlmostEqual(sum(fractions.values()), 1.0)

    def test_invalid_scoring_weights_sum_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            ScoringWeights(technical=40, fundamental=25, sentiment=20, macro=15, risk=10)


if __name__ == "__main__":
    unittest.main()
