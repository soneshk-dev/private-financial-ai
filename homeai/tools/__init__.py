"""Tool registry: the single definition of what a model (chat loop or MCP client)
can do. Every tool wraps a service function; no SQL lives here except the
guarded read-only ``run_sql``."""
