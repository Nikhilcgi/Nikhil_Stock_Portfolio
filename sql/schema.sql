CREATE TABLE IF NOT EXISTS schema_metadata (
    schema_version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
);

INSERT OR IGNORE INTO schema_metadata (schema_version) VALUES ('0.1.0');

CREATE TABLE IF NOT EXISTS accounts (
    account_key TEXT PRIMARY KEY,
    broker TEXT NOT NULL,
    depository TEXT,
    demat_account_hash TEXT,
    source_account_ref TEXT,
    valid_from DATE,
    valid_to DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS import_batches (
    batch_uid TEXT PRIMARY KEY,
    broker TEXT NOT NULL,
    account_key TEXT NOT NULL,
    report_kind TEXT NOT NULL,
    source_file TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    report_start DATE,
    report_end DATE,
    as_of_date DATE,
    header_row INTEGER,
    imported_row_count BIGINT NOT NULL,
    import_status TEXT NOT NULL,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    UNIQUE (account_key, report_kind, source_sha256)
);

CREATE TABLE IF NOT EXISTS trades (
    trade_uid TEXT PRIMARY KEY,
    broker TEXT NOT NULL,
    account_key TEXT NOT NULL,
    trade_date DATE NOT NULL,
    executed_at TIMESTAMP,
    exchange_timezone TEXT,
    exchange TEXT NOT NULL,
    segment TEXT NOT NULL,
    series TEXT,
    transaction_type TEXT NOT NULL,
    transaction_granularity TEXT NOT NULL DEFAULT 'EXECUTION_FILL',
    activity_classification TEXT,
    tax_lot_quality TEXT NOT NULL DEFAULT 'EXACT_FILL',
    symbol TEXT,
    raw_security_name TEXT,
    isin TEXT,
    raw_isin TEXT,
    broker_security_code TEXT,
    instrument_type TEXT,
    strike_price DECIMAL(38, 12),
    expiry_date DATE,
    quantity DECIMAL(38, 12) NOT NULL,
    price DECIMAL(38, 12) NOT NULL,
    gross_amount DECIMAL(38, 12) NOT NULL,
    calculated_gross_amount DECIMAL(38, 12),
    gross_amount_difference DECIMAL(38, 12),
    brokerage DECIMAL(38, 12),
    stt DECIMAL(38, 12),
    sebi_fees DECIMAL(38, 12),
    stamp_duty DECIMAL(38, 12),
    exchange_charges DECIMAL(38, 12),
    gst DECIMAL(38, 12),
    ipft_charges DECIMAL(38, 12),
    other_charges DECIMAL(38, 12),
    net_amount DECIMAL(38, 12),
    is_auction BOOLEAN NOT NULL DEFAULT false,
    broker_trade_id TEXT NOT NULL,
    broker_order_id TEXT,
    source_activity_uid TEXT,
    security_resolution_status TEXT NOT NULL DEFAULT 'UNRESOLVED',
    source_validation_status TEXT NOT NULL DEFAULT 'OK',
    source_file TEXT NOT NULL,
    source_row_number BIGINT NOT NULL,
    source_sha256 TEXT NOT NULL,
    row_hash TEXT NOT NULL,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    UNIQUE (account_key, exchange, segment, trade_date, broker_trade_id)
);

CREATE TABLE IF NOT EXISTS broker_period_charges (
    charge_uid TEXT PRIMARY KEY,
    broker TEXT NOT NULL,
    account_key TEXT NOT NULL,
    period_start DATE,
    period_end DATE,
    account_head TEXT NOT NULL,
    normalized_charge_type TEXT,
    amount DECIMAL(38, 12) NOT NULL,
    source_file TEXT NOT NULL,
    source_row_number BIGINT NOT NULL,
    source_sha256 TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS broker_security_aggregates (
    aggregate_uid TEXT PRIMARY KEY,
    broker TEXT NOT NULL,
    account_key TEXT NOT NULL,
    period_start DATE,
    period_end DATE,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    segment TEXT NOT NULL,
    buy_quantity DECIMAL(38, 12) NOT NULL,
    buy_value DECIMAL(38, 12) NOT NULL,
    sell_quantity DECIMAL(38, 12) NOT NULL,
    sell_value DECIMAL(38, 12) NOT NULL,
    source_file TEXT NOT NULL,
    source_row_number BIGINT NOT NULL,
    source_sha256 TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS broker_activity_aggregates (
    activity_uid TEXT PRIMARY KEY,
    broker TEXT NOT NULL,
    account_key TEXT NOT NULL,
    activity_date DATE NOT NULL,
    exchange TEXT,
    segment TEXT,
    broker_bill_number TEXT,
    symbol TEXT,
    isin TEXT,
    raw_security_name TEXT NOT NULL,
    buy_quantity DECIMAL(38, 12) NOT NULL,
    buy_value DECIMAL(38, 12) NOT NULL,
    sell_quantity DECIMAL(38, 12) NOT NULL,
    sell_value DECIMAL(38, 12) NOT NULL,
    brokerage DECIMAL(38, 12),
    gst DECIMAL(38, 12),
    stt DECIMAL(38, 12),
    sebi_fees DECIMAL(38, 12),
    stamp_duty DECIMAL(38, 12),
    exchange_charges DECIMAL(38, 12),
    other_charges DECIMAL(38, 12),
    reported_net_amount DECIMAL(38, 12),
    calculated_net_amount DECIMAL(38, 12),
    net_amount_difference DECIMAL(38, 12),
    activity_classification TEXT NOT NULL,
    source_validation_status TEXT NOT NULL,
    source_file TEXT NOT NULL,
    source_row_number BIGINT NOT NULL,
    source_sha256 TEXT NOT NULL,
    row_hash TEXT NOT NULL,
    UNIQUE (account_key, activity_date, exchange, broker_bill_number, raw_security_name)
);

CREATE TABLE IF NOT EXISTS custody_movements (
    movement_uid TEXT PRIMARY KEY,
    broker TEXT NOT NULL,
    account_key TEXT NOT NULL,
    movement_date DATE NOT NULL,
    isin TEXT NOT NULL,
    raw_security_name TEXT,
    source_reference TEXT,
    description TEXT NOT NULL,
    movement_type TEXT NOT NULL,
    debit_quantity DECIMAL(38, 12) NOT NULL,
    credit_quantity DECIMAL(38, 12) NOT NULL,
    quantity_delta DECIMAL(38, 12) NOT NULL,
    affects_total_quantity BOOLEAN NOT NULL,
    balance_quantity DECIMAL(38, 12),
    reported_amount DECIMAL(38, 12),
    is_corporate_action_candidate BOOLEAN NOT NULL DEFAULT false,
    source_page INTEGER,
    source_table INTEGER,
    source_row_number BIGINT NOT NULL,
    source_file TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    row_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS custody_position_reconciliations (
    reconciliation_uid TEXT PRIMARY KEY,
    broker TEXT NOT NULL,
    account_key TEXT NOT NULL,
    as_of_date DATE NOT NULL,
    isin TEXT NOT NULL,
    opening_quantity DECIMAL(38, 12) NOT NULL,
    movement_quantity_delta DECIMAL(38, 12) NOT NULL,
    calculated_closing_quantity DECIMAL(38, 12) NOT NULL,
    reported_closing_quantity DECIMAL(38, 12) NOT NULL,
    quantity_difference DECIMAL(38, 12) NOT NULL,
    reconciliation_status TEXT NOT NULL,
    source_file TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    UNIQUE (account_key, as_of_date, isin, source_sha256)
);

CREATE TABLE IF NOT EXISTS broker_holding_snapshots (
    snapshot_uid TEXT PRIMARY KEY,
    broker TEXT NOT NULL,
    account_key TEXT NOT NULL,
    as_of_date DATE,
    summary_json JSON,
    source_file TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    UNIQUE (account_key, as_of_date, source_sha256)
);

CREATE TABLE IF NOT EXISTS broker_holding_rows (
    holding_row_uid TEXT PRIMARY KEY,
    snapshot_uid TEXT NOT NULL,
    broker TEXT NOT NULL,
    account_key TEXT NOT NULL,
    as_of_date DATE,
    symbol TEXT,
    raw_security_name TEXT,
    isin TEXT,
    sector_raw TEXT,
    quantity_current DECIMAL(38, 12),
    quantity_available DECIMAL(38, 12),
    quantity_discrepant DECIMAL(38, 12),
    quantity_long_term DECIMAL(38, 12),
    quantity_frozen DECIMAL(38, 12),
    quantity_locked DECIMAL(38, 12),
    quantity_pledged DECIMAL(38, 12),
    quantity_pledged_margin DECIMAL(38, 12),
    quantity_pledged_loan DECIMAL(38, 12),
    quantity_remat DECIMAL(38, 12),
    quantity_locked_in DECIMAL(38, 12),
    quantity_safe_keep DECIMAL(38, 12),
    quantity_mtf_pledge DECIMAL(38, 12),
    quantity_margin_pledge DECIMAL(38, 12),
    quantity_cusa_pledge DECIMAL(38, 12),
    reconciliation_quantity DECIMAL(38, 12),
    quantity_component_difference DECIMAL(38, 12),
    average_price DECIMAL(38, 12),
    reported_invested_value DECIMAL(38, 12),
    previous_close DECIMAL(38, 12),
    current_value DECIMAL(38, 12),
    unrealized_pnl DECIMAL(38, 12),
    unrealized_pnl_ratio DECIMAL(38, 12),
    value_date DATE,
    valuation_status TEXT,
    source_file TEXT NOT NULL,
    source_row_number BIGINT NOT NULL,
    source_sha256 TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reconciliation_issues (
    issue_uid TEXT PRIMARY KEY,
    calculation_run_id TEXT,
    issue_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    broker TEXT,
    account_key TEXT,
    instrument_id TEXT,
    symbol TEXT,
    exchange TEXT,
    as_of_date DATE,
    details_json JSON NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN',
    created_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    resolved_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS instruments (
    instrument_id TEXT PRIMARY KEY,
    issuer_id TEXT,
    isin TEXT,
    security_type TEXT,
    security_class TEXT,
    face_value DECIMAL(38, 12),
    valid_from DATE,
    valid_to DATE,
    status TEXT NOT NULL DEFAULT 'ACTIVE'
);

CREATE TABLE IF NOT EXISTS instrument_aliases (
    alias_uid TEXT PRIMARY KEY,
    instrument_id TEXT NOT NULL,
    broker TEXT,
    exchange TEXT,
    symbol TEXT,
    series TEXT,
    broker_security_code TEXT,
    raw_security_name TEXT,
    valid_from DATE,
    valid_to DATE,
    evidence_uid TEXT,
    resolution_status TEXT NOT NULL DEFAULT 'PROPOSED'
);

CREATE TABLE IF NOT EXISTS source_evidence (
    evidence_uid TEXT PRIMARY KEY,
    source_class TEXT NOT NULL,
    authority TEXT,
    source_url TEXT,
    source_document_date DATE,
    retrieved_at TIMESTAMPTZ,
    sha256 TEXT,
    local_path TEXT,
    raw_payload JSON
);

CREATE TABLE IF NOT EXISTS corporate_action_events (
    event_uid TEXT PRIMARY KEY,
    logical_event_key TEXT NOT NULL,
    revision_number INTEGER NOT NULL DEFAULT 1,
    supersedes_event_uid TEXT,
    action_type TEXT NOT NULL,
    action_subtype TEXT,
    issuer_id TEXT,
    primary_instrument_id TEXT,
    announcement_date DATE,
    ex_date DATE,
    record_date DATE,
    legal_effective_date DATE,
    allotment_date DATE,
    listing_date DATE,
    declared_payment_date DATE,
    economic_posting_date DATE,
    tax_qualification TEXT NOT NULL DEFAULT 'UNKNOWN',
    status TEXT NOT NULL DEFAULT 'DISCOVERED',
    terms_json JSON,
    terms_hash TEXT,
    evidence_uid TEXT,
    approved_by TEXT,
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    UNIQUE (logical_event_key, revision_number)
);

CREATE TABLE IF NOT EXISTS corporate_action_legs (
    leg_uid TEXT PRIMARY KEY,
    event_uid TEXT NOT NULL,
    leg_number INTEGER NOT NULL,
    leg_role TEXT NOT NULL,
    from_instrument_id TEXT,
    to_instrument_id TEXT,
    ratio_numerator BIGINT,
    ratio_denominator BIGINT,
    cash_rate_per_unit DECIMAL(38, 12),
    currency TEXT DEFAULT 'INR',
    basis_method TEXT,
    tax_basis_weight DECIMAL(38, 12),
    performance_basis_weight DECIMAL(38, 12),
    holding_period_method TEXT,
    fifo_rank_method TEXT,
    rounding_scope TEXT,
    rounding_method TEXT,
    evidence_uid TEXT,
    UNIQUE (event_uid, leg_number)
);

CREATE TABLE IF NOT EXISTS calculation_runs (
    calculation_run_id TEXT PRIMARY KEY,
    run_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    data_cutoff TIMESTAMPTZ,
    code_version TEXT NOT NULL,
    input_digest TEXT NOT NULL,
    tax_rule_set_id TEXT,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ca_account_entitlements (
    calculation_run_id TEXT NOT NULL,
    event_uid TEXT NOT NULL,
    account_key TEXT NOT NULL,
    eligible_as_of TIMESTAMPTZ,
    entitlement_basis TEXT NOT NULL,
    eligible_quantity DECIMAL(38, 12),
    exact_entitlement DECIMAL(38, 12),
    whole_entitlement DECIMAL(38, 12),
    fractional_entitlement DECIMAL(38, 12),
    status TEXT NOT NULL,
    PRIMARY KEY (calculation_run_id, event_uid, account_key)
);

CREATE TABLE IF NOT EXISTS ledger_postings (
    posting_uid TEXT PRIMARY KEY,
    calculation_run_id TEXT NOT NULL,
    event_uid TEXT,
    account_key TEXT NOT NULL,
    posting_date DATE NOT NULL,
    book TEXT NOT NULL,
    posting_type TEXT NOT NULL,
    instrument_id TEXT,
    quantity_delta DECIMAL(38, 12),
    cash_delta DECIMAL(38, 12),
    receivable_delta DECIMAL(38, 12),
    tds_receivable_delta DECIMAL(38, 12),
    tax_basis_delta DECIMAL(38, 12),
    performance_basis_delta DECIMAL(38, 12),
    parent_lot_uid TEXT,
    child_lot_uid TEXT,
    tax_holding_start_date DATE,
    fifo_entry_date DATE,
    fifo_sequence BIGINT,
    metadata_json JSON
);

CREATE TABLE IF NOT EXISTS cash_flow_events (
    flow_uid TEXT PRIMARY KEY,
    portfolio_id TEXT NOT NULL,
    account_key TEXT,
    effective_at TIMESTAMPTZ,
    effective_date DATE NOT NULL,
    source_event_uid TEXT,
    flow_type TEXT NOT NULL,
    gross_amount DECIMAL(38, 12),
    tax_withheld DECIMAL(38, 12),
    net_amount DECIMAL(38, 12) NOT NULL,
    amount_to_account_scope DECIMAL(38, 12),
    amount_to_securities_scope DECIMAL(38, 12),
    timing_quality TEXT NOT NULL DEFAULT 'DATE_ONLY',
    is_estimated BOOLEAN NOT NULL DEFAULT false,
    source_evidence_uid TEXT
);

CREATE TABLE IF NOT EXISTS price_history (
    instrument_id TEXT NOT NULL,
    price_date DATE NOT NULL,
    exchange TEXT,
    open DECIMAL(38, 12),
    high DECIMAL(38, 12),
    low DECIMAL(38, 12),
    close DECIMAL(38, 12),
    volume DECIMAL(38, 12),
    price_status TEXT NOT NULL DEFAULT 'OBSERVED',
    source_evidence_uid TEXT,
    PRIMARY KEY (instrument_id, price_date)
);

CREATE TABLE IF NOT EXISTS position_daily (
    portfolio_id TEXT NOT NULL,
    account_key TEXT NOT NULL,
    valuation_date DATE NOT NULL,
    instrument_id TEXT NOT NULL,
    quantity_bod DECIMAL(38, 12),
    quantity_eod DECIMAL(38, 12),
    settled_quantity_eod DECIMAL(38, 12),
    raw_close DECIMAL(38, 12),
    price_date DATE,
    price_status TEXT,
    market_value DECIMAL(38, 12),
    economic_cost_basis DECIMAL(38, 12),
    tax_cost_basis DECIMAL(38, 12),
    realised_pnl_day DECIMAL(38, 12),
    dividend_receivable DECIMAL(38, 12),
    dividend_cash_day DECIMAL(38, 12),
    fees_day DECIMAL(38, 12),
    valuation_status TEXT NOT NULL,
    calculation_run_id TEXT NOT NULL,
    PRIMARY KEY (portfolio_id, account_key, valuation_date, instrument_id, calculation_run_id)
);

CREATE TABLE IF NOT EXISTS portfolio_daily (
    portfolio_id TEXT NOT NULL,
    valuation_date DATE NOT NULL,
    performance_scope TEXT NOT NULL,
    securities_market_value DECIMAL(38, 12),
    cash_balance DECIMAL(38, 12),
    receivables_value DECIMAL(38, 12),
    total_value DECIMAL(38, 12),
    contribution_day DECIMAL(38, 12),
    withdrawal_day DECIMAL(38, 12),
    net_external_flow_day DECIMAL(38, 12),
    cumulative_contributions DECIMAL(38, 12),
    cumulative_withdrawals DECIMAL(38, 12),
    cumulative_net_investment DECIMAL(38, 12),
    cumulative_gross_purchases DECIMAL(38, 12),
    open_cost_basis DECIMAL(38, 12),
    realised_pnl_day DECIMAL(38, 12),
    cumulative_realised_pnl DECIMAL(38, 12),
    unrealised_pnl DECIMAL(38, 12),
    income_day DECIMAL(38, 12),
    cumulative_income DECIMAL(38, 12),
    fees_day DECIMAL(38, 12),
    cumulative_fees DECIMAL(38, 12),
    rupee_gain_day DECIMAL(38, 12),
    total_gain DECIMAL(38, 12),
    daily_return DECIMAL(38, 12),
    twr_index DECIMAL(38, 12),
    drawdown DECIMAL(38, 12),
    held_position_count BIGINT,
    missing_price_count BIGINT,
    carried_price_count BIGINT,
    valuation_status TEXT NOT NULL,
    calculation_run_id TEXT NOT NULL,
    PRIMARY KEY (portfolio_id, valuation_date, performance_scope, calculation_run_id)
);

CREATE TABLE IF NOT EXISTS benchmark_performance_daily (
    portfolio_id TEXT NOT NULL,
    valuation_date DATE NOT NULL,
    performance_scope TEXT NOT NULL,
    benchmark_id TEXT NOT NULL,
    benchmark_level DECIMAL(38, 12),
    portfolio_normalized_index DECIMAL(38, 12),
    benchmark_normalized_index DECIMAL(38, 12),
    cashflow_matched_units DECIMAL(38, 12),
    cashflow_matched_value DECIMAL(38, 12),
    coverage_status TEXT NOT NULL,
    calculation_run_id TEXT NOT NULL,
    PRIMARY KEY (portfolio_id, valuation_date, performance_scope, benchmark_id, calculation_run_id)
);
