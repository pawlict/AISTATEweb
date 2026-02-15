-- AISTATEweb Database Schema (SQLite)
-- Version: 1.0.0
-- Supports: project management, AML analysis, counterparty memory, audit

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ============================================================
-- USERS & AUTH (multi-user ready, single-user by default)
-- ============================================================

CREATE TABLE IF NOT EXISTS users (
    id          TEXT PRIMARY KEY,
    username    TEXT UNIQUE NOT NULL,
    password_hash TEXT,          -- NULL for single-user mode (no auth)
    role        TEXT DEFAULT '',  -- user role (Transkryptor, Lingwista, etc.) or empty for admin-only users
    display_name TEXT NOT NULL DEFAULT '',
    email       TEXT DEFAULT '',
    is_active   INTEGER NOT NULL DEFAULT 1,
    settings    TEXT DEFAULT '{}',  -- JSON: per-user preferences
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- ============================================================
-- SYSTEM CONFIG (replaces flat settings.json for system-level)
-- ============================================================

CREATE TABLE IF NOT EXISTS system_config (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- ============================================================
-- PROJECTS & CASES
-- ============================================================

CREATE TABLE IF NOT EXISTS projects (
    id          TEXT PRIMARY KEY,
    owner_id    TEXT NOT NULL REFERENCES users(id),
    name        TEXT NOT NULL,
    description TEXT DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'active',  -- active | archived | deleted
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_projects_owner ON projects(owner_id);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);

CREATE TABLE IF NOT EXISTS cases (
    id          TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    case_type   TEXT NOT NULL,  -- transcription | diarization | analysis
                                -- translation | finance | aml
    status      TEXT NOT NULL DEFAULT 'open',  -- open | in_progress | closed | archived
    data_dir    TEXT NOT NULL DEFAULT '',       -- relative path to files on disk
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    metadata    TEXT DEFAULT '{}'  -- JSON: type-specific data (legacy project.json fields)
);

CREATE INDEX IF NOT EXISTS idx_cases_project ON cases(project_id);
CREATE INDEX IF NOT EXISTS idx_cases_type ON cases(case_type);
CREATE INDEX IF NOT EXISTS idx_cases_status ON cases(status);

CREATE TABLE IF NOT EXISTS case_files (
    id          TEXT PRIMARY KEY,
    case_id     TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    file_type   TEXT NOT NULL,   -- source | result | report | attachment | audio | transcript
    file_name   TEXT NOT NULL,
    file_path   TEXT NOT NULL,   -- relative path within data_www/
    mime_type   TEXT DEFAULT '',
    size_bytes  INTEGER DEFAULT 0,
    checksum    TEXT DEFAULT '',  -- SHA-256 of file content
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_case_files_case ON case_files(case_id);
CREATE INDEX IF NOT EXISTS idx_case_files_type ON case_files(file_type);

-- ============================================================
-- BANK STATEMENTS
-- ============================================================

CREATE TABLE IF NOT EXISTS statements (
    id              TEXT PRIMARY KEY,
    case_id         TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    file_id         TEXT REFERENCES case_files(id),
    bank_id         TEXT NOT NULL DEFAULT '',     -- ing, pko, mbank, etc.
    bank_name       TEXT NOT NULL DEFAULT '',
    period_from     TEXT,   -- YYYY-MM-DD
    period_to       TEXT,
    opening_balance TEXT,   -- Decimal as string for precision
    closing_balance TEXT,
    available_balance TEXT,
    currency        TEXT DEFAULT 'PLN',
    account_number  TEXT DEFAULT '',
    account_holder  TEXT DEFAULT '',
    declared_credits_sum   TEXT,
    declared_credits_count INTEGER,
    declared_debits_sum    TEXT,
    declared_debits_count  INTEGER,
    previous_closing_balance TEXT,
    debt_limit      TEXT,
    overdue_commission TEXT,
    blocked_amount  TEXT,
    parse_method    TEXT DEFAULT '',     -- table | text | ocr
    ocr_used        INTEGER DEFAULT 0,
    ocr_confidence  REAL,
    parser_version  TEXT DEFAULT '',
    pdf_hash        TEXT DEFAULT '',     -- SHA-256 of source PDF
    warnings        TEXT DEFAULT '[]',   -- JSON array
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_statements_case ON statements(case_id);
CREATE INDEX IF NOT EXISTS idx_statements_bank ON statements(bank_id);
CREATE INDEX IF NOT EXISTS idx_statements_period ON statements(period_from, period_to);

-- ============================================================
-- NORMALIZED TRANSACTIONS
-- ============================================================

CREATE TABLE IF NOT EXISTS transactions (
    id                  TEXT PRIMARY KEY,
    statement_id        TEXT NOT NULL REFERENCES statements(id) ON DELETE CASCADE,
    counterparty_id     TEXT REFERENCES counterparties(id),
    booking_date        TEXT,           -- YYYY-MM-DD
    tx_date             TEXT,           -- YYYY-MM-DD (data waluty)
    amount              TEXT NOT NULL,  -- Decimal as string
    currency            TEXT DEFAULT 'PLN',
    direction           TEXT NOT NULL,  -- CREDIT | DEBIT
    balance_after       TEXT,           -- Decimal as string
    -- Classification
    channel             TEXT DEFAULT '', -- CARD | TRANSFER | BLIK_P2P | BLIK_MERCHANT | CASH | FEE | OTHER
    category            TEXT DEFAULT '', -- from rules engine
    subcategory         TEXT DEFAULT '',
    risk_tags           TEXT DEFAULT '[]',  -- JSON array
    risk_score          REAL DEFAULT 0,
    -- Raw data
    title               TEXT DEFAULT '',
    counterparty_raw    TEXT DEFAULT '',
    bank_category       TEXT DEFAULT '',    -- e.g. TR.KART, ST.ZLEC, P.BLIK
    raw_text            TEXT DEFAULT '',
    -- Rules traceability
    rule_explains       TEXT DEFAULT '[]',  -- JSON array: [{rule, pattern, category}]
    -- Dedup
    tx_hash             TEXT,               -- hash(date+amount+counterparty+title)
    -- Flags
    is_recurring        INTEGER DEFAULT 0,
    recurring_group     TEXT DEFAULT '',
    is_anomaly          INTEGER DEFAULT 0,
    anomaly_type        TEXT DEFAULT '',
    anomaly_score       REAL DEFAULT 0,
    anomaly_explain     TEXT DEFAULT '',
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_tx_statement ON transactions(statement_id);
CREATE INDEX IF NOT EXISTS idx_tx_counterparty ON transactions(counterparty_id);
CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(booking_date);
CREATE INDEX IF NOT EXISTS idx_tx_channel ON transactions(channel);
CREATE INDEX IF NOT EXISTS idx_tx_category ON transactions(category);
CREATE INDEX IF NOT EXISTS idx_tx_hash ON transactions(tx_hash);
CREATE INDEX IF NOT EXISTS idx_tx_anomaly ON transactions(is_anomaly) WHERE is_anomaly = 1;

-- ============================================================
-- COUNTERPARTY MEMORY (global, shared across all statements)
-- ============================================================

CREATE TABLE IF NOT EXISTS counterparties (
    id              TEXT PRIMARY KEY,
    canonical_name  TEXT NOT NULL,
    label           TEXT NOT NULL DEFAULT 'neutral',  -- neutral | whitelist | blacklist
    note            TEXT DEFAULT '',
    tags            TEXT DEFAULT '[]',   -- JSON array
    auto_category   TEXT DEFAULT '',     -- auto-detected category
    confidence      REAL DEFAULT 0.5,
    times_seen      INTEGER DEFAULT 0,
    total_amount    REAL DEFAULT 0,
    first_seen      TEXT,
    last_seen       TEXT,
    sources         TEXT DEFAULT '[]',   -- JSON array of bank_ids
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_cp_label ON counterparties(label);
CREATE INDEX IF NOT EXISTS idx_cp_name ON counterparties(canonical_name);

CREATE TABLE IF NOT EXISTS counterparty_aliases (
    id              TEXT PRIMARY KEY,
    counterparty_id TEXT NOT NULL REFERENCES counterparties(id) ON DELETE CASCADE,
    alias           TEXT NOT NULL,
    alias_normalized TEXT NOT NULL,  -- lowercase, trimmed
    source          TEXT DEFAULT '',  -- bank name or "manual"
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_alias_cp ON counterparty_aliases(counterparty_id);
CREATE INDEX IF NOT EXISTS idx_alias_norm ON counterparty_aliases(alias_normalized);

-- ============================================================
-- AML: RISK SCORES & ALERTS
-- ============================================================

CREATE TABLE IF NOT EXISTS risk_assessments (
    id              TEXT PRIMARY KEY,
    statement_id    TEXT NOT NULL REFERENCES statements(id) ON DELETE CASCADE,
    total_score     REAL NOT NULL DEFAULT 0,  -- 0-100
    score_breakdown TEXT DEFAULT '{}',         -- JSON: component scores
    risk_reasons    TEXT DEFAULT '[]',         -- JSON array of {reason, score_delta, evidence_tx_ids}
    rules_version   TEXT DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_risk_statement ON risk_assessments(statement_id);

-- ============================================================
-- AML: FLOW GRAPH (precomputed edges/nodes)
-- ============================================================

CREATE TABLE IF NOT EXISTS graph_nodes (
    id          TEXT PRIMARY KEY,
    case_id     TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    node_type   TEXT NOT NULL,  -- ACCOUNT | COUNTERPARTY | MERCHANT | CASH_NODE | PAYMENT_PROVIDER
    label       TEXT NOT NULL,
    entity_id   TEXT,           -- links to counterparties.id if applicable
    risk_level  TEXT DEFAULT 'none',  -- none | low | medium | high
    metadata    TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_gn_case ON graph_nodes(case_id);
CREATE INDEX IF NOT EXISTS idx_gn_type ON graph_nodes(node_type);

CREATE TABLE IF NOT EXISTS graph_edges (
    id          TEXT PRIMARY KEY,
    case_id     TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    source_id   TEXT NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
    target_id   TEXT NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
    edge_type   TEXT NOT NULL,  -- TRANSFER | CARD_PAYMENT | BLIK_P2P | BLIK_MERCHANT | CASH | REFUND | FEE
    tx_count    INTEGER DEFAULT 1,
    total_amount REAL DEFAULT 0,
    first_date  TEXT,
    last_date   TEXT,
    tx_ids      TEXT DEFAULT '[]',  -- JSON array of transaction ids
    metadata    TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_ge_case ON graph_edges(case_id);
CREATE INDEX IF NOT EXISTS idx_ge_source ON graph_edges(source_id);
CREATE INDEX IF NOT EXISTS idx_ge_target ON graph_edges(target_id);

-- ============================================================
-- BASELINE / ANOMALY DETECTION PROFILES
-- ============================================================

CREATE TABLE IF NOT EXISTS baselines (
    id              TEXT PRIMARY KEY,
    case_id         TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    period_month    TEXT NOT NULL,  -- YYYY-MM
    channel         TEXT DEFAULT '',
    category        TEXT DEFAULT '',
    -- Statistics
    tx_count        INTEGER DEFAULT 0,
    total_amount    REAL DEFAULT 0,
    median_amount   REAL DEFAULT 0,
    p95_amount      REAL DEFAULT 0,
    std_amount      REAL DEFAULT 0,
    -- Aggregates
    total_credit    REAL DEFAULT 0,
    total_debit     REAL DEFAULT 0,
    unique_counterparties INTEGER DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_bl_case ON baselines(case_id);
CREATE INDEX IF NOT EXISTS idx_bl_period ON baselines(period_month);

-- ============================================================
-- LEARNING QUEUE (uncategorized items for user review)
-- ============================================================

CREATE TABLE IF NOT EXISTS learning_queue (
    id              TEXT PRIMARY KEY,
    counterparty_id TEXT REFERENCES counterparties(id),
    suggested_name  TEXT NOT NULL,
    suggested_category TEXT DEFAULT '',
    tx_sample_ids   TEXT DEFAULT '[]',  -- JSON array
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | rejected | skipped
    user_decision   TEXT DEFAULT '',       -- final label set by user
    user_note       TEXT DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    resolved_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_lq_status ON learning_queue(status);

-- ============================================================
-- AUDIT LOG
-- ============================================================

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    user_id     TEXT REFERENCES users(id),
    case_id     TEXT REFERENCES cases(id),
    action      TEXT NOT NULL,  -- upload | parse | classify | score | report | memory_update | etc.
    details     TEXT DEFAULT '{}',  -- JSON: action-specific details
    ip_address  TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_case ON audit_log(case_id);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);

-- ============================================================
-- TRANSACTION CLASSIFICATIONS (user feedback for self-learning)
-- ============================================================

CREATE TABLE IF NOT EXISTS tx_classifications (
    id              TEXT PRIMARY KEY,
    tx_id           TEXT NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    statement_id    TEXT NOT NULL REFERENCES statements(id) ON DELETE CASCADE,
    classification  TEXT NOT NULL DEFAULT 'neutral',  -- neutral | legitimate | suspicious | monitoring
    note            TEXT DEFAULT '',
    created_by      TEXT DEFAULT '',    -- user id
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE(tx_id)  -- one classification per transaction
);

CREATE INDEX IF NOT EXISTS idx_txcl_statement ON tx_classifications(statement_id);
CREATE INDEX IF NOT EXISTS idx_txcl_class ON tx_classifications(classification);

-- ============================================================
-- ACCOUNT PROFILES (multi-account, anonymization)
-- ============================================================

CREATE TABLE IF NOT EXISTS account_profiles (
    id              TEXT PRIMARY KEY,
    account_number  TEXT NOT NULL DEFAULT '',     -- full IBAN (stored encrypted/hashed reference)
    account_hash    TEXT NOT NULL UNIQUE,         -- SHA-256 for matching without exposing
    account_type    TEXT NOT NULL DEFAULT 'private',  -- private | business
    bank_id         TEXT DEFAULT '',
    bank_name       TEXT DEFAULT '',
    owner_label     TEXT DEFAULT '',              -- anonymized: "Klient A", "Firma XYZ"
    display_name    TEXT DEFAULT '',              -- user-given friendly name
    is_anonymized   INTEGER NOT NULL DEFAULT 1,  -- 1=hide details, 0=show
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_ap_hash ON account_profiles(account_hash);
CREATE INDEX IF NOT EXISTS idx_ap_type ON account_profiles(account_type);

-- ============================================================
-- FIELD MAPPING RULES (header/format corrections per bank)
-- ============================================================

CREATE TABLE IF NOT EXISTS field_rules (
    id              TEXT PRIMARY KEY,
    bank_id         TEXT NOT NULL,
    rule_type       TEXT NOT NULL,      -- header_remap | column_shift | field_format
    source_field    TEXT NOT NULL,       -- original field name or position
    target_field    TEXT NOT NULL,       -- corrected field name or position
    condition_json  TEXT DEFAULT '{}',   -- JSON: optional match conditions
    priority        INTEGER DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1,
    note            TEXT DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_fr_bank ON field_rules(bank_id);
CREATE INDEX IF NOT EXISTS idx_fr_type ON field_rules(rule_type);

-- ============================================================
-- PARSE TEMPLATES (column mapping for bank statement formats)
-- ============================================================

CREATE TABLE IF NOT EXISTS parse_templates (
    id              TEXT PRIMARY KEY,
    bank_id         TEXT NOT NULL,
    bank_name       TEXT DEFAULT '',
    name            TEXT NOT NULL DEFAULT '',
    column_mapping  TEXT NOT NULL DEFAULT '{}',  -- JSON: {col_index: field_type}
    header_row      INTEGER DEFAULT 0,           -- which row is header
    data_start_row  INTEGER DEFAULT 1,           -- first data row
    sample_headers  TEXT DEFAULT '[]',            -- JSON: original header cells for matching
    is_default      INTEGER DEFAULT 0,           -- default template for this bank
    is_active       INTEGER NOT NULL DEFAULT 1,  -- soft-delete
    times_used      INTEGER DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_pt_bank ON parse_templates(bank_id);
CREATE INDEX IF NOT EXISTS idx_pt_default ON parse_templates(is_default) WHERE is_default = 1;

-- ============================================================
-- AUTH: EXTENDED USER FIELDS (multi-user auth system)
-- ============================================================
-- The existing 'users' table is extended with auth-specific columns.
-- ALTER TABLE IF NOT EXISTS is not supported in SQLite, so we add
-- columns only if they don't exist yet (handled in Python migration code).

-- ============================================================
-- AUTH: SESSIONS (replaces sessions.json)
-- ============================================================

CREATE TABLE IF NOT EXISTS auth_sessions (
    token       TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    expires_at  TEXT NOT NULL,
    ip          TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_auth_sess_user ON auth_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_sess_expires ON auth_sessions(expires_at);

-- ============================================================
-- AUTH: AUDIT LOG (replaces audit_log.json — separate from AML audit_log)
-- ============================================================

CREATE TABLE IF NOT EXISTS auth_audit_log (
    id          TEXT PRIMARY KEY,
    timestamp   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    event       TEXT NOT NULL,
    user_id     TEXT DEFAULT '',
    username    TEXT DEFAULT '',
    ip          TEXT DEFAULT '',
    detail      TEXT DEFAULT '',
    actor_id    TEXT DEFAULT '',
    actor_name  TEXT DEFAULT '',
    fingerprint TEXT DEFAULT ''   -- JSON string
);

CREATE INDEX IF NOT EXISTS idx_auth_audit_ts ON auth_audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_auth_audit_user ON auth_audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_audit_event ON auth_audit_log(event);

-- ============================================================
-- AUTH: DEPLOYMENT CONFIG (replaces deployment.json)
-- ============================================================

CREATE TABLE IF NOT EXISTS deployment_config (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- ============================================================
-- AUTH: MESSAGES / CALL CENTER (replaces messages.json)
-- ============================================================

CREATE TABLE IF NOT EXISTS auth_messages (
    message_id    TEXT PRIMARY KEY,
    author_id     TEXT DEFAULT '',
    author_name   TEXT DEFAULT '',
    subject       TEXT NOT NULL DEFAULT '',
    content       TEXT NOT NULL DEFAULT '',
    target_groups TEXT DEFAULT '[]',  -- JSON array of role names
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS auth_message_reads (
    message_id  TEXT NOT NULL REFERENCES auth_messages(message_id) ON DELETE CASCADE,
    user_id     TEXT NOT NULL,
    read_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    PRIMARY KEY (message_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_auth_msg_created ON auth_messages(created_at);

-- ============================================================
-- PROJECT WORKSPACES (replaces flat project list)
-- ============================================================

CREATE TABLE IF NOT EXISTS project_workspaces (
    id          TEXT PRIMARY KEY,
    owner_id    TEXT NOT NULL,
    name        TEXT NOT NULL,
    description TEXT DEFAULT '',
    color       TEXT DEFAULT '#4a6cf7',
    icon        TEXT DEFAULT 'folder',
    status      TEXT NOT NULL DEFAULT 'active',  -- active | archived | deleted
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_pw_owner ON project_workspaces(owner_id);
CREATE INDEX IF NOT EXISTS idx_pw_status ON project_workspaces(status);

-- ============================================================
-- SUBPROJECTS (children of workspaces)
-- ============================================================

CREATE TABLE IF NOT EXISTS subprojects (
    id              TEXT PRIMARY KEY,
    workspace_id    TEXT NOT NULL REFERENCES project_workspaces(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    subproject_type TEXT NOT NULL DEFAULT 'analysis',
                    -- transcription | diarization | analysis | translation | chat | finance
    status          TEXT NOT NULL DEFAULT 'open',  -- open | in_progress | done | archived
    data_dir        TEXT DEFAULT '',   -- relative path to files on disk (projects/<legacy_id>)
    audio_file      TEXT DEFAULT '',
    metadata        TEXT DEFAULT '{}', -- JSON: type-specific data (legacy project.json fields)
    position        INTEGER DEFAULT 0, -- sort order within workspace
    created_by      TEXT DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_sp_workspace ON subprojects(workspace_id);
CREATE INDEX IF NOT EXISTS idx_sp_type ON subprojects(subproject_type);
CREATE INDEX IF NOT EXISTS idx_sp_status ON subprojects(status);

-- ============================================================
-- SUBPROJECT LINKS (connections between subprojects)
-- ============================================================

CREATE TABLE IF NOT EXISTS subproject_links (
    id          TEXT PRIMARY KEY,
    source_id   TEXT NOT NULL REFERENCES subprojects(id) ON DELETE CASCADE,
    target_id   TEXT NOT NULL REFERENCES subprojects(id) ON DELETE CASCADE,
    link_type   TEXT DEFAULT 'related',  -- related | depends_on | feeds_into
    note        TEXT DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE(source_id, target_id)
);

CREATE INDEX IF NOT EXISTS idx_sl_source ON subproject_links(source_id);
CREATE INDEX IF NOT EXISTS idx_sl_target ON subproject_links(target_id);

-- ============================================================
-- PROJECT MEMBERS (workspace collaboration)
-- ============================================================

CREATE TABLE IF NOT EXISTS project_members (
    workspace_id TEXT NOT NULL REFERENCES project_workspaces(id) ON DELETE CASCADE,
    user_id      TEXT NOT NULL,
    role         TEXT NOT NULL DEFAULT 'viewer', -- owner | manager | editor | commenter | viewer
    invited_by   TEXT DEFAULT '',
    invited_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    accepted_at  TEXT,
    status       TEXT NOT NULL DEFAULT 'accepted', -- accepted | removed
    PRIMARY KEY (workspace_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_pm_user ON project_members(user_id);
CREATE INDEX IF NOT EXISTS idx_pm_workspace ON project_members(workspace_id);

-- ============================================================
-- PROJECT INVITATIONS (pending invites)
-- ============================================================

CREATE TABLE IF NOT EXISTS project_invitations (
    id              TEXT PRIMARY KEY,
    workspace_id    TEXT NOT NULL REFERENCES project_workspaces(id) ON DELETE CASCADE,
    inviter_id      TEXT NOT NULL,
    invitee_id      TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'viewer',
    message         TEXT DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'pending', -- pending | accepted | rejected | cancelled
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    responded_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_pi_invitee ON project_invitations(invitee_id);
CREATE INDEX IF NOT EXISTS idx_pi_workspace ON project_invitations(workspace_id);
CREATE INDEX IF NOT EXISTS idx_pi_status ON project_invitations(status);

-- ============================================================
-- PROJECT ACTIVITY LOG
-- ============================================================

CREATE TABLE IF NOT EXISTS project_activity (
    id              TEXT PRIMARY KEY,
    workspace_id    TEXT NOT NULL REFERENCES project_workspaces(id) ON DELETE CASCADE,
    subproject_id   TEXT REFERENCES subprojects(id) ON DELETE SET NULL,
    user_id         TEXT DEFAULT '',
    user_name       TEXT DEFAULT '',
    action          TEXT NOT NULL, -- created | updated | opened | archived | member_added | member_removed | subproject_created | subproject_deleted | linked
    detail          TEXT DEFAULT '{}', -- JSON
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_pa_workspace ON project_activity(workspace_id);
CREATE INDEX IF NOT EXISTS idx_pa_created ON project_activity(created_at);
