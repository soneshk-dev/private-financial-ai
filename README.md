# Private Financial AI

A privacy-first personal financial assistant designed to be **set up and customized by AI coding assistants**.

## What Makes This Different

This isn't a traditional "clone and run" project. It's a **template for AI-assisted personalization**.

The intended workflow:
1. Fork this repository
2. Open it with an AI coding assistant (Claude Code, Cursor, Windsurf, etc.)
3. Tell the AI: "Help me set up my personal financial assistant"
4. The AI reads `CLAUDE.md` and guides you through customization

## Why This Approach?

Building a personal financial system requires many decisions:
- What banks do you use?
- Do you have investment accounts? Where?
- Do you hold cryptocurrency?
- What are your financial goals?
- How much do you care about privacy vs convenience?

Rather than building a one-size-fits-all app with a million config options, this project is designed so an AI can have a conversation with you and configure everything based on your specific situation.

## Features

- **Privacy-first**: All financial data stays on your machine in SQLite
- **Multi-source data**: Banks (via Plaid), crypto wallets, CSV imports
- **Smart AI routing**: Uses the right model for each query (saves money)
- **Flexible providers**: Claude, OpenAI, local models (Ollama), or mix
- **Conversation history**: Persistent chat with your financial AI
- **Budget tracking**: Set and monitor spending categories
- **Document vault**: Store important financial documents locally
- **Memory system**: AI remembers your goals, family, preferences

## Quick Start

```bash
# Clone the repo
git clone https://github.com/[your-username]/private-financial-ai.git
cd private-financial-ai

# Open with your AI coding assistant and say:
# "Help me set up my personal financial assistant"
```

## Requirements

- Python 3.11+
- An LLM provider (one or more of):
  - Anthropic API key (Claude) - recommended
  - Claude Max subscription (for CLI access)
  - OpenAI API key
  - Ollama installed locally
- Optional: Plaid developer account (for bank connections)

## Documentation

- `CLAUDE.md` - Instructions for AI assistants (start here if you're an AI)
- `docs/PROVIDERS.md` - LLM provider setup
- `docs/PLAID_SETUP.md` - Bank connection walkthrough
- `docs/CRYPTO_SETUP.md` - Cryptocurrency tracking
- `docs/ARCHITECTURE.md` - Technical deep-dive

## Privacy

Your financial data never leaves your machine unless you explicitly include it in a question to the AI. The AI providers (Claude, OpenAI, etc.) only see your questions and the analysis tools' outputs - not your raw transaction data.

## License

MIT - Use it, modify it, make it yours.

## Origin

This project evolved from a personal financial system built by a non-developer using AI coding assistants. It demonstrates what's possible when AI helps non-technical people build sophisticated, personalized software.
