"""
Plaid integration tools.
Handles bank account connections and transaction syncing.
"""

import os
import sqlite3
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any


class PlaidTools:
    """Tools for Plaid bank connections."""

    def __init__(self, db_path: str, secrets_path: Optional[str] = None):
        self.db_path = db_path
        self.secrets_path = secrets_path or os.path.expanduser('~/.private-financial-ai/secrets')
        self.client = None
        self._init_client()

    def _init_client(self):
        """Initialize Plaid client from config."""
        config_path = os.path.join(self.secrets_path, 'plaid.conf')
        if not os.path.exists(config_path):
            return

        config = {}
        try:
            with open(config_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if '=' in line and not line.startswith('#'):
                        key, value = line.split('=', 1)
                        config[key.strip()] = value.strip()
        except Exception:
            return

        client_id = config.get('PLAID_CLIENT_ID')
        secret = config.get('PLAID_SECRET')
        env = config.get('PLAID_ENV', 'development')

        if not client_id or not secret:
            return

        try:
            import plaid
            from plaid.api import plaid_api
            from plaid.configuration import Configuration

            env_map = {
                'sandbox': plaid.Environment.Sandbox,
                'development': plaid.Environment.Development,
                'production': plaid.Environment.Production,
            }

            configuration = Configuration(
                host=env_map.get(env, plaid.Environment.Development),
                api_key={
                    'clientId': client_id,
                    'secret': secret,
                }
            )

            api_client = plaid.ApiClient(configuration)
            self.client = plaid_api.PlaidApi(api_client)
        except ImportError:
            pass
        except Exception:
            pass

    def _get_conn(self):
        return sqlite3.connect(self.db_path)

    def is_available(self) -> bool:
        """Check if Plaid is configured."""
        return self.client is not None

    def get_plaid_status(self) -> Dict[str, Any]:
        """
        Get Plaid integration status.

        Returns:
            Dict with status and connected institutions
        """
        if not self.client:
            return {
                "status": "not_configured",
                "message": "Plaid credentials not found. See docs/PLAID_SETUP.md"
            }

        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                item_id,
                institution_name,
                status,
                updated_at
            FROM plaid_items
            WHERE status != 'removed'
        """)

        items = []
        for row in cursor.fetchall():
            items.append({
                "item_id": row[0],
                "institution": row[1],
                "status": row[2],
                "last_updated": row[3]
            })

        conn.close()

        return {
            "status": "configured",
            "connected_institutions": len(items),
            "items": items
        }

    def list_linked_accounts(self) -> Dict[str, Any]:
        """
        List all accounts linked via Plaid.

        Returns:
            Dict with account details
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                a.account_id,
                a.name,
                a.type,
                a.institution,
                a.current_balance,
                a.mask
            FROM accounts a
            JOIN plaid_accounts pa ON a.account_id = pa.account_id
            WHERE a.is_active = 1
            ORDER BY a.institution, a.name
        """)

        accounts = []
        for row in cursor.fetchall():
            accounts.append({
                "account_id": row[0],
                "name": row[1],
                "type": row[2],
                "institution": row[3],
                "balance": row[4],
                "mask": row[5]
            })

        conn.close()

        return {
            "accounts": accounts,
            "count": len(accounts)
        }

    def get_bank_balances(self) -> Dict[str, Any]:
        """
        Get current balances from all linked accounts.

        Returns:
            Dict with account balances
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                a.name,
                a.type,
                a.institution,
                a.current_balance,
                a.available_balance,
                a.credit_limit,
                a.updated_at
            FROM accounts a
            WHERE a.is_active = 1
            ORDER BY a.type, a.current_balance DESC
        """)

        accounts = []
        total_checking = 0
        total_savings = 0
        total_credit = 0
        total_available = 0

        for row in cursor.fetchall():
            account_type = row[1] or ''
            balance = row[3] or 0

            accounts.append({
                "name": row[0],
                "type": account_type,
                "institution": row[2],
                "balance": balance,
                "available": row[4],
                "credit_limit": row[5],
                "last_updated": row[6]
            })

            if 'checking' in account_type.lower():
                total_checking += balance
                total_available += (row[4] or balance)
            elif 'saving' in account_type.lower():
                total_savings += balance
            elif 'credit' in account_type.lower():
                total_credit += balance

        conn.close()

        return {
            "accounts": accounts,
            "summary": {
                "checking": round(total_checking, 2),
                "savings": round(total_savings, 2),
                "credit_used": round(abs(total_credit), 2),
                "total_available": round(total_available, 2)
            }
        }

    def sync_transactions(self) -> Dict[str, Any]:
        """
        Sync transactions from all linked Plaid accounts.

        Returns:
            Dict with sync results
        """
        if not self.client:
            return {
                "success": False,
                "error": "Plaid not configured"
            }

        conn = self._get_conn()
        cursor = conn.cursor()

        # Get all active items
        cursor.execute("SELECT item_id, access_token FROM plaid_items WHERE status = 'active'")
        items = cursor.fetchall()

        total_new = 0
        total_modified = 0
        errors = []

        try:
            from plaid.model.transactions_sync_request import TransactionsSyncRequest

            for item_id, access_token in items:
                try:
                    # Get cursor for incremental sync
                    cursor.execute(
                        "SELECT sync_cursor FROM plaid_items WHERE item_id = ?",
                        (item_id,)
                    )
                    row = cursor.fetchone()
                    sync_cursor = row[0] if row and row[0] else ""

                    # Sync transactions
                    request = TransactionsSyncRequest(
                        access_token=access_token,
                        cursor=sync_cursor if sync_cursor else None
                    )

                    response = self.client.transactions_sync(request)

                    # Process new transactions
                    for txn in response.added:
                        txn_id = f"plaid_{txn.transaction_id}"
                        amount = -txn.amount  # Plaid uses positive for expenses

                        cursor.execute("""
                            INSERT OR IGNORE INTO transactions
                            (transaction_id, account_id, date, amount, description,
                             merchant_name, category, source_type, plaid_transaction_id)
                            VALUES (?, ?, ?, ?, ?, ?, ?, 'plaid', ?)
                        """, (
                            txn_id,
                            f"plaid_{txn.account_id}",
                            txn.date.isoformat(),
                            amount,
                            txn.name,
                            txn.merchant_name,
                            txn.personal_finance_category.primary if txn.personal_finance_category else None,
                            txn.transaction_id
                        ))
                        total_new += 1

                    # Update cursor
                    cursor.execute(
                        "UPDATE plaid_items SET sync_cursor = ?, updated_at = ? WHERE item_id = ?",
                        (response.next_cursor, datetime.now().isoformat(), item_id)
                    )

                except Exception as e:
                    errors.append(f"Error syncing item {item_id}: {str(e)}")

            conn.commit()

        except ImportError:
            return {
                "success": False,
                "error": "Plaid library not installed"
            }
        finally:
            conn.close()

        return {
            "success": True,
            "new_transactions": total_new,
            "modified_transactions": total_modified,
            "errors": errors if errors else None
        }


# Tool definitions for LLM
PLAID_TOOLS = [
    {
        "name": "get_plaid_status",
        "description": "Get Plaid integration status including connected institutions and sync activity.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "list_linked_accounts",
        "description": "List all bank accounts linked via Plaid with status and last sync time.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_bank_balances",
        "description": "Get current balances from all linked bank accounts (checking, savings, credit cards).",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "sync_transactions",
        "description": "Sync transactions from all linked Plaid accounts. Returns count of new and modified transactions.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    }
]
