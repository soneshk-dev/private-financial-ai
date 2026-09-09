"""Connectors pull data from providers into the ledger. Each one is idempotent:
running it twice writes the same rows. Raw payloads are kept in ``raw_sync``
so a mapping bug can be replayed without another provider call."""
