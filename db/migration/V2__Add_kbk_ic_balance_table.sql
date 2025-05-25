-- Migration script to add kbk_ic_balance table

-- Create kbk_ic_balance table
CREATE TABLE IF NOT EXISTS kbk_ic_balance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user TEXT NOT NULL,
    department TEXT NOT NULL,
    balance INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_kbk_ic_balance_user ON kbk_ic_balance(user);
CREATE INDEX IF NOT EXISTS idx_kbk_ic_balance_department ON kbk_ic_balance(department);
CREATE INDEX IF NOT EXISTS idx_kbk_ic_balance_user_dept ON kbk_ic_balance(user, department);
