"""
Memory system tools.
Provides a persistent knowledge graph for storing information about
people, goals, accounts, and their relationships.
"""

import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Any


class MemoryTools:
    """Tools for the memory/knowledge graph system."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def _get_conn(self):
        return sqlite3.connect(self.db_path)

    def create_entity(
        self,
        name: str,
        entity_type: str
    ) -> Dict[str, Any]:
        """
        Create a new entity in the knowledge graph.

        Args:
            name: Entity name (must be unique)
            entity_type: Type of entity (person, goal, employer, account, etc.)

        Returns:
            Dict with created entity details
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO entities (name, entity_type, created_at)
                VALUES (?, ?, ?)
            """, (name, entity_type, datetime.now().isoformat()))

            entity_id = cursor.lastrowid
            conn.commit()

            return {
                "success": True,
                "entity_id": entity_id,
                "name": name,
                "entity_type": entity_type
            }

        except sqlite3.IntegrityError:
            return {
                "success": False,
                "error": f"Entity '{name}' already exists"
            }
        finally:
            conn.close()

    def add_observation(
        self,
        entity_name: str,
        observation: str,
        source: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Add an observation/fact about an entity.

        Args:
            entity_name: Name of the entity
            observation: The fact or observation to store
            source: Optional source of this information

        Returns:
            Dict with result
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        # Find the entity
        cursor.execute(
            "SELECT entity_id FROM entities WHERE name = ?",
            (entity_name,)
        )
        row = cursor.fetchone()

        if not row:
            conn.close()
            return {
                "success": False,
                "error": f"Entity '{entity_name}' not found"
            }

        entity_id = row[0]

        cursor.execute("""
            INSERT INTO observations (entity_id, content, source, created_at)
            VALUES (?, ?, ?, ?)
        """, (entity_id, observation, source, datetime.now().isoformat()))

        observation_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return {
            "success": True,
            "observation_id": observation_id,
            "entity_name": entity_name,
            "observation": observation
        }

    def create_relation(
        self,
        from_entity: str,
        to_entity: str,
        relation_type: str
    ) -> Dict[str, Any]:
        """
        Create a relationship between two entities.

        Args:
            from_entity: Source entity name
            to_entity: Target entity name
            relation_type: Type of relationship (spouse_of, works_at, has_goal, etc.)

        Returns:
            Dict with result
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        # Find both entities
        cursor.execute(
            "SELECT entity_id FROM entities WHERE name = ?",
            (from_entity,)
        )
        from_row = cursor.fetchone()

        cursor.execute(
            "SELECT entity_id FROM entities WHERE name = ?",
            (to_entity,)
        )
        to_row = cursor.fetchone()

        if not from_row:
            conn.close()
            return {"success": False, "error": f"Entity '{from_entity}' not found"}

        if not to_row:
            conn.close()
            return {"success": False, "error": f"Entity '{to_entity}' not found"}

        cursor.execute("""
            INSERT INTO relations (from_entity_id, to_entity_id, relation_type, created_at)
            VALUES (?, ?, ?, ?)
        """, (from_row[0], to_row[0], relation_type, datetime.now().isoformat()))

        conn.commit()
        conn.close()

        return {
            "success": True,
            "from_entity": from_entity,
            "relation": relation_type,
            "to_entity": to_entity
        }

    def get_entity(self, entity_name: str) -> Dict[str, Any]:
        """
        Get an entity with all its observations and relations.

        Args:
            entity_name: Name of the entity

        Returns:
            Dict with entity details, observations, and relations
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        # Get entity
        cursor.execute("""
            SELECT entity_id, name, entity_type, created_at
            FROM entities WHERE name = ?
        """, (entity_name,))

        entity_row = cursor.fetchone()
        if not entity_row:
            conn.close()
            return {"error": f"Entity '{entity_name}' not found"}

        entity = {
            "entity_id": entity_row[0],
            "name": entity_row[1],
            "entity_type": entity_row[2],
            "created_at": entity_row[3],
            "observations": [],
            "relations": []
        }

        # Get observations
        cursor.execute("""
            SELECT content, source, created_at
            FROM observations WHERE entity_id = ?
            ORDER BY created_at DESC
        """, (entity_row[0],))

        for row in cursor.fetchall():
            entity["observations"].append({
                "content": row[0],
                "source": row[1],
                "created_at": row[2]
            })

        # Get relations (both directions)
        cursor.execute("""
            SELECT e.name, r.relation_type, 'outgoing'
            FROM relations r
            JOIN entities e ON r.to_entity_id = e.entity_id
            WHERE r.from_entity_id = ?
            UNION ALL
            SELECT e.name, r.relation_type, 'incoming'
            FROM relations r
            JOIN entities e ON r.from_entity_id = e.entity_id
            WHERE r.to_entity_id = ?
        """, (entity_row[0], entity_row[0]))

        for row in cursor.fetchall():
            entity["relations"].append({
                "entity": row[0],
                "relation": row[1],
                "direction": row[2]
            })

        conn.close()
        return entity

    def search_memories(self, query: str) -> Dict[str, Any]:
        """
        Search across all memories (entities and observations).

        Args:
            query: Search term

        Returns:
            Dict with matching entities and observations
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        search_term = f"%{query}%"

        # Search entities
        cursor.execute("""
            SELECT name, entity_type FROM entities
            WHERE name LIKE ?
        """, (search_term,))

        matching_entities = []
        for row in cursor.fetchall():
            matching_entities.append({
                "name": row[0],
                "type": row[1]
            })

        # Search observations
        cursor.execute("""
            SELECT e.name, o.content
            FROM observations o
            JOIN entities e ON o.entity_id = e.entity_id
            WHERE o.content LIKE ?
        """, (search_term,))

        matching_observations = []
        for row in cursor.fetchall():
            matching_observations.append({
                "entity": row[0],
                "observation": row[1]
            })

        conn.close()

        return {
            "query": query,
            "entities": matching_entities,
            "observations": matching_observations
        }

    def get_all_memories(self) -> Dict[str, Any]:
        """
        Get all memory entities and their observations.

        Returns:
            Dict with all entities and observations
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT e.name, e.entity_type, o.content
            FROM entities e
            LEFT JOIN observations o ON e.entity_id = o.entity_id
            ORDER BY e.entity_type, e.name, o.created_at DESC
        """)

        entities = {}
        for row in cursor.fetchall():
            name = row[0]
            if name not in entities:
                entities[name] = {
                    "name": name,
                    "type": row[1],
                    "observations": []
                }
            if row[2]:  # If there's an observation
                entities[name]["observations"].append(row[2])

        conn.close()

        return {
            "entities": list(entities.values()),
            "count": len(entities)
        }

    def delete_entity(self, entity_name: str) -> Dict[str, Any]:
        """
        Delete an entity and all its observations/relations.

        Args:
            entity_name: Name of entity to delete

        Returns:
            Dict with result
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT entity_id FROM entities WHERE name = ?",
            (entity_name,)
        )
        row = cursor.fetchone()

        if not row:
            conn.close()
            return {"success": False, "error": f"Entity '{entity_name}' not found"}

        entity_id = row[0]

        # Delete observations (cascaded by FK, but explicit for clarity)
        cursor.execute("DELETE FROM observations WHERE entity_id = ?", (entity_id,))

        # Delete relations
        cursor.execute(
            "DELETE FROM relations WHERE from_entity_id = ? OR to_entity_id = ?",
            (entity_id, entity_id)
        )

        # Delete entity
        cursor.execute("DELETE FROM entities WHERE entity_id = ?", (entity_id,))

        conn.commit()
        conn.close()

        return {
            "success": True,
            "deleted": entity_name
        }

    def delete_observation(
        self,
        entity_name: str,
        observation_content: str
    ) -> Dict[str, Any]:
        """
        Delete a specific observation.

        Args:
            entity_name: Entity the observation belongs to
            observation_content: The observation text to delete

        Returns:
            Dict with result
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            DELETE FROM observations
            WHERE entity_id = (SELECT entity_id FROM entities WHERE name = ?)
              AND content = ?
        """, (entity_name, observation_content))

        deleted = cursor.rowcount
        conn.commit()
        conn.close()

        return {
            "success": deleted > 0,
            "deleted_count": deleted
        }


# Tool definitions for LLM
MEMORY_TOOLS = [
    {
        "name": "create_entity",
        "description": "Create a new entity in the knowledge graph (person, goal, employer, account, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Entity name (must be unique)"
                },
                "entity_type": {
                    "type": "string",
                    "description": "Type: person, goal, employer, account, institution, etc."
                }
            },
            "required": ["name", "entity_type"]
        }
    },
    {
        "name": "add_observation",
        "description": "Add an observation/fact about an existing entity.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_name": {
                    "type": "string",
                    "description": "Name of the entity"
                },
                "observation": {
                    "type": "string",
                    "description": "The fact or observation to store"
                },
                "source": {
                    "type": "string",
                    "description": "Optional source of this information"
                }
            },
            "required": ["entity_name", "observation"]
        }
    },
    {
        "name": "create_relation",
        "description": "Create a relationship between two entities.",
        "input_schema": {
            "type": "object",
            "properties": {
                "from_entity": {
                    "type": "string",
                    "description": "Source entity name"
                },
                "to_entity": {
                    "type": "string",
                    "description": "Target entity name"
                },
                "relation_type": {
                    "type": "string",
                    "description": "Type: spouse_of, works_at, has_goal, parent_of, etc."
                }
            },
            "required": ["from_entity", "to_entity", "relation_type"]
        }
    },
    {
        "name": "get_entity",
        "description": "Get an entity with all its observations and relations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_name": {
                    "type": "string",
                    "description": "Name of the entity to retrieve"
                }
            },
            "required": ["entity_name"]
        }
    },
    {
        "name": "search_memories",
        "description": "Search across all memories (entities and observations).",
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
        "name": "get_all_memories",
        "description": "Get all memory entities and their observations.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "delete_entity",
        "description": "Delete an entity and all its observations/relations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_name": {
                    "type": "string",
                    "description": "Name of entity to delete"
                }
            },
            "required": ["entity_name"]
        }
    },
    {
        "name": "delete_observation",
        "description": "Delete a specific observation from an entity.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_name": {
                    "type": "string",
                    "description": "Entity the observation belongs to"
                },
                "observation_content": {
                    "type": "string",
                    "description": "The observation text to delete"
                }
            },
            "required": ["entity_name", "observation_content"]
        }
    }
]
