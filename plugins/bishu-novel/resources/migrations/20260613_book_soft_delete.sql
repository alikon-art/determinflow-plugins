-- Migration: soft delete for books
-- 2026-06-13: deleted_at column

ALTER TABLE book ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
