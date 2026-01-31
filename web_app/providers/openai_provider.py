"""
OpenAI provider implementation.
"""

import os
import json
from typing import List, Dict, Any, Optional, Generator
from .base import LLMProvider, LLMResponse


class OpenAIProvider(LLMProvider):
    """Provider for OpenAI's GPT models."""

    # Pricing per million tokens (as of 2025)
    PRICING = {
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gpt-4o": {"input": 2.50, "output": 10.0},
        "gpt-4-turbo": {"input": 10.0, "output": 30.0},
        "o1-preview": {"input": 15.0, "output": 60.0},
        "o1-mini": {"input": 3.0, "output": 12.0},
    }

    # Model tiers
    DEFAULT_MODELS = {
        "simple": "gpt-4o-mini",
        "moderate": "gpt-4o",
        "complex": "gpt-4o",
    }

    def __init__(self, api_key: Optional[str] = None, config: Optional[Dict] = None):
        """
        Initialize OpenAI provider.

        Args:
            api_key: API key (or reads from config file/env)
            config: Optional config dict with 'api_key_file' and 'models'
        """
        self.api_key = api_key
        self.config = config or {}
        self.client = None
        self.models = self.DEFAULT_MODELS.copy()

        # Load API key from config file if specified
        if not self.api_key and self.config.get('api_key_file'):
            self.api_key = self._load_key_from_file(self.config['api_key_file'])

        # Fall back to environment variable
        if not self.api_key:
            self.api_key = os.environ.get('OPENAI_API_KEY')

        # Override models from config
        if self.config.get('models'):
            self.models.update(self.config['models'])

        # Initialize client if key available
        if self.api_key:
            try:
                from openai import OpenAI
                self.client = OpenAI(api_key=self.api_key)
            except ImportError:
                pass

    def _load_key_from_file(self, filepath: str) -> Optional[str]:
        """Load API key from a config file."""
        filepath = os.path.expanduser(filepath)
        if not os.path.exists(filepath):
            return None

        try:
            with open(filepath, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('OPENAI_API_KEY='):
                        return line.split('=', 1)[1].strip()
        except Exception:
            pass
        return None

    @property
    def name(self) -> str:
        return "openai"

    def is_available(self) -> bool:
        return self.client is not None

    def supports_tools(self) -> bool:
        return True

    def get_model_for_tier(self, tier: str) -> str:
        return self.models.get(tier, self.models['moderate'])

    def calculate_cost(self, tokens_in: int, tokens_out: int, model: str) -> float:
        pricing = self.PRICING.get(model)
        if not pricing:
            # Try partial match
            for key, price in self.PRICING.items():
                if key in model.lower():
                    pricing = price
                    break

        if not pricing:
            return 0.0

        cost_in = (tokens_in / 1_000_000) * pricing['input']
        cost_out = (tokens_out / 1_000_000) * pricing['output']
        return cost_in + cost_out

    def chat(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict]] = None,
        system: Optional[str] = None,
        stream: bool = False,
        model: Optional[str] = None,
        **kwargs
    ) -> LLMResponse | Generator:
        """Send a chat request to OpenAI."""

        if not self.client:
            raise RuntimeError("OpenAI client not initialized. Check API key.")

        model = model or self.get_model_for_tier('moderate')

        # Prepend system message if provided
        all_messages = []
        if system:
            all_messages.append({"role": "system", "content": system})
        all_messages.extend(messages)

        # Build request
        request = {
            "model": model,
            "messages": all_messages,
            "max_tokens": kwargs.get('max_tokens', 4096),
        }

        if tools:
            request["tools"] = self._convert_tools(tools)
            request["tool_choice"] = "auto"

        if stream:
            return self._stream_response(request, model)
        else:
            return self._sync_response(request, model)

    def _convert_tools(self, tools: List[Dict]) -> List[Dict]:
        """Convert generic tool format to OpenAI function format."""
        openai_tools = []
        for tool in tools:
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema", {"type": "object", "properties": {}})
                }
            })
        return openai_tools

    def _sync_response(self, request: Dict, model: str) -> LLMResponse:
        """Make a synchronous request."""
        response = self.client.chat.completions.create(**request)

        message = response.choices[0].message
        content = message.content or ""

        # Extract tool calls
        tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": json.loads(tc.function.arguments)
                })

        tokens_in = response.usage.prompt_tokens if response.usage else 0
        tokens_out = response.usage.completion_tokens if response.usage else 0
        cost = self.calculate_cost(tokens_in, tokens_out, model)

        return LLMResponse(
            content=content,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost=cost,
            tool_calls=tool_calls,
            stop_reason=response.choices[0].finish_reason,
            raw_response=response
        )

    def _stream_response(self, request: Dict, model: str) -> Generator:
        """Make a streaming request."""
        request["stream"] = True
        stream = self.client.chat.completions.create(**request)

        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta:
                delta = chunk.choices[0].delta
                if delta.content:
                    yield {"type": "text", "content": delta.content}
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        if tc.function:
                            yield {
                                "type": "tool_call",
                                "id": tc.id,
                                "name": tc.function.name,
                                "arguments": tc.function.arguments
                            }

            if chunk.choices and chunk.choices[0].finish_reason:
                yield {"type": "done"}

    def format_tool_result(self, tool_call_id: str, result: Any) -> Dict:
        """Format tool result for OpenAI."""
        if isinstance(result, dict):
            content = json.dumps(result)
        else:
            content = str(result)

        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content
        }
