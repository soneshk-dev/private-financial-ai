"""Configuration.

Everything personal lives outside this repo:

* ``HOMEAI_PRIVATE_DIR`` (default ``./private``) holds ``config.yaml`` and, later,
  ``profile.md``. It is gitignored here and is normally its own private repo.
* ``HOMEAI_VAULT_DIR`` (default ``~/homeai-vault``) holds the SQLite ledger,
  documents and raw provider payloads.
* ``secrets_dir`` (default ``~/.home-ai-secrets``) holds ``*.conf`` files with
  ``KEY=VALUE`` lines, one file per provider.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

AccountKind = Literal[
    "checking", "savings", "money_market", "cd", "cash_mgmt",
    "credit_card", "mortgage", "heloc", "loan", "student_loan",
    "brokerage", "retirement_401k", "roth_401k", "ira", "roth_ira", "hsa",
    "deferred_comp", "e529", "custodial",
    "crypto_wallet", "crypto_exchange",
    "real_estate", "vehicle", "other",
]

LIABILITY_KINDS = {"credit_card", "mortgage", "heloc", "loan", "student_loan"}

# Broad asset classes used for net-worth breakdowns.
KIND_CLASS = {
    "checking": "cash", "savings": "cash", "money_market": "cash", "cd": "cash", "cash_mgmt": "cash",
    "credit_card": "liability", "mortgage": "liability", "heloc": "liability",
    "loan": "liability", "student_loan": "liability",
    "brokerage": "investments", "custodial": "investments",
    "retirement_401k": "retirement", "roth_401k": "retirement", "ira": "retirement",
    "roth_ira": "retirement", "hsa": "retirement", "deferred_comp": "retirement", "e529": "education",
    "crypto_wallet": "crypto", "crypto_exchange": "crypto",
    "real_estate": "real_estate", "vehicle": "other", "other": "other",
}


class ApiConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 5010


class ManualAccount(BaseModel):
    """An account with no connector (house, car, a loan tracked by hand)."""
    name: str
    kind: str = "other"
    balance: float
    institution: str = ""
    entity: str = "personal"


class AccountOverride(BaseModel):
    """Force kind/entity/name/active on accounts matched by connector fields."""
    match: dict[str, Any]          # any of: source, source_account_id, institution, name_contains, mask, kind
    set: dict[str, Any]            # any of: kind, entity, name, is_active


class FlowRule(BaseModel):
    """Regex on description (case-insensitive) → flow_type, optionally category."""
    pattern: str
    flow_type: str
    category: str | None = None
    account_kind: str | None = None


class PlaidConfig(BaseModel):
    client_name: str = "homeai"
    products: list[str] = ["transactions"]
    country_codes: list[str] = ["US"]
    conf_file: str = "plaid.conf"
    key_file: str = "plaid_encryption.key"


class FinaConfig(BaseModel):
    conf_file: str = "fina.conf"
    institution_filter: str | None = "Fidelity"
    skip_kinds: list[str] = ["credit_card"]   # Plaid covers the Fidelity card better
    transaction_days: int = 120


class ZerionConfig(BaseModel):
    conf_file: str = "zerion.conf"
    wallets: list[dict[str, str]] = []        # {name, chain, address}


class BitcoinConfig(BaseModel):
    xpub_file: str = "bitcoin_xpubs.conf"
    every_days: int = 7
    gap_limit: int = 50


class Config(BaseModel):
    private_dir: Path
    vault_dir: Path
    secrets_dir: Path = Path("~/.home-ai-secrets")
    timezone: str = "America/Chicago"
    default_entity: str = "personal"
    api: ApiConfig = ApiConfig()
    manual_accounts: list[ManualAccount] = []
    account_overrides: list[AccountOverride] = []
    flow_rules: list[FlowRule] = []
    heloc_institutions: list[str] = []
    plaid: PlaidConfig = PlaidConfig()
    fina: FinaConfig = FinaConfig()
    zerion: ZerionConfig = ZerionConfig()
    bitcoin: BitcoinConfig = BitcoinConfig()

    @property
    def db_path(self) -> Path:
        return self.vault_dir / "ledger.db"

    @property
    def raw_dir(self) -> Path:
        return self.vault_dir / "raw"

    def secret(self, conf_file: str, key: str, env: str | None = None) -> str | None:
        """Read KEY from secrets_dir/conf_file, falling back to an env var."""
        if env and os.environ.get(env):
            return os.environ[env]
        path = self.secrets_dir.expanduser() / conf_file
        if path.exists():
            for line in path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and line.startswith(key + "="):
                    return line.split("=", 1)[1].strip()
        return None


def _default_private_dir() -> Path:
    return Path(os.environ.get("HOMEAI_PRIVATE_DIR", "private"))


def _default_vault_dir() -> Path:
    return Path(os.environ.get("HOMEAI_VAULT_DIR", "~/homeai-vault")).expanduser()


def load_config(path: str | os.PathLike | None = None) -> Config:
    """Load config.yaml (if present) and apply environment overrides."""
    private_dir = _default_private_dir()
    cfg_path = Path(path) if path else (Path(os.environ["HOMEAI_CONFIG"]) if os.environ.get("HOMEAI_CONFIG")
                                        else private_dir / "config.yaml")
    data: dict[str, Any] = {}
    if cfg_path.exists():
        data = yaml.safe_load(cfg_path.read_text()) or {}
    data.setdefault("private_dir", str(private_dir))
    data.setdefault("vault_dir", str(_default_vault_dir()))
    if os.environ.get("HOMEAI_SECRETS_DIR"):
        data["secrets_dir"] = os.environ["HOMEAI_SECRETS_DIR"]
    cfg = Config(**data)
    cfg.vault_dir = cfg.vault_dir.expanduser()
    cfg.secrets_dir = cfg.secrets_dir.expanduser()
    return cfg


@lru_cache(maxsize=1)
def get_config() -> Config:
    return load_config()
