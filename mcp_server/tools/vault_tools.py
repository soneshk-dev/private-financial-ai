"""
Document vault tools.
Secure storage for important financial documents with search and expiration tracking.
"""

import sqlite3
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any


class VaultTools:
    """Tools for document vault management."""

    def __init__(self, db_path: str, vault_path: Optional[str] = None):
        self.db_path = db_path
        self.vault_path = vault_path or os.path.expanduser('~/private-financial-ai/vault/documents')

    def _get_conn(self):
        return sqlite3.connect(self.db_path)

    def search_documents(self, query: str) -> Dict[str, Any]:
        """
        Search documents by content, tags, or metadata.

        Args:
            query: Search term

        Returns:
            Dict with matching documents
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        search_term = f"%{query}%"

        cursor.execute("""
            SELECT
                document_id,
                filename,
                document_type,
                provider,
                summary,
                tags,
                expiration_date
            FROM vault_documents
            WHERE filename LIKE ?
               OR extracted_text LIKE ?
               OR summary LIKE ?
               OR provider LIKE ?
               OR tags LIKE ?
            ORDER BY updated_at DESC
        """, (search_term, search_term, search_term, search_term, search_term))

        documents = []
        for row in cursor.fetchall():
            documents.append({
                "document_id": row[0],
                "filename": row[1],
                "document_type": row[2],
                "provider": row[3],
                "summary": row[4],
                "tags": row[5],
                "expiration_date": row[6]
            })

        conn.close()

        return {
            "query": query,
            "count": len(documents),
            "documents": documents
        }

    def list_documents(
        self,
        document_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        List documents in the vault.

        Args:
            document_type: Optional filter (insurance, will, trust, contract, benefits)

        Returns:
            Dict with document list
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        if document_type:
            cursor.execute("""
                SELECT
                    document_id,
                    filename,
                    document_type,
                    provider,
                    summary,
                    expiration_date,
                    updated_at
                FROM vault_documents
                WHERE document_type = ?
                ORDER BY document_type, provider, filename
            """, (document_type,))
        else:
            cursor.execute("""
                SELECT
                    document_id,
                    filename,
                    document_type,
                    provider,
                    summary,
                    expiration_date,
                    updated_at
                FROM vault_documents
                ORDER BY document_type, provider, filename
            """)

        documents = []
        for row in cursor.fetchall():
            documents.append({
                "document_id": row[0],
                "filename": row[1],
                "document_type": row[2],
                "provider": row[3],
                "summary": row[4],
                "expiration_date": row[5],
                "last_updated": row[6]
            })

        conn.close()

        return {
            "filter": document_type,
            "count": len(documents),
            "documents": documents
        }

    def get_document(self, document_id: int) -> Dict[str, Any]:
        """
        Get full details for a specific document.

        Args:
            document_id: The document ID

        Returns:
            Dict with full document details
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                document_id,
                filename,
                original_filename,
                file_path,
                file_size,
                mime_type,
                document_type,
                provider,
                policy_number,
                extracted_text,
                summary,
                effective_date,
                expiration_date,
                tags,
                created_at,
                updated_at
            FROM vault_documents
            WHERE document_id = ?
        """, (document_id,))

        row = cursor.fetchone()
        conn.close()

        if not row:
            return {"error": f"Document {document_id} not found"}

        return {
            "document_id": row[0],
            "filename": row[1],
            "original_filename": row[2],
            "file_path": row[3],
            "file_size": row[4],
            "mime_type": row[5],
            "document_type": row[6],
            "provider": row[7],
            "policy_number": row[8],
            "extracted_text": row[9][:500] + "..." if row[9] and len(row[9]) > 500 else row[9],
            "summary": row[10],
            "effective_date": row[11],
            "expiration_date": row[12],
            "tags": row[13],
            "created_at": row[14],
            "updated_at": row[15]
        }

    def get_expiring_documents(self, days: int = 30) -> Dict[str, Any]:
        """
        Get documents expiring within specified days.

        Args:
            days: Number of days to look ahead

        Returns:
            Dict with expiring documents
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        future_date = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d')

        cursor.execute("""
            SELECT
                document_id,
                filename,
                document_type,
                provider,
                expiration_date,
                summary
            FROM vault_documents
            WHERE expiration_date IS NOT NULL
              AND expiration_date <= ?
              AND expiration_date >= date('now')
            ORDER BY expiration_date ASC
        """, (future_date,))

        documents = []
        for row in cursor.fetchall():
            exp_date = datetime.strptime(row[4], '%Y-%m-%d')
            days_until = (exp_date - datetime.now()).days

            documents.append({
                "document_id": row[0],
                "filename": row[1],
                "document_type": row[2],
                "provider": row[3],
                "expiration_date": row[4],
                "days_until_expiration": days_until,
                "summary": row[5]
            })

        conn.close()

        return {
            "looking_ahead_days": days,
            "count": len(documents),
            "expiring_documents": documents
        }

    def update_document(
        self,
        document_id: int,
        **updates
    ) -> Dict[str, Any]:
        """
        Update document metadata.

        Args:
            document_id: The document ID
            **updates: Fields to update (summary, tags, expiration_date, etc.)

        Returns:
            Dict with result
        """
        allowed_fields = [
            'document_type', 'provider', 'policy_number', 'summary',
            'effective_date', 'expiration_date', 'tags'
        ]

        valid_updates = {k: v for k, v in updates.items() if k in allowed_fields}

        if not valid_updates:
            return {"success": False, "error": "No valid fields to update"}

        conn = self._get_conn()
        cursor = conn.cursor()

        set_clause = ", ".join(f"{k} = ?" for k in valid_updates.keys())
        values = list(valid_updates.values())
        values.append(datetime.now().isoformat())
        values.append(document_id)

        cursor.execute(f"""
            UPDATE vault_documents
            SET {set_clause}, updated_at = ?
            WHERE document_id = ?
        """, values)

        updated = cursor.rowcount
        conn.commit()
        conn.close()

        return {
            "success": updated > 0,
            "document_id": document_id,
            "updated_fields": list(valid_updates.keys())
        }

    def get_document_types(self) -> Dict[str, Any]:
        """
        Get summary of documents by type.

        Returns:
            Dict with document type counts
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                document_type,
                COUNT(*) as count
            FROM vault_documents
            GROUP BY document_type
            ORDER BY count DESC
        """)

        types = []
        total = 0
        for row in cursor.fetchall():
            types.append({
                "type": row[0] or "unclassified",
                "count": row[1]
            })
            total += row[1]

        conn.close()

        return {
            "document_types": types,
            "total_documents": total
        }


# Tool definitions for LLM
VAULT_TOOLS = [
    {
        "name": "search_documents",
        "description": "Search document vault by content, tags, or metadata.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search term"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "list_documents",
        "description": "List documents in the vault with optional type filter.",
        "input_schema": {
            "type": "object",
            "properties": {
                "document_type": {
                    "type": "string",
                    "description": "Filter by type: insurance, will, trust, contract, benefits"
                }
            }
        }
    },
    {
        "name": "get_document",
        "description": "Get full details for a specific document including extracted text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "document_id": {
                    "type": "integer",
                    "description": "The document ID"
                }
            },
            "required": ["document_id"]
        }
    },
    {
        "name": "get_expiring_documents",
        "description": "Get documents expiring within specified number of days.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Days to look ahead",
                    "default": 30
                }
            }
        }
    },
    {
        "name": "update_document",
        "description": "Update document metadata (type, provider, summary, dates, tags).",
        "input_schema": {
            "type": "object",
            "properties": {
                "document_id": {
                    "type": "integer",
                    "description": "The document ID"
                },
                "document_type": {
                    "type": "string",
                    "description": "New document type"
                },
                "provider": {
                    "type": "string",
                    "description": "Provider/company name"
                },
                "summary": {
                    "type": "string",
                    "description": "Document summary"
                },
                "expiration_date": {
                    "type": "string",
                    "description": "Expiration date (YYYY-MM-DD)"
                },
                "tags": {
                    "type": "string",
                    "description": "Comma-separated tags"
                }
            },
            "required": ["document_id"]
        }
    },
    {
        "name": "get_document_types",
        "description": "Get summary of documents by type.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    }
]
