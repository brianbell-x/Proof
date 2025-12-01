import os
import json
import time
import io
import contextlib
import traceback
import requests
import shortuuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from openai import OpenAI

proofs_dir = "proofs"
os.makedirs(proofs_dir, exist_ok=True)

def _strip_markdown_code_fences(content: str) -> str:
    if not content:
        return content
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        content = "\n".join(lines)
    return content.strip()

class JSONLogger:
    def __init__(self, proof_id: str, claim: str):
        self.proof_id = proof_id
        self.claim = claim
        self.timestamp = datetime.now().isoformat()
        self.events: List[Dict[str, Any]] = []
        self.log_file = os.path.join(proofs_dir, f"{proof_id}.json")
        
    def _init_log(self) -> None:
        log_data = {
            "proof_id": self.proof_id,
            "claim": self.claim,
            "timestamp": self.timestamp,
            "events": [],
            "metadata": None,
        }
        try:
            with open(self.log_file, "w", encoding="utf-8") as f:
                json.dump(log_data, f, indent=2)
        except (OSError, PermissionError):
            pass
    
    def log_event(self, event_type: str, data: Dict[str, Any]) -> None:
        event = {
            "type": event_type,
            **data
        }
        self.events.append(event)
        self._save_log()
    
    def _save_log(self) -> None:
        try:
            with open(self.log_file, "r", encoding="utf-8") as f:
                log_data = json.load(f)
            log_data["events"] = self.events
            with open(self.log_file, "w", encoding="utf-8") as f:
                json.dump(log_data, f, indent=2)
        except (OSError, PermissionError, json.JSONDecodeError):
            pass
    
    def set_metadata(self, metadata: Dict[str, Any]) -> None:
        try:
            with open(self.log_file, "r", encoding="utf-8") as f:
                log_data = json.load(f)
            log_data["metadata"] = metadata
            log_data["events"] = self.events
            with open(self.log_file, "w", encoding="utf-8") as f:
                json.dump(log_data, f, indent=2)
        except (OSError, PermissionError, json.JSONDecodeError):
            pass


class WebSearchTool:
    def __init__(self, api_key: str, base_url: str = "https://openrouter.ai/api/v1"):
        self.api_key = api_key
        self.base_url = base_url

    def search(self, query: str, max_results: Optional[int] = None) -> Dict[str, Any]:
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "x-ai/grok-4.1-fast:online",
                    "messages": [
                        {
                            "role": "user",
                            "content": f"Return Search Results for: {query}",
                        }
                    ],
                    "usage": {
                        "include": True
                    }
                },
            )

            if response.status_code != 200:
                return {
                    "error": f"Search failed with status {response.status_code}",
                    "query": query,
                    "results": [],
                }

            data = response.json()
            content = data["choices"][0]["message"]["content"]
            annotations = data["choices"][0]["message"].get("annotations", [])

            return {
                "query": query,
                "content": content,
                "results": self._parse_search_results(annotations, max_results),
            }

        except (requests.RequestException, KeyError, json.JSONDecodeError) as e:
            return {
                "error": str(e),
                "query": query,
                "results": [],
            }

    def _parse_search_results(
        self, annotations: List[Dict], max_results: Optional[int] = None
    ) -> List[Dict]:
        results = []
        for annotation in annotations:
            if annotation.get("type") == "url_citation":
                citation = annotation["url_citation"]
                results.append(
                    {
                        "title": citation.get("title", "Untitled"),
                        "url": citation["url"],
                        "content": citation.get("content", ""),
                        "type": "citation",
                    }
                )
        return results[:max_results] if max_results else results

def get_search_schema() -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for real-time information to verify claims. Use this when you need current data, statistics, or evidence from reliable sources.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query. Be specific and include relevant keywords for accurate results.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of search results to return (optional, no limit)",
                        "minimum": 1,
                    },
                },
                "required": ["query"],
            },
        },
    }


class CodeExecutionTool:
    TIMEOUT_SECONDS = 300

    def __init__(self, max_output_length: Optional[int] = None):
        self.timeout = self.TIMEOUT_SECONDS
        self.max_output_length = max_output_length
        self._globals = {
            "__builtins__": __builtins__,
            "math": __import__("math"),
            "statistics": __import__("statistics"),
            "datetime": __import__("datetime"),
            "json": __import__("json"),
        }

    def _execute_code(self, code: str, stdout_capture: io.StringIO, stderr_capture: io.StringIO) -> None:
        with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
            compiled_code = compile(code, "<string>", "exec")
            exec(compiled_code, self._globals)

    def execute(self, code: str) -> Dict[str, Any]:
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        result = {
            "code": code,
            "success": False,
            "output": "",
            "error": "",
            "execution_time": None,
        }

        start_time = datetime.now()
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(self._execute_code, code, stdout_capture, stderr_capture)
                try:
                    future.result(timeout=self.timeout)
                    end_time = datetime.now()
                    execution_time = (end_time - start_time).total_seconds()

                    result["success"] = True
                    result["output"] = stdout_capture.getvalue()
                    result["execution_time"] = execution_time

                    stderr_output = stderr_capture.getvalue()
                    if stderr_output:
                        result["warnings"] = stderr_output
                except FutureTimeoutError:
                    end_time = datetime.now()
                    execution_time = (end_time - start_time).total_seconds()
                    result["error"] = f"Execution timed out after {self.timeout} seconds"
                    result["execution_time"] = execution_time
                    result["output"] = stdout_capture.getvalue()
                    result["timeout"] = True
                except (
                    SyntaxError,
                    NameError,
                    TypeError,
                    ValueError,
                    ZeroDivisionError,
                    OverflowError,
                ) as e:
                    end_time = datetime.now()
                    execution_time = (end_time - start_time).total_seconds()
                    result["error"] = str(e)
                    result["traceback"] = traceback.format_exc()
                    result["output"] = stdout_capture.getvalue()
                    result["execution_time"] = execution_time
        except Exception as e:
            end_time = datetime.now()
            execution_time = (end_time - start_time).total_seconds()
            result["error"] = str(e)
            result["traceback"] = traceback.format_exc()
            result["output"] = stdout_capture.getvalue()
            result["execution_time"] = execution_time

        if (
            self.max_output_length
            and len(result["output"]) > self.max_output_length
        ):
            result["output"] = (
                result["output"][: self.max_output_length] + "... (truncated)"
            )
            result["truncated"] = True

        return result

    def calculate(self, expression: str) -> Dict[str, Any]:
        code = f"result = {expression}\nprint(repr(result))"
        return self.execute(code)

    def analyze_data(self, data_code: str) -> Dict[str, Any]:
        return self.execute(data_code)


def get_python_schema() -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "python_execute",
            "description": "Execute Python code for calculations, data analysis, and mathematical verification. Use this for numerical computations, statistical analysis, or when you need to perform calculations to verify claims.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "The Python code to execute. Include print statements to show results. Available modules: math, statistics, datetime, json.",
                    }
                },
                "required": ["code"],
            },
        },
    }


class ProofTool:
    def __init__(self, api_key: str, model: str = "x-ai/grok-4.1-fast"):
        self.api_key = api_key
        self.model = model
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )
        self.tools = {
            "web_search": WebSearchTool(api_key),
            "python_execute": CodeExecutionTool(),
        }
        self.master_prompt = self._load_prompt("prompts/proof_prompt.md")
        current_date = datetime.now().strftime("%Y-%m-%d")
        current_time = datetime.now().strftime("%H:%M:%S")
        self.system_prompt = self._interpolate(
            self.master_prompt,
            {"current_date": current_date, "current_time": current_time},
        )
        self.tool_schemas = [get_search_schema(), get_python_schema()]
        self.logger: Optional[JSONLogger] = None

    def _load_prompt(self, path: str) -> str:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return ""

    def _interpolate(self, text: str, values: Dict[str, str]) -> str:
        if not text:
            return text
        for k, v in values.items():
            text = text.replace("{" + k + "}", v)
        return text

    def _calculate_costs(
        self, prompt_tokens: int, completion_tokens: int, actual_cost: Optional[float] = None
    ) -> Dict[str, Any]:
        if actual_cost is not None:
            return {
                "total_usd": round(actual_cost, 6),
                "source": "api"
            }
        
        input_cost_per_million = 0.20
        output_cost_per_million = 0.50
        input_cost = (prompt_tokens / 1_000_000) * input_cost_per_million
        output_cost = (completion_tokens / 1_000_000) * output_cost_per_million
        total_cost = input_cost + output_cost
        return {
            "input_usd": round(input_cost, 6),
            "output_usd": round(output_cost, 6),
            "total_usd": round(total_cost, 6),
            "source": "estimated"
        }

    def _parse_tool_call(self, tool_call: Any) -> Tuple[str, Dict, str]:
        if hasattr(tool_call, "function"):
            tool_name = tool_call.function.name
            arguments = json.loads(tool_call.function.arguments)
            tool_call_id = tool_call.id
        elif isinstance(tool_call, dict):
            tool_name = tool_call.get("function", {}).get("name")
            arguments = json.loads(
                tool_call.get("function", {}).get("arguments", "{}")
            )
            tool_call_id = tool_call.get("id")
        else:
            raise ValueError(f"Unexpected tool_call format: {type(tool_call)}")
        return tool_name, arguments, tool_call_id

    def _execute_tool(self, tool_call: Any) -> Dict[str, Any]:
        start_time = time.time()

        try:
            tool_name, arguments, tool_call_id = self._parse_tool_call(tool_call)

            if tool_name not in self.tools:
                result = {
                    "error": f"Unknown tool: {tool_name}",
                    "tool_call_id": tool_call_id,
                }
            else:
                tool = self.tools[tool_name]
                if tool_name == "web_search":
                    result = tool.search(**arguments)
                elif tool_name == "python_execute":
                    result = tool.execute(**arguments)
                else:
                    result = {"error": f"Tool {tool_name} not implemented"}

                result["tool_call_id"] = tool_call_id
                result["tool_name"] = tool_name

            duration = time.time() - start_time
            
            if self.logger:
                self.logger.log_event("tool_result", {
                    "tool_name": tool_name,
                    "tool_call_id": tool_call_id,
                    "duration": round(duration, 3),
                    "result": result
                })

            return result

        except (ValueError, json.JSONDecodeError, KeyError) as e:
            duration = time.time() - start_time
            try:
                _, _, tool_call_id = self._parse_tool_call(tool_call)
                tool_name = self._parse_tool_call(tool_call)[0]
            except Exception:
                tool_call_id = None
                tool_name = None
            
            error_result = {
                "error": str(e),
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
            }
            
            if self.logger:
                self.logger.log_event("tool_result_error", {
                    "tool_name": tool_name or "unknown",
                    "tool_call_id": tool_call_id or "unknown",
                    "duration": round(duration, 3),
                    "error": str(e)
                })
            
            return error_result

    def _handle_embedded_tool_calls(
        self, result: Dict, messages: List[Dict], tools_used: set
    ) -> bool:
        if not isinstance(result.get("tool_calls"), list):
            return False

        embedded_calls = result.get("tool_calls", [])
        if not embedded_calls:
            return False

        processed_count = 0
        for emb in embedded_calls:
            if not (
                isinstance(emb, dict)
                and isinstance(emb.get("function"), dict)
            ):
                continue

            emb_id = emb.get("id") or f"embedded_{int(time.time() * 1000)}"
            emb_name = emb.get("function", {}).get("name")
            emb_args = emb.get("function", {}).get("arguments", "{}")

            emb_tool_call = {
                "id": emb_id,
                "type": "function",
                "function": {"name": emb_name, "arguments": emb_args},
            }

            try:
                if emb_name:
                    tools_used.add(emb_name)
                tool_result = self._execute_tool(emb_tool_call)
                tool_message = {
                    "role": "tool",
                    "tool_call_id": emb_id,
                    "content": json.dumps(tool_result),
                }
                messages.append(tool_message)
                processed_count += 1
            except Exception as e:
                if self.logger:
                    self.logger.log_event("embedded_tool_error", {
                        "tool_call_id": emb_id,
                        "tool_name": emb_name,
                        "error": str(e)
                    })

        return processed_count > 0

    def prove_claim(
        self, claim: str, max_iterations: Optional[int] = None
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        proof_id = shortuuid.uuid()
        self.logger = JSONLogger(proof_id, claim)
        self.logger._init_log()

        start_time = time.time()
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": claim},
        ]

        iteration = 0
        final_result = None
        tools_used = set()
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_cost = 0.0

        while True:
            iteration += 1
            if max_iterations and iteration > max_iterations:
                break

            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0,
                    response_format={"type": "json_object"},
                    extra_body={
                        "reasoning": {
                            "effort": "high"
                        },
                        "usage": {
                            "include": True
                        }
                    },
                )

                if hasattr(response, "usage") and response.usage:
                    usage = response.usage
                    total_prompt_tokens += getattr(usage, "prompt_tokens", 0)
                    total_completion_tokens += getattr(
                        usage, "completion_tokens", 0
                    )
                    api_cost = getattr(usage, "cost", None)
                    if api_cost is not None:
                        total_cost += api_cost

                message = response.choices[0].message
                message_dict = (
                    message.model_dump()
                    if hasattr(message, "model_dump")
                    else message
                )
                messages.append(message_dict)

                content = message.content or ""
                
                try:
                    cleaned_content = _strip_markdown_code_fences(content)
                    result = json.loads(cleaned_content) if cleaned_content else {}
                except (json.JSONDecodeError, TypeError):
                    result = {"error": "Invalid JSON response", "raw_content": content}
                    if self.logger:
                        self.logger.log_event("model_output_parse_error", {
                            "content": content,
                            "error": "Failed to parse JSON response"
                        })

                if self.logger:
                    self.logger.log_event("model_output", {
                        "content": result
                    })

                verdict = result.get("verdict") if isinstance(result, dict) else None
                if verdict is not None:
                    final_result = result
                    break

                embedded_tool_calls = result.get("tool_calls", []) if isinstance(result, dict) else []
                if isinstance(result, dict) and embedded_tool_calls:
                    if self._handle_embedded_tool_calls(result, messages, tools_used):
                        continue

            except Exception as e:
                if self.logger:
                    self.logger.log_event("iteration_error", {
                        "error": str(e)
                    })
                
                end_time = time.time()
                elapsed_time = end_time - start_time
                cost_info = self._calculate_costs(
                    total_prompt_tokens, total_completion_tokens, total_cost if total_cost > 0 else None
                )
                tokens_info = {
                    "prompt": total_prompt_tokens,
                    "completion": total_completion_tokens,
                    "total": total_prompt_tokens + total_completion_tokens,
                }
                metadata = {
                    "time_seconds": round(elapsed_time, 3),
                    "tokens": tokens_info,
                    "cost": cost_info,
                    "timestamp": datetime.now().isoformat(),
                }
                content = {
                    "error": str(e),
                    "claim": claim,
                }
                
                if self.logger:
                    self.logger.set_metadata(metadata)
                
                return (content, metadata)

        end_time = time.time()
        elapsed_time = end_time - start_time
        cost_info = self._calculate_costs(
            total_prompt_tokens, total_completion_tokens, total_cost if total_cost > 0 else None
        )
        tokens_info = {
            "prompt": total_prompt_tokens,
            "completion": total_completion_tokens,
            "total": total_prompt_tokens + total_completion_tokens,
        }

        metadata = {
            "time_seconds": round(elapsed_time, 3),
            "tokens": tokens_info,
            "cost": cost_info,
            "timestamp": datetime.now().isoformat(),
        }

        if final_result:
            if self.logger:
                self.logger.set_metadata(metadata)
            return (final_result, metadata)
        else:
            content = {
                "error": "No verdict reached",
                "claim": claim,
                "partial_result": result if "result" in locals() else None,
            }
            if self.logger:
                self.logger.set_metadata(metadata)
            return (content, metadata)


def get_tool_schema() -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "prove_claim",
            "description": "Verify whether a claim is true or false by stress-testing it through rigorous logical analysis and evidence gathering. Use this tool when the user wants to know if a claim is true or false, or when they ask about verifying a statement. The tool will return a verdict (PROVEN, DISPROVEN, UNSUPPORTED, or UNVERIFIABLE) along with detailed reasoning, evidence, and derivation steps.",
            "parameters": {
                "type": "object",
                "properties": {
                    "claim": {
                        "type": "string",
                        "description": "The claim or statement to verify. This should be a clear, specific statement that can be evaluated.",
                    },
                    "max_iterations": {
                        "type": "integer",
                        "description": "Maximum number of reasoning iterations (optional, defaults to unlimited)",
                        "minimum": 1,
                    },
                },
                "required": ["claim"],
            },
        },
    }


if __name__ == "__main__":
    import argparse
    import logging
    import sys
    from dotenv import load_dotenv

    load_dotenv()

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print("OPENROUTER_API_KEY not set. Skipping live test.")
        sys.exit(0)

    parser = argparse.ArgumentParser(description="Inline ProofAgent tool-call verifier")
    parser.add_argument("claim", nargs="*", help="Claim text to analyze")
    args = parser.parse_args()

    claim_text = " ".join(args.claim).strip() or "Donald Trump is racist."

    agent = ProofTool(api_key)

    try:
        for h in logging.getLogger().handlers:
            h.setLevel(logging.INFO)
        logging.getLogger().setLevel(logging.INFO)
    except Exception:
        pass

    tool_events = []
    _original_execute_tool = agent._execute_tool

    def _wrapper_execute_tool(tool_call, _orig=_original_execute_tool):
        try:
            if hasattr(tool_call, "function"):
                tool_name = getattr(tool_call.function, "name", "unknown")
                tool_call_id = getattr(tool_call, "id", None)
                arguments_raw = getattr(tool_call.function, "arguments", "{}")
                arguments = json.loads(arguments_raw or "{}")
            elif isinstance(tool_call, dict):
                tool_name = tool_call.get("function", {}).get("name", "unknown")
                tool_call_id = tool_call.get("id")
                arguments = json.loads(
                    tool_call.get("function", {}).get("arguments", "{}") or "{}"
                )
            else:
                tool_name = "unknown"
                tool_call_id = None
                arguments = {}
        except Exception as e:
            print(f"Error parsing tool_call: {e}")
            tool_name = "unknown"
            tool_call_id = None
            arguments = {}

        code_snippet = arguments.get("code", "")
        preview = ""
        try:
            if isinstance(code_snippet, str):
                preview = code_snippet[:400].replace("\n", "\\n")
        except Exception:
            preview = "<unavailable>"

        print("\nTOOL CALL")
        print(f"  id={tool_call_id} name={tool_name}")
        if tool_name == "python_execute":
            print(
                f"  code_length={len(code_snippet) if isinstance(code_snippet, str) else 0}"
            )
            print(f"  code_preview='{preview}'")

        result = _orig(tool_call)
        try:
            keys = list(result.keys()) if isinstance(result, dict) else []
        except Exception:
            keys = []
        print("TOOL RESULT keys:", keys)
        tool_events.append(
            {
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "arguments_keys": list(arguments.keys()),
                "has_code": bool(arguments.get("code")),
                "result_keys": keys,
            }
        )
        return result

    agent._execute_tool = _wrapper_execute_tool

    test_cases = [
        ("The President of the United States is Bill Clinton", "web_search"),
        ("2025 is a prime number", "code_execution"),
    ]

    for test_claim, test_type in test_cases:
        print(f"\n{'='*80}")
        print(f"Running {test_type} test: {test_claim}")
        print(f"{'='*80}")
        
        content, metadata = agent.prove_claim(test_claim)

        print("\nFINAL OUTPUT (CONTENT)")
        try:
            print(json.dumps(content, indent=2))
        except Exception:
            print(content)
        
        print("\nMETADATA")
        try:
            print(json.dumps(metadata, indent=2))
        except Exception:
            print(metadata)
        
        print(f"\n{'='*80}\n")










