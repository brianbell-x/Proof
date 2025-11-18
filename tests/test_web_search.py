import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from proof_tool import WebSearchTool, get_search_schema as get_tool_schema


class TestWebSearchTool(unittest.TestCase):
    def setUp(self):
        api_key = os.getenv("OPENROUTER_API_KEY", "dummy_key")
        self.tool = WebSearchTool(api_key)

    def test_initialization(self):
        self.assertIsNotNone(self.tool.api_key)
        self.assertEqual(self.tool.base_url, "https://openrouter.ai/api/v1")

    def test_schema(self):
        schema = get_tool_schema()
        self.assertEqual(schema["type"], "function")
        self.assertEqual(schema["function"]["name"], "web_search")
        self.assertIn("query", schema["function"]["parameters"]["properties"])
        self.assertIn("max_results", schema["function"]["parameters"]["properties"])
        required = schema["function"]["parameters"].get("required", [])
        self.assertIn("query", required)
        self.assertNotIn("max_results", required)

    def test_error_handling(self):
        invalid_tool = WebSearchTool("invalid_key")
        result = invalid_tool.search("test query")
        self.assertIn("error", result)
        self.assertEqual(result["query"], "test query")
        self.assertIn("timestamp", result)

        result = self.tool.search()
        self.assertIn("error", result)

    def test_response_structure(self):
        result = self.tool.search("test query")
        required_fields = ["query", "timestamp", "results"]
        for field in required_fields:
            self.assertIn(field, result, f"Missing field: {field}")
        self.assertIsInstance(result["results"], list)

    @unittest.skipUnless(
        os.getenv("OPENROUTER_API_KEY") and os.getenv("OPENROUTER_API_KEY") != "dummy_key",
        "Requires valid OPENROUTER_API_KEY"
    )
    def test_real_search(self):
        result = self.tool.search("Python programming", max_results=3)
        self.assertNotIn("error", result)
        self.assertIn("content", result)
        self.assertIn("results", result)
        self.assertGreater(len(result["results"]), 0)
        if result["results"]:
            self.assertLessEqual(len(result["results"]), 3)

if __name__ == '__main__':
    unittest.main()
