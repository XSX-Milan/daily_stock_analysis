# -*- coding: utf-8 -*-
"""Tests for config_registry field definitions and schema building.

Ensures every notification channel that has a sender implementation also
has its config keys registered in _FIELD_DEFINITIONS so the Web settings
page and /api/v1/system/config/schema can expose them.
"""

import unittest

from src.core.config_registry import (
    build_schema_response,
    get_category_definitions,
    get_field_definition,
)


class TestSlackFieldsRegistered(unittest.TestCase):
    """Slack config keys must be present in the registry."""

    _SLACK_KEYS = ("SLACK_BOT_TOKEN", "SLACK_CHANNEL_ID", "SLACK_WEBHOOK_URL")

    def test_field_definitions_exist(self):
        for key in self._SLACK_KEYS:
            field = get_field_definition(key)
            self.assertEqual(field["category"], "notification", f"{key} category")
            self.assertNotEqual(
                field["display_order"],
                9000,
                f"{key} should be explicitly registered, not inferred",
            )

    def test_bot_token_is_sensitive(self):
        field = get_field_definition("SLACK_BOT_TOKEN")
        self.assertTrue(field["is_sensitive"])
        self.assertEqual(field["ui_control"], "password")

    def test_webhook_url_is_sensitive(self):
        field = get_field_definition("SLACK_WEBHOOK_URL")
        self.assertTrue(field["is_sensitive"])
        self.assertEqual(field["ui_control"], "password")

    def test_channel_id_not_sensitive(self):
        field = get_field_definition("SLACK_CHANNEL_ID")
        self.assertFalse(field["is_sensitive"])

    def test_schema_response_includes_slack(self):
        schema = build_schema_response()
        notification_cat = next(
            (c for c in schema["categories"] if c["category"] == "notification"),
            None,
        )
        self.assertIsNotNone(notification_cat, "notification category missing")
        if notification_cat is None:
            return
        field_keys = {f["key"] for f in notification_cat["fields"]}
        for key in self._SLACK_KEYS:
            self.assertIn(key, field_keys, f"{key} missing from schema response")

    def test_display_order_between_discord_and_pushover(self):
        discord = get_field_definition("DISCORD_MAIN_CHANNEL_ID")
        pushover = get_field_definition("PUSHOVER_USER_KEY")
        for key in self._SLACK_KEYS:
            order = get_field_definition(key)["display_order"]
            self.assertGreater(
                order, discord["display_order"], f"{key} should appear after Discord"
            )
            self.assertLess(
                order, pushover["display_order"], f"{key} should appear before Pushover"
            )


class TestSensitiveFieldsUsePasswordControl(unittest.TestCase):
    """Every is_sensitive field must use ui_control='password' to avoid
    leaking secrets in the Web settings page."""

    def test_all_sensitive_fields_use_password(self):
        schema = build_schema_response()
        violations = []
        for cat in schema["categories"]:
            for field in cat["fields"]:
                if field.get("is_sensitive") and field.get("ui_control") != "password":
                    violations.append(field["key"])
        self.assertEqual(
            violations,
            [],
            f"Sensitive fields with non-password ui_control: {violations}",
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
