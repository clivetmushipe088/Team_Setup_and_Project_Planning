# File paths and categories for the ETL

XML_FILE = "data/raw/momo.xml"
DB_FILE = "data/db.sqlite3"
JSON_FILE = "data/processed/dashboard.json"
LOG_FILE = "data/logs/etl.log"
DEAD_LETTER_DIR = "data/logs/dead_letter"

CATEGORIES = [
    "incoming money",
    "payment",
    "transfer",
    "bank deposit",
    "airtime",
    "withdrawal",
    "other",
]
