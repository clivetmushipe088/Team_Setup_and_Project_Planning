-- =============================================================================
-- MoMo SMS Analytics - Sample Queries
-- =============================================================================
-- Author : Clive Tanaka Mushipe
-- Run    : mysql -u root --table < database/sample_queries.sql
--
-- Each query states the business question it answers and the index it relies
-- on. Together they exercise every table, both junction tables, both views,
-- aggregation, multi-table joins, a window function and FULLTEXT search.
-- =============================================================================

USE momo_sms_db;


-- -----------------------------------------------------------------------------
-- QUERY 1 - Volume and value by transaction category
-- Business question: where does the money go?
-- Exercises      : INNER JOIN, GROUP BY, aggregate functions, ORDER BY
-- Index used     : idx_txn_cat_date (leftmost prefix category_id)
-- -----------------------------------------------------------------------------
SELECT '=== QUERY 1: Volume and value by category ===' AS query_label;

SELECT
    c.category_name                              AS category,
    c.direction                                  AS wallet_effect,
    COUNT(t.transaction_id)                      AS txn_count,
    FORMAT(COALESCE(SUM(t.amount), 0), 2)        AS total_rwf,
    FORMAT(COALESCE(AVG(t.amount), 0), 2)        AS avg_rwf,
    FORMAT(COALESCE(SUM(t.fee), 0), 2)           AS total_fees_rwf
FROM transaction_categories c
    LEFT JOIN transactions t
        ON t.category_id = c.category_id
       AND t.status = 'completed'
GROUP BY c.category_id, c.category_name, c.direction
ORDER BY COALESCE(SUM(t.amount), 0) DESC;


-- -----------------------------------------------------------------------------
-- QUERY 2 - Monthly transaction trend
-- Business question: is activity growing month over month?
-- Exercises      : DATE_FORMAT, GROUP BY on a derived period, conditional SUM
-- Index used     : idx_txn_date
-- -----------------------------------------------------------------------------
SELECT '=== QUERY 2: Monthly trend ===' AS query_label;

SELECT
    DATE_FORMAT(t.transaction_date, '%Y-%m')                            AS month,
    COUNT(*)                                                            AS txn_count,
    FORMAT(SUM(t.amount), 2)                                            AS total_rwf,
    FORMAT(SUM(CASE WHEN c.direction = 'credit' THEN t.amount ELSE 0 END), 2) AS money_in_rwf,
    FORMAT(SUM(CASE WHEN c.direction = 'debit'  THEN t.amount ELSE 0 END), 2) AS money_out_rwf,
    FORMAT(SUM(t.fee), 2)                                               AS fees_rwf
FROM transactions t
    INNER JOIN transaction_categories c
        ON c.category_id = t.category_id
WHERE t.status = 'completed'
GROUP BY DATE_FORMAT(t.transaction_date, '%Y-%m')
ORDER BY month;


-- -----------------------------------------------------------------------------
-- QUERY 3 - Top 5 senders by value
-- Business question: who are our highest-value outbound customers?
-- Exercises      : the Users <-> Transactions M:N junction, LIMIT
-- Index used     : idx_participants_user_role (user_id, role)
-- -----------------------------------------------------------------------------
SELECT '=== QUERY 3: Top 5 senders by total value ===' AS query_label;

SELECT
    u.full_name                                  AS sender,
    u.user_type                                  AS party_type,
    COUNT(DISTINCT t.transaction_id)             AS txn_count,
    FORMAT(SUM(t.amount), 2)                     AS total_sent_rwf,
    FORMAT(MAX(t.amount), 2)                     AS largest_single_rwf
FROM users u
    INNER JOIN transaction_participants p
        ON p.user_id = u.user_id AND p.role = 'sender'
    INNER JOIN transactions t
        ON t.transaction_id = p.transaction_id
       AND t.status = 'completed'
GROUP BY u.user_id, u.full_name, u.user_type
ORDER BY SUM(t.amount) DESC
LIMIT 5;


-- -----------------------------------------------------------------------------
-- QUERY 4 - Full transaction ledger with both parties resolved
-- Business question: show a readable statement of every transaction.
-- Exercises      : the junction table joined TWICE (once per role) - this is
--                  the query that would need a UNION if we had used nullable
--                  sender_id / receiver_id columns instead.
-- Index used     : idx_participants_txn
-- -----------------------------------------------------------------------------
SELECT '=== QUERY 4: Transaction ledger with sender and receiver ===' AS query_label;

SELECT
    t.external_txn_ref                           AS reference,
    DATE_FORMAT(t.transaction_date, '%Y-%m-%d %H:%i') AS occurred_at,
    c.category_name                              AS category,
    FORMAT(t.amount, 0)                          AS amount_rwf,
    FORMAT(t.fee, 0)                             AS fee_rwf,
    COALESCE(snd.full_name, '(none)')            AS sender,
    COALESCE(rcv.full_name, '(none)')            AS receiver,
    t.status
FROM transactions t
    INNER JOIN transaction_categories c
        ON c.category_id = t.category_id
    LEFT JOIN transaction_participants ps
        ON ps.transaction_id = t.transaction_id AND ps.role = 'sender'
    LEFT JOIN users snd ON snd.user_id = ps.user_id
    LEFT JOIN transaction_participants pr
        ON pr.transaction_id = t.transaction_id AND pr.role = 'receiver'
    LEFT JOIN users rcv ON rcv.user_id = pr.user_id
ORDER BY t.transaction_date
LIMIT 10;


-- -----------------------------------------------------------------------------
-- QUERY 5 - ETL error triage
-- Business question: what failed in the last pipeline run, and why?
-- Exercises      : system_logs, ENUM filtering with IN, LEFT JOIN to a
--                  nullable FK (entries with no transaction are parse failures)
-- Index used     : idx_logs_level_created (log_level, created_at)
-- -----------------------------------------------------------------------------
SELECT '=== QUERY 5: ETL errors needing attention ===' AS query_label;

SELECT
    l.log_id,
    l.log_level                                  AS severity,
    l.stage,
    COALESCE(t.external_txn_ref, '(no transaction created)') AS related_txn,
    COALESCE(l.record_ref, '-')                  AS record_ref,
    l.message
FROM system_logs l
    LEFT JOIN transactions t
        ON t.transaction_id = l.transaction_id
WHERE l.log_level IN ('WARNING', 'ERROR', 'CRITICAL')
ORDER BY FIELD(l.log_level, 'CRITICAL', 'ERROR', 'WARNING'), l.created_at;


-- -----------------------------------------------------------------------------
-- QUERY 6 - Largest transaction per category (window function)
-- Business question: what was the single biggest transaction in each category?
-- Exercises      : RANK() OVER (PARTITION BY ... ORDER BY ...) in a CTE
-- Index used     : idx_txn_amount
-- -----------------------------------------------------------------------------
SELECT '=== QUERY 6: Largest transaction per category (window function) ===' AS query_label;

WITH ranked_transactions AS (
    SELECT
        c.category_name,
        t.external_txn_ref,
        t.amount,
        t.transaction_date,
        RANK() OVER (
            PARTITION BY t.category_id
            ORDER BY t.amount DESC
        ) AS amount_rank
    FROM transactions t
        INNER JOIN transaction_categories c
            ON c.category_id = t.category_id
    WHERE t.status = 'completed'
)
SELECT
    category_name                                AS category,
    external_txn_ref                             AS reference,
    FORMAT(amount, 2)                            AS amount_rwf,
    DATE_FORMAT(transaction_date, '%Y-%m-%d')    AS occurred_on
FROM ranked_transactions
WHERE amount_rank = 1
ORDER BY amount DESC;


-- -----------------------------------------------------------------------------
-- QUERY 7 - FULLTEXT search across raw SMS bodies
-- Business question: find every message mentioning an agent withdrawal.
-- Exercises      : MATCH ... AGAINST in NATURAL LANGUAGE MODE with relevance
--                  scoring. Uses ftx_txn_body instead of a LIKE '%...%' scan.
-- Index used     : ftx_txn_body (FULLTEXT)
-- -----------------------------------------------------------------------------
SELECT '=== QUERY 7: FULLTEXT search for agent withdrawals ===' AS query_label;

SELECT
    t.external_txn_ref                           AS reference,
    FORMAT(t.amount, 0)                          AS amount_rwf,
    ROUND(MATCH(t.raw_sms_body) AGAINST ('agent withdrawn' IN NATURAL LANGUAGE MODE), 4) AS relevance,
    LEFT(t.raw_sms_body, 70)                     AS sms_excerpt
FROM transactions t
WHERE MATCH(t.raw_sms_body) AGAINST ('agent withdrawn' IN NATURAL LANGUAGE MODE)
ORDER BY relevance DESC;


-- -----------------------------------------------------------------------------
-- QUERY 8 - Tag analytics through the second M:N junction
-- Business question: how much value sits behind each analytics tag?
-- Exercises      : transaction_tags junction, AVG on the confidence attribute
--                  that lives ON the relationship rather than on either entity
-- Index used     : idx_txn_tags_tag
-- -----------------------------------------------------------------------------
SELECT '=== QUERY 8: Value and confidence by tag ===' AS query_label;

SELECT
    g.tag_name                                   AS tag,
    g.tag_type                                   AS tag_origin,
    COUNT(tt.transaction_id)                     AS tagged_txns,
    FORMAT(COALESCE(SUM(t.amount), 0), 2)        AS total_value_rwf,
    ROUND(AVG(tt.confidence), 2)                 AS avg_confidence
FROM tags g
    LEFT JOIN transaction_tags tt ON tt.tag_id = g.tag_id
    LEFT JOIN transactions t      ON t.transaction_id = tt.transaction_id
GROUP BY g.tag_id, g.tag_name, g.tag_type
ORDER BY COUNT(tt.transaction_id) DESC, g.tag_name;


-- -----------------------------------------------------------------------------
-- QUERY 9 - Privacy-safe reporting through the masking view
-- Business question: give analysts a ledger without exposing full phone numbers.
-- Exercises      : v_transaction_summary (SECURITY RULE 21). Note the
--                  merchant rows: they have no phone number, so the view
--                  falls back to party_ref rather than showing a blank.
-- -----------------------------------------------------------------------------
SELECT '=== QUERY 9: Masked ledger (phone numbers redacted) ===' AS query_label;

SELECT
    external_txn_ref                             AS reference,
    category_name                                AS category,
    FORMAT(amount, 0)                            AS amount_rwf,
    sender_name,
    sender_ref_masked,
    receiver_name,
    receiver_ref_masked
FROM v_transaction_summary
WHERE amount >= 20000
ORDER BY amount DESC
LIMIT 8;


-- -----------------------------------------------------------------------------
-- QUERY 10 - Index verification with EXPLAIN
-- Demonstrates that the optimiser genuinely uses idx_txn_cat_date rather than
-- scanning the table. Proof that the indexes earn their place.
-- -----------------------------------------------------------------------------
SELECT '=== QUERY 10: EXPLAIN - proving idx_txn_cat_date is used ===' AS query_label;

EXPLAIN
SELECT transaction_id, amount, transaction_date
FROM transactions
WHERE category_id = 2
  AND transaction_date BETWEEN '2026-01-01' AND '2026-03-31';
