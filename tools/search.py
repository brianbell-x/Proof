"""
Web search tool for the Prover system.
Uses OpenRouter's web search capabilities to gather real-time information.
"""

import requests
import json
from typing import Dict, List, Any
from datetime import datetime


class WebSearchTool:
    """
    A tool for performing web searches to gather real-time information for claim verification.
    """

    def __init__(self, api_key: str, base_url: str = "https://openrouter.ai/api/v1"):
        """
        Initialize the web search tool.

        Args:
            api_key: OpenRouter API key
            base_url: OpenRouter API base URL
        """
        self.api_key = api_key
        self.base_url = base_url

    def search(self, query: str, max_results: int = 5) -> Dict[str, Any]:
        """
        Perform a web search using OpenRouter's web search capabilities.

        Args:
            query: The search query
            max_results: Maximum number of results to return

        Returns:
            Dict containing search results with metadata
        """
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "x-ai/grok-4-fast:online",
                    "messages": [
                        {
                            "role": "user",
                            "content": f"Search the web for: {query}. Provide factual, recent information with sources."
                        }
                    ],
                    "max_tokens": 10000,
                }
            )

            if response.status_code != 200:
                return {
                    "error": f"Search failed with status {response.status_code}",
                    "query": query,
                    "timestamp": datetime.now().isoformat(),
                    "results": []
                }

            data = response.json()
            content = data["choices"][0]["message"]["content"]

            # Extract any annotations (citations) from the response
            annotations = data["choices"][0]["message"].get("annotations", [])

            return {
                "query": query,
                "timestamp": datetime.now().isoformat(),
                "content": content,
                "annotations": annotations,
                "model": data.get("model", "unknown"),
                "results": self._parse_search_results(content, annotations)
            }

        except Exception as e:
            return {
                "error": str(e),
                "query": query,
                "timestamp": datetime.now().isoformat(),
                "results": []
            }

    def _parse_search_results(self, content: str, annotations: List[Dict]) -> List[Dict]:
        """
        Parse search results from the response content and annotations.

        Args:
            content: The response content
            annotations: List of annotation objects

        Returns:
            List of parsed search results
        """
        results = []

        # Process annotations for structured citation data
        for annotation in annotations:
            if annotation.get("type") == "url_citation":
                citation = annotation["url_citation"]
                results.append({
                    "title": citation.get("title", "Untitled"),
                    "url": citation["url"],
                    "content": citation.get("content", ""),
                    "type": "citation"
                })

        # If no structured annotations, create a single result from content
        if not results:
            results.append({
                "title": "Search Results",
                "url": "",
                "content": content,
                "type": "raw_content"
            })

        return results


def get_tool_schema() -> Dict[str, Any]:
    """
    Get the JSON schema for the web search tool.

    Returns:
        Tool schema dictionary
    """
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
                        "description": "The search query. Be specific and include relevant keywords for accurate results."
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of search results to return (default: 5)",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 10
                    }
                },
                "required": ["query"]
            }
        }
    }


if __name__ == "__main__":
    # Example usage
    import os
    from dotenv import load_dotenv

    load_dotenv()
    api_key = os.getenv("OPENROUTER_API_KEY")

    if api_key:
        tool = WebSearchTool(api_key)
        result = tool.search("Tesla FSD safety statistics 2024")
        print(json.dumps(result, indent=2))
    else:
        print("OPENROUTER_API_KEY not found in environment variables")


