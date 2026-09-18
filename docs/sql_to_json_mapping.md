# SQL → JSON Mapping

How each MySQL table and column in `momo_sms_db` is serialised into the JSON
structures in [`examples/json_schemas.json`](../examples/json_schemas.json).

The worked example of every rule below is
[`examples/complete_transaction.json`](../examples/complete_transaction.json):
a single API response that draws on all seven tables. It is a merchant payment, chosen so the nested participant demonstrates the `party_ref` fallback rather than merely describing it.

---

## Type conversion rules

| MySQL type | JSON type | Rule and reason |
|---|---|---|
| `DECIMAL(15,2)` | `string` | **Never a JSON number.** IEEE-754 doubles cannot represent every two-decimal value exactly, and a rounding error in a stored balance compounds silently. `"150000.00"` round-trips exactly. |
| `DATETIME` | `string` (ISO-8601) | MySQL `DATETIME` carries no timezone. The API attaches Africa/Kigali on the way out: `2026-01-12T13:30:00+02:00`. |
| `ENUM(...)` | `string` | Constrained by a JSON Schema `enum` with identical members, so the contract is enforced on both sides. |
| `BOOLEAN` / `TINYINT(1)` | `true` / `false` | n/a |
| `INT` / `BIGINT UNSIGNED` | `integer` | Safe as a JSON number below 2^53. Beyond that the id would need to become a string. |
| `CHAR(3)` (currency) | `string` | ISO-4217 code, kept beside the amount it qualifies. |
| `NULL` | `null` | Nullable columns are typed `["<type>", "null"]` rather than omitted, so a client can distinguish *"absent from the SMS"* from *"field not requested"*. |
| `TEXT` (SMS body) | `string` | Only for privileged callers. See PII below. |

---

## Structural rules

**Foreign keys become objects, not ids.** `transactions.category_id` never
appears in a response. It is replaced by the whole nested `category` object, so
a client renders a transaction from one request instead of two.

**Junction tables disappear.** Neither `transaction_participants` nor
`transaction_tags` is a top-level API resource. They are an implementation
detail of the two M:N relationships. Each becomes a nested array, and the
attributes stored *on* the relationship travel inside the array items:

- `transaction_participants.role` → `participants[].role`
- `transaction_tags.confidence` → `tags[].confidence`
- `transaction_tags.tagged_by` → `tags[].tagged_by`

This is the part of the mapping worth dwelling on: `confidence` belongs to
neither the transaction nor the tag. It only exists because the two are linked,
which is exactly why the relationship needs its own table in SQL and its own
position in the JSON.

**Composite keys dissolve.** `transaction_tags` has PK `(transaction_id, tag_id)`.
In JSON, `transaction_id` is implicit (it is the parent object) and `tag_id`
sits on the array item. The composite key has no JSON counterpart at all.

**Some fields are computed on serialisation.** `amounts.total` is
`amount + fee`. It is not stored, because storing a derived value invites the
two to drift apart; it is computed once at the API boundary so that no client
re-implements the arithmetic.

---

## Privacy rules

| Column | Public response | Privileged response |
|---|---|---|
| `users.phone_number` | `+250788****045` (masked), or the `party_ref` when the party has no number | full E.164 or `null` |
| `users.national_id` | omitted entirely | present |
| `transactions.raw_sms_body` | omitted entirely | inside `source` |
| `transactions.sms_hash` | omitted entirely | inside `source` |

Masking is produced by the database view, not by application code. An endpoint
that forgets to mask cannot leak a number it was never served.

---

## Table-by-table mapping

### `users` → `definitions.user`, `transaction.participants[]`

| Column | JSON path | Notes |
|---|---|---|
| `user_id` | `user_id` | |
| `party_ref` | `party_ref` | the natural key, an E.164 MSISDN *or* a service code |
| `phone_number` | `phone_number` | nullable; masked in public responses |
| *(derived)* | `has_msisdn` | whether `phone_number` was non-null |
| `full_name` | `full_name` | nullable, a till has a code, not a person's name |
| `is_verified` | `is_verified` | boolean |
| `user_type` | `user_type` | |
| `national_id` | `national_id` | omitted from public responses (PII) |
| `account_status` | `account_status` | |
| `first_seen_at` | `first_seen_at` | ISO-8601 |
| `created_at`, `updated_at` | same names | audit fields |

#### Parties that have no phone number

Half the counterparties in the source data are merchant tills
(`MTN:MoMoPay:Kigali_Mart`) or service endpoints (`MTN:Airtime`), which have no
MSISDN at all. Inside `participants[]` the displayable identifier is therefore
called **`masked_ref`**, not `phone_number`:

| Party | `party_ref` | `masked_ref` | `has_msisdn` |
|---|---|---|---|
| customer | `+250789876543` | `+250789****543` | `true` |
| merchant till | `MTN:MoMoPay:Kigali_Mart` | `MTN:MoMoPay:Kigali_Mart` | `false` |

Two decisions are worth stating:

- **The field is not called `phone_number`.** For a till it holds a code, and a
  field whose name lies about its contents is worse than a slightly longer
  name. It matches the `sender_ref_masked` / `receiver_ref_masked` columns of
  `v_transaction_summary`, so the API and the database agree.
- **A till code is not PII.** It identifies a shop, not a person, so there is
  nothing to mask, so the fallback is safe rather than a leak.

### `transaction_categories` → `transaction.category`

| Column | JSON path | Notes |
|---|---|---|
| `category_id` | `category.category_id` | |
| `category_code` | `category.code` | renamed, `category.category_code` stutters. Codes are uppercase (`PAYMENT_MERCHANT`) |
| `category_name` | `category.name` | renamed for the same reason |
| `direction` | `category.direction` | |
| `description` | `category.description` | |
| `is_active` | `category.is_active` | boolean |

### `transactions` → `definitions.transaction` (root)

| Column | JSON path | Notes |
|---|---|---|
| `transaction_id` | `transaction_id` | |
| `external_txn_ref` | `reference` | renamed, shorter and unambiguous in context |
| `category_id` | *(gone)* | replaced by the nested `category` object |
| `amount` | `amounts.principal` | decimal string |
| `fee` | `amounts.fee` | decimal string |
| `balance_after` | `amounts.balance_after` | decimal string or `null` |
| `currency` | `amounts.currency` | grouped with the values it qualifies |
| *(computed)* | `amounts.total` | `amount + fee` |
| `transaction_date` | `transaction_date` | ISO-8601 `+02:00` |
| `status` | `status` | |
| `channel` | `channel` | |
| `notes` | `notes` | analyst annotation; non-null means a human reviewed this record |
| `raw_sms_body` | `source.raw_sms_body` | privileged only |
| `sms_hash` | `source.sms_hash` | privileged only |
| `processed_at` | `source.processed_at` | |

### `transaction_participants` → `transaction.participants[]` *(junction)*

| Column | JSON path | Notes |
|---|---|---|
| `participation_id` | *(not serialised)* | internal surrogate key |
| `transaction_id` | *(implicit)* | it is the parent object |
| `user_id` | `participants[].user_id` | |
| *(joined)* | `participants[].party_ref`, `.full_name`, `.masked_ref` | from `users` |
| `role` | `participants[].role` | **the relationship's own attribute** |
| `party_label` | `participants[].party_label` | name as printed in this SMS |

### `tags` + `transaction_tags` → `transaction.tags[]` *(junction)*

| Column | JSON path | Notes |
|---|---|---|
| `tags.tag_id` | `tags[].tag_id` | |
| `tags.tag_name` | `tags[].name` | |
| `tags.tag_type` | `tags[].type` | |
| `tags.description` | `tags[].description` | |
| `transaction_tags.confidence` | `tags[].confidence` | **relationship attribute** |
| `transaction_tags.tagged_by` | `tags[].tagged_by` | **relationship attribute** |
| `transaction_tags.tagged_at` | `tags[].tagged_at` | **relationship attribute** |

### `system_logs` → `transaction.processing_log[]`

| Column | JSON path | Notes |
|---|---|---|
| `log_id` | `log_id` | |
| `transaction_id` | `transaction_id` | `null` for messages that never became a transaction |
| `stage` | `stage` | |
| `event_type` | `event_type` | what a client should filter on, because it is indexed, the free-text `message` is not |
| `log_level` | `level` | renamed, `log_level` is redundant inside a log object |
| `message` | `message` | |
| `source_file`, `record_ref` | same names | dead-letter replay pointers |
| `records_affected` | `records_affected` | |
| `ip_address` | `ip_address` | nullable |
| `created_at` | `created_at` | ISO-8601 |

---

## API response shapes

| Endpoint | Example in `json_schemas.json` | Shape |
|---|---|---|
| `GET /transactions/{id}` | `examples.complete_transaction` | full nested object, all seven tables |
| `GET /transactions` | `examples.transaction_list_response` | compact list, tags collapse to names, `source` dropped, plus `pagination` |
| `GET /analytics/by-category` | `examples.analytics_response` | serialises the `v_category_totals` view |
| any write conflict | `examples.error_response_duplicate` | `409` carrying `db_constraint: uq_transactions_sms_hash` |
| any validation failure | `examples.error_response_validation` | `422` carrying `db_constraint: chk_transactions_amount_positive` |

The two error shapes deliberately surface the name of the database constraint
that rejected the write. That lets a client tell a duplicate from a bad value
without parsing an error string, and it keeps the database as the single source
of truth for what is valid.
