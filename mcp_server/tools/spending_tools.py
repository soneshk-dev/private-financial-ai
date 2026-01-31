"""
Spending analysis tools.
Provides transaction search, category breakdowns, and cash flow analysis.
"""

import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any


class SpendingTools:
    """Tools for analyzing spending and transactions."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def _get_conn(self):
        return sqlite3.connect(self.db_path)

    def get_spending_by_category(
        self,
        year: Optional[int] = None,
        month: Optional[int] = None,
        top_level_only: bool = False,
        limit: int = 15
    ) -> Dict[str, Any]:
        """
        Get spending breakdown by category.

        Args:
            year: Filter to specific year (optional)
            month: Filter to specific month 1-12 (requires year)
            top_level_only: If True, only show top-level categories
            limit: Max categories to return

        Returns:
            Dict with categories, amounts, and totals
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        # Build date filter
        date_filter = ""
        params = []

        if year and month:
            date_filter = "AND strftime('%Y-%m', date) = ?"
            params.append(f"{year:04d}-{month:02d}")
        elif year:
            date_filter = "AND strftime('%Y', date) = ?"
            params.append(f"{year:04d}")

        # Category expression
        if top_level_only:
            category_expr = "CASE WHEN INSTR(category_normalized, ':') > 0 THEN SUBSTR(category_normalized, 1, INSTR(category_normalized, ':') - 1) ELSE category_normalized END"
        else:
            category_expr = "category_normalized"

        query = f"""
        SELECT
            {category_expr} as category,
            SUM(ABS(amount)) as total,
            COUNT(*) as transaction_count
        FROM transactions
        WHERE amount < 0
          AND is_duplicate = 0
          AND is_transfer = 0
          AND category_normalized NOT LIKE '%Transfer%'
          AND category_normalized NOT LIKE '%Investment%'
          AND category_normalized NOT LIKE '%Cryptocurrency%'
          {date_filter}
        GROUP BY {category_expr}
        ORDER BY total DESC
        LIMIT ?
        """
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()

        categories = []
        total_spending = 0

        for row in rows:
            categories.append({
                "category": row[0] or "Uncategorized",
                "amount": round(row[1], 2),
                "transaction_count": row[2]
            })
            total_spending += row[1]

        conn.close()

        return {
            "categories": categories,
            "total_spending": round(total_spending, 2),
            "period": f"{year}-{month:02d}" if month else str(year) if year else "all time"
        }

    def search_transactions(
        self,
        merchant: str,
        limit: int = 20
    ) -> Dict[str, Any]:
        """
        Search transactions by merchant name or description.

        Args:
            merchant: Search term
            limit: Max results

        Returns:
            Dict with matching transactions
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        query = """
        SELECT
            date,
            merchant_name,
            description,
            amount,
            category_normalized
        FROM transactions
        WHERE (merchant_name LIKE ? OR description LIKE ?)
          AND is_duplicate = 0
        ORDER BY date DESC
        LIMIT ?
        """

        search_term = f"%{merchant}%"
        cursor.execute(query, (search_term, search_term, limit))
        rows = cursor.fetchall()

        transactions = []
        for row in rows:
            transactions.append({
                "date": row[0],
                "merchant": row[1] or row[2],
                "amount": row[3],
                "category": row[4]
            })

        conn.close()

        return {
            "search_term": merchant,
            "count": len(transactions),
            "transactions": transactions
        }

    def get_monthly_cash_flow(self, months: int = 6) -> Dict[str, Any]:
        """
        Get monthly income and expenses.

        Args:
            months: Number of months to analyze

        Returns:
            Dict with monthly cash flow data
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        # Get date range
        end_date = datetime.now()
        start_date = end_date - timedelta(days=months * 30)

        query = """
        SELECT
            strftime('%Y-%m', date) as month,
            SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) as income,
            SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END) as expenses
        FROM transactions
        WHERE date >= ?
          AND is_duplicate = 0
          AND is_transfer = 0
        GROUP BY strftime('%Y-%m', date)
        ORDER BY month DESC
        """

        cursor.execute(query, (start_date.strftime('%Y-%m-%d'),))
        rows = cursor.fetchall()

        monthly_data = []
        for row in rows:
            income = row[1] or 0
            expenses = row[2] or 0
            net = income - expenses
            savings_rate = (net / income * 100) if income > 0 else 0

            monthly_data.append({
                "month": row[0],
                "income": round(income, 2),
                "expenses": round(expenses, 2),
                "net": round(net, 2),
                "savings_rate": round(savings_rate, 1)
            })

        conn.close()

        return {
            "months_analyzed": months,
            "data": monthly_data
        }

    def detect_recurring_expenses(
        self,
        months: int = 6,
        min_occurrences: int = 3
    ) -> Dict[str, Any]:
        """
        Detect recurring expenses/subscriptions.

        Args:
            months: Number of months to analyze
            min_occurrences: Minimum occurrences to be considered recurring

        Returns:
            Dict with detected subscriptions
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        start_date = (datetime.now() - timedelta(days=months * 30)).strftime('%Y-%m-%d')

        query = """
        SELECT
            COALESCE(merchant_name, description) as merchant,
            ROUND(ABS(amount), 0) as amount_rounded,
            COUNT(*) as occurrences,
            AVG(ABS(amount)) as avg_amount,
            GROUP_CONCAT(DISTINCT strftime('%Y-%m', date)) as months_charged
        FROM transactions
        WHERE date >= ?
          AND amount < 0
          AND is_duplicate = 0
          AND is_transfer = 0
        GROUP BY merchant, amount_rounded
        HAVING occurrences >= ?
        ORDER BY avg_amount DESC
        """

        cursor.execute(query, (start_date, min_occurrences))
        rows = cursor.fetchall()

        recurring = []
        total_monthly = 0

        for row in rows:
            monthly_amount = row[3]
            recurring.append({
                "merchant": row[0],
                "amount": round(row[3], 2),
                "frequency": row[2],
                "months": row[4]
            })
            total_monthly += monthly_amount

        conn.close()

        return {
            "recurring_expenses": recurring,
            "estimated_monthly_total": round(total_monthly, 2),
            "months_analyzed": months
        }

    def get_deposits(
        self,
        months: int = 4,
        limit: int = 30
    ) -> Dict[str, Any]:
        """
        Get recent deposits/income.

        Args:
            months: Months to look back
            limit: Max transactions

        Returns:
            Dict with deposit transactions
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        start_date = (datetime.now() - timedelta(days=months * 30)).strftime('%Y-%m-%d')

        query = """
        SELECT
            date,
            COALESCE(merchant_name, description) as source,
            amount,
            category_normalized
        FROM transactions
        WHERE date >= ?
          AND amount > 0
          AND is_duplicate = 0
          AND is_transfer = 0
        ORDER BY date DESC
        LIMIT ?
        """

        cursor.execute(query, (start_date, limit))
        rows = cursor.fetchall()

        deposits = []
        for row in rows:
            deposits.append({
                "date": row[0],
                "source": row[1],
                "amount": round(row[2], 2),
                "category": row[3]
            })

        conn.close()

        return {
            "deposits": deposits,
            "count": len(deposits)
        }


# Tool definitions for LLM
SPENDING_TOOLS = [
    {
        "name": "get_spending_by_category",
        "description": "Get spending breakdown by category. Can filter by year and/or month. Returns categories sorted by amount spent.",
        "input_schema": {
            "type": "object",
            "properties": {
                "year": {
                    "type": "integer",
                    "description": "Filter to specific year (e.g., 2024)"
                },
                "month": {
                    "type": "integer",
                    "description": "Filter to specific month 1-12 (requires year)"
                },
                "top_level_only": {
                    "type": "boolean",
                    "description": "If true, only show top-level categories",
                    "default": False
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum categories to return",
                    "default": 15
                }
            }
        }
    },
    {
        "name": "search_transactions",
        "description": "Search transactions by merchant name or description.",
        "input_schema": {
            "type": "object",
            "properties": {
                "merchant": {
                    "type": "string",
                    "description": "Search term to match against merchant/description"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results to return",
                    "default": 20
                }
            },
            "required": ["merchant"]
        }
    },
    {
        "name": "get_monthly_cash_flow",
        "description": "Get monthly income, expenses, and savings rate.",
        "input_schema": {
            "type": "object",
            "properties": {
                "months": {
                    "type": "integer",
                    "description": "Number of months to analyze",
                    "default": 6
                }
            }
        }
    },
    {
        "name": "detect_recurring_expenses",
        "description": "Detect recurring expenses and subscriptions based on transaction patterns.",
        "input_schema": {
            "type": "object",
            "properties": {
                "months": {
                    "type": "integer",
                    "description": "Number of months to analyze",
                    "default": 6
                },
                "min_occurrences": {
                    "type": "integer",
                    "description": "Minimum times a charge must appear to be considered recurring",
                    "default": 3
                }
            }
        }
    },
    {
        "name": "get_deposits",
        "description": "Get recent deposits and income transactions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "months": {
                    "type": "integer",
                    "description": "Number of months to look back",
                    "default": 4
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum transactions to return",
                    "default": 30
                }
            }
        }
    }
]
