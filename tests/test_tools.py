import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from tools.python_repl import PythonREPLTool
from tools.search import WebSearchTool


class TestPythonREPLTool(unittest.TestCase):

    def setUp(self):
        self.tool = PythonREPLTool()

    def test_execute_simple_code(self):
        result = self.tool.execute("print(42)")
        self.assertTrue(result["success"])
        self.assertIn("42", result["output"])
        self.assertIsNotNone(result["execution_time"])

    def test_execute_calculation(self):
        result = self.tool.calculate("3 * 4 + 2")
        self.assertTrue(result["success"])
        self.assertIn("14", result["output"])

    def test_execute_with_error(self):
        result = self.tool.execute("1 / 0")
        self.assertFalse(result["success"])
        self.assertIn("error", result)
        self.assertIn("division by zero", result["error"])

    def test_execute_complex_code(self):
        code = """
import math
radius = 5
area = math.pi * radius ** 2
print(f"Area: {area:.2f}")
"""
        result = self.tool.execute(code)
        self.assertTrue(result["success"])
        self.assertIn("Area:", result["output"])


class TestWebSearchTool(unittest.TestCase):

    def setUp(self):
        self.tool = WebSearchTool("dummy_key")

    def test_initialization(self):
        self.assertIsNotNone(self.tool.api_key)
        self.assertEqual(self.tool.base_url, "https://openrouter.ai/api/v1")

    def test_search_error_handling(self):
        result = self.tool.search("test query")
        self.assertIn("error", result)
        self.assertEqual(result["query"], "test query")
        self.assertIn("timestamp", result)

    def test_get_tool_schema(self):
        from tools.search import get_tool_schema
        schema = get_tool_schema()
        self.assertEqual(schema["type"], "function")
        self.assertEqual(schema["function"]["name"], "web_search")
        self.assertIn("query", schema["function"]["parameters"]["properties"])
        self.assertIn("max_results", schema["function"]["parameters"]["properties"])


class TestPythonREPLSchema(unittest.TestCase):

    def test_get_tool_schema(self):
        from tools.python_repl import get_tool_schema
        schema = get_tool_schema()
        self.assertEqual(schema["type"], "function")
        self.assertEqual(schema["function"]["name"], "python_execute")
        self.assertIn("code", schema["function"]["parameters"]["properties"])


if __name__ == '__main__':
    unittest.main()
