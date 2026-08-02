-- Migration: add book-level scale parameters
-- 2026-06-13: estimated_length + words_per_chapter

ALTER TABLE book ADD COLUMN IF NOT EXISTS estimated_length TEXT DEFAULT '中';
ALTER TABLE book ADD COLUMN IF NOT EXISTS words_per_chapter TEXT DEFAULT '2000-2500';
