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
    set: dict[str, Any]            # any of: kind, entity, name, is_active, txn_since (YYYY-MM-DD cutover)


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


class LlmProvider(BaseModel):
    """An OpenAI-compatible local endpoint (vLLM, TabbyAPI, Ollama)."""
    name: str
    base_url: str
    model: str = "auto"          # 'auto' = first model the server lists
    api_key: str = "local"
    timeout: int = 300
    max_tokens: int = 4096


class LlmConfig(BaseModel):
    # backend "builtin": homeai's own loop over `providers`.
    # backend "hermes": relay to a hermes-agent gateway that consumes homeai's MCP server;
    #                   `providers` then only serve as the emergency fallback.
    backend: Literal["builtin", "hermes"] = "builtin"
    hermes_url: str = "http://127.0.0.1:9319/v1"
    hermes_timeout: int = 600
    hermes_fallback_builtin: bool = True
    providers: list[LlmProvider] = [LlmProvider(name="ollama", base_url="http://127.0.0.1:11434/v1")]
    default: str = "ollama"
    fallback: str | None = None
    max_iterations: int = 12
    temperature: float = 0.2
    history_messages: int = 30


class AccessConfig(BaseModel):
    """Cloudflare Access JWT verification (off unless team_domain and aud are set).
    When on, every request must carry a valid Cf-Access-Jwt-Assertion header."""
    team_domain: str | None = None      # e.g. "example" for example.cloudflareaccess.com
    aud: str | None = None              # the Access application's Application Audience tag


class TelegramConfig(BaseModel):
    conf_file: str = "telegram.conf"


class EntityDef(BaseModel):
    slug: str                                  # e.g. "business:acme" (personal is implicit)
    name: str
    kind: str = "business"
    tax_form: str | None = None
    notes: str | None = None


class EntityRule(BaseModel):
    """Regex on description/merchant → entity (and optionally flow) for future and retagged rows."""
    pattern: str
    entity: str
    flow_type: str | None = None


class GoalDef(BaseModel):
    slug: str
    name: str
    kind: Literal["save", "debt", "reserve", "purchase", "retirement"] = "save"
    target_amount: float | None = None
    target_date: str | None = None
    start_amount: float | None = None
    current_amount: float | None = None
    linked_accounts: list[str] = []            # account ids or name substrings
    monthly_contribution: float | None = None
    priority: int = 2
    notes: str | None = None


class IncomeDef(BaseModel):
    name: str
    match: str                                 # regex on description/merchant of income rows
    monthly: float | None = None               # override; else average of matches over the last 3 months
    until: str | None = None                   # last month the income is expected (YYYY-MM-DD)


class RunwayConfig(BaseModel):
    horizon_months: int = 24
    burn_months: int = 6                       # months averaged for the burn rate
    reserve_classes: list[str] = ["cash"]
    include_investment_classes: list[str] = [] # e.g. ["investments"] to count taxable brokerage as reserve
    incomes: list[IncomeDef] = []
    entity: str = "personal"


class TaxConfig(BaseModel):
    year: int = 2026
    filing_status: str = "mfj"
    standard_deduction: float = 32200          # 2026 MFJ; override for other statuses/years
    brackets: list[list[float]] = [            # 2026 MFJ ordinary brackets [upper_bound, rate]; verify against IRS
        [24800, 0.10], [100800, 0.12], [211400, 0.22], [403550, 0.24], [512450, 0.32], [768700, 0.35], [1e18, 0.37]]
    state_rate: float = 0.0495                 # flat state rate (Illinois)
    niit_threshold: float = 250000
    prior_year_total_tax: float | None = None  # for the safe-harbour test
    prior_year_agi: float | None = None
    withholding_federal_ytd: float = 0         # not visible in the ledger (deposits are net)
    withholding_state_ytd: float = 0
    gross_wages_ytd: float | None = None       # if known, replaces net deposits as the wage figure
    additional_income: dict[str, float] = {}   # e.g. {"capital_gains": 12000, "k1": 30000}
    wage_patterns: list[str] = ["PAYROLL", "SEVERANCE"]
    federal_payment_patterns: list[str] = ["IRS", "USATAXPYMT"]
    state_payment_patterns: list[str] = ["DEPT OF REV", "DEPT OF REVENUE"]


class AlertsConfig(BaseModel):
    aave_hf_below: float = 1.5
    budget_over: bool = True
    large_transaction: float = 5000
    connector_errors: bool = True
    unknown_inflows: bool = True
    runway_months_below: float = 6


class Config(BaseModel):
    private_dir: Path
    vault_dir: Path
    entities: list[EntityDef] = []
    entity_rules: list[EntityRule] = []
    goals: list[GoalDef] = []
    runway: RunwayConfig = RunwayConfig()
    tax: TaxConfig = TaxConfig()
    alerts: AlertsConfig = AlertsConfig()
    secrets_dir: Path = Path("~/.home-ai-secrets")
    timezone: str = "America/Chicago"
    default_entity: str = "personal"
    profile_file: str = "profile.md"     # hand-written part of the context, in private_dir
    api: ApiConfig = ApiConfig()
    llm: LlmConfig = LlmConfig()
    telegram: TelegramConfig = TelegramConfig()
    access: AccessConfig = AccessConfig()
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
