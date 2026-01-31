"""
Claude CLI provider implementation.
Uses the Claude Code CLI for users with Max subscription (free usage).
"""

import subprocess
import json
import shutil
import tempfile
import os
from typing import List, Dict, Any, Optional, Generator
from .base import LLMProvider, LLMResponse


class ClaudeCLIProvider(LLMProvider):
    """
    Provider that uses Claude Code CLI.
    Useful for Max subscription users who get free API access via CLI.
    """

    # Model mapping for CLI
    MODEL_MAP = {
        "simple": "haiku",
        "moderate": "sonnet",
        "complex": "opus",
    }

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize Claude CLI provider.

        Args:
            config: Optional config dict with 'models'
        """
        self.config = config or {}
        self.models = self.MODEL_MAP.copy()

        # Override models from config
        if self.config.get('models'):
            for tier, model in self.config['models'].items():
                # Strip 'cli:' prefix if present
                if model.startswith('cli:'):
                    model = model[4:]
                self.models[tier] = model

        self._available = None
        self._cli_path = None

    @property
    def name(self) -> str:
        return "claude_cli"

    def _find_cli(self) -> Optional[str]:
        """Find the Claude CLI executable."""
        if self._cli_path:
            return self._cli_path

        # Check common locations
        cli_path = shutil.which('claude')
        if cli_path:
            self._cli_path = cli_path
            return cli_path

        # Check npm global install
        npm_path = os.path.expanduser('~/.npm-global/bin/claude')
        if os.path.exists(npm_path):
            self._cli_path = npm_path
            return npm_path

        return None

    def is_available(self) -> bool:
        """Check if Claude CLI is installed and authenticated."""
        if self._available is not None:
            return self._available

        cli_path = self._find_cli()
        if not cli_path:
            self._available = False
            return False

        # Check if authenticated
        try:
            result = subprocess.run(
                [cli_path, 'auth', 'status'],
                capture_output=True,
                text=True,
                timeout=10
            )
            self._available = result.returncode == 0
        except Exception:
            self._available = False

        return self._available

    def supports_tools(self) -> bool:
        """Claude CLI supports MCP tools."""
        return True

    def get_model_for_tier(self, tier: str) -> str:
        model = self.models.get(tier, self.models['moderate'])
        return f"cli:{model}"

    def calculate_cost(self, tokens_in: int, tokens_out: int, model: str) -> float:
        """CLI usage is free for Max subscribers."""
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
        """
        Send a chat request via Claude CLI.

        Note: CLI doesn't support multi-turn conversation well,
        so we format the full conversation into a single prompt.
        """
        if not self.is_available():
            raise RuntimeError("Claude CLI not available. Install with: npm install -g @anthropic-ai/claude-cli")

        cli_path = self._find_cli()
        model = model or self.get_model_for_tier('moderate')

        # Strip 'cli:' prefix for actual CLI command
        cli_model = model.replace('cli:', '')

        # Format messages into a single prompt
        prompt = self._format_messages(messages, system)

        # Build CLI command
        cmd = [
            cli_path,
            '--print',  # Non-interactive mode
            '--model', cli_model,
            '--output-format', 'json',
        ]

        # Add allowed tools if specified
        if tools and kwargs.get('allowed_tools'):
            cmd.extend(['--allowedTools', kwargs['allowed_tools']])

        # Add the prompt
        cmd.extend(['-p', prompt])

        if stream:
            return self._stream_response(cmd, model)
        else:
            return self._sync_response(cmd, model)

    def _format_messages(self, messages: List[Dict], system: Optional[str] = None) -> str:
        """Format conversation messages into a single prompt."""
        parts = []

        if system:
            parts.append(f"System: {system}\n")

        for msg in messages:
            role = msg.get('role', 'user')
            content = msg.get('content', '')

            if role == 'user':
                parts.append(f"User: {content}")
            elif role == 'assistant':
                parts.append(f"Assistant: {content}")
            elif role == 'tool':
                parts.append(f"Tool Result: {content}")

        return "\n\n".join(parts)

    def _sync_response(self, cmd: List[str], model: str) -> LLMResponse:
        """Execute CLI command synchronously."""
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )

            if result.returncode != 0:
                raise RuntimeError(f"CLI error: {result.stderr}")

            # Parse JSON output
            try:
                data = json.loads(result.stdout)
                content = data.get('result', result.stdout)
                tool_calls = data.get('tool_calls', [])
            except json.JSONDecodeError:
                content = result.stdout
                tool_calls = []

            # Estimate tokens (CLI doesn't provide counts)
            tokens_in = len(' '.join(cmd)) // 4
            tokens_out = len(content) // 4

            return LLMResponse(
                content=content,
                model=model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost=0.0,  # Free for Max subscribers
                tool_calls=tool_calls,
                stop_reason="end_turn",
                raw_response=result
            )

        except subprocess.TimeoutExpired:
            raise RuntimeError("CLI request timed out")

    def _stream_response(self, cmd: List[str], model: str) -> Generator:
        """Execute CLI command with streaming output."""
        # Remove --output-format json for streaming
        cmd = [c for c in cmd if c != 'json' and c != '--output-format']

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            for line in process.stdout:
                if line.strip():
                    yield {"type": "text", "content": line}

            process.wait()
            yield {"type": "done"}

        except Exception as e:
            yield {"type": "error", "content": str(e)}

    def format_tool_result(self, tool_call_id: str, result: Any) -> Dict:
        """Format tool result for CLI."""
        if isinstance(result, dict):
            content = json.dumps(result)
        else:
            content = str(result)

        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content
        }
