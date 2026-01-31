# Private Financial AI - Instructions for AI Assistants

This repository is designed to be **forked and personalized by AI assistants** working with non-technical users. If you're an AI (Claude Code, Cursor, etc.) reading this, your job is to guide the user through setup and customization.

## What This Is

A privacy-first personal financial assistant that:
- Keeps all sensitive financial data **local** (SQLite database on user's machine)
- Uses AI (Claude, OpenAI, local models) only for analysis and conversation
- Aggregates data from banks (Plaid), crypto wallets, and CSV imports
- Provides intelligent analysis of spending, investments, budgets, and goals

## First-Time Setup Flow

When a user forks this repo and asks for help setting it up, follow this sequence:

### 1. Gather Personalization Info
Read `personalization/onboarding-questions.md` and have a conversation with the user to understand:
- Their name and family structure
- Financial goals
- What bank accounts they have
- Whether they have investment accounts and where
- Whether they hold cryptocurrency
- Their privacy preferences (cloud API vs local models)

### 2. Configure LLM Providers
Based on their preferences, help them set up `config/providers/providers.yaml`:
- **Claude API** (recommended): Best experience, requires Anthropic API key (~$5-20/month typical usage)
- **Claude CLI**: Free if they have Claude Max subscription ($20/month flat)
- **OpenAI**: Alternative cloud option
- **Ollama**: Fully local/private, requires decent GPU

### 3. Set Up Data Sources
Guide them through:
- **Plaid** (recommended): Connect bank accounts for automatic transaction sync. See `docs/PLAID_SETUP.md`
- **Crypto wallets** (optional): Bitcoin xpubs and/or EVM wallet addresses. See `docs/CRYPTO_SETUP.md`
- **CSV imports**: For historical data or unsupported institutions

### 4. Create Their Personal Context Files
Using their answers from step 1, generate:
- `CHECKPOINT.md` from `personalization/templates/CHECKPOINT.template.md`
- `CLAUDE_LITE.md` from `personalization/templates/CLAUDE_LITE.template.md`

### 5. Initialize Database
Run the schema to create empty tables:
```bash
sqlite3 ~/private-financial-ai/vault/databases/main.db < database/schema.sql
```

### 6. Start the Server
```bash
cd ~/private-financial-ai/web_app
python -m venv ../venv
source ../venv/bin/activate
pip install -r requirements.txt
python app.py
```

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      Web UI (Flask)                         │
│              Modern chat interface + dashboard              │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      Smart Router                           │
│    Classifies queries, selects optimal model/provider       │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐     ┌───────────────┐     ┌───────────────┐
│  Claude API   │     │  Claude CLI   │     │ Local/Other   │
│  (Anthropic)  │     │  (Max sub)    │     │   (Ollama)    │
└───────────────┘     └───────────────┘     └───────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Financial Tools                          │
│  spending_tools, portfolio_tools, plaid_tools, crypto_tools │
│  memory_tools, budget_tools, vault_tools                    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   SQLite Database                           │
│              All financial data stays LOCAL                 │
└─────────────────────────────────────────────────────────────┘
```

## File Structure

```
private-financial-ai/
├── CLAUDE.md                 # YOU ARE HERE - AI instructions
├── README.md                 # Brief human-readable intro
├── CHECKPOINT.md             # [Generated] Current user state
├── CLAUDE_LITE.md            # [Generated] Operational context
│
├── personalization/
│   ├── manifest.yaml         # Decisions to guide user through
│   ├── onboarding-questions.md
│   └── templates/
│       ├── CHECKPOINT.template.md
│       └── CLAUDE_LITE.template.md
│
├── config/
│   ├── providers/
│   │   ├── providers.yaml    # [Generated] LLM configuration
│   │   └── *.example         # Example configs
│   ├── plaid.conf            # [Generated] Bank connection
│   ├── zapper.conf           # [Generated] EVM wallet tracking
│   └── bitcoin_xpubs.conf    # [Generated] Bitcoin tracking
│
├── web_app/
│   ├── app.py                # Main Flask application
│   ├── router.py             # Query classification & routing
│   ├── providers/            # LLM provider implementations
│   └── templates/            # HTML templates
│
├── mcp_server/tools/         # Financial analysis tools
│   ├── spending_tools.py     # Transaction analysis
│   ├── portfolio_tools.py    # Investment tracking
│   ├── plaid_tools.py        # Bank connection
│   ├── crypto_tools.py       # Crypto wallet tracking
│   ├── memory_tools.py       # Knowledge graph
│   ├── budget_tools.py       # Budget management
│   └── vault_tools.py        # Document storage
│
├── database/
│   └── schema.sql            # Database structure
│
├── vault/
│   ├── databases/main.db     # [Generated] User's financial data
│   └── documents/            # [Generated] Stored documents
│
└── docs/
    ├── PROVIDERS.md          # LLM setup guide
    ├── PLAID_SETUP.md        # Bank connection walkthrough
    ├── CRYPTO_SETUP.md       # Wallet tracking setup
    └── ARCHITECTURE.md       # Technical deep-dive
```

## Key Concepts

### Smart Router
The router analyzes each query and decides:
1. **Complexity**: simple (balance check) vs complex (tax optimization advice)
2. **Tools needed**: Does this require database access?
3. **Best provider**: Based on complexity, cost settings, and availability

### Financial Tools
Tools are functions the AI can call to access financial data:
- `get_spending_by_category` - Where is money going?
- `get_portfolio_summary` - Investment overview
- `search_transactions` - Find specific purchases
- `get_budget_status` - Am I on track?
- `get_crypto_holdings` - Crypto portfolio

### Memory System
A knowledge graph storing persistent information:
- **Entities**: People, goals, accounts, employers
- **Observations**: Facts about entities
- **Relations**: Connections between entities

### Privacy Model
- All financial data stored in local SQLite
- AI providers only see queries and analysis requests
- No financial data sent to cloud unless user explicitly shares in a question

## Customization Points

When helping users customize, these are the main areas:

| Area | File(s) | What to Change |
|------|---------|----------------|
| LLM providers | `config/providers/providers.yaml` | Add/remove providers, adjust routing |
| Data sources | `config/*.conf` | Plaid, crypto wallets |
| Personal context | `CHECKPOINT.md`, `CLAUDE_LITE.md` | Family, goals, accounts |
| UI branding | `web_app/templates/index.html` | Colors, fonts, name |
| Budget categories | Database | Customize spending categories |
| Tools | `mcp_server/tools/` | Add domain-specific analysis |

## Common User Requests

### "Set up my bank connections"
→ Guide through `docs/PLAID_SETUP.md`, help create Plaid developer account

### "I want to track my crypto"
→ Guide through `docs/CRYPTO_SETUP.md`, collect wallet addresses/xpubs

### "Make it work offline"
→ Set up Ollama with appropriate models, disable cloud providers

### "Add my family/goals"
→ Update memory system with entities and observations

### "Change the colors/branding"
→ Modify CSS variables in `index.html`

## Development Commands

```bash
# Start server
cd ~/private-financial-ai/web_app
source ../venv/bin/activate
python app.py

# Access UI
open http://localhost:5001

# Database access
sqlite3 ~/private-financial-ai/vault/databases/main.db

# Check Ollama (if using local models)
ollama list
ollama ps
```

## Troubleshooting

| Issue | Likely Cause | Solution |
|-------|--------------|----------|
| "No API key" error | Missing provider config | Check `config/providers/` |
| Tools not working | Database not initialized | Run schema.sql |
| Plaid sync fails | Invalid credentials | Re-check Plaid dashboard |
| Slow responses | Using wrong model tier | Adjust router settings |

---

## For AI Assistants: Important Guidelines

1. **Never commit secrets** - API keys, Plaid credentials, wallet addresses stay in config/ (gitignored)

2. **Respect privacy** - Don't send financial data to external services beyond what's needed for the query

3. **Explain costs** - Be transparent about API costs when helping users choose providers

4. **Incremental setup** - Don't overwhelm users; start with basics (one LLM provider, maybe just CSV imports) and expand

5. **Test as you go** - After each configuration step, verify it works before moving on

6. **Keep context files updated** - When user's situation changes, update CHECKPOINT.md and CLAUDE_LITE.md
