"""
Cryptocurrency tracking tools.
Supports Bitcoin (via xpub), EVM wallets (via Zapper), and DeFi positions.
"""

import os
import sqlite3
import requests
from datetime import datetime
from typing import Dict, List, Optional, Any


class CryptoTools:
    """Tools for cryptocurrency tracking."""

    def __init__(self, db_path: str, secrets_path: Optional[str] = None):
        self.db_path = db_path
        self.secrets_path = secrets_path or os.path.expanduser('~/.private-financial-ai/secrets')
        self.zapper_api_key = self._load_zapper_key()

    def _load_zapper_key(self) -> Optional[str]:
        """Load Zapper API key from config."""
        config_path = os.path.join(self.secrets_path, 'zapper.conf')
        if not os.path.exists(config_path):
            return None

        try:
            with open(config_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('ZAPPER_API_KEY='):
                        return line.split('=', 1)[1].strip()
        except Exception:
            pass
        return None

    def _get_conn(self):
        return sqlite3.connect(self.db_path)

    def get_crypto_holdings(self) -> Dict[str, Any]:
        """
        Get all cryptocurrency holdings.

        Returns:
            Dict with crypto holdings by type
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        result = {
            "bitcoin": [],
            "evm_tokens": [],
            "defi_positions": [],
            "total_value": 0
        }

        # Get Bitcoin holdings
        cursor.execute("""
            SELECT label, balance_btc, balance_usd, last_updated
            FROM bitcoin_wallets
            WHERE balance_btc > 0
        """)

        for row in cursor.fetchall():
            value = row[2] or 0
            result["bitcoin"].append({
                "label": row[0],
                "balance_btc": row[1],
                "value_usd": round(value, 2),
                "last_updated": row[3]
            })
            result["total_value"] += value

        # Get EVM token balances
        cursor.execute("""
            SELECT
                cw.label,
                cb.chain,
                cb.token_symbol,
                cb.token_name,
                cb.balance,
                cb.balance_usd,
                cb.last_updated
            FROM crypto_balances cb
            JOIN crypto_wallets cw ON cb.wallet_id = cw.wallet_id
            WHERE cb.balance_usd > 1
            ORDER BY cb.balance_usd DESC
        """)

        for row in cursor.fetchall():
            value = row[5] or 0
            result["evm_tokens"].append({
                "wallet": row[0],
                "chain": row[1],
                "symbol": row[2],
                "name": row[3],
                "balance": row[4],
                "value_usd": round(value, 2)
            })
            result["total_value"] += value

        # Get DeFi positions
        cursor.execute("""
            SELECT
                cw.label,
                dp.protocol,
                dp.chain,
                dp.position_type,
                dp.balance_usd,
                dp.last_updated
            FROM defi_positions dp
            JOIN crypto_wallets cw ON dp.wallet_id = cw.wallet_id
            WHERE dp.balance_usd > 1
            ORDER BY dp.balance_usd DESC
        """)

        for row in cursor.fetchall():
            value = row[4] or 0
            result["defi_positions"].append({
                "wallet": row[0],
                "protocol": row[1],
                "chain": row[2],
                "position_type": row[3],
                "value_usd": round(value, 2)
            })
            # DeFi positions already included in token balances typically

        conn.close()

        result["total_value"] = round(result["total_value"], 2)
        return result

    def get_defi_positions(self, protocol: Optional[str] = None) -> Dict[str, Any]:
        """
        Get detailed DeFi position breakdown.

        Args:
            protocol: Optional filter by protocol name

        Returns:
            Dict with DeFi positions and details
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        if protocol:
            cursor.execute("""
                SELECT
                    dp.position_id,
                    cw.label,
                    dp.protocol,
                    dp.chain,
                    dp.position_type,
                    dp.balance_usd
                FROM defi_positions dp
                JOIN crypto_wallets cw ON dp.wallet_id = cw.wallet_id
                WHERE dp.protocol LIKE ?
                ORDER BY dp.balance_usd DESC
            """, (f"%{protocol}%",))
        else:
            cursor.execute("""
                SELECT
                    dp.position_id,
                    cw.label,
                    dp.protocol,
                    dp.chain,
                    dp.position_type,
                    dp.balance_usd
                FROM defi_positions dp
                JOIN crypto_wallets cw ON dp.wallet_id = cw.wallet_id
                ORDER BY dp.balance_usd DESC
            """)

        positions = []

        for row in cursor.fetchall():
            position = {
                "position_id": row[0],
                "wallet": row[1],
                "protocol": row[2],
                "chain": row[3],
                "position_type": row[4],
                "balance_usd": round(row[5], 2) if row[5] else 0,
                "details": []
            }

            # Get position details
            cursor.execute("""
                SELECT detail_type, token_symbol, token_name, balance, balance_usd
                FROM defi_position_details
                WHERE position_id = ?
                ORDER BY balance_usd DESC
            """, (row[0],))

            for detail in cursor.fetchall():
                position["details"].append({
                    "type": detail[0],
                    "symbol": detail[1],
                    "name": detail[2],
                    "balance": detail[3],
                    "value_usd": round(detail[4], 2) if detail[4] else 0
                })

            positions.append(position)

        conn.close()

        return {
            "positions": positions,
            "filter": protocol
        }

    def sync_evm_wallets(self) -> Dict[str, Any]:
        """
        Sync EVM wallet balances from Zapper.

        Returns:
            Dict with sync results
        """
        if not self.zapper_api_key:
            return {
                "success": False,
                "error": "Zapper API key not configured. See docs/CRYPTO_SETUP.md"
            }

        conn = self._get_conn()
        cursor = conn.cursor()

        # Get all active wallets
        cursor.execute("""
            SELECT wallet_id, address, label
            FROM crypto_wallets
            WHERE is_active = 1
        """)
        wallets = cursor.fetchall()

        if not wallets:
            conn.close()
            return {
                "success": False,
                "error": "No wallets configured"
            }

        total_synced = 0
        errors = []

        for wallet_id, address, label in wallets:
            try:
                # Fetch balances from Zapper
                headers = {
                    "Authorization": f"Basic {self.zapper_api_key}",
                    "Content-Type": "application/json"
                }

                # Get token balances
                response = requests.get(
                    f"https://api.zapper.xyz/v2/balances",
                    headers=headers,
                    params={"addresses[]": address},
                    timeout=30
                )

                if response.status_code == 200:
                    data = response.json()

                    # Clear old balances
                    cursor.execute(
                        "DELETE FROM crypto_balances WHERE wallet_id = ?",
                        (wallet_id,)
                    )

                    # Insert new balances
                    for item in data.get('balances', []):
                        cursor.execute("""
                            INSERT INTO crypto_balances
                            (wallet_id, chain, token_symbol, token_name,
                             balance, balance_usd, price_usd, last_updated)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            wallet_id,
                            item.get('network', 'ethereum'),
                            item.get('symbol'),
                            item.get('name'),
                            item.get('balance'),
                            item.get('balanceUSD'),
                            item.get('price'),
                            datetime.now().isoformat()
                        ))
                        total_synced += 1

            except Exception as e:
                errors.append(f"Error syncing {label}: {str(e)}")

        conn.commit()
        conn.close()

        return {
            "success": True,
            "wallets_synced": len(wallets),
            "balances_updated": total_synced,
            "errors": errors if errors else None
        }

    def get_bitcoin_holdings(self) -> Dict[str, Any]:
        """
        Get Bitcoin wallet holdings.

        Returns:
            Dict with Bitcoin balances
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT label, balance_btc, balance_usd, last_updated
            FROM bitcoin_wallets
            ORDER BY balance_usd DESC
        """)

        wallets = []
        total_btc = 0
        total_usd = 0

        for row in cursor.fetchall():
            btc = row[1] or 0
            usd = row[2] or 0
            wallets.append({
                "label": row[0],
                "balance_btc": btc,
                "value_usd": round(usd, 2),
                "last_updated": row[3]
            })
            total_btc += btc
            total_usd += usd

        conn.close()

        return {
            "wallets": wallets,
            "total_btc": round(total_btc, 8),
            "total_usd": round(total_usd, 2)
        }


# Tool definitions for LLM
CRYPTO_TOOLS = [
    {
        "name": "get_crypto_holdings",
        "description": "Get all cryptocurrency holdings including Bitcoin, EVM tokens, and DeFi positions.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_defi_positions",
        "description": "Get detailed DeFi position breakdown (supplied, borrowed, claimable rewards).",
        "input_schema": {
            "type": "object",
            "properties": {
                "protocol": {
                    "type": "string",
                    "description": "Filter by protocol name (e.g., 'Aave', 'Uniswap')"
                }
            }
        }
    },
    {
        "name": "get_bitcoin_holdings",
        "description": "Get Bitcoin wallet holdings and total balance.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "sync_evm_wallets",
        "description": "Sync EVM wallet balances from Zapper API.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    }
]
