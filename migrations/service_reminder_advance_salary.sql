ALTER TABLE bookings
ADD COLUMN IF NOT EXISTS reminder_sent_at TEXT;

ALTER TABLE bookings
ADD COLUMN IF NOT EXISTS reminder_snooze_until TEXT;

ALTER TABLE bookings
ADD COLUMN IF NOT EXISTS service_reminder_sent INTEGER NOT NULL DEFAULT 0;

ALTER TABLE salary_records
ADD COLUMN IF NOT EXISTS gross_salary REAL DEFAULT 0;

ALTER TABLE salary_records
ADD COLUMN IF NOT EXISTS pocket_money_deduction REAL DEFAULT 0;

ALTER TABLE salary_records
ADD COLUMN IF NOT EXISTS monthly_advance_entry_count INTEGER DEFAULT 0;

ALTER TABLE salary_records
ADD COLUMN IF NOT EXISTS previous_pending_debt REAL DEFAULT 0;

ALTER TABLE salary_records
ADD COLUMN IF NOT EXISTS debt_recovery_deduction REAL DEFAULT 0;

ALTER TABLE salary_records
ADD COLUMN IF NOT EXISTS remaining_debt_balance REAL DEFAULT 0;

ALTER TABLE salary_records
ADD COLUMN IF NOT EXISTS final_payable_salary REAL DEFAULT 0;

ALTER TABLE salary_records
ADD COLUMN IF NOT EXISTS net_salary REAL DEFAULT 0;

CREATE TABLE IF NOT EXISTS pocket_money_entries (
    id SERIAL PRIMARY KEY,
    worker_id TEXT NOT NULL,
    amount NUMERIC(10,2) NOT NULL,
    entry_date DATE NOT NULL DEFAULT CURRENT_DATE,
    note TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (worker_id) REFERENCES workers(id)
);

CREATE TABLE IF NOT EXISTS worker_debts (
    id SERIAL PRIMARY KEY,
    worker_id TEXT NOT NULL,
    debt_amount NUMERIC(10,2) NOT NULL,
    debt_date DATE NOT NULL DEFAULT CURRENT_DATE,
    reason TEXT,
    remaining_balance NUMERIC(10,2) NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (worker_id) REFERENCES workers(id)
);

CREATE TABLE IF NOT EXISTS debt_recoveries (
    id SERIAL PRIMARY KEY,
    debt_id INTEGER NOT NULL,
    worker_id TEXT NOT NULL,
    salary_record_id INTEGER,
    recovery_amount NUMERIC(10,2) NOT NULL,
    recovery_date DATE NOT NULL DEFAULT CURRENT_DATE,
    note TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (debt_id) REFERENCES worker_debts(id),
    FOREIGN KEY (worker_id) REFERENCES workers(id),
    FOREIGN KEY (salary_record_id) REFERENCES salary_records(id)
);

UPDATE salary_records
SET gross_salary = COALESCE(NULLIF(gross_salary, 0), base_salary, total_salary, 0),
    final_payable_salary = COALESCE(NULLIF(final_payable_salary, 0), total_salary, 0),
    net_salary = COALESCE(NULLIF(net_salary, 0), total_salary, 0);
