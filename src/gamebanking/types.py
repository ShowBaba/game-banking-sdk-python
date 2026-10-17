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
    #: Set on merchant accounts.
    merchant_id: Optional[str]
    #: The deposit product of a savings or fixed-deposit account.
    product_id: Optional[str]
    #: Receives the account's interest; None pays the account itself.
    interest_account_id: Optional[str]
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
    #: Interest paid to savers (negative), earned but unpaid, and money in fixed deposits.
    interest_expense_minor: int
    accrued_interest_minor: int
    fixed_deposits_minor: int
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


# ---- Webhooks -------------------------------------------------------------------

class WebhookEndpoint(TypedDict, total=False):
    id: str
    url: str
    description: Optional[str]
    #: ["*"] means every type.
    event_types: List[str]
    #: "active" or "disabled". The engine disables an endpoint after three days of failed deliveries.
    status: str
    disabled_reason: Optional[str]
    secret_prefix: str
    #: Present only when the endpoint is created or its secret rotated.
    secret: str
    #: Until then deliveries are also signed with the previous secret.
    previous_secret_expires_at: Optional[str]
    failing_since: Optional[str]
    last_success_at: Optional[str]
    last_failure_at: Optional[str]
    created_at: str
    updated_at: str


class AlertCharge(TypedDict):
    #: "fee" or "levy": charged on a debit, refunded on a credit.
    kind: str
    name: str
    fee_rule_id: Optional[str]
    amount_minor: int


class AlertBalance(TypedDict):
    posted_minor: int
    available_minor: int


class AlertCounterparty(TypedDict):
    #: "customer" or "bank". Customer account numbers are masked to the last four digits.
    type: str
    account_name: str
    account_number: str
    bank_code: str


class AccountAlert(TypedDict):
    """The data of an account.debited or account.credited event."""

    account_id: str
    account_number: str
    account_name: str
    player_id: Optional[str]
    bank_id: str
    bank_code: str
    transaction_id: str
    session_id: str
    transaction_type: str
    related_transaction_id: Optional[str]
    #: The principal (0 for a fee-only transaction).
    amount_minor: int
    charges: List[AlertCharge]
    #: Principal plus charges: what left (or reached) the account.
    total_minor: int
    total_display: str
    currency: CurrencyBrief
    balance_after: AlertBalance
    narration: Optional[str]
    reference: Optional[str]
    counterparty: Optional[AlertCounterparty]
    game_time: str
    #: Increases with every ledger entry: keep the alert with the highest sequence for the latest balance.
    sequence: int


class WebhookEvent(TypedDict):
    """The body of a webhook delivery, and an item of the events feed. Deduplicate on ``id``."""

    id: str
    #: account.debited, account.credited or webhook.test
    type: str
    created_at: str
    game_time: Optional[str]
    game_id: str
    environment: str
    #: An AccountAlert for account.* events.
    data: Dict[str, Any]


class WebhookEventPage(TypedDict):
    data: List[WebhookEvent]
    next_cursor: Optional[str]
    has_more: bool


class WebhookDelivery(TypedDict):
    id: str
    event_id: str
    event_type: str
    endpoint_id: str
    endpoint_url: str
    #: pending, delivering, delivered or failed
    state: str
    attempts: int
    next_attempt_at: Optional[str]
    last_attempt_at: Optional[str]
    #: The endpoint's HTTP status on the last attempt.
    last_status: Optional[int]
    last_error: Optional[str]
    last_response_ms: Optional[int]
    delivered_at: Optional[str]
    created_at: str


# ---- Merchants and cards ---------------------------------------------------------

class Merchant(TypedDict):
    id: str
    external_merchant_id: str
    name: str
    category: str
    owner_player_id: Optional[str]
    #: "active" or "suspended" (card payments declined).
    status: str
    metadata: Dict[str, Any]
    created_at: str
    updated_at: str


class CardProgram(TypedDict):
    id: str
    bank_id: str
    name: str
    bin: str
    validity_months: int
    #: How long an authorisation holds funds, in game seconds.
    auth_expiry_seconds: int
    per_txn_limit_minor: Optional[int]
    daily_limit_minor: Optional[int]
    status: str
    created_at: str
    updated_at: str


class Card(TypedDict):
    id: str
    bank_id: str
    account_id: str
    player_id: str
    program_id: str
    masked_number: str
    last4: str
    expiry_month: int
    #: Valid through the end of expiry_month of game time.
    expiry_year: int
    name_on_card: str
    #: active, blocked, lost, stolen, expired or closed
    status: str
    status_reason: Optional[str]
    per_txn_limit_minor: Optional[int]
    daily_limit_minor: Optional[int]
    effective_per_txn_limit_minor: Optional[int]
    effective_daily_limit_minor: Optional[int]
    metadata: Dict[str, Any]
    status_changed_at: str
    created_at: str
    updated_at: str


class IssueCardResult(TypedDict):
    """``card_number`` and ``cvv`` are shown only here."""

    card: Card
    card_number: str
    cvv: str
    fees: List[FeeCharge]
    fees_total_minor: int
    balance: Balance


class CardRefund(TypedDict):
    id: str
    transaction_id: str
    amount_minor: int
    reason: Optional[str]
    game_time: str
    created_at: str


class CardAuthorization(TypedDict):
    id: str
    card_id: str
    card_last4: str
    bank_id: str
    account_id: str
    #: {"id", "name", "category"}
    merchant: Dict[str, str]
    merchant_account_id: str
    #: approved, declined, captured, released, expired or refunded
    status: str
    decline_code: Optional[str]
    decline_message: Optional[str]
    amount_minor: int
    captured_minor: int
    refunded_minor: int
    currency: CurrencyBrief
    hold_id: Optional[str]
    reserved_fee_minor: int
    expires_at_game: Optional[str]
    capture_transaction_id: Optional[str]
    reference: Optional[str]
    description: Optional[str]
    refunds: List[CardRefund]
    game_time: str
    created_at: str
    updated_at: str
    closed_at: Optional[str]


class _AuthorizeCardResult(TypedDict):
    authorization: CardAuthorization
    fees: List[FeeCharge]
    fees_total_minor: int
    balance: Balance  # the cardholder's account after the call


class AuthorizeCardResult(_AuthorizeCardResult, total=False):
    """A decline is a result: check ``authorization["status"]`` and ``decline_code``.
    An approved payment is captured at once (unless ``capture=False``) and the result
    then also carries ``transaction``, ``merchant_balance`` and ``total_debit_minor``."""

    transaction: Transaction
    merchant_balance: Balance
    total_debit_minor: int


class CaptureCardResult(TypedDict):
    authorization: CardAuthorization
    transaction: Transaction
    card_balance: Balance
    merchant_balance: Balance
    fees: List[FeeCharge]
    fees_total_minor: int
    total_debit_minor: int


class RefundCardResult(TypedDict):
    refund: CardRefund
    authorization: CardAuthorization
    transaction: Transaction
    card_balance: Balance
    merchant_balance: Balance


#: Why a card payment was declined (``authorization["decline_code"]``).
DECLINE_CODES = (
    "invalid_expiry", "invalid_cvv", "card_blocked", "card_lost", "card_stolen", "card_expired", "card_closed",
    "account_frozen", "account_closed", "merchant_inactive", "exceeds_transaction_limit", "exceeds_daily_limit",
    "insufficient_funds",
)


# ---- Savings and fixed deposits ---------------------------------------------------

class DepositProduct(TypedDict, total=False):
    id: str
    bank_id: str
    code: str
    name: str
    #: "savings" or "fixed_deposit"
    kind: str
    #: Savings: [{"from_minor": 0, "rate_bps": 300}, …] annual rates by balance.
    rate_tiers: List[Dict[str, int]]
    #: "whole_balance" or "banded"
    tier_method: str
    #: Fixed deposits: [{"days": 90, "rate_bps": 800}, …]
    terms: List[Dict[str, int]]
    day_count: str
    accrual_basis: str
    payout_frequency: str
    withholding_tax_bps: int
    min_opening_minor: int
    min_balance_minor: int
    max_balance_minor: Optional[int]
    withdrawals_per_month: Optional[int]
    #: "block", "forfeit_interest" or "fee"
    excess_withdrawal_action: str
    early_forfeit_bps: int
    early_penalty_fixed_minor: int
    early_penalty_bps: int
    default_maturity_instruction: str
    status: str
    version: int
    created_at: str
    updated_at: str


class DepositQuote(TypedDict):
    product_id: str
    amount_minor: int
    days: int
    rate_bps: int
    gross_interest_minor: int
    tax_minor: int
    net_interest_minor: int
    maturity_amount_minor: int


class AccountInterest(TypedDict):
    account_id: str
    product_id: str
    product_name: str
    payout_frequency: str
    #: The rate the current balance earns (a fixed deposit's locked rate).
    rate_bps: int
    accrued_interest_minor: int
    accrued_through: str
    next_payout_day: str
    forfeit_month: Optional[str]
    withdrawals_this_month: int
    withdrawals_per_month: Optional[int]
    payouts: List[Dict[str, Any]]


class FixedDeposit(TypedDict):
    id: str
    bank_id: str
    account_id: str
    account_number: str
    player_id: str
    product_id: str
    product_name: str
    source_account_id: str
    payout_account_id: str
    principal_minor: int
    rate_bps: int
    term_days: int
    start_day: str
    maturity_day: str
    #: "payout", "rollover_principal" or "rollover_all"
    maturity_instruction: str
    #: "active", "matured" or "broken"
    status: str
    terms_completed: int
    interest_paid_minor: int
    accrued_interest_minor: int
    balance_minor: int
    created_at: str
    closed_at: Optional[str]


class BreakQuote(TypedDict):
    fixed_deposit_id: str
    principal_minor: int
    accrued_interest_minor: int
    forfeited_interest_minor: int
    interest_paid_minor: int
    tax_minor: int
    penalty_minor: int
    payout_minor: int
    payout_account_id: str
