# Plaid Setup Guide

Plaid connects your bank accounts to automatically import transactions. This guide walks you through the complete setup process.

## Overview

**What Plaid does:**
- Securely connects to 12,000+ financial institutions
- Automatically syncs transactions daily
- Provides real-time balance information
- Works with checking, savings, credit cards, and some investment accounts

**Privacy note:** Plaid acts as a secure intermediary. Your bank credentials are never stored in this application - they go directly to Plaid's secure infrastructure.

## Step 1: Create a Plaid Account

1. Go to [dashboard.plaid.com](https://dashboard.plaid.com)
2. Click "Get Started" or "Sign Up"
3. Fill out the registration form
4. Verify your email

## Step 2: Get Your API Credentials

1. Log into the Plaid Dashboard
2. Navigate to **Developers** → **Keys**
3. You'll see:
   - `client_id` - Your unique identifier
   - `secret` - For each environment (sandbox, development, production)

4. Copy the **development** secret (we'll start there)

## Step 3: Configure Your Application

Create the secrets directory if it doesn't exist:
```bash
mkdir -p ~/.private-financial-ai/secrets
```

Create the Plaid configuration file:
```bash
nano ~/.private-financial-ai/secrets/plaid.conf
```

Add your credentials:
```
PLAID_CLIENT_ID=your_client_id_here
PLAID_SECRET=your_development_secret_here
PLAID_ENV=development
```

Set secure permissions:
```bash
chmod 600 ~/.private-financial-ai/secrets/plaid.conf
```

## Step 4: Understand Plaid Environments

| Environment | Cost | Real Data? | Use Case |
|-------------|------|------------|----------|
| **Sandbox** | Free | No (test data) | Initial testing |
| **Development** | Free | Yes | Personal use (up to 100 connections) |
| **Production** | Paid | Yes | If you need more than 100 connections |

**Recommendation:** Start with `development` - it's free and uses real bank connections.

## Step 5: Link Your First Bank Account

1. Start your Private Financial AI server
2. Go to the web interface
3. Click "Connect Bank Account" or navigate to Settings → Bank Connections
4. Click "Add Account"
5. Search for your bank in the Plaid Link modal
6. Enter your bank credentials (these go to Plaid, not our app)
7. Complete any MFA challenges (text codes, etc.)
8. Select which accounts to link

## Step 6: Initial Sync

After linking, the system will:
1. Fetch the last 90 days of transactions
2. Categorize transactions automatically
3. Calculate balances

This may take a minute for accounts with many transactions.

## Step 7: Set Up Automatic Sync

The application syncs automatically every day at 6 AM. You can also:
- Click "Sync Now" in the UI for immediate sync
- Call the API directly: `POST /api/plaid/sync`

## Supported Institutions

Plaid supports most US banks including:
- Chase
- Bank of America
- Wells Fargo
- Capital One
- Citibank
- US Bank
- Most credit unions
- Many more...

Check [plaid.com/institutions](https://plaid.com/institutions) for the full list.

## Troubleshooting

### "Institution not supported"
Some smaller banks or credit unions may not be available. Options:
- Check if the bank has a different name in Plaid
- Use CSV import as an alternative
- Contact Plaid to request support

### "Connection error" during link
- Try a different browser
- Disable ad blockers temporarily
- Check if your bank is experiencing issues

### "Re-authentication required"
Banks periodically require you to re-enter credentials. When this happens:
1. Go to Settings → Bank Connections
2. Click "Fix" next to the affected account
3. Re-enter your credentials

### "Missing transactions"
- Plaid only fetches transactions after the connection date
- Historical data (before connection) requires CSV import
- Some pending transactions may not appear immediately

## Multi-Factor Authentication (MFA)

When linking accounts with MFA enabled:
1. Enter your username/password
2. Wait for the MFA challenge (text, email, or authenticator)
3. Enter the code in the Plaid Link modal
4. Complete the connection

## Security Best Practices

1. **Never share your Plaid credentials** - They can access your bank data
2. **Use development, not sandbox** - Sandbox uses fake data
3. **Monitor connected accounts** - Review in Settings periodically
4. **Revoke unused connections** - Remove accounts you no longer need

## Costs

For personal use, Plaid's **Development** environment is free and sufficient:
- Up to 100 connected items (bank connections)
- Real bank data
- No monthly fees

If you need more than 100 connections, you'll need Production access which has per-connection fees.

## Next Steps

After setting up Plaid:
1. Import historical transactions via CSV (for data before Plaid connection)
2. Review transaction categories and correct any mistakes
3. Set up budget categories based on your spending patterns
