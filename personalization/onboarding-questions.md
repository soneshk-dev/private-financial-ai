# Onboarding Conversation Guide

This document outlines the conversation flow for helping a new user set up their Private Financial AI. As an AI assistant, use this as a guide but adapt naturally to the conversation.

## Opening

Start with something like:

> "Let's set up your personal financial assistant. I'll ask you some questions to customize it for your situation. We can always change things later, so don't worry about getting everything perfect right now."

## Phase 1: Personal Information

### Your Name
> "First, what's your name? This helps me personalize the assistant."

**Store as**: `user_name`

### Family/Household
> "Who else is in your household? A spouse or partner? Children?"

For each person mentioned, gather:
- Name
- Relationship (spouse, child, etc.)
- For children: approximate age or expected college year (if relevant)

**Store as**: `family_members[]`

**Example responses to handle**:
- "Just me" → Note: single household
- "My wife Sarah and two kids" → Follow up for kids' names/ages
- "Partner Alex, no kids" → Note: partner named Alex

### Work (Optional)
> "Where do you work? This is optional but helps categorize paychecks correctly."

**Store as**: `employer`

---

## Phase 2: Financial Goals

> "What are you trying to accomplish financially? Common goals include retirement savings, paying off debt, saving for kids' college, or building an emergency fund."

Let them list freely, then for each goal ask:
- Target amount (if applicable)
- Target date (if applicable)

**Example conversation**:
> User: "Mainly retirement and paying off our mortgage"
>
> AI: "Great. For retirement, do you have a target age or amount in mind?"
>
> User: "Hoping to retire around 60 with about $2M saved"
>
> AI: "And the mortgage - what's the rough balance and when would you like it paid off?"

**Store as**: `financial_goals[]`

---

## Phase 3: AI Provider

> "Now let's set up the AI that powers this assistant. You have a few options:"

Present the options based on their likely situation:

### For most users (recommend Claude):
> "I recommend using Claude (from Anthropic). It costs about $5-20 per month depending on usage. You'll need to get an API key from anthropic.com."

### If they mention cost concerns:
> "If you have a Claude Max subscription ($20/month), you can use the Claude CLI which gives you unlimited access at no extra cost."

### If they mention privacy concerns:
> "If you want everything to stay on your computer, you can use Ollama to run AI models locally. It requires a decent graphics card but has no ongoing costs and maximum privacy."

### If they're technical or want flexibility:
> "You can also set up multiple providers - for example, use free local models for simple questions and Claude for complex analysis."

**Questions to determine**:
1. Which provider(s)?
2. Cost vs quality preference (if using paid API)

**Store as**: `primary_provider`, `cost_preference`

---

## Phase 4: Bank Connections

> "Would you like to automatically sync your bank transactions? This uses a service called Plaid that securely connects to most US banks."

**If yes**:
> "Great! You'll need to create a free Plaid developer account. I'll walk you through that - it takes about 10 minutes. Which banks do you use?"

List their banks for reference during Plaid setup.

**If no or hesitant**:
> "No problem. You can always import transactions manually from CSV files that most banks let you download. We can set up Plaid later if you change your mind."

**Store as**: `use_plaid`, `banks[]`

---

## Phase 5: Investments

> "Do you have any investment accounts you'd like to track? Things like 401k, IRA, brokerage accounts?"

**If yes**:
> "Where are those accounts held? Fidelity, Vanguard, Schwab, somewhere else?"

Note: Most investment tracking is done via CSV import (download positions from brokerage website). Some may work with Plaid for basic balance info.

**Store as**: `has_investments`, `investment_institutions[]`

---

## Phase 6: Cryptocurrency

> "Do you hold any cryptocurrency?"

**If yes**:
> "What types? Bitcoin, Ethereum, exchange accounts, DeFi?"

For Bitcoin:
> "To track Bitcoin, I'll need your wallet's extended public key (xpub). This lets me see your balance without being able to spend anything. Do you know how to find that, or should I explain?"

For Ethereum/EVM:
> "For Ethereum tracking, I just need your wallet address - the one that starts with 0x."

For DeFi:
> "For DeFi positions, we'll use a service called Zapper. You can get a free API key at protocol.zapper.xyz."

**Store as**: `has_crypto`, `crypto_types[]`, relevant wallet info

---

## Phase 7: Privacy Preferences

> "Last question: how do you feel about your financial data and cloud services?"

Options:
1. **Comfortable**: "I'm fine with the AI seeing my queries"
2. **Minimize**: "I'd prefer local processing when possible"
3. **Local only**: "I don't want anything going to the cloud"

This affects router configuration.

**Store as**: `privacy_preference`

---

## Wrap-up

After gathering info:

> "Great, I have everything I need. Here's what I'll set up:
>
> - [Summary of their configuration]
>
> Ready to proceed?"

Then:
1. Generate configuration files
2. Guide through any external setup (Plaid, API keys)
3. Initialize database
4. Start the server
5. Verify everything works

---

## Handling Common Situations

### "I'm not sure about X"
> "That's fine - we can skip it for now and add it later. The system is designed to grow with you."

### "This seems complicated"
> "Let's take it one step at a time. The most basic setup just needs an AI provider and some transaction data - everything else is optional."

### "I already have transactions in CSV files"
> "Perfect! We can import those directly. What bank or format are they from?"

### "Can I change this later?"
> "Absolutely. All these settings can be updated anytime. Nothing is permanent."

### They want to start minimal
> "Let's start simple then: just the AI provider and manual CSV imports. You can add bank connections and crypto tracking whenever you're ready."
