"""
Portfolio and investment analysis tools.
Provides holdings, allocation, and performance data.
"""

import sqlite3
from typing import Dict, List, Optional, Any


class PortfolioTools:
    """Tools for analyzing investment portfolio."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def _get_conn(self):
        return sqlite3.connect(self.db_path)

    def get_portfolio_summary(self) -> Dict[str, Any]:
        """
        Get overall portfolio summary.

        Returns:
            Dict with total value, allocation by account type, and gains
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        # Get holdings by account type
        query = """
        SELECT
            ia.account_type,
            ia.institution,
            SUM(h.current_value) as total_value,
            SUM(h.cost_basis) as total_cost
        FROM holdings h
        JOIN investment_accounts ia ON h.account_id = ia.account_id
        WHERE h.is_active = 1 AND ia.is_active = 1
        GROUP BY ia.account_type, ia.institution
        ORDER BY total_value DESC
        """

        cursor.execute(query)
        rows = cursor.fetchall()

        accounts = []
        total_value = 0
        total_cost = 0

        for row in rows:
            value = row[2] or 0
            cost = row[3] or 0
            accounts.append({
                "account_type": row[0],
                "institution": row[1],
                "value": round(value, 2),
                "cost_basis": round(cost, 2) if cost else None,
                "gain": round(value - cost, 2) if cost else None
            })
            total_value += value
            total_cost += cost if cost else 0

        conn.close()

        return {
            "total_value": round(total_value, 2),
            "total_cost_basis": round(total_cost, 2) if total_cost else None,
            "total_gain": round(total_value - total_cost, 2) if total_cost else None,
            "accounts": accounts
        }

    def get_holdings_by_account(
        self,
        account_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get individual holdings, optionally filtered by account.

        Args:
            account_name: Optional account name filter

        Returns:
            Dict with holdings details
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        if account_name:
            query = """
            SELECT
                ia.account_name,
                h.symbol,
                h.name,
                h.quantity,
                h.price,
                h.current_value,
                h.cost_basis,
                h.asset_type
            FROM holdings h
            JOIN investment_accounts ia ON h.account_id = ia.account_id
            WHERE h.is_active = 1 AND ia.is_active = 1
              AND ia.account_name LIKE ?
            ORDER BY h.current_value DESC
            """
            cursor.execute(query, (f"%{account_name}%",))
        else:
            query = """
            SELECT
                ia.account_name,
                h.symbol,
                h.name,
                h.quantity,
                h.price,
                h.current_value,
                h.cost_basis,
                h.asset_type
            FROM holdings h
            JOIN investment_accounts ia ON h.account_id = ia.account_id
            WHERE h.is_active = 1 AND ia.is_active = 1
            ORDER BY h.current_value DESC
            """
            cursor.execute(query)

        rows = cursor.fetchall()

        holdings = []
        for row in rows:
            value = row[5] or 0
            cost = row[6]
            holdings.append({
                "account": row[0],
                "symbol": row[1],
                "name": row[2],
                "quantity": row[3],
                "price": row[4],
                "value": round(value, 2),
                "cost_basis": round(cost, 2) if cost else None,
                "gain": round(value - cost, 2) if cost else None,
                "asset_type": row[7]
            })

        conn.close()

        return {
            "holdings": holdings,
            "count": len(holdings),
            "filter": account_name
        }

    def get_asset_allocation(self) -> Dict[str, Any]:
        """
        Get asset allocation breakdown.

        Returns:
            Dict with allocation by asset type
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        query = """
        SELECT
            COALESCE(h.asset_type, 'Unknown') as asset_type,
            SUM(h.current_value) as total_value
        FROM holdings h
        JOIN investment_accounts ia ON h.account_id = ia.account_id
        WHERE h.is_active = 1 AND ia.is_active = 1
        GROUP BY h.asset_type
        ORDER BY total_value DESC
        """

        cursor.execute(query)
        rows = cursor.fetchall()

        total = sum(row[1] or 0 for row in rows)
        allocation = []

        for row in rows:
            value = row[1] or 0
            pct = (value / total * 100) if total > 0 else 0
            allocation.append({
                "asset_type": row[0],
                "value": round(value, 2),
                "percentage": round(pct, 1)
            })

        conn.close()

        return {
            "total_value": round(total, 2),
            "allocation": allocation
        }

    def get_top_holdings(self, limit: int = 10) -> Dict[str, Any]:
        """
        Get top holdings by value.

        Args:
            limit: Number of holdings to return

        Returns:
            Dict with top holdings
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        query = """
        SELECT
            h.symbol,
            h.name,
            SUM(h.current_value) as total_value,
            SUM(h.quantity) as total_quantity,
            h.price
        FROM holdings h
        JOIN investment_accounts ia ON h.account_id = ia.account_id
        WHERE h.is_active = 1 AND ia.is_active = 1
          AND h.symbol IS NOT NULL
        GROUP BY h.symbol, h.name
        ORDER BY total_value DESC
        LIMIT ?
        """

        cursor.execute(query, (limit,))
        rows = cursor.fetchall()

        holdings = []
        for row in rows:
            holdings.append({
                "symbol": row[0],
                "name": row[1],
                "total_value": round(row[2], 2),
                "total_quantity": row[3],
                "price": row[4]
            })

        conn.close()

        return {
            "top_holdings": holdings
        }

    def get_account_summary(self) -> Dict[str, Any]:
        """
        Get summary grouped by account type (401k, IRA, Brokerage, etc.)

        Returns:
            Dict with account type summaries
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        query = """
        SELECT
            ia.account_type,
            COUNT(DISTINCT ia.account_id) as account_count,
            SUM(h.current_value) as total_value
        FROM investment_accounts ia
        LEFT JOIN holdings h ON ia.account_id = h.account_id AND h.is_active = 1
        WHERE ia.is_active = 1
        GROUP BY ia.account_type
        ORDER BY total_value DESC
        """

        cursor.execute(query)
        rows = cursor.fetchall()

        summary = []
        total = 0

        for row in rows:
            value = row[2] or 0
            summary.append({
                "account_type": row[0],
                "account_count": row[1],
                "total_value": round(value, 2)
            })
            total += value

        conn.close()

        return {
            "total_portfolio": round(total, 2),
            "by_account_type": summary
        }


# Tool definitions for LLM
PORTFOLIO_TOOLS = [
    {
        "name": "get_portfolio_summary",
        "description": "Get overall portfolio summary including total value, allocation by account type, and gains.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_holdings_by_account",
        "description": "Get individual holdings with current values and cost basis. Optionally filter by account name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "account_name": {
                    "type": "string",
                    "description": "Optional filter by account name"
                }
            }
        }
    },
    {
        "name": "get_asset_allocation",
        "description": "Get asset allocation breakdown (stocks, bonds, cash, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_top_holdings",
        "description": "Get top holdings by current value.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Number of holdings to return",
                    "default": 10
                }
            }
        }
    },
    {
        "name": "get_account_summary",
        "description": "Get portfolio summary grouped by account type (401k, IRA, Brokerage, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    }
]
