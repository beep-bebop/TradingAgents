import json
import unittest
from unittest.mock import patch

from tradingagents.dataflows import alpha_vantage_common, alpha_vantage_stock
from tradingagents.dataflows.alpha_vantage_common import AlphaVantageRateLimitError


class _Response:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


class AlphaVantageFreeTierTests(unittest.TestCase):
    def test_premium_information_response_is_treated_as_unavailable(self):
        def fake_get(*args, **kwargs):
            return _Response(
                json.dumps(
                    {
                        "Information": (
                            "Thank you for using Alpha Vantage! This is a premium "
                            "endpoint."
                        )
                    }
                )
            )

        with patch.dict("os.environ", {"ALPHA_VANTAGE_API_KEY": "demo"}):
            with patch.object(alpha_vantage_common.requests, "get", fake_get):
                with self.assertRaisesRegex(
                    AlphaVantageRateLimitError, "premium endpoint"
                ):
                    alpha_vantage_common._make_api_request(
                        "TIME_SERIES_DAILY_ADJUSTED", {}
                    )

    def test_stock_data_uses_free_daily_endpoint(self):
        calls = []

        def fake_request(function_name, params):
            calls.append(function_name)
            return "timestamp,open,high,low,close,volume\n2026-06-01,1,2,1,2,100\n"

        with patch.object(alpha_vantage_stock, "_make_api_request", fake_request):
            alpha_vantage_stock.get_stock("NVDA", "2026-06-01", "2026-06-02")

        self.assertEqual(calls, ["TIME_SERIES_DAILY"])


if __name__ == "__main__":
    unittest.main()
