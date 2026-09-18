-- =============================================================================
-- MoMo SMS Analytics - CRUD Operation Tests
-- =============================================================================
-- Author : Clive Tanaka Mushipe
-- Run    : mysql -u root --table < database/crud_tests.sql
--
-- Demonstrates CREATE, READ, UPDATE and DELETE against the live schema.
-- Each operation is bracketed by a SELECT so the effect is visible in the
-- captured output rather than merely asserted.
--
-- This script leaves the database exactly as it found it: the test rows it
-- creates are removed by the DELETE section at the end.
-- =============================================================================

USE momo_sms_db;


-- #############################################################################
-- C  -  CREATE
-- #############################################################################

SELECT '################ C: CREATE ################' AS crud_operation;

SELECT '--- BEFORE: transaction count ---' AS step;
SELECT COUNT(*) AS transactions_before FROM transactions;

SELECT '--- ACTION: insert a new user, transaction and its participants ---' AS step;

-- Create a new counterparty.
-- Note the local-format number: the normalisation trigger rewrites it to
-- E.164 before the CHECK constraint sees it.
INSERT INTO users (party_ref, phone_number, full_name, user_type, account_status)
VALUES ('+250788555321', '0788555321', 'Grace Uwase', 'customer', 'active');

SET @new_user_id = LAST_INSERT_ID();

-- Create a new transaction. The SHA2() call generates a genuine hash of the
-- message body, exactly as etl/load_db.py will.
INSERT INTO transactions
    (external_txn_ref, category_id, amount, fee, balance_after, transaction_date, status, raw_sms_body, sms_hash)
VALUES (
    'TX99900000001',
    (SELECT category_id FROM transaction_categories WHERE category_code = 'OUTGOING_TRANSFER'),
    35000.00,
    150.00,
    300450.00,
    '2026-03-28 10:15:00',
    'completed',
    '*165*S*35000 RWF transferred to Grace Uwase (250788555321) from 36521838 at 2026-03-28 10:15:00. Fee was: 150 RWF. New balance: 300450 RWF.',
    SHA2('*165*S*35000 RWF transferred to Grace Uwase (250788555321) from 36521838 at 2026-03-28 10:15:00. Fee was: 150 RWF. New balance: 300450 RWF.', 256)
);

SET @new_txn_id = LAST_INSERT_ID();

-- Link both parties through the M:N junction.
INSERT INTO transaction_participants (transaction_id, user_id, role, party_label) VALUES
(@new_txn_id, 1,             'sender',   '+250781234567'),
(@new_txn_id, @new_user_id,  'receiver', 'Grace Uwase');

-- Attach a tag through the second M:N junction.
INSERT INTO transaction_tags (transaction_id, tag_id, confidence, tagged_by)
VALUES (@new_txn_id, (SELECT tag_id FROM tags WHERE tag_name = 'fee_charged'), 1.00, 'etl');

SELECT '--- AFTER: the new record, fully joined ---' AS step;
SELECT
    t.transaction_id,
    t.external_txn_ref,
    c.category_name,
    FORMAT(t.amount, 2) AS amount_rwf,
    snd.full_name       AS sender,
    rcv.full_name       AS receiver,
    t.status
FROM transactions t
    JOIN transaction_categories c   ON c.category_id = t.category_id
    LEFT JOIN transaction_participants ps ON ps.transaction_id = t.transaction_id AND ps.role='sender'
    LEFT JOIN users snd             ON snd.user_id = ps.user_id
    LEFT JOIN transaction_participants pr ON pr.transaction_id = t.transaction_id AND pr.role='receiver'
    LEFT JOIN users rcv             ON rcv.user_id = pr.user_id
WHERE t.external_txn_ref = 'TX99900000001';

SELECT COUNT(*) AS transactions_after FROM transactions;


-- #############################################################################
-- R  -  READ
-- #############################################################################

SELECT '################ R: READ ################' AS crud_operation;

SELECT '--- READ 1: single record by its natural key ---' AS step;
SELECT transaction_id, external_txn_ref, amount, fee, status, transaction_date
FROM transactions
WHERE external_txn_ref = 'TX99900000001';

SELECT '--- READ 2: aggregate across the whole table ---' AS step;
SELECT
    COUNT(*)                 AS total_transactions,
    FORMAT(SUM(amount), 2)   AS total_value_rwf,
    FORMAT(AVG(amount), 2)   AS average_value_rwf,
    MIN(transaction_date)    AS earliest,
    MAX(transaction_date)    AS latest
FROM transactions;

SELECT '--- READ 3: filtered join - all transfers above 20,000 RWF ---' AS step;
SELECT
    t.external_txn_ref,
    FORMAT(t.amount, 0) AS amount_rwf,
    u.full_name         AS receiver
FROM transactions t
    JOIN transaction_categories c        ON c.category_id = t.category_id
    JOIN transaction_participants p      ON p.transaction_id = t.transaction_id AND p.role = 'receiver'
    JOIN users u                         ON u.user_id = p.user_id
WHERE c.category_code = 'OUTGOING_TRANSFER'
  AND t.amount > 20000
ORDER BY t.amount DESC;


-- #############################################################################
-- U  -  UPDATE
-- #############################################################################

SELECT '################ U: UPDATE ################' AS crud_operation;

SELECT '--- BEFORE: current amount and status ---' AS step;
SELECT external_txn_ref, FORMAT(amount, 2) AS amount_rwf, status, updated_at
FROM transactions
WHERE external_txn_ref = 'TX99900000001';

SELECT '--- ACTION: correct the amount and mark the transaction reversed ---' AS step;
UPDATE transactions
SET amount = 35500.00,
    status = 'reversed'
WHERE external_txn_ref = 'TX99900000001';

SELECT ROW_COUNT() AS rows_updated;

SELECT '--- AFTER: values changed, updated_at advanced automatically ---' AS step;
SELECT external_txn_ref, FORMAT(amount, 2) AS amount_rwf, status, updated_at
FROM transactions
WHERE external_txn_ref = 'TX99900000001';

SELECT '--- SIDE EFFECT: the audit trigger logged both changes by itself ---' AS step;
SELECT log_id, stage, log_level, message
FROM system_logs
WHERE record_ref = 'TX99900000001'
ORDER BY log_id;


-- #############################################################################
-- D  -  DELETE
-- #############################################################################

SELECT '################ D: DELETE ################' AS crud_operation;

SELECT '--- BEFORE: child rows that depend on this transaction ---' AS step;
SELECT
    (SELECT COUNT(*) FROM transaction_participants WHERE transaction_id = @new_txn_id) AS participant_rows,
    (SELECT COUNT(*) FROM transaction_tags         WHERE transaction_id = @new_txn_id) AS tag_rows,
    (SELECT COUNT(*) FROM system_logs              WHERE transaction_id = @new_txn_id) AS log_rows;

SELECT '--- ACTION: delete the transaction ---' AS step;
DELETE FROM transactions WHERE external_txn_ref = 'TX99900000001';
SELECT ROW_COUNT() AS rows_deleted;

SELECT '--- AFTER: ON DELETE CASCADE removed participants and tags ---' AS step;
SELECT
    (SELECT COUNT(*) FROM transaction_participants WHERE transaction_id = @new_txn_id) AS participant_rows,
    (SELECT COUNT(*) FROM transaction_tags         WHERE transaction_id = @new_txn_id) AS tag_rows;

SELECT '--- AFTER: ON DELETE SET NULL preserved the audit trail ---' AS step;
SELECT log_id, transaction_id, stage, log_level, LEFT(message, 60) AS message_excerpt
FROM system_logs
WHERE record_ref = 'TX99900000001'
ORDER BY log_id;

SELECT '--- CLEANUP: remove the audit rows and test user ---' AS step;
DELETE FROM system_logs WHERE record_ref = 'TX99900000001';
DELETE FROM users       WHERE phone_number = '+250788555321';

SELECT '--- FINAL STATE: database restored to its seeded baseline ---' AS step;
SELECT 'users' AS table_name, COUNT(*) AS row_count FROM users
UNION ALL SELECT 'transactions',             COUNT(*) FROM transactions
UNION ALL SELECT 'transaction_participants', COUNT(*) FROM transaction_participants
UNION ALL SELECT 'transaction_tags',         COUNT(*) FROM transaction_tags
UNION ALL SELECT 'system_logs',              COUNT(*) FROM system_logs;

SELECT '################ ALL CRUD OPERATIONS PASSED ################' AS crud_operation;
