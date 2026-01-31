# Architecture Overview

This document explains how Private Financial AI is structured and how the components interact.

## System Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              User Interface                                 │
│                         (Flask Templates + JavaScript)                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │  Chat View   │  │  Dashboard   │  │   Budgets    │  │    Vault     │   │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Flask Application                                  │
│                              (app.py)                                        │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                         API Endpoints                                   │ │
│  │  /api/chat/stream   /api/widgets   /api/plaid/*   /api/vault/*   ...  │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                 ▼
┌──────────────────────┐  ┌──────────────────┐  ┌──────────────────────────┐
│    Smart Router      │  │  Financial Tools │  │   External Services      │
│    (router.py)       │  │  (mcp_server/)   │  │                          │
│                      │  │                  │  │  ┌──────────────────┐   │
│  Query Analysis:     │  │  • spending      │  │  │      Plaid       │   │
│  • Complexity        │  │  • portfolio     │  │  │  (bank data)     │   │
│  • Tool needs        │  │  • budget        │  │  └──────────────────┘   │
│  • Best provider     │  │  • memory        │  │  ┌──────────────────┐   │
│                      │  │  • vault         │  │  │     Zapper       │   │
└──────────────────────┘  │  • crypto        │  │  │  (EVM/DeFi)      │   │
          │               └──────────────────┘  │  └──────────────────┘   │
          ▼                         │           │  ┌──────────────────┐   │
┌──────────────────────┐           │           │  │  Blockchain APIs │   │
│   LLM Providers      │           │           │  │  (Bitcoin)       │   │
│   (providers/)       │           │           │  └──────────────────┘   │
│                      │           │           └──────────────────────────┘
│  ┌────────────────┐  │           │
│  │   Anthropic    │  │           ▼
│  └────────────────┘  │  ┌──────────────────────────────────────────────┐
│  ┌────────────────┐  │  │              SQLite Database                 │
│  │   Claude CLI   │  │  │              (vault/databases/main.db)       │
│  └────────────────┘  │  │                                              │
│  ┌────────────────┐  │  │  ┌────────────┐ ┌────────────┐ ┌──────────┐ │
│  │    OpenAI      │  │  │  │transactions│ │  holdings  │ │ entities │ │
│  └────────────────┘  │  │  └────────────┘ └────────────┘ └──────────┘ │
│  ┌────────────────┐  │  │  ┌────────────┐ ┌────────────┐ ┌──────────┐ │
│  │    Ollama      │  │  │  │  accounts  │ │  budgets   │ │  vault   │ │
│  └────────────────┘  │  │  └────────────┘ └────────────┘ └──────────┘ │
└──────────────────────┘  └──────────────────────────────────────────────┘
```

## Request Flow

### Chat Query Example

1. **User sends message:** "How much did I spend on food last month?"

2. **Flask receives request:** `POST /api/chat/stream`

3. **Router analyzes query:**
   - Complexity: Simple (single category, single time period)
   - Tools needed: Yes (`get_spending_by_category`)
   - Recommended model: Haiku (simple query)

4. **Provider selected:** Based on config (e.g., Anthropic Haiku)

5. **LLM called with tools:** Message + available tool definitions

6. **LLM decides to call tool:** `get_spending_by_category(category="Food", month="2026-01")`

7. **Tool executes:** Queries SQLite, returns spending breakdown

8. **LLM receives tool result:** Formats response for user

9. **Response streamed:** Back to UI via Server-Sent Events

## Key Components

### 1. Flask Application (`web_app/app.py`)

The main application handling:
- HTTP routing for all endpoints
- Server-Sent Events for streaming chat
- Session management
- Static file serving

**Key endpoints:**
- `POST /api/chat/stream` - Main chat interface
- `GET /api/widgets/summary` - Dashboard data
- `POST /api/plaid/sync` - Trigger bank sync
- `GET/POST /api/memory/*` - Knowledge graph operations

### 2. Smart Router (`web_app/router.py`)

Analyzes queries to select the optimal model:

```python
class QueryClassifier:
    def classify(self, query: str) -> Classification:
        # Returns: complexity, needs_tools, recommended_tier
```

**Classification factors:**
- **Keywords:** "compare", "analyze", "optimize" → complex
- **Time spans:** Multi-year analysis → complex
- **Specificity:** Single lookup vs. comprehensive review

### 3. LLM Providers (`web_app/providers/`)

Abstract interface for different AI services:

```python
class LLMProvider(ABC):
    @abstractmethod
    def chat(self, messages, tools=None, stream=False): ...

    @abstractmethod
    def supports_tools(self) -> bool: ...
```

Implementations:
- `anthropic.py` - Claude API
- `claude_cli.py` - Claude CLI (subprocess)
- `openai.py` - OpenAI API
- `ollama.py` - Local Ollama

### 4. Financial Tools (`mcp_server/tools/`)

Functions the LLM can call to access financial data:

| Module | Purpose | Key Functions |
|--------|---------|---------------|
| `spending_tools.py` | Transaction analysis | `get_spending_by_category`, `search_transactions` |
| `portfolio_tools.py` | Investment tracking | `get_portfolio_summary`, `get_holdings` |
| `plaid_tools.py` | Bank connections | `sync_transactions`, `get_balances` |
| `crypto_tools.py` | Crypto tracking | `get_crypto_holdings`, `get_defi_positions` |
| `memory_tools.py` | Knowledge graph | `create_entity`, `add_observation` |
| `budget_tools.py` | Budget management | `get_budget_status`, `set_budget` |
| `vault_tools.py` | Document storage | `search_documents`, `get_document` |

### 5. Database (`vault/databases/main.db`)

SQLite database with tables for:

**Financial data:**
- `transactions` - All spending/income transactions
- `accounts` - Bank accounts, credit cards
- `holdings` - Investment positions
- `investment_accounts` - Brokerage accounts

**Crypto:**
- `bitcoin_wallets` - BTC tracking
- `crypto_balances` - Token balances
- `defi_positions` - DeFi protocol positions

**User data:**
- `entities` - Knowledge graph nodes
- `observations` - Facts about entities
- `relations` - Connections between entities
- `budgets` - Monthly budget limits

**System:**
- `conversations` - Chat history
- `conversation_messages` - Individual messages
- `vault_documents` - Stored documents
- `api_usage` - Cost tracking

## Data Flow Patterns

### Bank Transaction Sync

```
Plaid API
    │
    ▼
plaid_tools.sync_transactions()
    │
    ├─► Fetch new transactions
    │
    ├─► Deduplicate (check source_type, date, amount)
    │
    ├─► Categorize (using category rules)
    │
    └─► Insert into transactions table
```

### Crypto Balance Update

```
Zapper API / Blockchain
    │
    ▼
crypto_tools.sync_balances()
    │
    ├─► Fetch token balances
    │
    ├─► Fetch DeFi positions
    │
    ├─► Calculate total values
    │
    └─► Update crypto_balances, defi_positions tables
```

### Memory System

```
User: "Remember that our goal is $2M for retirement"
    │
    ▼
LLM extracts: entity="Retirement Goal", observation="Target $2M"
    │
    ▼
memory_tools.add_observation()
    │
    ├─► Check if entity exists (create if not)
    │
    └─► Add observation with timestamp
```

## Security Model

### Local-First Data

All sensitive financial data stays in SQLite:
- Transaction details
- Account numbers
- Balances
- Portfolio positions

### What Goes to AI Providers

Only when explicitly included in queries:
- User's question text
- Tool results (aggregated data, not raw transactions)
- Memory/context (user-controlled)

**Example:** User asks "How much did I spend on food?"
- Sent to AI: The question + tool result ("Food & Dining: $850")
- NOT sent: Individual transaction records

### API Key Security

- Keys stored in `~/.private-financial-ai/secrets/`
- Files have 600 permissions (owner read/write only)
- Never logged or included in error messages
- Never committed to git (directory is gitignored)

## Extensibility

### Adding a New Tool

1. Create `mcp_server/tools/new_tool.py`:
```python
class NewTools:
    def __init__(self, db_path):
        self.db_path = db_path

    def my_function(self, param1, param2):
        # Implementation
        return result

NEW_TOOLS = [
    {
        "name": "my_function",
        "description": "What this tool does",
        "input_schema": {
            "type": "object",
            "properties": {
                "param1": {"type": "string"},
                "param2": {"type": "integer"}
            },
            "required": ["param1"]
        }
    }
]
```

2. Register in `app.py`:
```python
from mcp_server.tools.new_tool import NewTools, NEW_TOOLS

new_tools = NewTools(DB_PATH)
# Add to tool list and handler
```

### Adding a New Provider

1. Create `web_app/providers/new_provider.py`:
```python
from .base import LLMProvider

class NewProvider(LLMProvider):
    def chat(self, messages, tools=None, stream=False):
        # Implementation
        pass

    def supports_tools(self):
        return True  # or False
```

2. Register in `providers/__init__.py`

3. Add configuration in `providers.yaml.example`

## Performance Considerations

### Database Indexing

Key indexes for query performance:
- `transactions(date)` - Date range queries
- `transactions(category_normalized)` - Category analysis
- `holdings(account_id)` - Portfolio queries

### Caching

- Widget data cached briefly to avoid repeated queries
- Crypto prices cached for a few minutes
- Memory entities loaded once per session

### Streaming

Chat uses Server-Sent Events for real-time streaming:
- User sees response as it's generated
- Tool calls shown as they execute
- No waiting for complete response
