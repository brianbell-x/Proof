"""
Python REPL tool for the Prover system.
Provides a sandboxed environment for executing Python code, calculations, and data analysis.
"""

import io
import contextlib
import traceback
from typing import Dict, Any
from datetime import datetime


class PythonREPLTool:
    """
    A tool for executing Python code in a sandboxed environment.
    Useful for calculations, data analysis, and mathematical verification.
    """

    def __init__(self, timeout: int = 10, max_output_length: int = None):
        """
        Initialize the Python REPL tool.

        Args:
            timeout: Maximum execution time in seconds (not implemented yet)
            max_output_length: Maximum length of output to return (optional, no limit)
        """
        self.timeout = timeout
        self.max_output_length = max_output_length
        self._globals = {
            "__builtins__": __builtins__,
            # Add commonly used modules
            "math": __import__("math"),
            "statistics": __import__("statistics"),
            "datetime": __import__("datetime"),
            "json": __import__("json"),
        }

    def execute(self, code: str) -> Dict[str, Any]:
        """
        Execute Python code in a sandboxed environment.

        Args:
            code: The Python code to execute

        Returns:
            Dict containing execution results and metadata
        """
        # Capture stdout and stderr
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        result = {
            "code": code,
            "timestamp": datetime.now().isoformat(),
            "success": False,
            "output": "",
            "error": "",
            "execution_time": None
        }

        try:
            # Execute the code with restricted globals
            with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
                start_time = datetime.now()

                # Compile and execute the code
                compiled_code = compile(code, '<string>', 'exec')
                exec(compiled_code, self._globals)

                end_time = datetime.now()
                execution_time = (end_time - start_time).total_seconds()

            result["success"] = True
            result["output"] = stdout_capture.getvalue()
            result["execution_time"] = execution_time

            # Check for stderr output (warnings, etc.)
            stderr_output = stderr_capture.getvalue()
            if stderr_output:
                result["warnings"] = stderr_output

        except Exception as e:
            result["error"] = str(e)
            result["traceback"] = traceback.format_exc()

            # Include any partial output
            result["output"] = stdout_capture.getvalue()

        # Truncate output if too long (only if max_output_length is set)
        if self.max_output_length and len(result["output"]) > self.max_output_length:
            result["output"] = result["output"][:self.max_output_length] + "... (truncated)"
            result["truncated"] = True

        return result

    def calculate(self, expression: str) -> Dict[str, Any]:
        """
        Evaluate a mathematical expression.

        Args:
            expression: The mathematical expression to evaluate

        Returns:
            Dict containing the result and metadata
        """
        # Wrap the expression in a way that captures the result
        code = f"""
result = {expression}
print(repr(result))
"""
        return self.execute(code)

    def analyze_data(self, data_code: str) -> Dict[str, Any]:
        """
        Execute data analysis code.

        Args:
            data_code: Python code for data analysis

        Returns:
            Dict containing analysis results
        """
        return self.execute(data_code)


def get_tool_schema() -> Dict[str, Any]:
    """
    Get the JSON schema for the Python REPL tool.

    Returns:
        Tool schema dictionary
    """
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
                        "description": "The Python code to execute. Include print statements to show results. Available modules: math, statistics, datetime, json."
                    }
                },
                "required": ["code"]
            }
        }
    }


if __name__ == "__main__":
    # Example usage
    tool = PythonREPLTool()

    # Test calculation
    result = tool.calculate("2 * 3.14159 * 5")  # Circumference
    print("Calculation result:")
    print(result)

    # Test code execution
    code_result = tool.execute("""
import math
radius = 5
area = math.pi * radius ** 2
volume = (4/3) * math.pi * radius ** 3
print(f"Area: {area:.2f}")
print(f"Volume: {volume:.2f}")
""")
    print("\nCode execution result:")
    print(code_result)