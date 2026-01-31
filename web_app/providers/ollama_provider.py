"""
Ollama provider implementation for local models.
"""

import json
import requests
from typing import List, Dict, Any, Optional, Generator
from .base import LLMProvider, LLMResponse


class OllamaProvider(LLMProvider):
    """Provider for local Ollama models."""

    # Model tiers (common recommendations)
    DEFAULT_MODELS = {
        "simple": "llama3.2:3b",
        "moderate": "qwen2.5:14b",
        "complex": "qwen2.5:14b",
    }

    # Models known to support tool calling
    TOOL_CAPABLE_MODELS = [
        "qwen2.5", "qwen2", "qwen3",
        "llama3.1", "llama3.2", "llama3.3",
        "mistral", "mixtral",
        "command-r",
    ]

    def __init__(self, host: str = "http://localhost:11434", config: Optional[Dict] = None):
        """
        Initialize Ollama provider.

        Args:
            host: Ollama server URL
            config: Optional config dict with 'host' and 'models'
        """
        self.config = config or {}
        self.host = self.config.get('host', host)
        self.models = self.DEFAULT_MODELS.copy()

        # Override models from config
        if self.config.get('models'):
            self.models.update(self.config['models'])

        self._available = None  # Cache availability check

    @property
    def name(self) -> str:
        return "ollama"

    def is_available(self) -> bool:
        """Check if Ollama is running and accessible."""
        if self._available is not None:
            return self._available

        try:
            response = requests.get(f"{self.host}/api/tags", timeout=2)
            self._available = response.status_code == 200
        except Exception:
            self._available = False

        return self._available

    def supports_tools(self) -> bool:
        """
        Ollama tool support depends on the model.
        Returns True if any configured model supports tools.
        """
        for tier, model in self.models.items():
            model_family = model.split(':')[0].lower()
            if any(tc in model_family for tc in self.TOOL_CAPABLE_MODELS):
                return True
        return False

    def get_model_for_tier(self, tier: str) -> str:
        return self.models.get(tier, self.models['moderate'])

    def get_available_models(self) -> List[str]:
        """Get list of models available in Ollama."""
        try:
            response = requests.get(f"{self.host}/api/tags", timeout=5)
            if response.status_code == 200:
                data = response.json()
                return [m['name'] for m in data.get('models', [])]
        except Exception:
            pass
        return []

    def calculate_cost(self, tokens_in: int, tokens_out: int, model: str) -> float:
        """Local models are free."""
        return 0.0

    def chat(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict]] = None,
        system: Optional[str] = None,
        stream: bool = False,
        model: Optional[str] = None,
        **kwargs
    ) -> LLMResponse | Generator:
        """Send a chat request to Ollama."""

        if not self.is_available():
            raise RuntimeError("Ollama is not running. Start with: ollama serve")

        model = model or self.get_model_for_tier('moderate')

        # Build request
        request = {
            "model": model,
            "messages": messages,
            "stream": stream,
        }

        if system:
            request["system"] = system

        if tools:
            # Check if model supports tools
            model_family = model.split(':')[0].lower()
            if any(tc in model_family for tc in self.TOOL_CAPABLE_MODELS):
                request["tools"] = self._convert_tools(tools)

        if stream:
            return self._stream_response(request, model)
        else:
            return self._sync_response(request, model)

    def _convert_tools(self, tools: List[Dict]) -> List[Dict]:
        """Convert generic tool format to Ollama format."""
        ollama_tools = []
        for tool in tools:
            ollama_tools.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema", {"type": "object", "properties": {}})
                }
            })
        return ollama_tools

    def _sync_response(self, request: Dict, model: str) -> LLMResponse:
        """Make a synchronous request."""
        request["stream"] = False

        response = requests.post(
            f"{self.host}/api/chat",
            json=request,
            timeout=300  # 5 minute timeout for large models
        )
        response.raise_for_status()
        data = response.json()

        message = data.get("message", {})
        content = message.get("content", "")

        # Extract tool calls if present
        tool_calls = []
        if message.get("tool_calls"):
            for tc in message["tool_calls"]:
                tool_calls.append({
                    "id": tc.get("id", f"call_{len(tool_calls)}"),
                    "name": tc["function"]["name"],
                    "arguments": tc["function"].get("arguments", {})
                })

        # Ollama doesn't always provide token counts
        tokens_in = data.get("prompt_eval_count", 0)
        tokens_out = data.get("eval_count", 0)

        return LLMResponse(
            content=content,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost=0.0,  # Local is free
            tool_calls=tool_calls,
            stop_reason=data.get("done_reason", ""),
            raw_response=data
        )

    def _stream_response(self, request: Dict, model: str) -> Generator:
        """Make a streaming request."""
        request["stream"] = True

        response = requests.post(
            f"{self.host}/api/chat",
            json=request,
            stream=True,
            timeout=300
        )
        response.raise_for_status()

        for line in response.iter_lines():
            if line:
                try:
                    data = json.loads(line)
                    message = data.get("message", {})

                    if message.get("content"):
                        yield {"type": "text", "content": message["content"]}

                    if message.get("tool_calls"):
                        for tc in message["tool_calls"]:
                            yield {
                                "type": "tool_call",
                                "id": tc.get("id", "call_0"),
                                "name": tc["function"]["name"],
                                "arguments": tc["function"].get("arguments", {})
                            }

                    if data.get("done"):
                        yield {"type": "done"}

                except json.JSONDecodeError:
                    continue

    def format_tool_result(self, tool_call_id: str, result: Any) -> Dict:
        """Format tool result for Ollama."""
        if isinstance(result, dict):
            content = json.dumps(result)
        else:
            content = str(result)

        return {
            "role": "tool",
            "content": content
        }
