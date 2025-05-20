CREATE TABLE kbk_ic_manager (
    user TEXT NOT NULL PRIMARY KEY,
    card TEXT UNIQUE,
    department TEXT,
    status INTEGER,
    last_updated TEXT
);