# File paths and categories for the ETL

XML_FILE = "data/raw/modified_sms_v2.xml"
JSON_FILE = "data/processed/dashboard.json"
LOG_FILE = "data/logs/etl.log"
DEAD_LETTER_DIR = "data/logs/dead_letter"

# MySQL connection. Override via the environment in deployment; never commit
# real credentials. See section 6 of database/database_setup.sql.
DB_HOST = "localhost"
DB_NAME = "momo_sms_db"
DB_USER = "momo_app"

# Transaction categories.
#
# These codes are the single source of truth: database_setup.sql seeds
# transaction_categories from this exact list, so the Python pipeline and the
# database cannot drift apart. Changing a code here means changing the seed
# data too.
CATEGORIES = [
    "INCOMING_TRANSFER",
    "OUTGOING_TRANSFER",
    "PAYMENT_MERCHANT",
    "AIRTIME_PURCHASE",
    "BANK_DEPOSIT",
    "CASH_IN",
    "CASH_OUT",
    "UTILITY_PAYMENT",
    "INTERNATIONAL_IN",
    "REVERSAL",
]

# The sample dataset labels transactions with its own vocabulary. This maps
# those values onto the categories above.
XML_TYPE_TO_CATEGORY = {
    "incoming_money": "INCOMING_TRANSFER",
    "payment": "PAYMENT_MERCHANT",
    "transfer": "OUTGOING_TRANSFER",
    "airtime": "AIRTIME_PURCHASE",
}
