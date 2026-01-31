# LLM Provider Setup Guide

This guide helps you choose and configure AI providers for your Private Financial AI.

## Quick Comparison

| Provider | Cost | Privacy | Quality | Setup Difficulty |
|----------|------|---------|---------|------------------|
| **Claude API** | ~$5-20/mo | Cloud | Excellent | Easy |
| **Claude CLI** | $0 (with Max) | Cloud | Excellent | Easy |
| **OpenAI** | ~$5-20/mo | Cloud | Excellent | Easy |
| **Ollama** | $0 | Local | Good | Moderate |

## Recommended Setup

For most users, we recommend:

1. **Primary:** Claude API (best quality, reasonable cost)
2. **Fallback:** Claude CLI if you have Max subscription (free backup)

For privacy-conscious users:
1. **Primary:** Ollama (fully local)
2. **Fallback:** Claude API (for complex queries only)

---

## Claude (Anthropic) - Recommended

### Why Claude?
- Best-in-class reasoning for financial analysis
- Excellent tool use (calling your financial data)
- Clear, helpful responses

### Pricing (as of 2025)
| Model | Input | Output | Best For |
|-------|-------|--------|----------|
| Haiku | $1/M tokens | $5/M tokens | Simple queries |
| Sonnet | $3/M tokens | $15/M tokens | Most queries |
| Opus | $15/M tokens | $75/M tokens | Complex analysis |

**Typical monthly cost:** $5-20 depending on usage

### Setup

1. Create account at [console.anthropic.com](https://console.anthropic.com)
2. Add payment method
3. Generate API key: Settings → API Keys → Create Key
4. Configure:

```bash
mkdir -p ~/.private-financial-ai/secrets
echo "ANTHROPIC_API_KEY=sk-ant-your-key-here" > ~/.private-financial-ai/secrets/anthropic.conf
chmod 600 ~/.private-financial-ai/secrets/anthropic.conf
```

5. Enable in `config/providers/providers.yaml`:
```yaml
providers:
  anthropic:
    enabled: true
    api_key_file: ~/.private-financial-ai/secrets/anthropic.conf
```

---

## Claude CLI (Max Subscription)

If you have a Claude Max subscription ($20/month), you can use the CLI for unlimited queries at no additional API cost.

### What You Get
- Same Claude models (Haiku, Sonnet, Opus)
- No per-token charges
- Rate limits: ~45 Opus or ~225 Sonnet per 5 hours

### Setup

1. Install Claude CLI:
```bash
# macOS/Linux
curl -fsSL https://cli.anthropic.com/install.sh | sh

# Or via npm
npm install -g @anthropic-ai/claude-cli
```

2. Authenticate:
```bash
claude auth login
```

3. Enable in `config/providers/providers.yaml`:
```yaml
providers:
  claude_cli:
    enabled: true
```

No API key needed - uses OAuth from the `claude auth login` step.

---

## OpenAI

Alternative cloud provider with similar capabilities.

### Pricing (as of 2025)
| Model | Input | Output | Best For |
|-------|-------|--------|----------|
| GPT-4o-mini | $0.15/M | $0.60/M | Simple queries |
| GPT-4o | $2.50/M | $10/M | Most queries |
| o1 | $15/M | $60/M | Complex reasoning |

### Setup

1. Create account at [platform.openai.com](https://platform.openai.com)
2. Add payment method
3. Generate API key: API Keys → Create new secret key
4. Configure:

```bash
echo "OPENAI_API_KEY=sk-your-key-here" > ~/.private-financial-ai/secrets/openai.conf
chmod 600 ~/.private-financial-ai/secrets/openai.conf
```

5. Enable in `config/providers/providers.yaml`:
```yaml
providers:
  openai:
    enabled: true
    api_key_file: ~/.private-financial-ai/secrets/openai.conf
```

---

## Ollama (Local Models)

Run AI models entirely on your machine. Maximum privacy, zero ongoing cost.

### Requirements
- **GPU recommended:** 8GB+ VRAM for decent performance
- **RAM:** 16GB+ system RAM
- **Storage:** 5-30GB per model

### Recommended Models by VRAM

| VRAM | Model | Quality | Speed |
|------|-------|---------|-------|
| 8GB | `llama3.2:3b` | Good | Fast |
| 8GB | `qwen2.5:7b` | Better | Medium |
| 16GB | `qwen2.5:14b` | Great | Medium |
| 16GB | `llama3:8b` | Great | Fast |
| 24GB | `qwen2.5:32b` | Excellent | Slower |

### Setup

1. Install Ollama:
```bash
# Linux
curl -fsSL https://ollama.ai/install.sh | sh

# macOS
brew install ollama

# Or download from ollama.ai
```

2. Start Ollama:
```bash
ollama serve
```

3. Pull a model:
```bash
ollama pull qwen2.5:14b
```

4. Verify it's working:
```bash
ollama run qwen2.5:14b "Hello, how are you?"
```

5. Enable in `config/providers/providers.yaml`:
```yaml
providers:
  ollama:
    enabled: true
    host: http://localhost:11434
    models:
      simple: llama3.2:3b
      moderate: qwen2.5:14b
      complex: qwen2.5:14b
```

### Tool Use Support

Not all Ollama models support tool calling (needed for financial queries). Known working models:
- `qwen2.5:*` - Good tool support
- `llama3.1:*` and `llama3.2:*` - Good tool support
- `mistral:*` - Partial tool support

---

## Router Configuration

The smart router automatically selects the best model for each query.

### Cost Optimization Settings

In `config/providers/providers.yaml`:

```yaml
routing:
  cost_optimization: balanced  # quality | balanced | cost_conscious
```

**quality:** Always use the best model
- Simple queries → Sonnet
- Complex queries → Opus

**balanced (default):** Match model to query complexity
- Simple queries → Haiku
- Moderate queries → Sonnet
- Complex queries → Sonnet (or Opus if enabled)

**cost_conscious:** Minimize spending
- Simple queries → Haiku
- Moderate queries → Haiku (upgrade only if needed)
- Complex queries → Sonnet

### Fallback Configuration

If your primary provider fails (rate limit, network issue), the router tries fallbacks:

```yaml
routing:
  fallback_enabled: true
  fallback_order:
    - anthropic
    - claude_cli
    - openai
    - ollama
```

---

## Monitoring Usage

### API Costs
The UI shows your API usage and costs in the footer. You can also check:
- Anthropic: console.anthropic.com → Usage
- OpenAI: platform.openai.com → Usage

### CLI Usage
If using Claude CLI, the footer shows:
- Queries in last 5 hours
- Queries in last 7 days
- Estimated savings vs API

---

## Troubleshooting

### "API key invalid"
- Double-check the key in your secrets file
- Ensure no extra spaces or newlines
- Verify the key is active in your provider's dashboard

### "Rate limited"
- Claude CLI: Wait for 5-hour window to reset
- API: Check your usage limits in the dashboard
- Consider enabling fallback providers

### "Ollama not responding"
- Verify Ollama is running: `ollama ps`
- Check the host setting matches where Ollama is running
- Try restarting: `ollama serve`

### "Model not found"
- For Ollama: `ollama pull model-name`
- For API: Check model name spelling in config

### "Tool calls failing"
- Some models don't support tools well
- Try a different model tier
- Ensure you're using a tool-capable model
