"""
Smart Query Router

Analyzes queries to determine:
1. Complexity level (simple, moderate, complex)
2. Whether tools are needed
3. Best provider and model to use

This enables cost optimization by using cheaper models for simple queries.
"""

import re
import os
import yaml
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from providers import (
    LLMProvider,
    AnthropicProvider,
    OpenAIProvider,
    OllamaProvider,
    ClaudeCLIProvider,
)


@dataclass
class QueryClassification:
    """Result of query analysis."""
    complexity: str  # 'simple', 'moderate', 'complex'
    needs_tools: bool
    suggested_tier: str  # 'simple', 'moderate', 'complex'
    reason: str


@dataclass
class RoutingDecision:
    """Final routing decision."""
    provider: LLMProvider
    model: str
    classification: QueryClassification


class QueryClassifier:
    """Analyzes queries to determine complexity and tool needs."""

    # Keywords indicating complex queries
    COMPLEX_KEYWORDS = [
        r'\b(optimize|optimization)\b',
        r'\b(strategy|strategies)\b',
        r'\b(recommend|recommendation|advice)\b',
        r'\b(analyze|analysis)\b',
        r'\b(compare|comparison)\b',
        r'\b(projection|forecast|predict)\b',
        r'\b(tax|taxes)\b.*\b(plan|strategy|optimize)\b',
        r'\b(retirement|retire)\b.*\b(plan|ready|enough)\b',
        r'\b(should i|what should)\b',
        r'\b(pros and cons|trade-?offs?)\b',
        r'\b(comprehensive|detailed|thorough)\b',
    ]

    # Keywords indicating moderate queries
    MODERATE_KEYWORDS = [
        r'\b(breakdown|break down)\b',
        r'\b(trend|trends|trending)\b',
        r'\b(summary|summarize)\b',
        r'\b(over time|month over month|year over year)\b',
        r'\b(category|categories)\b',
        r'\b(top \d+|biggest|largest|highest)\b',
        r'\b(vs|versus|compared to)\b',
        r'\b(why|how come)\b',
        r'\b(explain|understanding)\b',
    ]

    # Keywords indicating simple queries
    SIMPLE_KEYWORDS = [
        r'\b(balance|balances)\b',
        r'\b(how much|what is)\b.*\b(balance|total|value)\b',
        r'\b(list|show)\b.*\b(accounts?|transactions?)\b',
        r'\b(search|find)\b.*\b(transaction|purchase|charge)\b',
        r'\b(last|recent)\b.*\b(transaction|purchase)\b',
        r'\b(current|today)\b.*\b(balance|value)\b',
    ]

    # Patterns indicating tool needs
    TOOL_NEED_PATTERNS = [
        r'\b(spend|spending|spent)\b',
        r'\b(balance|balances)\b',
        r'\b(transaction|transactions|purchase|purchases)\b',
        r'\b(portfolio|holdings|investments?)\b',
        r'\b(budget|budgets)\b',
        r'\b(income|salary|paycheck)\b',
        r'\b(crypto|bitcoin|ethereum)\b',
        r'\b(category|categories)\b',
        r'\b(account|accounts)\b',
        r'\b(net worth)\b',
        r'\b(cash flow)\b',
        r'\b(savings? rate)\b',
        r'\b(recurring|subscription)\b',
        r'\b(document|documents|vault)\b',
        r'\b(goal|goals)\b',
        r'\b(memory|remember)\b',
    ]

    # Conversational patterns (no tools needed)
    CONVERSATIONAL_PATTERNS = [
        r'^(hi|hello|hey|good morning|good afternoon|good evening)',
        r'^(thanks|thank you|thx)',
        r'^(help|what can you do)',
        r'^(who are you|what are you)',
        r'\?$',  # Simple questions ending with ?
    ]

    # Patterns eligible for local models (very simple lookups)
    LOCAL_ELIGIBLE_PATTERNS = [
        r'^(what is|show|list|get)\s+(my\s+)?(current\s+)?(balance|total)',
        r'^how much (do i have|is in)',
        r'^list (my\s+)?(accounts?|budgets?)',
    ]

    def classify(self, query: str) -> QueryClassification:
        """
        Classify a query by complexity and tool needs.

        Args:
            query: The user's query string

        Returns:
            QueryClassification with complexity, tool needs, and reasoning
        """
        query_lower = query.lower().strip()

        # Check if conversational (no tools)
        if self._is_conversational(query_lower):
            return QueryClassification(
                complexity='simple',
                needs_tools=False,
                suggested_tier='simple',
                reason='Conversational query, no financial data needed'
            )

        # Determine if tools are needed
        needs_tools = self._needs_tools(query_lower)

        # Determine complexity
        complexity, reason = self._assess_complexity(query_lower)

        # Determine suggested tier
        if complexity == 'complex':
            suggested_tier = 'complex'
        elif complexity == 'moderate':
            suggested_tier = 'moderate'
        else:
            suggested_tier = 'simple'

        return QueryClassification(
            complexity=complexity,
            needs_tools=needs_tools,
            suggested_tier=suggested_tier,
            reason=reason
        )

    def _is_conversational(self, query: str) -> bool:
        """Check if query is conversational (greeting, thanks, help)."""
        for pattern in self.CONVERSATIONAL_PATTERNS:
            if re.search(pattern, query, re.IGNORECASE):
                # But not if it also mentions financial terms
                if not self._needs_tools(query):
                    return True
        return False

    def _needs_tools(self, query: str) -> bool:
        """Determine if query needs financial tools."""
        for pattern in self.TOOL_NEED_PATTERNS:
            if re.search(pattern, query, re.IGNORECASE):
                return True
        return False

    def _is_local_eligible(self, query: str) -> bool:
        """Check if query is simple enough for local models."""
        for pattern in self.LOCAL_ELIGIBLE_PATTERNS:
            if re.search(pattern, query, re.IGNORECASE):
                return True
        return False

    def _assess_complexity(self, query: str) -> Tuple[str, str]:
        """
        Assess query complexity.

        Returns:
            Tuple of (complexity_level, reason)
        """
        # Check for complex patterns first
        for pattern in self.COMPLEX_KEYWORDS:
            if re.search(pattern, query, re.IGNORECASE):
                return ('complex', f'Complex query pattern detected')

        # Check for multi-part queries
        if query.count('?') > 1:
            return ('moderate', 'Multiple questions in query')

        if ' and ' in query and len(query.split(' and ')) > 2:
            return ('moderate', 'Multi-part query')

        # Check for time-based analysis
        time_patterns = [
            r'\b(last|past)\s+\d+\s+(months?|years?|weeks?)\b',
            r'\b(this|last|next)\s+(month|year|quarter)\b',
            r'\b(year to date|ytd|mtd)\b',
            r'\b(20\d{2})\b',  # Year reference
        ]
        for pattern in time_patterns:
            if re.search(pattern, query, re.IGNORECASE):
                # Time-based queries are at least moderate
                for complex_pattern in self.COMPLEX_KEYWORDS:
                    if re.search(complex_pattern, query, re.IGNORECASE):
                        return ('complex', 'Time-based analysis with complex operation')
                return ('moderate', 'Time-based analysis query')

        # Check for moderate patterns
        for pattern in self.MODERATE_KEYWORDS:
            if re.search(pattern, query, re.IGNORECASE):
                return ('moderate', 'Moderate query pattern detected')

        # Check for simple patterns
        for pattern in self.SIMPLE_KEYWORDS:
            if re.search(pattern, query, re.IGNORECASE):
                return ('simple', 'Simple lookup query')

        # Default to moderate for safety
        return ('moderate', 'Default classification')


class SmartRouter:
    """
    Routes queries to the optimal provider and model based on:
    - Query complexity
    - Available providers
    - User's cost preferences
    - Tool requirements
    """

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize the router with configuration.

        Args:
            config_path: Path to providers.yaml config file
        """
        self.config = self._load_config(config_path)
        self.providers = self._init_providers()
        self.classifier = QueryClassifier()

        # Cost optimization setting
        self.cost_mode = self.config.get('routing', {}).get('cost_optimization', 'balanced')

    def _load_config(self, config_path: Optional[str]) -> Dict:
        """Load configuration from YAML file."""
        if not config_path:
            # Default locations
            candidates = [
                os.path.expanduser('~/.private-financial-ai/config/providers/providers.yaml'),
                os.path.join(os.path.dirname(__file__), '..', 'config', 'providers', 'providers.yaml'),
                'config/providers/providers.yaml',
            ]
            for path in candidates:
                if os.path.exists(path):
                    config_path = path
                    break

        if config_path and os.path.exists(config_path):
            with open(config_path, 'r') as f:
                return yaml.safe_load(f) or {}

        return {}

    def _init_providers(self) -> Dict[str, LLMProvider]:
        """Initialize enabled providers from config."""
        providers = {}
        provider_config = self.config.get('providers', {})

        # Initialize each enabled provider
        if provider_config.get('anthropic', {}).get('enabled', True):
            try:
                providers['anthropic'] = AnthropicProvider(
                    config=provider_config.get('anthropic', {})
                )
            except Exception:
                pass

        if provider_config.get('claude_cli', {}).get('enabled', False):
            try:
                providers['claude_cli'] = ClaudeCLIProvider(
                    config=provider_config.get('claude_cli', {})
                )
            except Exception:
                pass

        if provider_config.get('openai', {}).get('enabled', False):
            try:
                providers['openai'] = OpenAIProvider(
                    config=provider_config.get('openai', {})
                )
            except Exception:
                pass

        if provider_config.get('ollama', {}).get('enabled', False):
            try:
                providers['ollama'] = OllamaProvider(
                    config=provider_config.get('ollama', {})
                )
            except Exception:
                pass

        return providers

    def get_available_providers(self) -> List[str]:
        """Get list of available provider names."""
        return [name for name, provider in self.providers.items() if provider.is_available()]

    def route(self, query: str, prefer_provider: Optional[str] = None) -> RoutingDecision:
        """
        Route a query to the best provider and model.

        Args:
            query: The user's query
            prefer_provider: Optional preferred provider name

        Returns:
            RoutingDecision with provider, model, and classification
        """
        # Classify the query
        classification = self.classifier.classify(query)

        # Get the best provider
        provider = self._select_provider(classification, prefer_provider)

        # Get the model for this tier
        model = provider.get_model_for_tier(classification.suggested_tier)

        return RoutingDecision(
            provider=provider,
            model=model,
            classification=classification
        )

    def _select_provider(
        self,
        classification: QueryClassification,
        prefer_provider: Optional[str] = None
    ) -> LLMProvider:
        """Select the best available provider."""

        # If specific provider requested and available, use it
        if prefer_provider and prefer_provider in self.providers:
            provider = self.providers[prefer_provider]
            if provider.is_available():
                # Check tool support if needed
                if classification.needs_tools and not provider.supports_tools():
                    pass  # Fall through to find tool-capable provider
                else:
                    return provider

        # Get available providers
        available = [
            (name, p) for name, p in self.providers.items()
            if p.is_available()
        ]

        if not available:
            raise RuntimeError("No LLM providers available. Check configuration.")

        # Filter by tool support if needed
        if classification.needs_tools:
            tool_capable = [(name, p) for name, p in available if p.supports_tools()]
            if tool_capable:
                available = tool_capable

        # Apply cost optimization preference
        if self.cost_mode == 'cost_conscious':
            # Prefer free options
            return self._get_preferred_provider(available, ['claude_cli', 'ollama', 'anthropic', 'openai'])
        elif self.cost_mode == 'quality':
            # Prefer best quality
            return self._get_preferred_provider(available, ['anthropic', 'openai', 'claude_cli', 'ollama'])
        else:
            # Balanced: use CLI if available, otherwise API
            return self._get_preferred_provider(available, ['claude_cli', 'anthropic', 'openai', 'ollama'])

    def _get_preferred_provider(
        self,
        available: List[Tuple[str, LLMProvider]],
        preference_order: List[str]
    ) -> LLMProvider:
        """Get provider based on preference order."""
        available_dict = dict(available)

        for preferred in preference_order:
            if preferred in available_dict:
                return available_dict[preferred]

        # Return first available
        return available[0][1]

    def classify_query(self, query: str) -> QueryClassification:
        """Classify a query without routing (for inspection)."""
        return self.classifier.classify(query)
