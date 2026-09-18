-- =============================================================================
-- MoMo SMS Analytics - Database Setup Script
-- =============================================================================
-- Course      : Database Design and Implementation (Week 2)
-- Author      : Clive Tanaka Mushipe <c.mushipe@alustudent.com>
-- Target      : MySQL 8.0+ (developed and tested on MySQL 9.7.1)
-- Engine      : InnoDB (required for FOREIGN KEY and transactional integrity)
-- Charset     : utf8mb4 (MoMo SMS bodies may contain non-ASCII characters)
--
-- Purpose     : Creates the complete schema for storing, categorising and
--               auditing MTN Mobile Money SMS transaction data extracted from
--               an XML export, then seeds it from the course dataset.
--
-- Run with    : mysql -u root -p < database/database_setup.sql
--
-- Contents    : 1. Database creation
--               2. DDL - table definitions with constraints and comments
--               3. Indexes for query performance
--               4. Triggers enforcing cross-row business rules
--               5. Views for privacy-safe reporting
--               6. Application users with least-privilege grants
--               7. DML - seed data
--               8. Verification output
--
-- NOTE        : This script is idempotent. It drops and recreates the database
--               so it can be re-run safely during development.
-- =============================================================================


-- =============================================================================
-- SECTION 1: DATABASE CREATION
-- =============================================================================

DROP DATABASE IF EXISTS momo_sms_db;

CREATE DATABASE momo_sms_db
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE momo_sms_db;


-- =============================================================================
-- SECTION 2: DDL - TABLE DEFINITIONS
-- =============================================================================
-- Tables are created parent-first so that FOREIGN KEY targets always exist.
-- Order: users -> transaction_categories -> tags -> transactions
--        -> transaction_participants -> transaction_tags -> system_logs
-- =============================================================================


-- -----------------------------------------------------------------------------
-- TABLE: users
-- -----------------------------------------------------------------------------
-- Every party that can appear in a MoMo transaction.
--
-- KEY DESIGN DECISION - why party_ref exists and phone_number is nullable:
--
--   Not every counterparty in the source data is a phone subscriber. The course
--   dataset contains receivers such as 'MTN:MoMoPay:Kigali_Mart' (a merchant
--   till) and 'MTN:Airtime' (a service endpoint), neither of which has an
--   MSISDN at all. Subscriber numbers that ARE present arrive in the local
--   '07XXXXXXXX' form rather than E.164.
--
--   A users table keyed on a mandatory, strictly-formatted phone number could
--   not store a single row of that dataset. So the natural key is party_ref -
--   always present, always unique, holding either the normalised MSISDN or the
--   service code. phone_number becomes a nullable attribute that must still be
--   valid E.164 WHEN PRESENT, which keeps the accuracy guarantee without making
--   half the data unstorable.
-- -----------------------------------------------------------------------------
CREATE TABLE users (
    user_id         INT UNSIGNED    NOT NULL AUTO_INCREMENT
                                    COMMENT 'Surrogate primary key. Internal only, never exposed in the SMS text.',

    party_ref       VARCHAR(64)     NOT NULL
                                    COMMENT 'Canonical identifier and natural key. Either a normalised E.164 MSISDN ("+250788123456") or a service code ("MTN:MoMoPay:Kigali_Mart"). Always present.',

    phone_number    VARCHAR(16)     DEFAULT NULL
                                    COMMENT 'E.164 MSISDN when this party is a phone subscriber. NULL for merchant tills and service endpoints, which have no number.',

    full_name       VARCHAR(120)    DEFAULT NULL
                                    COMMENT 'Display name as it appears in the SMS body. NULL when the source never names the party.',

    user_type       ENUM('customer','merchant','agent','bank','system')
                                    NOT NULL DEFAULT 'customer'
                                    COMMENT 'Party classification. Drives how the counterparty is displayed in the dashboard.',

    is_verified     BOOLEAN         NOT NULL DEFAULT FALSE
                                    COMMENT 'Whether the wallet has completed KYC verification.',

    national_id     VARCHAR(32)     DEFAULT NULL
                                    COMMENT 'Optional KYC reference. NULL for counterparties we only know from an SMS. Never exported to the dashboard.',

    account_status  ENUM('active','suspended','closed')
                                    NOT NULL DEFAULT 'active'
                                    COMMENT 'Lifecycle state of the MoMo wallet. Suspended/closed wallets are excluded from active-user analytics.',

    first_seen_at   DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                    COMMENT 'Timestamp of the earliest SMS in which this party appeared. Used for cohort analysis.',

    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                    COMMENT 'Row insertion time (audit).',

    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                    ON UPDATE CURRENT_TIMESTAMP
                                    COMMENT 'Row last-modified time (audit).',

    PRIMARY KEY (user_id),

    -- ACCURACY RULE 1: one row per party. This is what stops the ETL creating
    -- duplicate people when a name is spelled differently across messages.
    CONSTRAINT uq_users_party_ref UNIQUE (party_ref),

    -- ACCURACY RULE 2: a phone number identifies exactly one party.
    -- NULLs are exempt in MySQL, so many tills can coexist without numbers.
    CONSTRAINT uq_users_phone UNIQUE (phone_number),

    -- ACCURACY RULE 3: reject malformed MSISDNs - but only when one is given.
    -- Rwandan mobile numbers are +250 followed by 9 digits. Local 07... input
    -- is rewritten to this form by trg_users_normalise_input before the
    -- constraint is evaluated, so raw source data loads without preprocessing.
    CONSTRAINT chk_users_phone_format
        CHECK (phone_number IS NULL OR phone_number REGEXP '^\\+250[0-9]{9}$'),

    -- ACCURACY RULE 4: a party_ref must be substantive, not whitespace.
    CONSTRAINT chk_users_party_ref_not_blank
        CHECK (CHAR_LENGTH(TRIM(party_ref)) >= 3),

    -- ACCURACY RULE 5: a name, when given, must be more than whitespace.
    CONSTRAINT chk_users_name_not_blank
        CHECK (full_name IS NULL OR CHAR_LENGTH(TRIM(full_name)) >= 2)
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_unicode_ci
COMMENT = 'All parties observed in MoMo SMS messages: customers, merchants, agents, banks and service endpoints. Keyed on party_ref because not every party has a phone number.';


-- -----------------------------------------------------------------------------
-- TABLE: transaction_categories
-- -----------------------------------------------------------------------------
-- Lookup table for transaction types, seeded from CATEGORIES in etl/config.py
-- so the database and the Python pipeline cannot drift apart.
--
-- A lookup table is used rather than an ENUM on transactions because categories
-- carry their own attributes (direction, description) and MTN adds product
-- types without consulting our schema. An ENUM would need a migration; a row
-- does not.
-- -----------------------------------------------------------------------------
CREATE TABLE transaction_categories (
    category_id     SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT
                                    COMMENT 'Surrogate primary key.',

    category_code   VARCHAR(40)     NOT NULL
                                    COMMENT 'Machine-readable code used by the ETL, e.g. "INCOMING_TRANSFER". Matches CATEGORIES in etl/config.py.',

    category_name   VARCHAR(80)     NOT NULL
                                    COMMENT 'Human-readable label shown on the dashboard, e.g. "Incoming Money Transfer".',

    direction       ENUM('credit','debit','neutral')
                                    NOT NULL
                                    COMMENT 'Effect on the wallet balance: credit increases it, debit decreases it, neutral for reversals and informational messages.',

    description     VARCHAR(255)    NOT NULL
                                    COMMENT 'Plain-English definition of the category, used as dashboard tooltip text and in the data dictionary.',

    is_active       BOOLEAN         NOT NULL DEFAULT TRUE
                                    COMMENT 'Soft-delete flag. Retired categories stay for historical rows but are hidden from new classification.',

    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                    COMMENT 'Row insertion time (audit).',

    PRIMARY KEY (category_id),

    -- ACCURACY RULE 6: code and name are both unique, so the ETL can look a
    -- category up by either one.
    CONSTRAINT uq_categories_code UNIQUE (category_code),
    CONSTRAINT uq_categories_name UNIQUE (category_name),

    CONSTRAINT chk_categories_code_format
        CHECK (category_code REGEXP '^[A-Z][A-Z0-9_]{2,39}$')
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_unicode_ci
COMMENT = 'Lookup of MoMo transaction types with their effect on the wallet balance.';


-- -----------------------------------------------------------------------------
-- TABLE: tags
-- -----------------------------------------------------------------------------
-- Free-form labels attachable to any transaction: analytics buckets
-- ("high_value"), data-quality flags ("needs_review"), spending themes
-- ("groceries"). A transaction may carry many tags and a tag applies to many
-- transactions - the M:N relationship resolved by transaction_tags below.
-- -----------------------------------------------------------------------------
CREATE TABLE tags (
    tag_id          SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT
                                    COMMENT 'Surrogate primary key.',

    tag_name        VARCHAR(50)     NOT NULL
                                    COMMENT 'Lowercase snake_case label, e.g. "high_value". Unique across the system.',

    tag_type        ENUM('analytics','data_quality','user_defined')
                                    NOT NULL DEFAULT 'analytics'
                                    COMMENT 'Origin of the tag: derived by analytics rules, raised by data-quality checks, or added manually.',

    description     VARCHAR(255)    DEFAULT NULL
                                    COMMENT 'What the tag means and when it is applied.',

    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                    COMMENT 'Row insertion time (audit).',

    PRIMARY KEY (tag_id),
    CONSTRAINT uq_tags_name UNIQUE (tag_name),
    CONSTRAINT chk_tags_name_format
        CHECK (tag_name REGEXP '^[a-z][a-z0-9_]{1,49}$')
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_unicode_ci
COMMENT = 'Reusable labels attached to transactions for analytics and data-quality triage.';


-- -----------------------------------------------------------------------------
-- TABLE: transactions
-- -----------------------------------------------------------------------------
-- The central fact table: one row per MoMo SMS that represents a financial
-- event. Deliberately holds no sender/receiver columns - participants are
-- modelled in transaction_participants so that messages with one, two or (in
-- future) more parties all fit the same structure.
-- -----------------------------------------------------------------------------
CREATE TABLE transactions (
    transaction_id      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT
                                    COMMENT 'Surrogate primary key. BIGINT because SMS volume grows without bound.',

    external_txn_ref    VARCHAR(40) NOT NULL
                                    COMMENT 'MTN transaction ID parsed from the SMS body (e.g. "TXN001"). Unique per transaction.',

    category_id         SMALLINT UNSIGNED NOT NULL
                                    COMMENT 'FK -> transaction_categories.category_id. Assigned by etl/categorize.py.',

    amount              DECIMAL(15,2) NOT NULL
                                    COMMENT 'Principal amount in RWF. DECIMAL (not FLOAT) so currency arithmetic is exact.',

    fee                 DECIMAL(15,2) NOT NULL DEFAULT 0.00
                                    COMMENT 'Transaction fee charged by MTN, in RWF. Zero when the message reports no fee.',

    balance_after       DECIMAL(15,2) DEFAULT NULL
                                    COMMENT 'Wallet balance after the transaction, when the SMS reports it. NULL if absent from the message.',

    currency            CHAR(3)     NOT NULL DEFAULT 'RWF'
                                    COMMENT 'ISO-4217 currency code. Constant RWF today; present so the schema survives multi-country expansion.',

    transaction_date    DATETIME    NOT NULL
                                    COMMENT 'When the transaction occurred, parsed from the SMS. Primary time axis for all reporting.',

    status              ENUM('pending','completed','failed','reversed')
                                    NOT NULL DEFAULT 'completed'
                                    COMMENT 'Settlement state. Most parsed SMS messages report a completed transaction.',

    channel             ENUM('sms','ussd','app','api')
                                    NOT NULL DEFAULT 'sms'
                                    COMMENT 'How the transaction reached us. Always "sms" for the XML export pipeline.',

    raw_sms_body        TEXT        NOT NULL
                                    COMMENT 'Verbatim SMS text. Retained for auditability, re-parsing after ETL fixes, and FULLTEXT search.',

    sms_hash            CHAR(64)    NOT NULL
                                    COMMENT 'SHA-256 of the raw SMS body. UNIQUE - this is what makes the ETL idempotent on re-runs.',

    notes               VARCHAR(500) DEFAULT NULL
                                    COMMENT 'Free-text annotation added by an analyst during review. Never written by the ETL.',

    processed_at        DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP
                                    COMMENT 'When the ETL wrote this row.',

    created_at          DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP
                                    COMMENT 'Row insertion time (audit).',

    updated_at          DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP
                                    ON UPDATE CURRENT_TIMESTAMP
                                    COMMENT 'Row last-modified time (audit).',

    PRIMARY KEY (transaction_id),

    -- SECURITY/ACCURACY RULE 7: re-running the ETL on the same XML export
    -- cannot create duplicate financial records. The hash of the SMS body is
    -- the deduplication key.
    CONSTRAINT uq_transactions_sms_hash UNIQUE (sms_hash),

    -- ACCURACY RULE 8: MTN transaction references are unique.
    CONSTRAINT uq_transactions_external_ref UNIQUE (external_txn_ref),

    -- ACCURACY RULE 9: money cannot be zero or negative. A parser bug that
    -- produced 0 or -500 is rejected rather than silently stored.
    CONSTRAINT chk_transactions_amount_positive
        CHECK (amount > 0),

    -- ACCURACY RULE 10: fees are never negative.
    CONSTRAINT chk_transactions_fee_non_negative
        CHECK (fee >= 0),

    -- ACCURACY RULE 11: a balance, when present, cannot be negative.
    CONSTRAINT chk_transactions_balance_non_negative
        CHECK (balance_after IS NULL OR balance_after >= 0),

    -- ACCURACY RULE 12: currency must be a 3-letter uppercase ISO code.
    CONSTRAINT chk_transactions_currency_format
        CHECK (currency REGEXP '^[A-Z]{3}$'),

    -- ACCURACY RULE 13: the hash must be a full 64-char lowercase SHA-256.
    CONSTRAINT chk_transactions_hash_format
        CHECK (sms_hash REGEXP '^[0-9a-f]{64}$'),

    -- REFERENTIAL INTEGRITY: a transaction must always have a valid category.
    -- ON DELETE RESTRICT deliberately blocks deleting a category still in use,
    -- so historical transactions can never be orphaned.
    CONSTRAINT fk_transactions_category
        FOREIGN KEY (category_id)
        REFERENCES transaction_categories (category_id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_unicode_ci
COMMENT = 'Central fact table - one row per financial MoMo SMS, deduplicated by SHA-256 of the message body.';


-- -----------------------------------------------------------------------------
-- TABLE: transaction_participants   [ JUNCTION - resolves Users M:N Transactions ]
-- -----------------------------------------------------------------------------
-- A user takes part in many transactions; a transaction involves many users
-- (a sender and a receiver). That is a genuine many-to-many relationship, and
-- this table is its resolution.
--
-- Why not sender_id / receiver_id columns on transactions?
--   * Airtime purchases and bank deposits have no human counterparty, so one
--     of the two columns would always be NULL.
--   * "Show me everything user X did" would need a UNION of two queries and
--     could not use a single index.
--   * Adding a third role later (agent, biller) would require a migration.
-- The junction removes all three problems and keeps the model in 3NF.
-- -----------------------------------------------------------------------------
CREATE TABLE transaction_participants (
    participation_id    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT
                                    COMMENT 'Surrogate primary key for the junction row.',

    transaction_id      BIGINT UNSIGNED NOT NULL
                                    COMMENT 'FK -> transactions.transaction_id.',

    user_id             INT UNSIGNED NOT NULL
                                    COMMENT 'FK -> users.user_id.',

    role                ENUM('sender','receiver')
                                    NOT NULL
                                    COMMENT 'Side of the transaction this user is on. Extensible to agent/biller later.',

    party_label         VARCHAR(120) DEFAULT NULL
                                    COMMENT 'Identifier exactly as it appeared in this SMS, kept even if the canonical users row is later corrected.',

    created_at          DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP
                                    COMMENT 'Row insertion time (audit).',

    PRIMARY KEY (participation_id),

    -- ACCURACY RULE 14: a transaction has at most one sender and at most one
    -- receiver. This is what stops a parser bug attaching three senders.
    CONSTRAINT uq_participants_txn_role UNIQUE (transaction_id, role),

    -- ACCURACY RULE 15: the same user cannot be listed twice on one transaction.
    CONSTRAINT uq_participants_txn_user UNIQUE (transaction_id, user_id),

    -- REFERENTIAL INTEGRITY: deleting a transaction removes its participation
    -- rows (they have no meaning alone), but a user who has transacted cannot
    -- be deleted - their financial history must be preserved.
    CONSTRAINT fk_participants_transaction
        FOREIGN KEY (transaction_id)
        REFERENCES transactions (transaction_id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,

    CONSTRAINT fk_participants_user
        FOREIGN KEY (user_id)
        REFERENCES users (user_id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_unicode_ci
COMMENT = 'JUNCTION TABLE resolving the M:N relationship between users and transactions, qualified by role (sender/receiver).';


-- -----------------------------------------------------------------------------
-- TABLE: transaction_tags   [ JUNCTION - resolves Transactions M:N Tags ]
-- -----------------------------------------------------------------------------
-- Second many-to-many relationship: one transaction can carry several tags and
-- one tag is applied to many transactions. Uses a composite primary key rather
-- than a surrogate, because (transaction_id, tag_id) is already unique and
-- minimal - a transaction cannot carry the same tag twice.
-- -----------------------------------------------------------------------------
CREATE TABLE transaction_tags (
    transaction_id  BIGINT UNSIGNED NOT NULL
                                    COMMENT 'FK -> transactions.transaction_id. Part of the composite PK.',

    tag_id          SMALLINT UNSIGNED NOT NULL
                                    COMMENT 'FK -> tags.tag_id. Part of the composite PK.',

    confidence      DECIMAL(3,2)    NOT NULL DEFAULT 1.00
                                    COMMENT 'How certain the tagging rule is, 0.00-1.00. An attribute of the RELATIONSHIP, not of either entity. Manual tags are 1.00; heuristics may be lower.',

    tagged_by       ENUM('etl','analyst','rule_engine')
                                    NOT NULL DEFAULT 'etl'
                                    COMMENT 'What applied the tag, for provenance.',

    tagged_at       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                    COMMENT 'When the tag was applied.',

    -- Composite primary key: the pair is the identity of the row.
    PRIMARY KEY (transaction_id, tag_id),

    -- ACCURACY RULE 16: confidence is a probability, so it must sit in [0,1].
    CONSTRAINT chk_tags_confidence_range
        CHECK (confidence >= 0.00 AND confidence <= 1.00),

    CONSTRAINT fk_txn_tags_transaction
        FOREIGN KEY (transaction_id)
        REFERENCES transactions (transaction_id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,

    CONSTRAINT fk_txn_tags_tag
        FOREIGN KEY (tag_id)
        REFERENCES tags (tag_id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_unicode_ci
COMMENT = 'JUNCTION TABLE resolving the M:N relationship between transactions and tags, with tagging provenance.';


-- -----------------------------------------------------------------------------
-- TABLE: system_logs
-- -----------------------------------------------------------------------------
-- Operational audit trail for the ETL pipeline. Records every stage outcome,
-- every rejected message, and (via the audit trigger below) every change made
-- to a stored transaction amount.
--
-- transaction_id is NULLABLE on purpose. A message that fails during parsing
-- never becomes a transaction, but the failure must still be logged - that is
-- precisely the record an engineer needs to debug the parser.
-- -----------------------------------------------------------------------------
CREATE TABLE system_logs (
    log_id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT
                                    COMMENT 'Surrogate primary key.',

    transaction_id  BIGINT UNSIGNED DEFAULT NULL
                                    COMMENT 'FK -> transactions.transaction_id. NULL when the message never became a transaction (e.g. a parse failure).',

    stage           ENUM('parse','clean','categorize','load','export','audit')
                                    NOT NULL
                                    COMMENT 'Pipeline stage that emitted the entry. Mirrors the modules in etl/.',

    event_type      VARCHAR(80)     NOT NULL
                                    COMMENT 'Machine-readable event name, e.g. PARSE_SUCCESS, DB_INSERT_FAIL. Indexed, so it filters far better than the free-text message.',

    log_level       ENUM('DEBUG','INFO','WARNING','ERROR','CRITICAL')
                                    NOT NULL DEFAULT 'INFO'
                                    COMMENT 'Severity. ERROR and above drive the dead-letter queue and the triage query.',

    message         VARCHAR(500)    NOT NULL
                                    COMMENT 'Human-readable description of what happened.',

    source_file     VARCHAR(255)    DEFAULT NULL
                                    COMMENT 'Input file being processed, e.g. "data/raw/modified_sms_v2.xml".',

    record_ref      VARCHAR(100)    DEFAULT NULL
                                    COMMENT 'Pointer to the offending record (XML index or transaction reference) for dead-letter replay.',

    records_affected INT UNSIGNED   NOT NULL DEFAULT 0
                                    COMMENT 'Row count touched by the stage. Used to report throughput per run.',

    ip_address      VARCHAR(45)     DEFAULT NULL
                                    COMMENT 'Host that performed the action. VARCHAR(45) so an IPv6 address fits as well as IPv4.',

    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                    COMMENT 'When the entry was written.',

    PRIMARY KEY (log_id),

    -- REFERENTIAL INTEGRITY: if a transaction is deleted we keep its log
    -- history but detach the pointer. Deleting a transaction must never
    -- destroy the audit trail that explains what happened to it.
    CONSTRAINT fk_logs_transaction
        FOREIGN KEY (transaction_id)
        REFERENCES transactions (transaction_id)
        ON DELETE SET NULL
        ON UPDATE CASCADE,

    CONSTRAINT chk_logs_message_not_blank
        CHECK (CHAR_LENGTH(TRIM(message)) > 0),

    CONSTRAINT chk_logs_event_type_format
        CHECK (event_type REGEXP '^[A-Z][A-Z0-9_]{2,79}$')
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_unicode_ci
COMMENT = 'ETL and audit trail. Records stage outcomes, rejected messages and amount changes.';


-- =============================================================================
-- SECTION 3: INDEXES
-- =============================================================================
-- Primary keys and UNIQUE constraints already create indexes, so only the
-- additional access paths are declared here. Each index below is justified by
-- a specific query in database/sample_queries.sql. An index that serves no
-- query is pure write overhead.
-- =============================================================================

-- Query 2 (monthly trend) and every date-range filter scan by date.
CREATE INDEX idx_txn_date
    ON transactions (transaction_date);

-- Composite, column order matters: filter by category first, then narrow by
-- date. Serves "payments in March" without touching the table.
--
-- Deliberately NOT accompanied by a separate single-column index on
-- category_id: a composite index already serves queries on its leftmost
-- prefix, so that index would be redundant storage that slows every INSERT for
-- no read benefit. Query 10 proves the optimiser picks this one.
CREATE INDEX idx_txn_cat_date
    ON transactions (category_id, transaction_date);

-- Dashboard filters the ledger by settlement state.
CREATE INDEX idx_txn_status
    ON transactions (status);

-- Query 6 ranks by value.
CREATE INDEX idx_txn_amount
    ON transactions (amount);

-- Query 3 walks the junction from the user side, filtered by role.
CREATE INDEX idx_participants_user_role
    ON transaction_participants (user_id, role);

-- Query 4: resolve all parties on a given transaction.
CREATE INDEX idx_participants_txn
    ON transaction_participants (transaction_id);

-- Users are looked up by name in the dashboard search box.
CREATE INDEX idx_users_name
    ON users (full_name);

-- Segment analytics by party type and status.
CREATE INDEX idx_users_type_status
    ON users (user_type, account_status);

-- Query 5 triages recent errors: filter by level, order by time.
CREATE INDEX idx_logs_level_created
    ON system_logs (log_level, created_at);

-- Filtering the audit trail by what happened rather than by severity.
CREATE INDEX idx_logs_event_type
    ON system_logs (event_type);

-- Follow the audit trail for one transaction.
CREATE INDEX idx_logs_transaction
    ON system_logs (transaction_id);

-- Reverse lookup on the tag junction (the PK covers transaction_id -> tag_id).
CREATE INDEX idx_txn_tags_tag
    ON transaction_tags (tag_id);

-- Query 7: natural-language search across SMS bodies. InnoDB FULLTEXT avoids
-- the full table scan that LIKE '%...%' would force.
CREATE FULLTEXT INDEX ftx_txn_body
    ON transactions (raw_sms_body);


-- =============================================================================
-- SECTION 4: TRIGGERS - CROSS-ROW BUSINESS RULES
-- =============================================================================
-- CHECK constraints can only see the row being written and cannot call
-- non-deterministic functions such as NOW(). The rules below need one or the
-- other, so they are implemented as triggers.
-- =============================================================================

DELIMITER $$

-- -----------------------------------------------------------------------------
-- ACCURACY RULE 17: normalise party identifiers on the way in.
--
-- The source data carries local-format numbers ('0781234567'). Rewriting them
-- to E.164 here means the same subscriber cannot be stored twice under two
-- spellings, and it lets raw source values be inserted directly without
-- preprocessing.
--
-- BEFORE INSERT triggers run before CHECK constraints are evaluated in MySQL,
-- so the value the constraint sees is the normalised one.
-- -----------------------------------------------------------------------------
CREATE TRIGGER trg_users_normalise_input
BEFORE INSERT ON users
FOR EACH ROW
BEGIN
    SET NEW.party_ref = TRIM(NEW.party_ref);
    SET NEW.full_name = NULLIF(TRIM(COALESCE(NEW.full_name, '')), '');

    IF NEW.phone_number IS NOT NULL THEN
        SET NEW.phone_number = REPLACE(TRIM(NEW.phone_number), ' ', '');
        -- Local format 07XXXXXXXX -> E.164 +2507XXXXXXXX
        IF NEW.phone_number REGEXP '^0[0-9]{9}$' THEN
            SET NEW.phone_number = CONCAT('+250', SUBSTRING(NEW.phone_number, 2));
        END IF;
        -- Bare 2507XXXXXXXX (no plus) -> +2507XXXXXXXX
        IF NEW.phone_number REGEXP '^250[0-9]{9}$' THEN
            SET NEW.phone_number = CONCAT('+', NEW.phone_number);
        END IF;
    END IF;

    -- Keep party_ref in step when it is itself a phone number.
    IF NEW.party_ref REGEXP '^0[0-9]{9}$' THEN
        SET NEW.party_ref = CONCAT('+250', SUBSTRING(NEW.party_ref, 2));
    END IF;
END$$

-- -----------------------------------------------------------------------------
-- SECURITY RULE 18: no future-dated transactions.
-- A transaction cannot have happened tomorrow. This catches timezone bugs and
-- malformed dates in the XML, and is the kind of tampering a forward-dated
-- entry would need. NOW() is non-deterministic, so this cannot be a CHECK.
-- -----------------------------------------------------------------------------
CREATE TRIGGER trg_transactions_no_future_date
BEFORE INSERT ON transactions
FOR EACH ROW
BEGIN
    IF NEW.transaction_date > NOW() THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'SECURITY RULE VIOLATION: transaction_date cannot be in the future.';
    END IF;
END$$

-- Same rule on UPDATE - a rule enforced only on INSERT is no rule at all.
CREATE TRIGGER trg_transactions_no_future_date_upd
BEFORE UPDATE ON transactions
FOR EACH ROW
BEGIN
    IF NEW.transaction_date > NOW() THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'SECURITY RULE VIOLATION: transaction_date cannot be in the future.';
    END IF;
END$$

-- -----------------------------------------------------------------------------
-- SECURITY RULE 19: a user cannot send money to themselves.
-- This spans two rows of transaction_participants, so no CHECK constraint can
-- express it. Self-transfers are a classic wash-trading pattern and also a
-- reliable signal of a mis-parsed message.
-- -----------------------------------------------------------------------------
CREATE TRIGGER trg_participants_no_self_transfer
BEFORE INSERT ON transaction_participants
FOR EACH ROW
BEGIN
    DECLARE v_conflicts INT DEFAULT 0;

    SELECT COUNT(*) INTO v_conflicts
    FROM transaction_participants
    WHERE transaction_id = NEW.transaction_id
      AND user_id        = NEW.user_id
      AND role          <> NEW.role;

    IF v_conflicts > 0 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'SECURITY RULE VIOLATION: the same user cannot be both sender and receiver on one transaction.';
    END IF;
END$$

-- -----------------------------------------------------------------------------
-- SECURITY RULE 20: immutable financial audit trail.
-- Any change to a stored amount or status writes an entry into system_logs
-- recording the old and new values, the account that made the change and the
-- host it came from. Nobody can quietly edit a financial figure - the database
-- records it whether they want it recorded or not.
-- -----------------------------------------------------------------------------
CREATE TRIGGER trg_transactions_audit_amount_change
AFTER UPDATE ON transactions
FOR EACH ROW
BEGIN
    IF OLD.amount <> NEW.amount THEN
        INSERT INTO system_logs (transaction_id, stage, event_type, log_level,
                                 message, record_ref, records_affected, ip_address)
        VALUES (NEW.transaction_id, 'audit', 'AMOUNT_CHANGED', 'WARNING',
                CONCAT('AUDIT: amount changed from ', OLD.amount, ' to ',
                       NEW.amount, ' by user ', CURRENT_USER()),
                NEW.external_txn_ref, 1,
                -- USER() is 'account@host'; take the host the change came from.
                SUBSTRING_INDEX(USER(), '@', -1));
    END IF;

    IF OLD.status <> NEW.status THEN
        INSERT INTO system_logs (transaction_id, stage, event_type, log_level,
                                 message, record_ref, records_affected)
        VALUES (NEW.transaction_id, 'audit', 'STATUS_CHANGED', 'INFO',
                CONCAT('AUDIT: status changed from ', OLD.status, ' to ',
                       NEW.status, ' by user ', CURRENT_USER()),
                NEW.external_txn_ref, 1);
    END IF;
END$$

DELIMITER ;


-- =============================================================================
-- SECTION 5: VIEWS
-- =============================================================================

-- -----------------------------------------------------------------------------
-- SECURITY RULE 21: phone-number masking.
-- Analysts and the dashboard read this view instead of the base tables. Full
-- MSISDNs are personally identifiable information; the view exposes only
-- "+250788****456". Denies by construction rather than by policy.
--
-- COALESCE matters here: a merchant till has no phone number, and CONCAT()
-- returns NULL if any argument is NULL. Without the fallback, every merchant
-- row would show an empty column instead of its party_ref.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_transaction_summary AS
SELECT
    t.transaction_id,
    t.external_txn_ref,
    c.category_name,
    c.direction,
    t.amount,
    t.fee,
    t.currency,
    t.transaction_date,
    t.status,
    snd.full_name AS sender_name,
    COALESCE(CONCAT(LEFT(snd.phone_number, 7), '****', RIGHT(snd.phone_number, 3)),
             snd.party_ref) AS sender_ref_masked,
    rcv.full_name AS receiver_name,
    COALESCE(CONCAT(LEFT(rcv.phone_number, 7), '****', RIGHT(rcv.phone_number, 3)),
             rcv.party_ref) AS receiver_ref_masked
FROM transactions t
    INNER JOIN transaction_categories c
        ON t.category_id = c.category_id
    LEFT JOIN transaction_participants ps
        ON ps.transaction_id = t.transaction_id AND ps.role = 'sender'
    LEFT JOIN users snd
        ON snd.user_id = ps.user_id
    LEFT JOIN transaction_participants pr
        ON pr.transaction_id = t.transaction_id AND pr.role = 'receiver'
    LEFT JOIN users rcv
        ON rcv.user_id = pr.user_id;


-- Per-category totals, used by the dashboard export step.
CREATE OR REPLACE VIEW v_category_totals AS
SELECT
    c.category_id,
    c.category_code,
    c.category_name,
    c.direction,
    COUNT(t.transaction_id)             AS transaction_count,
    COALESCE(SUM(t.amount), 0)          AS total_amount,
    COALESCE(SUM(t.fee), 0)             AS total_fees,
    COALESCE(ROUND(AVG(t.amount), 2), 0) AS average_amount,
    MIN(t.transaction_date)             AS first_transaction,
    MAX(t.transaction_date)             AS last_transaction
FROM transaction_categories c
    LEFT JOIN transactions t
        ON t.category_id = c.category_id
GROUP BY c.category_id, c.category_code, c.category_name, c.direction;


-- Daily volume split by direction - feeds the dashboard time-series chart.
CREATE OR REPLACE VIEW v_daily_summary AS
SELECT
    DATE(t.transaction_date)    AS txn_date,
    c.direction,
    COUNT(*)                    AS transaction_count,
    SUM(t.amount)               AS total_volume,
    SUM(t.fee)                  AS total_fees
FROM transactions t
    INNER JOIN transaction_categories c
        ON c.category_id = t.category_id
WHERE t.status = 'completed'
GROUP BY DATE(t.transaction_date), c.direction;


-- =============================================================================
-- SECTION 6: APPLICATION USERS - LEAST PRIVILEGE
-- =============================================================================
-- SECURITY RULE 22: the application never connects as root.
-- momo_app can read and write transaction data but cannot DROP tables, cannot
-- DELETE rows, and cannot touch any other database on the server. If the API
-- were ever compromised through SQL injection, the blast radius is bounded by
-- these grants.
--
-- SECURITY NOTE: the passwords below are development placeholders, committed
-- only so this script runs end to end as coursework. A real deployment reads
-- them from the environment (see .env.example) and never stores them in
-- version control.
-- =============================================================================

DROP USER IF EXISTS 'momo_app'@'localhost';
CREATE USER 'momo_app'@'localhost' IDENTIFIED BY 'ChangeMe_Str0ng!2026';

-- Read/write on data, but no DELETE and no DDL.
GRANT SELECT, INSERT, UPDATE ON momo_sms_db.* TO 'momo_app'@'localhost';

-- Read-only reporting account for the dashboard: sees only the masked views.
DROP USER IF EXISTS 'momo_readonly'@'localhost';
CREATE USER 'momo_readonly'@'localhost' IDENTIFIED BY 'ReadOnly_Str0ng!2026';
GRANT SELECT ON momo_sms_db.v_transaction_summary TO 'momo_readonly'@'localhost';
GRANT SELECT ON momo_sms_db.v_category_totals     TO 'momo_readonly'@'localhost';
GRANT SELECT ON momo_sms_db.v_daily_summary       TO 'momo_readonly'@'localhost';

FLUSH PRIVILEGES;


-- =============================================================================
-- SECTION 7: DML - SEED DATA
-- =============================================================================
-- The transaction rows below are derived from the course dataset at
-- data/raw/modified_sms_v2.xml (25 records). Their amounts, dates, phone
-- numbers, merchant codes and SMS bodies are the real values from that file.
--
-- A small number of SYNTHETIC rows are added on top, clearly marked, to cover
-- the five categories the sample does not exercise (CASH_IN, CASH_OUT,
-- BANK_DEPOSIT, UTILITY_PAYMENT, INTERNATIONAL_IN, REVERSAL) so that every
-- category and every constraint keeps test coverage.
--
-- Note how the party identifiers exercise the party_ref design: subscriber
-- numbers arrive as '07...' and are normalised to E.164 by the trigger, while
-- merchant tills ('MTN:MoMoPay:Kigali_Mart') and services ('MTN:Airtime') have
-- no phone number at all.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 7.1 transaction_categories  (10 rows - matches CATEGORIES in etl/config.py)
-- -----------------------------------------------------------------------------
INSERT INTO transaction_categories (category_code, category_name, direction, description) VALUES
('INCOMING_TRANSFER', 'Incoming Money Transfer',     'credit',  'Money received from another MoMo user.'),
('OUTGOING_TRANSFER', 'Outgoing Money Transfer',     'debit',   'Money sent to another MoMo user.'),
('PAYMENT_MERCHANT',  'Merchant Payment',            'debit',   'Payment to a registered MoMo merchant till or code holder.'),
('AIRTIME_PURCHASE',  'Airtime Top-Up',              'debit',   'Airtime or data bundle purchase through MoMo.'),
('BANK_DEPOSIT',      'Bank to MoMo Deposit',        'credit',  'Funds moved from a linked bank account into the MoMo wallet.'),
('CASH_IN',           'Cash In via Agent',           'credit',  'Cash deposited into the wallet through a MoMo agent.'),
('CASH_OUT',          'Cash Out via Agent',          'debit',   'Cash withdrawn from the wallet through a MoMo agent.'),
('UTILITY_PAYMENT',   'Utility Bill Payment',        'debit',   'Payment of electricity, water, internet or similar bills.'),
('INTERNATIONAL_IN',  'International Remittance In', 'credit',  'Money received from outside the country.'),
('REVERSAL',          'Transaction Reversal',        'neutral', 'A refund or reversal of a previous transaction.');

-- -----------------------------------------------------------------------------
-- 7.3 tags  (10 rows)
-- -----------------------------------------------------------------------------
INSERT INTO tags (tag_name, tag_type, description) VALUES
('high_value',      'analytics',    'Transaction amount at or above 20,000 RWF.'),
('recurring',       'analytics',    'Matches a repeating pattern for the same party.'),
('groceries',       'user_defined', 'Spending on food and household supplies.'),
('utilities',       'user_defined', 'Electricity, water, internet and similar bills.'),
('needs_review',    'data_quality', 'Parser confidence was low, or the value is unusual - a human should verify.'),
('missing_balance', 'data_quality', 'The source SMS did not report a balance after the transaction.'),
('fee_charged',     'analytics',    'MTN charged a non-zero fee on this transaction.'),
('cross_bank',      'analytics',    'Transaction involved a partner bank rather than a MoMo wallet.'),
('international',   'analytics',    'Transaction crossed a national border.'),
('merchant_till',   'analytics',    'Paid to a MoMoPay merchant till rather than a person.');

-- 7.2 users  (27 rows: 23 derived from the sample XML, 4 synthetic)
INSERT INTO users (party_ref, phone_number, full_name, user_type, is_verified, account_status) VALUES
    ('+250781234567', '+250781234567', 'Alice', 'customer', 1, 'active'),
    ('+250789876543', '+250789876543', 'Account Owner', 'customer', 1, 'active'),
    ('MTN:MoMoPay:Kigali_Mart', NULL, 'Kigali Mart', 'merchant', 0, 'active'),
    ('+250782345678', '+250782345678', 'Bob', 'customer', 1, 'active'),
    ('+250783456789', '+250783456789', 'Carol', 'customer', 1, 'active'),
    ('MTN:Airtime', NULL, 'MTN Airtime Service', 'system', 0, 'active'),
    ('MTN:MoMoPay:Pharmacy_Plus', NULL, 'Pharmacy Plus', 'merchant', 0, 'active'),
    ('+250784567890', '+250784567890', 'David', 'customer', 1, 'active'),
    ('+250785678901', '+250785678901', 'Eve', 'customer', 1, 'active'),
    ('MTN:MoMoPay:Supermarket_A', NULL, 'Supermarket A', 'merchant', 0, 'active'),
    ('+250786789012', '+250786789012', 'Frank', 'customer', 1, 'active'),
    ('+250787890123', '+250787890123', 'Grace', 'customer', 1, 'active'),
    ('MTN:MoMoPay:Restaurant_B', NULL, 'Restaurant B', 'merchant', 0, 'active'),
    ('+250788901234', '+250788901234', 'Henry', 'customer', 1, 'active'),
    ('+250781234560', '+250781234560', 'Irene', 'customer', 1, 'active'),
    ('MTN:MoMoPay:Electronics_Store', NULL, 'Electronics Store', 'merchant', 0, 'active'),
    ('+250782345670', '+250782345670', 'James', 'customer', 1, 'active'),
    ('MTN:MoMoPay:School_Fees', NULL, 'School Fees', 'merchant', 0, 'active'),
    ('+250783456780', '+250783456780', 'Kate', 'customer', 1, 'active'),
    ('+250784567891', '+250784567891', 'Leo', 'customer', 1, 'active'),
    ('MTN:MoMoPay:Bakery_C', NULL, 'Bakery C', 'merchant', 0, 'active'),
    ('+250785678902', '+250785678902', 'Mia', 'customer', 1, 'active'),
    ('MTN:MoMoPay:Gym_D', NULL, 'Gym D', 'merchant', 0, 'active'),
    ('+250788111934', '+250788111934', 'MoMo Agent Nyabugogo', 'agent', 1, 'active'),
    ('+250788222731', '+250788222731', 'Bank of Kigali', 'bank', 1, 'active'),
    ('MTN:Utility:CashPower', NULL, 'CASH POWER Utility', 'system', 0, 'active'),
    ('+250722660590', '+250722660590', 'Divine Ingabire', 'customer', 0, 'suspended');

-- 7.4 transactions  (32 rows: 25 from the sample XML, 7 synthetic)
INSERT INTO transactions
    (external_txn_ref, category_id, amount, fee, balance_after, currency,
     transaction_date, status, channel, raw_sms_body, sms_hash, notes)
VALUES
    ('TXN001', 1, 5000.00, 0.00, 15000.00, 'RWF', '2024-01-03 08:12:00', 'completed', 'sms',
     'You have received 5000 RWF from Alice (0781234567). Your new balance is 15000 RWF. TxnId: TXN001',
     SHA2('You have received 5000 RWF from Alice (0781234567). Your new balance is 15000 RWF. TxnId: TXN001', 256), NULL),
    ('TXN002', 3, 2000.00, 0.00, 13000.00, 'RWF', '2024-01-04 10:30:00', 'completed', 'sms',
     'Your payment of 2000 RWF to Kigali Mart was successful. TxnId: TXN002',
     SHA2('Your payment of 2000 RWF to Kigali Mart was successful. TxnId: TXN002', 256), NULL),
    ('TXN003', 2, 10000.00, 0.00, 3000.00, 'RWF', '2024-01-05 14:22:00', 'completed', 'sms',
     'You have transferred 10000 RWF to Bob (0782345678). TxnId: TXN003',
     SHA2('You have transferred 10000 RWF to Bob (0782345678). TxnId: TXN003', 256), NULL),
    ('TXN004', 1, 15000.00, 0.00, 18000.00, 'RWF', '2024-01-06 09:05:00', 'completed', 'sms',
     'You have received 15000 RWF from Carol (0783456789). TxnId: TXN004',
     SHA2('You have received 15000 RWF from Carol (0783456789). TxnId: TXN004', 256), NULL),
    ('TXN005', 4, 500.00, 0.00, 17500.00, 'RWF', '2024-01-07 11:00:00', 'completed', 'sms',
     'You have bought airtime worth 500 RWF. TxnId: TXN005',
     SHA2('You have bought airtime worth 500 RWF. TxnId: TXN005', 256), NULL),
    ('TXN006', 3, 3500.00, 0.00, 14000.00, 'RWF', '2024-01-08 16:45:00', 'completed', 'sms',
     'Your payment of 3500 RWF to Pharmacy Plus was successful. TxnId: TXN006',
     SHA2('Your payment of 3500 RWF to Pharmacy Plus was successful. TxnId: TXN006', 256), NULL),
    ('TXN007', 1, 20000.00, 0.00, 34000.00, 'RWF', '2024-01-09 08:30:00', 'completed', 'sms',
     'You have received 20000 RWF from David (0784567890). TxnId: TXN007',
     SHA2('You have received 20000 RWF from David (0784567890). TxnId: TXN007', 256), NULL),
    ('TXN008', 2, 7500.00, 0.00, 26500.00, 'RWF', '2024-01-10 13:15:00', 'completed', 'sms',
     'You have transferred 7500 RWF to Eve (0785678901). TxnId: TXN008',
     SHA2('You have transferred 7500 RWF to Eve (0785678901). TxnId: TXN008', 256), NULL),
    ('TXN009', 3, 1200.00, 0.00, 25300.00, 'RWF', '2024-01-11 17:00:00', 'completed', 'sms',
     'Your payment of 1200 RWF to Supermarket A was successful. TxnId: TXN009',
     SHA2('Your payment of 1200 RWF to Supermarket A was successful. TxnId: TXN009', 256), NULL),
    ('TXN010', 1, 8000.00, 0.00, 33300.00, 'RWF', '2024-01-12 09:45:00', 'completed', 'sms',
     'You have received 8000 RWF from Frank (0786789012). TxnId: TXN010',
     SHA2('You have received 8000 RWF from Frank (0786789012). TxnId: TXN010', 256), NULL),
    ('TXN011', 4, 1000.00, 0.00, 32300.00, 'RWF', '2024-01-13 12:00:00', 'completed', 'sms',
     'You have bought airtime worth 1000 RWF. TxnId: TXN011',
     SHA2('You have bought airtime worth 1000 RWF. TxnId: TXN011', 256), NULL),
    ('TXN012', 2, 25000.00, 0.00, 7300.00, 'RWF', '2024-01-14 15:30:00', 'completed', 'sms',
     'You have transferred 25000 RWF to Grace (0787890123). TxnId: TXN012',
     SHA2('You have transferred 25000 RWF to Grace (0787890123). TxnId: TXN012', 256), NULL),
    ('TXN013', 3, 4500.00, 0.00, 2800.00, 'RWF', '2024-01-15 19:00:00', 'completed', 'sms',
     'Your payment of 4500 RWF to Restaurant B was successful. TxnId: TXN013',
     SHA2('Your payment of 4500 RWF to Restaurant B was successful. TxnId: TXN013', 256), NULL),
    ('TXN014', 1, 30000.00, 0.00, 32800.00, 'RWF', '2024-01-16 10:15:00', 'completed', 'sms',
     'You have received 30000 RWF from Henry (0788901234). TxnId: TXN014',
     SHA2('You have received 30000 RWF from Henry (0788901234). TxnId: TXN014', 256), NULL),
    ('TXN015', 2, 5000.00, 0.00, 27800.00, 'RWF', '2024-01-17 14:00:00', 'completed', 'sms',
     'You have transferred 5000 RWF to Irene (0781234560). TxnId: TXN015',
     SHA2('You have transferred 5000 RWF to Irene (0781234560). TxnId: TXN015', 256), NULL),
    ('TXN016', 3, 6000.00, 0.00, 21800.00, 'RWF', '2024-01-18 11:30:00', 'completed', 'sms',
     'Your payment of 6000 RWF to Electronics Store was successful. TxnId: TXN016',
     SHA2('Your payment of 6000 RWF to Electronics Store was successful. TxnId: TXN016', 256), NULL),
    ('TXN017', 1, 12000.00, 0.00, 33800.00, 'RWF', '2024-01-19 08:00:00', 'completed', 'sms',
     'You have received 12000 RWF from James (0782345670). TxnId: TXN017',
     SHA2('You have received 12000 RWF from James (0782345670). TxnId: TXN017', 256), NULL),
    ('TXN018', 4, 2000.00, 0.00, 31800.00, 'RWF', '2024-01-20 13:45:00', 'completed', 'sms',
     'You have bought airtime worth 2000 RWF. TxnId: TXN018',
     SHA2('You have bought airtime worth 2000 RWF. TxnId: TXN018', 256), NULL),
    ('TXN019', 3, 9000.00, 0.00, 22800.00, 'RWF', '2024-01-21 09:30:00', 'completed', 'sms',
     'Your payment of 9000 RWF to School Fees was successful. TxnId: TXN019',
     SHA2('Your payment of 9000 RWF to School Fees was successful. TxnId: TXN019', 256), NULL),
    ('TXN020', 1, 50000.00, 0.00, 72800.00, 'RWF', '2024-01-22 16:00:00', 'completed', 'sms',
     'You have received 50000 RWF from Kate (0783456780). TxnId: TXN020',
     SHA2('You have received 50000 RWF from Kate (0783456780). TxnId: TXN020', 256), NULL),
    ('TXN021', 2, 3000.00, 0.00, 69800.00, 'RWF', '2024-01-23 10:00:00', 'completed', 'sms',
     'You have transferred 3000 RWF to Leo (0784567891). TxnId: TXN021',
     SHA2('You have transferred 3000 RWF to Leo (0784567891). TxnId: TXN021', 256), NULL),
    ('TXN022', 3, 1500.00, 0.00, 68300.00, 'RWF', '2024-01-24 07:30:00', 'completed', 'sms',
     'Your payment of 1500 RWF to Bakery C was successful. TxnId: TXN022',
     SHA2('Your payment of 1500 RWF to Bakery C was successful. TxnId: TXN022', 256), NULL),
    ('TXN023', 1, 18000.00, 0.00, 86300.00, 'RWF', '2024-01-25 11:00:00', 'completed', 'sms',
     'You have received 18000 RWF from Mia (0785678902). TxnId: TXN023',
     SHA2('You have received 18000 RWF from Mia (0785678902). TxnId: TXN023', 256), NULL),
    ('TXN024', 4, 500.00, 0.00, 85800.00, 'RWF', '2024-01-26 14:30:00', 'completed', 'sms',
     'You have bought airtime worth 500 RWF. TxnId: TXN024',
     SHA2('You have bought airtime worth 500 RWF. TxnId: TXN024', 256), NULL),
    ('TXN025', 3, 7000.00, 0.00, 78800.00, 'RWF', '2024-01-27 06:00:00', 'completed', 'sms',
     'Your payment of 7000 RWF to Gym D was successful. TxnId: TXN025',
     SHA2('Your payment of 7000 RWF to Gym D was successful. TxnId: TXN025', 256), NULL),
    ('TXN901', 6, 100000.00, 0.00, 178800.00, 'RWF', '2024-01-28 09:00:00', 'completed', 'sms',
     'Cash In: 100000 RWF deposited via agent MoMo Agent Nyabugogo. TxnId: TXN901',
     SHA2('Cash In: 100000 RWF deposited via agent MoMo Agent Nyabugogo. TxnId: TXN901', 256), NULL),
    ('TXN902', 7, 30000.00, 200.00, 148800.00, 'RWF', '2024-01-29 14:20:00', 'completed', 'sms',
     'Cash Out: 30000 RWF withdrawn via agent. Fee: 200 RWF. TxnId: TXN902',
     SHA2('Cash Out: 30000 RWF withdrawn via agent. Fee: 200 RWF. TxnId: TXN902', 256), NULL),
    ('TXN903', 5, 150000.00, 0.00, 298800.00, 'RWF', '2024-01-30 11:15:00', 'completed', 'sms',
     'You have received 150000 RWF from Bank of Kigali via bank deposit. TxnId: TXN903',
     SHA2('You have received 150000 RWF from Bank of Kigali via bank deposit. TxnId: TXN903', 256), NULL),
    ('TXN904', 8, 15000.00, 0.00, 283800.00, 'RWF', '2024-01-31 07:45:00', 'completed', 'sms',
     'Your payment of 15000 RWF to CASH POWER was successful. TxnId: TXN904',
     SHA2('Your payment of 15000 RWF to CASH POWER was successful. TxnId: TXN904', 256), NULL),
    ('TXN905', 9, 250000.00, 0.00, 533800.00, 'RWF', '2024-02-01 11:00:00', 'completed', 'sms',
     'International remittance of 250000 RWF received. TxnId: TXN905',
     SHA2('International remittance of 250000 RWF received. TxnId: TXN905', 256), 'Flagged for review: above the 200,000 RWF threshold'),
    ('TXN906', 10, 3000.00, 0.00, 536800.00, 'RWF', '2024-02-02 16:30:00', 'reversed', 'sms',
     'Transaction TXN021 has been reversed. 3000 RWF returned. TxnId: TXN906',
     SHA2('Transaction TXN021 has been reversed. 3000 RWF returned. TxnId: TXN906', 256), 'Reversal of TXN021 at the customer''s request'),
    ('TXN907', 2, 60000.00, 200.00, 476800.00, 'RWF', '2024-02-03 13:05:00', 'completed', 'sms',
     'You have transferred 60000 RWF to Divine Ingabire (0722660590). TxnId: TXN907',
     SHA2('You have transferred 60000 RWF to Divine Ingabire (0722660590). TxnId: TXN907', 256), NULL);

-- 7.5 transaction_participants  (64 rows)
INSERT INTO transaction_participants (transaction_id, user_id, role, party_label) VALUES
    (1, 1, 'sender',   '+250781234567'),
    (1, 2, 'receiver', '+250789876543'),
    (2, 2, 'sender',   '+250789876543'),
    (2, 3, 'receiver', 'MTN:MoMoPay:Kigali_Mart'),
    (3, 2, 'sender',   '+250789876543'),
    (3, 4, 'receiver', '+250782345678'),
    (4, 5, 'sender',   '+250783456789'),
    (4, 2, 'receiver', '+250789876543'),
    (5, 2, 'sender',   '+250789876543'),
    (5, 6, 'receiver', 'MTN:Airtime'),
    (6, 2, 'sender',   '+250789876543'),
    (6, 7, 'receiver', 'MTN:MoMoPay:Pharmacy_Plus'),
    (7, 8, 'sender',   '+250784567890'),
    (7, 2, 'receiver', '+250789876543'),
    (8, 2, 'sender',   '+250789876543'),
    (8, 9, 'receiver', '+250785678901'),
    (9, 2, 'sender',   '+250789876543'),
    (9, 10, 'receiver', 'MTN:MoMoPay:Supermarket_A'),
    (10, 11, 'sender',   '+250786789012'),
    (10, 2, 'receiver', '+250789876543'),
    (11, 2, 'sender',   '+250789876543'),
    (11, 6, 'receiver', 'MTN:Airtime'),
    (12, 2, 'sender',   '+250789876543'),
    (12, 12, 'receiver', '+250787890123'),
    (13, 2, 'sender',   '+250789876543'),
    (13, 13, 'receiver', 'MTN:MoMoPay:Restaurant_B'),
    (14, 14, 'sender',   '+250788901234'),
    (14, 2, 'receiver', '+250789876543'),
    (15, 2, 'sender',   '+250789876543'),
    (15, 15, 'receiver', '+250781234560'),
    (16, 2, 'sender',   '+250789876543'),
    (16, 16, 'receiver', 'MTN:MoMoPay:Electronics_Store'),
    (17, 17, 'sender',   '+250782345670'),
    (17, 2, 'receiver', '+250789876543'),
    (18, 2, 'sender',   '+250789876543'),
    (18, 6, 'receiver', 'MTN:Airtime'),
    (19, 2, 'sender',   '+250789876543'),
    (19, 18, 'receiver', 'MTN:MoMoPay:School_Fees'),
    (20, 19, 'sender',   '+250783456780'),
    (20, 2, 'receiver', '+250789876543'),
    (21, 2, 'sender',   '+250789876543'),
    (21, 20, 'receiver', '+250784567891'),
    (22, 2, 'sender',   '+250789876543'),
    (22, 21, 'receiver', 'MTN:MoMoPay:Bakery_C'),
    (23, 22, 'sender',   '+250785678902'),
    (23, 2, 'receiver', '+250789876543'),
    (24, 2, 'sender',   '+250789876543'),
    (24, 6, 'receiver', 'MTN:Airtime'),
    (25, 2, 'sender',   '+250789876543'),
    (25, 23, 'receiver', 'MTN:MoMoPay:Gym_D'),
    (26, 24, 'sender',   '+250788111934'),
    (26, 2, 'receiver', '+250789876543'),
    (27, 2, 'sender',   '+250789876543'),
    (27, 24, 'receiver', '+250788111934'),
    (28, 25, 'sender',   '+250788222731'),
    (28, 2, 'receiver', '+250789876543'),
    (29, 2, 'sender',   '+250789876543'),
    (29, 26, 'receiver', 'MTN:Utility:CashPower'),
    (30, 25, 'sender',   '+250788222731'),
    (30, 2, 'receiver', '+250789876543'),
    (31, 20, 'sender',   '+250784567891'),
    (31, 2, 'receiver', '+250789876543'),
    (32, 2, 'sender',   '+250789876543'),
    (32, 27, 'receiver', '+250722660590');

-- 7.6 transaction_tags  (28 rows)
INSERT INTO transaction_tags (transaction_id, tag_id, confidence, tagged_by) VALUES
    (2, 10, 1.00, 'etl'),
    (5, 2, 0.80, 'rule_engine'),
    (6, 10, 1.00, 'etl'),
    (7, 1, 1.00, 'etl'),
    (9, 10, 1.00, 'etl'),
    (11, 2, 0.80, 'rule_engine'),
    (12, 1, 1.00, 'etl'),
    (13, 10, 1.00, 'etl'),
    (14, 1, 1.00, 'etl'),
    (16, 10, 1.00, 'etl'),
    (18, 2, 0.80, 'rule_engine'),
    (19, 10, 1.00, 'etl'),
    (20, 1, 1.00, 'etl'),
    (22, 10, 1.00, 'etl'),
    (24, 2, 0.80, 'rule_engine'),
    (25, 10, 1.00, 'etl'),
    (26, 1, 1.00, 'etl'),
    (27, 1, 1.00, 'etl'),
    (27, 7, 1.00, 'etl'),
    (28, 1, 1.00, 'etl'),
    (28, 8, 1.00, 'etl'),
    (29, 4, 1.00, 'analyst'),
    (30, 1, 1.00, 'etl'),
    (30, 9, 1.00, 'etl'),
    (30, 5, 0.45, 'analyst'),
    (31, 5, 0.55, 'analyst'),
    (32, 1, 1.00, 'etl'),
    (32, 7, 1.00, 'etl');

-- -----------------------------------------------------------------------------
-- 7.7 system_logs  (18 rows)
-- Entries with transaction_id = NULL are messages that never became
-- transactions - exactly the records an engineer needs to debug the parser.
-- -----------------------------------------------------------------------------
INSERT INTO system_logs (transaction_id, stage, event_type, log_level, message, source_file, record_ref, records_affected, ip_address) VALUES
(NULL, 'parse',      'ETL_RUN_START',      'INFO',     'Started parsing MoMo SMS export.',                                          'data/raw/modified_sms_v2.xml', NULL,        0,  '127.0.0.1'),
(NULL, 'parse',      'PARSE_SUCCESS',      'INFO',     'Extracted 25 <sms> elements from the XML export.',                          'data/raw/modified_sms_v2.xml', NULL,        25, '127.0.0.1'),
(NULL, 'parse',      'PARSE_MALFORMED',    'ERROR',    'Malformed <sms> element: missing required "body" attribute. Skipped.',      'data/raw/modified_sms_v2.xml', 'sms[12]',   1,  '127.0.0.1'),
(NULL, 'parse',      'PARSE_BAD_DATE',     'ERROR',    'Unparseable date value "31/02/2024 25:00" - routed to the dead-letter queue.', 'data/raw/modified_sms_v2.xml', 'sms[19]', 1,  '127.0.0.1'),
(NULL, 'clean',      'AMOUNT_CORRECTED',   'WARNING',  'Amount "1,2OO RWF" contained letter O instead of zero. Auto-corrected.',    'data/raw/modified_sms_v2.xml', 'sms[7]',    1,  '127.0.0.1'),
(NULL, 'clean',      'PHONE_NORMALISED',   'INFO',     'Normalised 23 local-format numbers (07XXXXXXXX) to E.164.',                 'data/raw/modified_sms_v2.xml', NULL,        23, '127.0.0.1'),
(NULL, 'clean',      'PARTY_REF_ASSIGNED', 'INFO',     'Assigned party_ref to 8 non-subscriber counterparties (merchant tills and services).', 'data/raw/modified_sms_v2.xml', NULL, 8, '127.0.0.1'),
(NULL, 'categorize', 'CATEGORY_UNMATCHED', 'WARNING',  'No keyword matched - message could not be classified with confidence.',     'data/raw/modified_sms_v2.xml', 'sms[23]',   1,  '127.0.0.1'),
(NULL, 'categorize', 'CATEGORIZE_DONE',    'INFO',     'Classified 25 messages across 4 categories.',                               'data/raw/modified_sms_v2.xml', NULL,        25, '127.0.0.1'),
(1,    'load',       'DB_INSERT_OK',       'INFO',     'Inserted transaction and 2 participant rows.',                              'data/raw/modified_sms_v2.xml', 'TXN001',    3,  '127.0.0.1'),
(2,    'load',       'DB_INSERT_OK',       'INFO',     'Inserted merchant payment; receiver had no MSISDN, stored by party_ref.',   'data/raw/modified_sms_v2.xml', 'TXN002',    3,  '127.0.0.1'),
(NULL, 'load',       'DB_DUPLICATE',       'ERROR',    'Duplicate sms_hash rejected by uq_transactions_sms_hash - already loaded.', 'data/raw/modified_sms_v2.xml', 'TXN002',    0,  '127.0.0.1'),
(NULL, 'load',       'DB_CONNECTION_LOST', 'CRITICAL', 'Lost connection to MySQL during batch 3; transaction rolled back.',         'data/raw/modified_sms_v2.xml', 'batch[3]',  0,  '127.0.0.1'),
(NULL, 'load',       'ETL_RUN_COMPLETE',   'INFO',     'Load complete: 32 transactions committed, 2 rejected.',                     'data/raw/modified_sms_v2.xml', NULL,        32, '127.0.0.1'),
(30,   'categorize', 'THRESHOLD_EXCEEDED', 'WARNING',  'Amount 250000 is above the 200000 RWF review threshold.',                   'data/raw/modified_sms_v2.xml', 'TXN905',    1,  '127.0.0.1'),
(31,   'audit',      'STATUS_CHANGED',     'WARNING',  'Transaction reversed by the provider at the customer request.',             NULL,                           'TXN906',    1,  '10.0.0.14'),
(NULL, 'export',     'EXPORT_OK',          'INFO',     'Wrote dashboard aggregates to data/processed/dashboard.json.',              NULL,                           NULL,        10, '127.0.0.1'),
(NULL, 'export',     'EXPORT_OK',          'INFO',     'Rendered data/processed/dashboard.html from v_daily_summary.',              NULL,                           NULL,        1,  '127.0.0.1');


-- =============================================================================
-- SECTION 8: VERIFICATION
-- =============================================================================

SELECT '=== TABLES AND VIEWS CREATED ===' AS verification_step;
SHOW FULL TABLES;

SELECT '=== ROW COUNTS ===' AS verification_step;
SELECT 'transaction_categories'   AS table_name, COUNT(*) AS row_count FROM transaction_categories
UNION ALL SELECT 'users',                    COUNT(*) FROM users
UNION ALL SELECT 'tags',                     COUNT(*) FROM tags
UNION ALL SELECT 'transactions',             COUNT(*) FROM transactions
UNION ALL SELECT 'transaction_participants', COUNT(*) FROM transaction_participants
UNION ALL SELECT 'transaction_tags',         COUNT(*) FROM transaction_tags
UNION ALL SELECT 'system_logs',              COUNT(*) FROM system_logs;

SELECT '=== PARTY_REF DESIGN: parties with no phone number ===' AS verification_step;
SELECT party_ref, phone_number, full_name, user_type
FROM users WHERE phone_number IS NULL ORDER BY party_ref;

SELECT '=== PHONE NORMALISATION: all stored numbers are E.164 ===' AS verification_step;
SELECT COUNT(*) AS total_with_phone,
       SUM(phone_number REGEXP '^\\+250[0-9]{9}$') AS valid_e164
FROM users WHERE phone_number IS NOT NULL;

SELECT '=== TRIGGERS INSTALLED ===' AS verification_step;
SELECT TRIGGER_NAME, ACTION_TIMING, EVENT_MANIPULATION, EVENT_OBJECT_TABLE
FROM information_schema.TRIGGERS
WHERE TRIGGER_SCHEMA = 'momo_sms_db'
ORDER BY EVENT_OBJECT_TABLE, TRIGGER_NAME;

SELECT '=== CHECK CONSTRAINTS ===' AS verification_step;
SELECT CONSTRAINT_NAME, CHECK_CLAUSE
FROM information_schema.CHECK_CONSTRAINTS
WHERE CONSTRAINT_SCHEMA = 'momo_sms_db'
ORDER BY CONSTRAINT_NAME;

SELECT '=== FOREIGN KEYS ===' AS verification_step;
SELECT TABLE_NAME, COLUMN_NAME, CONSTRAINT_NAME,
       REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME
FROM information_schema.KEY_COLUMN_USAGE
WHERE TABLE_SCHEMA = 'momo_sms_db' AND REFERENCED_TABLE_NAME IS NOT NULL
ORDER BY TABLE_NAME, CONSTRAINT_NAME;

SELECT '=== EVERY CATEGORY HAS COVERAGE ===' AS verification_step;
SELECT category_code, transaction_count, total_amount FROM v_category_totals
ORDER BY category_code;

SELECT '=== SETUP COMPLETE ===' AS verification_step;
