-- =============================================================================
-- MoMo SMS Analytics - Security & Accuracy Rules Demonstration
-- =============================================================================
-- Author : Clive Tanaka Mushipe
-- Run    : mysql -u root --table --force < database/security_rules_demo.sql
--
-- IMPORTANT: --force is required. Every numbered statement below is DESIGNED
-- TO FAIL. Without --force, the client stops at the first rejection and you
-- only see one of the ten rules working.
--
-- Each test attempts to write bad data and shows the database refusing it.
-- A rule that is only documented is a suggestion; a rule the engine enforces
-- is a guarantee. These are the guarantees.
--
-- The script makes no lasting changes - every write it attempts is rejected,
-- and the one statement that succeeds (Rule 7) is rolled back.
-- =============================================================================

USE momo_sms_db;

SELECT '########## SECURITY & ACCURACY RULE DEMONSTRATION ##########' AS demo;


-- -----------------------------------------------------------------------------
-- RULE 1 - Duplicate SMS rejection  (UNIQUE uq_transactions_sms_hash)
-- Threat: re-running the ETL on the same XML export double-counts every
--         transaction, inflating reported revenue.
-- Expected: ERROR 1062 (23000) Duplicate entry
-- -----------------------------------------------------------------------------
SELECT '--- RULE 1: duplicate SMS body must be rejected (expect ERROR 1062) ---' AS rule_test;

INSERT INTO transactions
    (external_txn_ref, category_id, amount, fee, transaction_date, raw_sms_body, sms_hash)
VALUES (
    'TX_DUPLICATE_TEST', 1, 5000.00, 0.00, '2024-01-03 08:12:00',
    -- Verbatim body of TXN001, already loaded from the course dataset.
    'You have received 5000 RWF from Alice (0781234567). Your new balance is 15000 RWF. TxnId: TXN001',
    SHA2('You have received 5000 RWF from Alice (0781234567). Your new balance is 15000 RWF. TxnId: TXN001', 256)
);


-- -----------------------------------------------------------------------------
-- RULE 2 - Negative amount rejection  (CHECK chk_transactions_amount_positive)
-- Threat: a parser bug or a malicious edit storing a negative amount would
--         silently reduce reported totals.
-- Expected: ERROR 3819 (HY000) Check constraint violated
-- -----------------------------------------------------------------------------
SELECT '--- RULE 2: negative amount must be rejected (expect ERROR 3819) ---' AS rule_test;

INSERT INTO transactions
    (external_txn_ref, category_id, amount, fee, transaction_date, raw_sms_body, sms_hash)
VALUES (
    'TX_NEGATIVE_TEST', 1, -5000.00, 0.00, '2026-03-01 10:00:00',
    'Fabricated negative amount message.',
    SHA2('Fabricated negative amount message.', 256)
);


-- -----------------------------------------------------------------------------
-- RULE 3 - Zero amount rejection  (CHECK chk_transactions_amount_positive)
-- Threat: a failed parse that yields 0 would pollute averages and medians.
-- Expected: ERROR 3819
-- -----------------------------------------------------------------------------
SELECT '--- RULE 3: zero amount must be rejected (expect ERROR 3819) ---' AS rule_test;

INSERT INTO transactions
    (external_txn_ref, category_id, amount, fee, transaction_date, raw_sms_body, sms_hash)
VALUES (
    'TX_ZERO_TEST', 1, 0.00, 0.00, '2026-03-01 10:00:00',
    'Fabricated zero amount message.',
    SHA2('Fabricated zero amount message.', 256)
);


-- -----------------------------------------------------------------------------
-- RULE 4 - Malformed phone number rejection  (CHECK chk_users_phone_format)
-- Threat: unnormalised MSISDNs create duplicate customer records and break
--         every per-user aggregate. Note the test value is '12345': a
--         local-format number like '0788123456' would be NORMALISED to
--         E.164 by trg_users_normalise_input and correctly accepted, so it
--         would not demonstrate the constraint.
-- Expected: ERROR 3819
-- -----------------------------------------------------------------------------
SELECT '--- RULE 4: malformed phone number must be rejected (expect ERROR 3819) ---' AS rule_test;

INSERT INTO users (party_ref, phone_number, full_name, user_type)
VALUES ('BADREF', '12345', 'Bad Number Person', 'customer');


-- -----------------------------------------------------------------------------
-- RULE 5 - Orphan transaction rejection  (FK fk_transactions_category)
-- Threat: a transaction pointing at a category that does not exist is
--         invisible to every category-based report.
-- Expected: ERROR 1452 (23000) Cannot add or update a child row
-- -----------------------------------------------------------------------------
SELECT '--- RULE 5: transaction with a non-existent category must be rejected (expect ERROR 1452) ---' AS rule_test;

INSERT INTO transactions
    (external_txn_ref, category_id, amount, fee, transaction_date, raw_sms_body, sms_hash)
VALUES (
    'TX_ORPHAN_TEST', 999, 5000.00, 0.00, '2026-03-01 10:00:00',
    'Fabricated orphan category message.',
    SHA2('Fabricated orphan category message.', 256)
);


-- -----------------------------------------------------------------------------
-- RULE 6 - Category deletion blocked while in use  (ON DELETE RESTRICT)
-- Threat: deleting a lookup row would orphan historical financial records.
-- Expected: ERROR 1451 (23000) Cannot delete or update a parent row
-- -----------------------------------------------------------------------------
SELECT '--- RULE 6: deleting an in-use category must be blocked (expect ERROR 1451) ---' AS rule_test;

DELETE FROM transaction_categories WHERE category_code = 'PAYMENT_MERCHANT';


-- -----------------------------------------------------------------------------
-- RULE 7 - Self-transfer blocked  (TRIGGER trg_participants_no_self_transfer)
-- Threat: a user appearing as both sender and receiver on one transaction is
--         either a mis-parsed message or a wash-trading / laundering pattern.
--         This rule spans two rows, so no CHECK constraint can express it.
-- Expected: ERROR 1644 (45000) with our custom message
-- Note    : wrapped in a transaction and rolled back, because the first INSERT
--           legitimately succeeds - it is the second that must be refused.
-- -----------------------------------------------------------------------------
SELECT '--- RULE 7: same user as sender AND receiver must be blocked (expect ERROR 1644) ---' AS rule_test;

-- Every seeded transaction already has both parties, so a scratch transaction
-- is created here with a sender only. Adding that same user as the receiver is
-- the self-transfer the trigger must refuse.
START TRANSACTION;

INSERT INTO transactions
    (external_txn_ref, category_id, amount, fee, transaction_date, raw_sms_body, sms_hash)
VALUES ('TX_SELF_TEST', 1, 1000.00, 0.00, '2024-01-03 09:00:00',
        'Scratch row for the self-transfer rule test.',
        SHA2('Scratch row for the self-transfer rule test.', 256));

SET @scratch_txn = LAST_INSERT_ID();

-- Valid: user 1 is the sender. This succeeds.
INSERT INTO transaction_participants (transaction_id, user_id, role)
VALUES (@scratch_txn, 1, 'sender');

-- Refused: user 1 cannot also be the receiver of their own transaction.
INSERT INTO transaction_participants (transaction_id, user_id, role)
VALUES (@scratch_txn, 1, 'receiver');

ROLLBACK;


-- -----------------------------------------------------------------------------
-- RULE 8 - Future-dated transaction blocked  (TRIGGER trg_transactions_no_future_date)
-- Threat: a transaction dated in the future indicates a timezone bug, a
--         corrupt source date, or deliberate tampering. NOW() is
--         non-deterministic so this cannot be a CHECK constraint.
-- Expected: ERROR 1644 (45000) with our custom message
-- -----------------------------------------------------------------------------
SELECT '--- RULE 8: future-dated transaction must be rejected (expect ERROR 1644) ---' AS rule_test;

INSERT INTO transactions
    (external_txn_ref, category_id, amount, fee, transaction_date, raw_sms_body, sms_hash)
VALUES (
    'TX_FUTURE_TEST', 1, 5000.00, 0.00, DATE_ADD(NOW(), INTERVAL 10 DAY),
    'Fabricated future-dated message.',
    SHA2('Fabricated future-dated message.', 256)
);


-- -----------------------------------------------------------------------------
-- RULE 9 - Two senders on one transaction blocked  (UNIQUE uq_participants_txn_role)
-- Threat: a parser attaching multiple senders makes the ledger ambiguous and
--         double-counts outbound value per user.
-- Expected: ERROR 1062 (23000) Duplicate entry
-- -----------------------------------------------------------------------------
SELECT '--- RULE 9: a second sender on one transaction must be rejected (expect ERROR 1062) ---' AS rule_test;

INSERT INTO transaction_participants (transaction_id, user_id, role, party_label)
VALUES (1, 5, 'sender', 'Patrick Habimana');


-- -----------------------------------------------------------------------------
-- RULE 10 - Confidence out of range blocked  (CHECK chk_tags_confidence_range)
-- Threat: a confidence score above 1.0 breaks every weighted calculation
--         that consumes it.
-- Expected: ERROR 3819
-- -----------------------------------------------------------------------------
SELECT '--- RULE 10: confidence above 1.00 must be rejected (expect ERROR 3819) ---' AS rule_test;

INSERT INTO transaction_tags (transaction_id, tag_id, confidence, tagged_by)
VALUES (1, 5, 1.85, 'etl');


-- #############################################################################
-- POSITIVE EVIDENCE - rules that protect rather than reject
-- #############################################################################

-- -----------------------------------------------------------------------------
-- RULE 11 - Automatic audit trail  (TRIGGER trg_transactions_audit_amount_change)
-- Nobody can quietly change a financial figure: the database logs it whether
-- the person making the change wants it logged or not.
-- -----------------------------------------------------------------------------
SELECT '--- RULE 11: amount changes are logged automatically (no way to opt out) ---' AS rule_test;

START TRANSACTION;

SELECT 'BEFORE the update - audit entries for TXN001:' AS step;
SELECT COUNT(*) AS audit_entries FROM system_logs
WHERE record_ref = 'TXN001' AND stage = 'audit';

UPDATE transactions SET amount = 5555.00 WHERE external_txn_ref = 'TXN001';

SELECT 'AFTER the update - the trigger wrote this entry by itself:' AS step;
SELECT log_id, stage, log_level, message
FROM system_logs
WHERE record_ref = 'TXN001' AND stage = 'audit';

ROLLBACK;

SELECT 'Rolled back - baseline restored:' AS step;
SELECT external_txn_ref, FORMAT(amount, 2) AS amount_rwf
FROM transactions WHERE external_txn_ref = 'TXN001';


-- -----------------------------------------------------------------------------
-- RULE 12 - Phone-number masking  (VIEW v_transaction_summary)
-- Analysts read the view, never the base table. Full MSISDNs are personally
-- identifiable information and the view makes exposing them impossible by
-- construction rather than by policy.
-- -----------------------------------------------------------------------------
SELECT '--- RULE 12: the reporting view exposes only masked phone numbers ---' AS rule_test;

SELECT 'Base table (restricted - full PII):' AS data_source;
SELECT full_name, phone_number FROM users WHERE user_id IN (1, 2, 3);

SELECT 'Reporting view (what analysts actually see):' AS data_source;
SELECT DISTINCT sender_name, sender_ref_masked
FROM v_transaction_summary
WHERE sender_name IS NOT NULL
ORDER BY sender_name
LIMIT 5;


-- -----------------------------------------------------------------------------
-- RULE 13 - Least-privilege application accounts  (GRANT)
-- The application never connects as root. If the API were compromised through
-- SQL injection, the blast radius is bounded by these grants: momo_app cannot
-- DROP a table or DELETE a row, and momo_readonly sees only the masked views.
-- -----------------------------------------------------------------------------
SELECT '--- RULE 13: application accounts hold the minimum privileges needed ---' AS rule_test;

SELECT 'Grants for momo_app (note: no DELETE, no DROP, no other database):' AS account;
SHOW GRANTS FOR 'momo_app'@'localhost';

SELECT 'Grants for momo_readonly (masked views only, no base tables):' AS account;
SHOW GRANTS FOR 'momo_readonly'@'localhost';

-- Grants are only a claim until the server enforces them. To prove enforcement,
-- run these from the shell as the restricted accounts (they cannot be run from
-- inside this script because they require a different connection):
--
--   # momo_app is refused DELETE       -> ERROR 1142 DELETE command denied
--   mysql -u momo_app -p -e "USE momo_sms_db; DELETE FROM transactions WHERE transaction_id=1;"
--
--   # momo_app is refused DDL          -> ERROR 1142 DROP command denied
--   mysql -u momo_app -p -e "USE momo_sms_db; DROP TABLE system_logs;"
--
--   # momo_readonly cannot see raw PII -> ERROR 1142 SELECT command denied for table 'users'
--   mysql -u momo_readonly -p -e "USE momo_sms_db; SELECT phone_number FROM users LIMIT 1;"
--
--   # but CAN read the masked view     -> succeeds, phone numbers redacted
--   mysql -u momo_readonly -p -e "SELECT sender_name, sender_ref_masked FROM momo_sms_db.v_transaction_summary LIMIT 2;"
--
-- Captured output of all four is in docs/screenshots/ and the design document.


SELECT '########## END OF DEMONSTRATION ##########' AS demo;
SELECT 'Every rejection above is the database refusing bad data. No lasting changes were made.' AS summary;
