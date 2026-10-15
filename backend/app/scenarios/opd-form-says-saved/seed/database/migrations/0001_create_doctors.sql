-- 0001: doctors of the OPD
CREATE TABLE doctors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    department TEXT NOT NULL,
    phone TEXT NOT NULL,
    email TEXT NOT NULL,
    consultation_fee REAL NOT NULL,
    room TEXT NOT NULL,
    availability TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (email)
);
