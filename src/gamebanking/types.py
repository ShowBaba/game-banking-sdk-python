"""Response shapes. At runtime these are plain dicts; the TypedDicts give editors
and type checkers the field names. Amounts are ints in minor units."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class CurrencyBrief(TypedDict):
    code: str
    exponent: int
    symbol: Optional[str]


class Currency(CurrencyBrief):
    id: str
    name: str
    standard: bool
    status: str


class Account(TypedDict):
    id: str
    bank_id: str
    bank_code: str
    owner_type: str
    player_id: Optional[str]
    system_role: Optional[str]
    account_type: str
    account_number: str
    account_name: str
    currency: CurrencyBrief
    status: str
    allow_negative_balance: bool
    posted_balance: int
    available_balance: int
    held_balance: int
    version: int
    metadata: Dict[str, Any]
    created_at: str
    updated_at: str


class Bank(TypedDict, total=False):
    id: str
    environment: str
    name: str
    slug: str
    bank_code: str
    base_currency: Currency
    branding: Dict[str, Any]
    feature_flags: Dict[str, bool]
    config_version: int
    status: str
    created_at: str
    updated_at: str
    system_accounts: List[Account]


class Balance(TypedDict, total=False):
    account_id: str
    account_number: str
    currency: CurrencyBrief
    posted_balance: int
    available_balance: int
    held_balance: int
    posted_display: str
    available_display: str
    version: int
    as_of: str
    as_of_game_time: str


class Player(TypedDict):
    id: str
    external_player_id: str
    display_name: Optional[str]
    status: str
    metadata: Dict[str, Any]
    created_at: str
    updated_at: str


class Entry(TypedDict):
    id: str
    account_id: str
    account_number: str
    account_name: str
    side: str
    amount_minor: int
    balance_after: int
    #: "principal", "fee" or "levy".
    kind: str


class Transaction(TypedDict, total=False):
    id: str
    session_id: str
    type: str
    status: str
    bank_id: str
    currency: CurrencyBrief
    amount_minor: int
    amount_display: str
    reference: Optional[str]
    narration: Optional[str]
    initiated_by: Dict[str, str]
    related_transaction_id: Optional[str]
    reversed_by_transaction_id: str
    metadata: Dict[str, Any]
    created_at: str
    posted_at: Optional[str]
    game_time: str
    entries: List[Entry]


class HistoryItem(TypedDict):
    entry_id: str
    transaction_id: str
    session_id: str
    type: str
    status: str
    direction: str
    amount_minor: int
    amount_display: str
    balance_after: int
    #: "principal", "fee" or "levy". A fee or levy line's narration is the fee's name.
    kind: str
    narration: Optional[str]
    reference: Optional[str]
    counterparty: Optional[Dict[str, str]]
    real_time: str
    game_time: str
    related_transaction_id: Optional[str]


class HistoryPage(TypedDict):
    data: List[HistoryItem]
    next_cursor: Optional[str]
    has_more: bool


class Hold(TypedDict):
    id: str
    bank_id: str
    account_id: str
    destination_account_id: Optional[str]
    amount_minor: int
    #: Held on top of the amount for the capture's expected fees.
    reserved_fee_minor: int
    captured_amount_minor: Optional[int]
    status: str
    reason: str
    reference: Optional[str]
    expires_at_game: str
    capture_transaction_id: Optional[str]
    created_at: str
    created_game_time: str
    closed_at: Optional[str]
    closed_game_time: Optional[str]


class NameEnquiry(TypedDict):
    bank_code: str
    bank_name: str
    account_number: str
    account_name: str
    status: str


class Clock(TypedDict):
    mode: str
    speed: int
    time_zone: str
    game_time: str
    game_day: str
    real_time: str


class Limits(TypedDict):
    bank_id: str
    currency: str
    limits: Dict[str, Optional[Dict[str, Optional[int]]]]
    game_day: str
    game_funding_used_today: int
    note: str


class ReconciliationReport(TypedDict):
    started_at: str
    finished_at: str
    accounts_checked: int
    transactions_checked: int
    differences: List[Dict[str, Any]]
    ok: bool


class FundingResult(TypedDict):
    transaction: Transaction
    balance: Balance


class FeeCharge(TypedDict):
    """One fee or levy charged on a payment."""

    fee_rule_id: str
    fee_rule_version: int
    code: str
    name: str
    kind: str
    amount_minor: int
    credit_account: str


class TransferResult(TypedDict, total=False):
    transaction: Transaction
    source_balance: Balance
    destination_balance: Balance
    #: Fees and levies charged to the sender on top of the amount.
    fees: List[FeeCharge]
    fees_total_minor: int
    #: Amount plus fees.
    total_debit_minor: int


class HoldResult(TypedDict):
    hold: Hold
    balance: Balance


class CaptureResult(TypedDict, total=False):
    hold: Hold
    transaction: Transaction
    source_balance: Balance
    destination_balance: Balance
    fees: List[FeeCharge]
    fees_total_minor: int
    total_debit_minor: int


class FeeRule(TypedDict):
    """A fee or levy a bank charges. Amounts are minor units; times are game time."""

    id: str
    bank_id: str
    code: str
    name: str
    #: "transfer", "hold_capture" or "account_maintenance".
    event: str
    #: "fee" (credits fee_income) or "levy" (credits levies_payable).
    kind: str
    #: "fixed", "percentage" or "combined".
    model: str
    fixed_minor: int
    #: Basis points: 100 = 1%.
    percentage_bps: int
    min_fee_minor: Optional[int]
    max_fee_minor: Optional[int]
    min_amount_minor: Optional[int]
    max_amount_minor: Optional[int]
    payer: str
    credit_account: str
    status: str
    effective_from: str
    effective_to: Optional[str]
    version: int
    #: "in_effect", "scheduled", "ended" or "inactive". Only in_effect rules charge.
    state: str
    warnings: List[str]
    created_at: str
    updated_at: str


class FeeQuote(TypedDict):
    bank_id: str
    event: str
    amount_minor: int
    fees: List[FeeCharge]
    fees_total_minor: int
    total_debit_minor: int
    game_time: str


class BankBooks(TypedDict):
    """The bank's own ledger accounts, from which its profit and loss derives."""

    bank_id: str
    currency: str
    fee_income_minor: int
    levies_payable_minor: int
    accounts: List[Dict[str, Any]]
    as_of: str


class AdvanceClockResult(TypedDict):
    clock: Clock
    previous_game_time: str
    jobs: Dict[str, Any]


class Developer(TypedDict):
    id: str
    name: str
    contact_email: str
    status: str
    has_password: bool
    created_at: str
    updated_at: str


class Game(TypedDict):
    id: str
    developer_id: str
    name: str
    slug: str
    status: str
    created_at: str
    updated_at: str


class ApiKey(TypedDict, total=False):
    id: str
    game_id: str
    environment: str
    label: str
    prefix: str
    #: Present only in the response that created the key.
    secret: str
    scopes: List[str]
    last_used_at: Optional[str]
    expires_at: Optional[str]
    revoked_at: Optional[str]
    created_at: str


class DeveloperCredential(TypedDict, total=False):
    id: str
    label: str
    prefix: str
    secret: str
    last_used_at: Optional[str]
    expires_at: Optional[str]
    revoked_at: Optional[str]
    created_at: str


class AuditLog(TypedDict):
    id: str
    developer_id: Optional[str]
    game_id: Optional[str]
    environment: Optional[str]
    actor_type: str
    actor_id: str
    action: str
    target_type: Optional[str]
    target_id: Optional[str]
    correlation_id: Optional[str]
    metadata: Dict[str, Any]
    created_at: str
