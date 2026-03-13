import unittest

from src.core.config_registry import (
    build_schema_response,
    get_category_definitions,
    get_field_definition,
)


class RecommendationConfigRegistryTestCase(unittest.TestCase):
    def test_recommendation_category_is_registered(self) -> None:
        category_map = {item["category"]: item for item in get_category_definitions()}

        self.assertIn("recommendation", category_map)
        self.assertEqual(category_map["recommendation"]["title"], "推荐选股")
        self.assertEqual(
            category_map["recommendation"]["description"],
            "Stock recommendation scoring weights and parameters",
        )
        self.assertEqual(category_map["recommendation"]["display_order"], 65)

    def test_recommendation_fields_defaults_and_validation(self) -> None:
        expected_defaults = {
            "RECOMMEND_WEIGHT_TECHNICAL": "30",
            "RECOMMEND_WEIGHT_FUNDAMENTAL": "25",
            "RECOMMEND_WEIGHT_SENTIMENT": "20",
            "RECOMMEND_WEIGHT_MACRO": "15",
            "RECOMMEND_WEIGHT_RISK": "10",
            "RECOMMEND_SECTOR_TOP_N": "10",
            "RECOMMEND_SCORE_THRESHOLD_AI": "60",
        }

        for key, expected_default in expected_defaults.items():
            definition = get_field_definition(key)
            self.assertEqual(definition["category"], "recommendation")
            self.assertEqual(definition["default_value"], expected_default)

        weight_keys = (
            "RECOMMEND_WEIGHT_TECHNICAL",
            "RECOMMEND_WEIGHT_FUNDAMENTAL",
            "RECOMMEND_WEIGHT_SENTIMENT",
            "RECOMMEND_WEIGHT_MACRO",
            "RECOMMEND_WEIGHT_RISK",
        )
        for key in weight_keys:
            definition = get_field_definition(key)
            self.assertEqual(definition["data_type"], "number")
            self.assertEqual(definition["ui_control"], "number")
            self.assertEqual(definition["validation"].get("min"), 0)
            self.assertEqual(definition["validation"].get("max"), 100)

    def test_recommendation_category_appears_in_schema_response(self) -> None:
        categories = build_schema_response()["categories"]
        category_names = [item["category"] for item in categories]

        self.assertIn("recommendation", category_names)


if __name__ == "__main__":
    unittest.main()
