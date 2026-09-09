"""Category normalisation and flow-type inference.

The ledger stores one ``flow_type`` per transaction so every downstream query
(spending, cash flow, budgets, briefings) reads ``flow`` instead of
re-implementing a chain of ``LIKE`` exclusions. Rules are deterministic and
live here; user overrides live on the row (``flow_type_override``).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

FLOW_TYPES = (
    "expense", "income", "transfer", "investment_buy", "investment_sell",
    "dividend", "interest", "loan_payment", "tax", "fee", "refund", "unknown",
)
SPENDING_FLOWS = ("expense", "fee", "refund")           # refund is a negative expense
INCOME_FLOWS = ("income", "dividend", "interest")
EXCLUDED_FROM_CASHFLOW = ("transfer",)

MASTER_CATEGORIES = [
    "Food & Dining", "Shopping", "Transportation", "Entertainment", "Health & Wellness",
    "Home & Housing", "Utilities", "Education", "Financial Services", "Business",
    "Personal Care", "Travel", "Transfers", "Income", "Uncategorized",
]

# ---------------------------------------------------------------------------
# Plaid personal_finance_category → normalized
# ---------------------------------------------------------------------------
PLAID_LEVEL1 = {
    "FOOD_AND_DRINK": "Food & Dining", "GENERAL_MERCHANDISE": "Shopping",
    "TRANSPORTATION": "Transportation", "ENTERTAINMENT": "Entertainment",
    "MEDICAL": "Health & Wellness", "PERSONAL_CARE": "Personal Care", "TRAVEL": "Travel",
    "HOME_IMPROVEMENT": "Home & Housing", "RENT_AND_UTILITIES": "Utilities",
    "LOAN_PAYMENTS": "Financial Services", "BANK_FEES": "Financial Services",
    "GOVERNMENT_AND_NON_PROFIT": "Financial Services", "GENERAL_SERVICES": "Shopping",
    "TRANSFER_OUT": "Transfers", "TRANSFER_IN": "Transfers", "INCOME": "Income", "OTHER": "Uncategorized",
}
PLAID_DETAILED = {
    "FOOD_AND_DRINK_RESTAURANT": "Restaurants", "FOOD_AND_DRINK_GROCERIES": "Groceries",
    "FOOD_AND_DRINK_COFFEE": "Coffee & Beverages", "FOOD_AND_DRINK_FAST_FOOD": "Fast Food",
    "FOOD_AND_DRINK_BEER_WINE_AND_LIQUOR": "Alcohol & Liquor", "FOOD_AND_DRINK_OTHER_FOOD_AND_DRINK": "Other Food",
    "GENERAL_MERCHANDISE_SUPERSTORES": "Superstores",
    "GENERAL_MERCHANDISE_CLOTHING_AND_ACCESSORIES": "Clothing & Accessories",
    "GENERAL_MERCHANDISE_ELECTRONICS": "Electronics", "GENERAL_MERCHANDISE_DEPARTMENT_STORES": "Department Stores",
    "GENERAL_MERCHANDISE_ONLINE_MARKETPLACES": "Online Shopping", "GENERAL_MERCHANDISE_SPORTING_GOODS": "Sporting Goods",
    "GENERAL_MERCHANDISE_BOOKSTORES_AND_NEWSSTANDS": "Books & News", "GENERAL_MERCHANDISE_PET_SUPPLIES": "Pet Supplies",
    "GENERAL_MERCHANDISE_TOBACCO_AND_VAPE": "Tobacco & Vape",
    "GENERAL_MERCHANDISE_OTHER_GENERAL_MERCHANDISE": "Other Merchandise",
    "TRANSPORTATION_GAS": "Gas & Fuel", "TRANSPORTATION_PARKING": "Parking",
    "TRANSPORTATION_PUBLIC_TRANSIT": "Public Transit", "TRANSPORTATION_TAXIS_AND_RIDE_SHARES": "Rideshare & Taxis",
    "ENTERTAINMENT_TV_AND_MOVIES": "TV & Movies",
    "ENTERTAINMENT_SPORTING_EVENTS_AMUSEMENT_PARKS_AND_MUSEUMS": "Events & Museums",
    "ENTERTAINMENT_OTHER_ENTERTAINMENT": "Other Entertainment",
    "MEDICAL_PHARMACIES_AND_SUPPLEMENTS": "Pharmacy & Supplements",
    "PERSONAL_CARE_HAIR_AND_BEAUTY": "Hair & Beauty", "PERSONAL_CARE_GYMS_AND_FITNESS_CENTERS": "Gym & Fitness",
    "TRAVEL_LODGING": "Hotels & Lodging", "TRAVEL_FLIGHTS": "Flights",
    "HOME_IMPROVEMENT_HARDWARE": "Hardware", "HOME_IMPROVEMENT_FURNITURE": "Furniture",
    "HOME_IMPROVEMENT_SECURITY": "Security", "HOME_IMPROVEMENT_REPAIR_AND_MAINTENANCE": "Repairs & Maintenance",
    "HOME_IMPROVEMENT_OTHER_HOME_IMPROVEMENT": "Other Home Improvement",
    "RENT_AND_UTILITIES_TELEPHONE": "Phone", "RENT_AND_UTILITIES_OTHER_UTILITIES": "Other Utilities",
    "RENT_AND_UTILITIES_RENT": "Rent", "RENT_AND_UTILITIES_INTERNET_AND_CABLE": "Internet & Cable",
    "RENT_AND_UTILITIES_GAS_AND_ELECTRICITY": "Gas & Electric", "RENT_AND_UTILITIES_WATER": "Water",
    "LOAN_PAYMENTS_CREDIT_CARD_PAYMENT": "Credit Card Payment", "LOAN_PAYMENTS_MORTGAGE_PAYMENT": "Mortgage Payment",
    "LOAN_PAYMENTS_CAR_PAYMENT": "Car Payment", "LOAN_PAYMENTS_STUDENT_LOAN_PAYMENT": "Student Loan Payment",
    "LOAN_PAYMENTS_PERSONAL_LOAN_PAYMENT": "Personal Loan Payment", "LOAN_PAYMENTS_OTHER_PAYMENT": "Other Loan Payment",
    "BANK_FEES_INTEREST_CHARGE": "Interest Charges", "BANK_FEES_OTHER_BANK_FEES": "Bank Fees",
    "GOVERNMENT_AND_NON_PROFIT_TAX_PAYMENT": "Tax Payment",
    "GOVERNMENT_AND_NON_PROFIT_GOVERNMENT_DEPARTMENTS_AND_AGENCIES": "Government Fees",
    "GOVERNMENT_AND_NON_PROFIT_DONATIONS": "Donations",
    "GENERAL_SERVICES_AUTOMOTIVE": "Auto Services", "GENERAL_SERVICES_POSTAGE_AND_SHIPPING": "Shipping & Postage",
    "GENERAL_SERVICES_INSURANCE": "Insurance", "GENERAL_SERVICES_EDUCATION": "Education",
    "GENERAL_SERVICES_CHILDCARE": "Childcare", "GENERAL_SERVICES_OTHER_GENERAL_SERVICES": "Other Services",
    "TRANSFER_OUT_ACCOUNT_TRANSFER": "Account Transfer", "TRANSFER_OUT_OTHER_TRANSFER_OUT": "Other Transfer Out",
    "TRANSFER_OUT_INVESTMENT_AND_RETIREMENT_FUNDS": "Investment Transfer",
    "TRANSFER_OUT_SAVINGS": "Savings Transfer", "TRANSFER_OUT_WITHDRAWAL": "Withdrawal",
    "TRANSFER_IN_ACCOUNT_TRANSFER": "Account Transfer", "TRANSFER_IN_OTHER_TRANSFER_IN": "Other Transfer In",
    "TRANSFER_IN_CASH_ADVANCES_AND_LOANS": "Cash Advance", "TRANSFER_IN_DEPOSIT": "Deposit",
    "TRANSFER_IN_INVESTMENT_AND_RETIREMENT_FUNDS": "Investment Transfer", "TRANSFER_IN_SAVINGS": "Savings Transfer",
    "INCOME_WAGES": "Salary & Wages", "INCOME_INTEREST_EARNED": "Interest Earned",
    "INCOME_DIVIDENDS": "Dividends", "INCOME_TAX_REFUND": "Tax Refund", "INCOME_UNEMPLOYMENT": "Unemployment",
    "INCOME_RETIREMENT_PENSION": "Retirement & Pension", "INCOME_OTHER_INCOME": "Other Income",
    "OTHER": "Unknown",
}
_PLAID_PREFIX_WORDS = {"FOOD", "AND", "DRINK", "GENERAL", "MERCHANDISE", "TRANSFER", "IN", "OUT", "RENT",
                       "UTILITIES", "HOME", "IMPROVEMENT", "PERSONAL", "CARE", "BANK", "FEES", "LOAN",
                       "PAYMENTS", "GOVERNMENT", "NON", "PROFIT", "SERVICES", "INCOME"}

# ---------------------------------------------------------------------------
# Fina (Fidelity via aggregator) categories → normalized
# ---------------------------------------------------------------------------
FINA_MAP = {
    "transfer": "Transfers > Internal Transfer",
    "primary paycheck": "Income > Salary & Wages",
    "credit card payment": "Transfers > Credit Card Payment",
    "buy & trade": "Financial Services > Investment Trades",
    "sell & trade": "Financial Services > Investment Sales",
    "insurance": "Financial Services > Insurance",
    "loans & financial fees": "Financial Services > Loans & Fees",
    "bills & utilities": "Utilities > Bills",
    "other income": "Income > Other Income",
    "subscriptions": "Entertainment > Subscriptions",
    "other shopping": "Shopping > Other",
    "home": "Home & Housing > Home",
    "uncategorized": "Uncategorized",
    "groceries": "Food & Dining > Groceries",
    "restaurants & other": "Food & Dining > Restaurants",
    "taxes": "Financial Services > Taxes",
    "gym": "Health & Wellness > Gym & Fitness",
    "dividends & capital gains": "Income > Dividends",
    "interest": "Income > Interest Earned",
}

_LEVEL1_HINTS = [
    ("food", "Food & Dining"), ("dining", "Food & Dining"), ("restaurant", "Food & Dining"),
    ("grocer", "Food & Dining"), ("shop", "Shopping"), ("retail", "Shopping"),
    ("transport", "Transportation"), ("auto", "Transportation"), ("car", "Transportation"),
    ("health", "Health & Wellness"), ("medical", "Health & Wellness"), ("home", "Home & Housing"),
    ("housing", "Home & Housing"), ("utilit", "Utilities"), ("bills", "Utilities"),
    ("entertain", "Entertainment"), ("financ", "Financial Services"), ("bank", "Financial Services"),
    ("invest", "Financial Services"), ("transfer", "Transfers"), ("education", "Education"),
    ("school", "Education"), ("personal", "Personal Care"), ("business", "Business"),
    ("travel", "Travel"), ("income", "Income"),
]


def _title(text: str) -> str:
    small = {"and", "or", "the", "a", "an", "of", "to", "for"}
    out = []
    for w in text.split():
        if w == "&":
            out.append("&")
        elif w.lower() in small and out:
            out.append(w.lower())
        else:
            out.append(w.capitalize())
    return " ".join(out)


def match_master(level1: str) -> str:
    low = level1.strip().lower()
    for m in MASTER_CATEGORIES:
        if m.lower() == low:
            return m
    for hint, m in _LEVEL1_HINTS:
        if hint in low:
            return m
    return "Uncategorized"


def normalize_category(raw: str | None, source: str | None = None) -> str:
    """Map a provider category string to the canonical ``Level1 > Sub`` form."""
    if not raw:
        return "Uncategorized"
    raw = raw.strip()
    if source is None:
        if raw.isupper() or raw.split(" > ")[0] in PLAID_LEVEL1:
            source = "plaid"
        elif raw.lower() in FINA_MAP:
            source = "fina"
        else:
            source = "text"
    if source == "plaid":
        primary, _, detailed = raw.partition(" > ")
        l1 = PLAID_LEVEL1.get(primary.strip(), "Uncategorized")
        d = detailed.strip()
        if not d:
            return l1
        sub = PLAID_DETAILED.get(d)
        if sub is None:
            words = [w for w in d.split("_")]
            meaningful, started = [], False
            for w in words:
                if started or w not in _PLAID_PREFIX_WORDS:
                    started = True
                    meaningful.append(w)
            sub = " ".join(w.capitalize() for w in (meaningful or words[-2:])).replace(" And ", " & ")
        return f"{l1} > {sub}"
    if source == "fina":
        low = raw.lower()
        if low in FINA_MAP:
            return FINA_MAP[low]
        if " > " in raw:
            return normalize_category(raw, "text")
        return f"Uncategorized > {_title(raw)}"
    # free text (LLM / CSV / already normalized)
    if " > " in raw:
        l1, sub = raw.split(" > ", 1)
        return f"{match_master(l1)} > {_title(sub.strip())}"
    return match_master(raw)


def level1(category: str | None) -> str:
    if not category:
        return "Uncategorized"
    return category.split(" > ", 1)[0]


# ---------------------------------------------------------------------------
# Flow inference
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Rule:
    pattern: re.Pattern
    flow_type: str
    category: str | None = None
    account_kind: str | None = None


def compile_rules(rules) -> list[Rule]:
    out = []
    for r in rules or []:
        out.append(Rule(re.compile(r.pattern, re.I), r.flow_type, getattr(r, "category", None),
                        getattr(r, "account_kind", None)))
    return out


_DESC_RULES = [
    (re.compile(r"\bREINVEST", re.I), "investment_buy"),
    (re.compile(r"\bDIVIDEND", re.I), "dividend"),
    (re.compile(r"\bYOU BOUGHT\b|\bBUY\b.*\bSHARES\b|\bPURCHASE OF\b", re.I), "investment_buy"),
    (re.compile(r"\bYOU SOLD\b|\bSALE OF\b", re.I), "investment_sell"),
    (re.compile(r"\bINTEREST (EARNED|PAID|CREDIT|RECEIVED)\b", re.I), "interest"),
    (re.compile(r"\bINTEREST CHARGE|\bFINANCE CHARGE", re.I), "fee"),
    (re.compile(r"\b(IRS|USATAXPYMT|TAX ?PAYMENT|ESTIMATED TAX|IL DEPT OF REVENUE|DEPT OF REV)\b", re.I), "tax"),
    (re.compile(r"\b(PAYROLL|DIRECT DEP|DIR DEP|SALARY|SEVERANCE)\b", re.I), "income"),
]
_TRANSFER_DESC = re.compile(r"\b(TRANSFER|XFER|ZELLE|VENMO|ONLINE PAYMENT|AUTOPAY|PAYMENT THANK YOU|"
                            r"PAYMENT - THANK YOU|MOBILE PAYMENT|ACH PMT|EPAY)\b", re.I)
_LIABILITY_KINDS = {"mortgage", "heloc", "loan", "student_loan"}
_EXPENSE_L1 = {"Food & Dining", "Shopping", "Transportation", "Entertainment", "Health & Wellness",
               "Home & Housing", "Utilities", "Education", "Business", "Personal Care", "Travel"}


def infer_flow(category: str | None, amount: float, account_kind: str = "checking",
               description: str | None = None, rules: list[Rule] | None = None) -> str:
    """Return the flow_type for a transaction. Deterministic, no I/O."""
    desc = description or ""
    cat = category or "Uncategorized"
    l1, _, sub = cat.partition(" > ")
    subl = sub.lower()

    # 0. user rules
    for r in rules or []:
        if r.account_kind and r.account_kind != account_kind:
            continue
        if r.pattern.search(desc):
            return r.flow_type

    # 1. loan accounts: everything is servicing the loan
    if account_kind in _LIABILITY_KINDS:
        if amount < 0 and re.search(r"INTEREST", desc, re.I):
            return "fee"
        return "loan_payment"

    # 2. strong description signals
    for pat, flow in _DESC_RULES:
        if pat.search(desc):
            if flow == "interest" and amount < 0:
                return "fee"
            return flow

    # 3. category signals
    if l1 == "Income":
        if "interest" in subl:
            return "interest"
        if "dividend" in subl:
            return "dividend"
        if "refund" in subl:
            return "refund"
        return "income"
    if l1 == "Transfers":
        return "transfer"
    if "cryptocurrency" in cat.lower() or "brokerage" in cat.lower():
        return "investment_buy" if amount < 0 else "investment_sell"
    if l1 == "Financial Services":
        if "investment trade" in subl or subl.startswith("buy"):
            return "investment_buy"
        if "investment sale" in subl or subl.startswith("sell"):
            return "investment_sell"
        if "tax" in subl:
            return "tax"
        if "credit card payment" in subl:
            return "transfer"
        if "mortgage" in subl or "loan" in subl or "car payment" in subl or "student" in subl:
            return "loan_payment"
        if "interest" in subl or "fee" in subl:
            return "fee"
        if "payment reversal" in subl or "returned payment" in subl:
            return "refund"
        return "expense" if amount < 0 else "refund"

    # 4. account-kind signals
    if account_kind == "credit_card" and amount > 0 and (_TRANSFER_DESC.search(desc) or l1 == "Uncategorized"):
        return "transfer"
    if account_kind in ("crypto_exchange", "crypto_wallet") and l1 == "Uncategorized":
        return "investment_buy" if amount < 0 else "investment_sell"

    # 5. sign + generic
    if amount > 0:
        if l1 in _EXPENSE_L1:
            return "refund"
        if _TRANSFER_DESC.search(desc):
            return "transfer"
        return "unknown"
    if _TRANSFER_DESC.search(desc) and l1 == "Uncategorized":
        return "transfer"
    return "expense"


def apply_category_rules(conn, merchant: str | None, description: str | None) -> tuple[str | None, str | None]:
    """Look up merchant/description against ``category_rules``.

    Returns (category, flow_type) or (None, None). Exact matches beat contains
    matches; higher priority wins within a kind; regex rules run last.
    """
    text = f"{merchant or ''} {description or ''}".strip().lower()
    if not text:
        return None, None
    rows = conn.execute(
        "SELECT pattern, match_kind, category, flow_type FROM category_rules "
        "ORDER BY CASE match_kind WHEN 'exact' THEN 0 WHEN 'contains' THEN 1 ELSE 2 END, priority DESC"
    ).fetchall()
    m = (merchant or "").strip().lower()
    for pattern, kind, category, flow in rows:
        p = pattern.lower()
        if kind == "exact" and (m == p or (description or "").strip().lower() == p):
            return category, flow
        if kind == "contains" and p and p in text:
            return category, flow
        if kind == "regex":
            try:
                if re.search(pattern, text, re.I):
                    return category, flow
            except re.error:
                continue
    return None, None
