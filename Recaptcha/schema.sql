-- Run this in Supabase SQL Editor (https://supabase.com/dashboard → SQL Editor)

CREATE TABLE IF NOT EXISTS fetch_batches (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    year TEXT,
    scheme TEXT,
    semester TEXT,
    department TEXT,
    subjects JSONB DEFAULT '[]',
    credits JSONB DEFAULT '{}',
    student_count INTEGER DEFAULT 0,
    usn_prefix TEXT,
    run_id TEXT,
    saved_at TIMESTAMPTZ DEFAULT now(),
    credits_updated_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS student_results (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    batch_id TEXT REFERENCES fetch_batches(id) ON DELETE CASCADE,
    usn TEXT,
    name TEXT,
    subjects JSONB DEFAULT '[]',
    percentage REAL,
    sgpa REAL,
    result_status TEXT
);

CREATE INDEX IF NOT EXISTS idx_students_batch ON student_results(batch_id);
CREATE INDEX IF NOT EXISTS idx_students_usn ON student_results(usn);
