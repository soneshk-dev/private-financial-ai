# Cryptocurrency Tracking Setup

Track your Bitcoin, Ethereum, and DeFi holdings with automatic price updates.

## Overview

This system supports:
- **Bitcoin** - Via extended public keys (xpub/ypub/zpub)
- **Ethereum & EVM chains** - Via wallet addresses + Zapper API
- **DeFi positions** - Aave, Uniswap, Compound, etc. via Zapper
- **Exchange accounts** - Some work with Plaid (Coinbase, Kraken)

## Bitcoin Tracking

### What You Need
An extended public key (xpub, ypub, or zpub) from your wallet. This allows balance tracking without spending capability.

### Finding Your xpub

**Ledger (via Ledger Live):**
1. Open Ledger Live
2. Go to Settings → Accounts
3. Select your Bitcoin account
4. Click "Advanced" → "Extended public key"
5. Copy the key starting with `xpub`, `ypub`, or `zpub`

**Trezor (via Trezor Suite):**
1. Open Trezor Suite
2. Select your Bitcoin account
3. Click Account details
4. Click "Show xpub"

**Electrum:**
1. Open your wallet
2. Go to Wallet → Information
3. Copy the "Master Public Key"

**Other wallets:**
Look for "Export xpub" or "Extended public key" in settings.

### Configure Bitcoin Tracking

Create the config file:
```bash
nano ~/.private-financial-ai/secrets/bitcoin_xpubs.conf
```

Add your wallets (one per line):
```
LEDGER_MAIN=xpub6CUGRUonZSQ4TWtTMmzXdrXDtypWZiD6...
TREZOR_SAVINGS=zpub6rFR7y4Q2AijBEqTUquhVz398htDFrtymD9xYYfG1...
```

Set permissions:
```bash
chmod 600 ~/.private-financial-ai/secrets/bitcoin_xpubs.conf
```

### Security Note
- xpubs can VIEW all addresses and balances
- xpubs CANNOT spend your Bitcoin
- Still treat them as sensitive - they reveal your full transaction history

---

## Ethereum & EVM Tracking

### What You Need
1. Your wallet address(es) - the 0x... address
2. A Zapper API key (free)

### Get Zapper API Key

1. Go to [protocol.zapper.xyz](https://protocol.zapper.xyz)
2. Create an account
3. Generate an API key
4. The free tier is generous enough for personal use

### Configure Zapper

Create the config file:
```bash
nano ~/.private-financial-ai/secrets/zapper.conf
```

Add your API key:
```
ZAPPER_API_KEY=your_api_key_here
```

### Add Wallet Addresses

Wallet addresses are stored in the database. Add them via:
1. The web UI: Settings → Crypto Wallets → Add Wallet
2. Or ask the AI: "Add my Ethereum wallet 0x..."

### Supported Networks

Zapper tracks balances on:
- Ethereum mainnet
- Polygon
- Arbitrum
- Optimism
- Base
- Avalanche
- BNB Chain
- And more...

---

## DeFi Position Tracking

If you have funds in DeFi protocols, Zapper automatically detects and tracks:

### Supported Protocols
- **Lending:** Aave, Compound, Maker
- **DEXs:** Uniswap, Sushiswap, Curve
- **Yield:** Yearn, Convex, Lido
- **And many more...**

### What's Tracked
- Supplied collateral
- Borrowed amounts
- Pending rewards
- LP positions
- Staked tokens

### Health Factor Monitoring (Aave)

If you have Aave loans, the system calculates:
- **Health Factor** - How close to liquidation
- **Collateral value** - What you've supplied
- **Debt value** - What you owe
- **Liquidation price** - BTC/ETH price that triggers liquidation

This appears as a badge on the crypto widget with color-coded warnings.

---

## Exchange Account Tracking

### Plaid-Supported Exchanges

Some exchanges work with Plaid:
- Coinbase
- Kraken
- Gemini

Connect these the same way as bank accounts (Settings → Connect Account).

### Manual Tracking

For exchanges not supported by Plaid:
1. Export your holdings as CSV
2. Import via the web UI
3. Update periodically

---

## Sync Frequency

- **Bitcoin:** Checked on-demand when viewing portfolio
- **Ethereum/DeFi:** Synced when calling Zapper API
- **Exchange (Plaid):** Daily automatic sync

---

## Troubleshooting

### "Bitcoin balance showing 0"
- Verify your xpub is correct
- Check if it's xpub (legacy), ypub (segwit), or zpub (native segwit)
- Try a different derivation path if available

### "Missing EVM tokens"
- Ensure Zapper API key is valid
- Check that the wallet address is correct
- Some very new or obscure tokens may not be tracked

### "DeFi position not showing"
- Zapper may not support all protocols
- Try refreshing the sync
- Check Zapper's app directly to verify they see the position

### "Wrong prices"
- Price data comes from CoinGecko via Zapper
- Extreme volatility may cause temporary mismatches
- Very small-cap tokens may have unreliable pricing

---

## Privacy Considerations

### What's Sent to External Services

**Zapper:**
- Your wallet addresses (public anyway)
- No personal information

**Bitcoin tracking:**
- Your xpub (can derive all addresses)
- Uses public blockchain explorers

### What Stays Local
- Your total portfolio value
- Transaction categorization
- AI analysis of your crypto holdings
