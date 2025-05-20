-- Flyway migration script based on init_database in http_reader.py

-- Create kbk_ic_manager table
CREATE TABLE IF NOT EXISTS kbk_ic_manager (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user TEXT NOT NULL,
    card TEXT NOT NULL UNIQUE,
    department TEXT NOT NULL,
    status INTEGER NOT NULL DEFAULT 0,
    last_updated TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Create index on kbk_ic_manager.card
CREATE INDEX IF NOT EXISTS idx_card ON kbk_ic_manager(card);

-- Create kbk_ic_en_count table
CREATE TABLE IF NOT EXISTS kbk_ic_en_count (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user TEXT NOT NULL,
    department TEXT NOT NULL,
    transaction_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Create kbk_ic_cn_count table
CREATE TABLE IF NOT EXISTS kbk_ic_cn_count (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user TEXT NOT NULL,
    department TEXT NOT NULL,
    transaction_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Create kbk_ic_nm_count table
CREATE TABLE IF NOT EXISTS kbk_ic_nm_count (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user TEXT NOT NULL,
    department TEXT NOT NULL,
    transaction_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Create kbk_ic_failure_records table
CREATE TABLE IF NOT EXISTS kbk_ic_failure_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user TEXT,
    department TEXT,
    transaction_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    failure_type INTEGER NOT NULL
);