import unittest
import sys
import os
import json
import logging
from unittest.mock import Mock
from typing import Dict, Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from tool.proof_tool import ProofAgent, _strip_markdown_code_fences

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TestProofAgentUnit(unittest.TestCase):
    def setUp(self):
        api_key = os.getenv("OPENROUTER_API_KEY", "test_key")
        self.agent = ProofAgent(api_key)

    def test_initialization(self):
        self.assertIsNotNone(self.agent.api_key)
        self.assertEqual(self.agent.model, "x-ai/grok-4-fast")
        self.assertIn("web_search", self.agent.tools)
        self.assertIn("python_execute", self.agent.tools)
        self.assertEqual(len(self.agent.tool_schemas), 2)

    def test_load_prompt_valid(self):
        result = self.agent._load_prompt("prompts/proof_prompt.md")
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_load_prompt_invalid(self):
        result = self.agent._load_prompt("nonexistent_file.md")
        self.assertEqual(result, "")
        logger.info("Prompt file not found handled correctly")

    def test_interpolate_basic(self):
        text = "Today is {current_date} at {current_time}"
        values = {"current_date": "2025-01-01", "current_time": "12:00:00"}
        result = self.agent._interpolate(text, values)
        self.assertEqual(result, "Today is 2025-01-01 at 12:00:00")

    def test_interpolate_empty_text(self):
        result = self.agent._interpolate("", {"key": "value"})
        self.assertEqual(result, "")

    def test_interpolate_no_placeholders(self):
        text = "No placeholders here"
        result = self.agent._interpolate(text, {"key": "value"})
        self.assertEqual(result, text)

    def test_calculate_costs(self):
        result = self.agent._calculate_costs(1000000, 500000)
        self.assertEqual(result["input_usd"], 0.20)
        self.assertEqual(result["output_usd"], 0.25)
        self.assertEqual(result["total_usd"], 0.45)

    def test_calculate_costs_zero(self):
        result = self.agent._calculate_costs(0, 0)
        self.assertEqual(result["input_usd"], 0.0)
        self.assertEqual(result["output_usd"], 0.0)
        self.assertEqual(result["total_usd"], 0.0)

    def test_parse_tool_call_dict_format(self):
        tool_call = {
            "id": "call_123",
            "function": {
                "name": "web_search",
                "arguments": '{"query": "test"}'
            }
        }
        name, args, call_id = self.agent._parse_tool_call(tool_call)
        self.assertEqual(name, "web_search")
        self.assertEqual(args, {"query": "test"})
        self.assertEqual(call_id, "call_123")

    def test_parse_tool_call_object_format(self):
        mock_tool_call = Mock()
        mock_tool_call.id = "call_456"
        mock_tool_call.function.name = "python_execute"
        mock_tool_call.function.arguments = '{"code": "print(1)"}'
        
        name, args, call_id = self.agent._parse_tool_call(mock_tool_call)
        self.assertEqual(name, "python_execute")
        self.assertEqual(args, {"code": "print(1)"})
        self.assertEqual(call_id, "call_456")

    def test_parse_tool_call_invalid_format(self):
        with self.assertRaises(ValueError):
            self.agent._parse_tool_call("invalid")

    def test_parse_tool_call_missing_arguments(self):
        tool_call = {
            "id": "call_123",
            "function": {
                "name": "web_search"
            }
        }
        name, args, call_id = self.agent._parse_tool_call(tool_call)
        self.assertEqual(args, {})

    def test_execute_tool_unknown_tool(self):
        tool_call = {
            "id": "call_123",
            "function": {
                "name": "unknown_tool",
                "arguments": "{}"
            }
        }
        result = self.agent._execute_tool(tool_call)
        self.assertIn("error", result)
        self.assertEqual(result["error"], "Unknown tool: unknown_tool")
        logger.info(f"Unknown tool handled: {result['error']}")

    def test_execute_tool_web_search(self):
        tool_call = {
            "id": "call_123",
            "function": {
                "name": "web_search",
                "arguments": '{"query": "test"}'
            }
        }
        result = self.agent._execute_tool(tool_call)
        self.assertIn("tool_call_id", result)
        self.assertIn("tool_name", result)
        self.assertEqual(result["tool_name"], "web_search")
        logger.info(f"Web search executed: {result.get('error', 'success')}")

    def test_execute_tool_python_execute(self):
        tool_call = {
            "id": "call_456",
            "function": {
                "name": "python_execute",
                "arguments": '{"code": "print(42)"}'
            }
        }
        result = self.agent._execute_tool(tool_call)
        self.assertIn("tool_call_id", result)
        self.assertIn("tool_name", result)
        self.assertEqual(result["tool_name"], "python_execute")
        if "success" in result:
            logger.info(f"Python execute success: {result['success']}")

    def test_execute_tool_invalid_json(self):
        tool_call = {
            "id": "call_123",
            "function": {
                "name": "web_search",
                "arguments": "invalid json{"
            }
        }
        result = self.agent._execute_tool(tool_call)
        self.assertIn("error", result)
        logger.info(f"Invalid JSON handled: {result['error']}")

    def test_handle_embedded_tool_calls_valid(self):
        result = {
            "tool_calls": [
                {
                    "id": "emb_1",
                    "function": {
                        "name": "python_execute",
                        "arguments": '{"code": "print(1)"}'
                    }
                }
            ]
        }
        messages = []
        tools_used = set()
        handled = self.agent._handle_embedded_tool_calls(result, messages, tools_used)
        self.assertTrue(handled)
        self.assertIn("python_execute", tools_used)
        self.assertGreater(len(messages), 0)

    def test_handle_embedded_tool_calls_invalid_structure(self):
        result = {
            "tool_calls": ["invalid"]
        }
        messages = []
        tools_used = set()
        handled = self.agent._handle_embedded_tool_calls(result, messages, tools_used)
        self.assertTrue(handled)
        logger.info("Invalid embedded tool call structure handled")

    def test_handle_embedded_tool_calls_no_tool_calls(self):
        result = {}
        messages = []
        tools_used = set()
        handled = self.agent._handle_embedded_tool_calls(result, messages, tools_used)
        self.assertFalse(handled)


class TestProofAgentEdgeCases(unittest.TestCase):
    def setUp(self):
        api_key = os.getenv("OPENROUTER_API_KEY", "test_key")
        self.agent = ProofAgent(api_key)

    def test_prove_claim_empty_claim(self):
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message = Mock()
        mock_response.choices[0].message.content = '{"verdict": "UNVERIFIABLE"}'
        mock_response.choices[0].message.tool_calls = None
        mock_response.choices[0].message.model_dump = Mock(return_value={"content": '{"verdict": "UNVERIFIABLE"}'})
        mock_response.choices[0].finish_reason = "stop"
        mock_response.usage = Mock()
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50
        
        self.agent.client.chat.completions.create = Mock(return_value=mock_response)
        
        content, metadata = self.agent.prove_claim("", max_iterations=1)
        self.assertIn("verdict", content)
        logger.info(f"Empty claim handled: {content.get('verdict')}")

    def test_prove_claim_max_iterations(self):
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message = Mock()
        mock_response.choices[0].message.content = '{"reasoning": "thinking..."}'
        mock_response.choices[0].message.tool_calls = None
        mock_response.choices[0].message.model_dump = Mock(return_value={"content": '{"reasoning": "thinking..."}'})
        mock_response.choices[0].finish_reason = "stop"
        mock_response.usage = Mock()
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50
        
        self.agent.client.chat.completions.create = Mock(return_value=mock_response)
        
        content, metadata = self.agent.prove_claim("Test claim", max_iterations=2)
        self.assertIn("iterations_used", metadata)
        self.assertLessEqual(metadata["iterations_used"], 3)
        logger.info(f"Max iterations respected: {metadata['iterations_used']}")

    def test_prove_claim_invalid_json_response(self):
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message = Mock()
        mock_response.choices[0].message.content = "Not valid JSON"
        mock_response.choices[0].message.tool_calls = None
        mock_response.choices[0].message.model_dump = Mock(return_value={"content": "Not valid JSON"})
        mock_response.choices[0].finish_reason = "stop"
        mock_response.usage = Mock()
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50
        
        self.agent.client.chat.completions.create = Mock(return_value=mock_response)
        
        content, metadata = self.agent.prove_claim("Test claim", max_iterations=1)
        self.assertIn("error", content)
        logger.info(f"Invalid JSON response handled: {content.get('error')}")

    def test_prove_claim_api_error(self):
        self.agent.client.chat.completions.create = Mock(side_effect=Exception("API Error"))
        
        content, metadata = self.agent.prove_claim("Test claim", max_iterations=1)
        self.assertIn("error", content)
        self.assertEqual(content["error"], "API Error")
        logger.info(f"API error handled: {content['error']}")

    def test_prove_claim_with_tool_calls(self):
        mock_tool_call = Mock()
        mock_tool_call.id = "call_123"
        mock_tool_call.function.name = "python_execute"
        mock_tool_call.function.arguments = '{"code": "print(1)"}'

        mock_response_with_tools = Mock()
        mock_response_with_tools.choices = [Mock()]
        mock_response_with_tools.choices[0].message = Mock()
        mock_response_with_tools.choices[0].message.content = None
        mock_response_with_tools.choices[0].message.tool_calls = [mock_tool_call]
        mock_response_with_tools.choices[0].message.model_dump = Mock(return_value={"content": None, "tool_calls": [mock_tool_call]})
        mock_response_with_tools.choices[0].finish_reason = "tool_calls"
        mock_response_with_tools.usage = Mock()
        mock_response_with_tools.usage.prompt_tokens = 100
        mock_response_with_tools.usage.completion_tokens = 50

        mock_response_final = Mock()
        mock_response_final.choices = [Mock()]
        mock_response_final.choices[0].message = Mock()
        mock_response_final.choices[0].message.content = '{"verdict": "PROVEN"}'
        mock_response_final.choices[0].message.tool_calls = None
        mock_response_final.choices[0].message.model_dump = Mock(return_value={"content": '{"verdict": "PROVEN"}'})
        mock_response_final.choices[0].finish_reason = "stop"
        mock_response_final.usage = Mock()
        mock_response_final.usage.prompt_tokens = 150
        mock_response_final.usage.completion_tokens = 75

        self.agent.client.chat.completions.create = Mock(side_effect=[
            mock_response_with_tools,
            mock_response_final
        ])

        content, metadata = self.agent.prove_claim("Test claim", max_iterations=5)
        self.assertIn("verdict", content)
        self.assertIn("tools_used", metadata)
        logger.info(f"Tool calls handled: {metadata.get('tools_used')}")


class TestStripMarkdownCodeFences(unittest.TestCase):
    def test_strip_simple_fence(self):
        content = "```json\n{\"key\": \"value\"}\n```"
        result = _strip_markdown_code_fences(content)
        self.assertEqual(result, '{"key": "value"}')

    def test_strip_no_fence(self):
        content = '{"key": "value"}'
        result = _strip_markdown_code_fences(content)
        self.assertEqual(result, '{"key": "value"}')

    def test_strip_empty_content(self):
        result = _strip_markdown_code_fences("")
        self.assertEqual(result, "")

    def test_strip_only_opening_fence(self):
        content = "```json\n{\"key\": \"value\"}"
        result = _strip_markdown_code_fences(content)
        self.assertEqual(result, '{"key": "value"}')

    def test_strip_multiline_content(self):
        content = "```\nline1\nline2\nline3\n```"
        result = _strip_markdown_code_fences(content)
        self.assertEqual(result, "line1\nline2\nline3")


if __name__ == '__main__':
    unittest.main()
