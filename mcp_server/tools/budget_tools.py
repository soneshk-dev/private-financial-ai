"""
Budget management tools.
Provides budget tracking, status, and alerts.
"""

import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Any


class BudgetTools:
    """Tools for budget management."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def _get_conn(self):
        return sqlite3.connect(self.db_path)

    def get_budget_status(
        self,
        month: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get budget vs actual spending for a month.

        Args:
            month: Month in YYYY-MM format (default: current month)

        Returns:
            Dict with budget status by category
        """
        if not month:
            month = datetime.now().strftime('%Y-%m')

        conn = self._get_conn()
        cursor = conn.cursor()

        # Get budgets
        cursor.execute("""
            SELECT category, monthly_limit
            FROM budgets
            WHERE is_active = 1
        """)

        budgets = {row[0]: row[1] for row in cursor.fetchall()}

        # Get actual spending for the month
        cursor.execute("""
            SELECT
                category_normalized,
                SUM(ABS(amount)) as spent
            FROM transactions
            WHERE strftime('%Y-%m', date) = ?
              AND amount < 0
              AND is_duplicate = 0
              AND is_transfer = 0
            GROUP BY category_normalized
        """, (month,))

        spending = {row[0]: row[1] for row in cursor.fetchall()}

        conn.close()

        # Build status
        categories = []
        total_budget = 0
        total_spent = 0
        alerts = []

        for category, limit in sorted(budgets.items()):
            spent = 0
            # Match spending to budget category (may need prefix matching)
            for spend_cat, amount in spending.items():
                if spend_cat and (
                    spend_cat == category or
                    spend_cat.startswith(category + ':') or
                    spend_cat.startswith(category + ' ')
                ):
                    spent += amount

            pct = (spent / limit * 100) if limit > 0 else 0
            remaining = limit - spent

            status = "on_track"
            if pct >= 100:
                status = "exceeded"
                alerts.append(f"{category}: Exceeded by ${spent - limit:.2f}")
            elif pct >= 80:
                status = "warning"
                alerts.append(f"{category}: {pct:.0f}% used, ${remaining:.2f} remaining")

            categories.append({
                "category": category,
                "budget": round(limit, 2),
                "spent": round(spent, 2),
                "remaining": round(remaining, 2),
                "percentage": round(pct, 1),
                "status": status
            })

            total_budget += limit
            total_spent += spent

        return {
            "month": month,
            "categories": categories,
            "totals": {
                "budget": round(total_budget, 2),
                "spent": round(total_spent, 2),
                "remaining": round(total_budget - total_spent, 2),
                "percentage": round((total_spent / total_budget * 100) if total_budget > 0 else 0, 1)
            },
            "alerts": alerts if alerts else None
        }

    def set_budget(
        self,
        category: str,
        monthly_limit: float
    ) -> Dict[str, Any]:
        """
        Set or update a budget for a category.

        Args:
            category: Category name (should match transaction categories)
            monthly_limit: Monthly budget amount

        Returns:
            Dict with result
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO budgets (category, monthly_limit, is_active, created_at, updated_at)
            VALUES (?, ?, 1, ?, ?)
            ON CONFLICT(category) DO UPDATE SET
                monthly_limit = excluded.monthly_limit,
                updated_at = excluded.updated_at
        """, (category, monthly_limit, datetime.now().isoformat(), datetime.now().isoformat()))

        conn.commit()
        conn.close()

        return {
            "success": True,
            "category": category,
            "monthly_limit": monthly_limit
        }

    def list_budgets(self) -> Dict[str, Any]:
        """
        List all configured budgets.

        Returns:
            Dict with all budget categories and limits
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT category, monthly_limit, is_active, updated_at
            FROM budgets
            ORDER BY monthly_limit DESC
        """)

        budgets = []
        total = 0

        for row in cursor.fetchall():
            limit = row[1]
            budgets.append({
                "category": row[0],
                "monthly_limit": round(limit, 2),
                "is_active": bool(row[2]),
                "last_updated": row[3]
            })
            if row[2]:  # If active
                total += limit

        conn.close()

        return {
            "budgets": budgets,
            "total_monthly_budget": round(total, 2),
            "count": len(budgets)
        }

    def delete_budget(self, category: str) -> Dict[str, Any]:
        """
        Delete a budget category.

        Args:
            category: Category to delete

        Returns:
            Dict with result
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM budgets WHERE category = ?", (category,))
        deleted = cursor.rowcount

        conn.commit()
        conn.close()

        return {
            "success": deleted > 0,
            "deleted": category if deleted > 0 else None
        }

    def get_spending_vs_budget_trend(
        self,
        months: int = 6
    ) -> Dict[str, Any]:
        """
        Get spending vs budget trend over multiple months.

        Args:
            months: Number of months to analyze

        Returns:
            Dict with monthly trends
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        # Get total monthly budget
        cursor.execute("""
            SELECT SUM(monthly_limit)
            FROM budgets
            WHERE is_active = 1
        """)
        total_budget = cursor.fetchone()[0] or 0

        # Get monthly spending
        cursor.execute("""
            SELECT
                strftime('%Y-%m', date) as month,
                SUM(ABS(amount)) as spent
            FROM transactions
            WHERE date >= date('now', ? || ' months')
              AND amount < 0
              AND is_duplicate = 0
              AND is_transfer = 0
              AND category_normalized NOT LIKE '%Transfer%'
              AND category_normalized NOT LIKE '%Investment%'
            GROUP BY strftime('%Y-%m', date)
            ORDER BY month DESC
            LIMIT ?
        """, (f"-{months}", months))

        trend = []
        for row in cursor.fetchall():
            spent = row[1]
            pct = (spent / total_budget * 100) if total_budget > 0 else 0
            trend.append({
                "month": row[0],
                "budget": round(total_budget, 2),
                "spent": round(spent, 2),
                "percentage": round(pct, 1),
                "under_budget": spent <= total_budget
            })

        conn.close()

        return {
            "monthly_budget": round(total_budget, 2),
            "trend": trend
        }


# Tool definitions for LLM
BUDGET_TOOLS = [
    {
        "name": "get_budget_status",
        "description": "Get budget vs actual spending for current or specified month. Shows each category with budget, spent, and remaining amounts.",
        "input_schema": {
            "type": "object",
            "properties": {
                "month": {
                    "type": "string",
                    "description": "Month in YYYY-MM format (default: current month)"
                }
            }
        }
    },
    {
        "name": "set_budget",
        "description": "Set or update a monthly budget for a spending category.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Category name (should match transaction categories)"
                },
                "monthly_limit": {
                    "type": "number",
                    "description": "Monthly budget amount"
                }
            },
            "required": ["category", "monthly_limit"]
        }
    },
    {
        "name": "list_budgets",
        "description": "List all configured budget categories with their monthly limits.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "delete_budget",
        "description": "Delete a budget category.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Category to delete"
                }
            },
            "required": ["category"]
        }
    },
    {
        "name": "get_spending_vs_budget_trend",
        "description": "Get spending vs budget trend over multiple months.",
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
    }
]
