-- Runtime columns introduced after the original product schema, plus the
-- database-level single-active-job guarantee used by JobService.

ALTER TABLE character
    ADD COLUMN IF NOT EXISTS essence TEXT;

ALTER TABLE chapter
    ADD COLUMN IF NOT EXISTS post_hoc_status TEXT;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM novel_job
        WHERE status IN ('queued', 'running')
          AND operation <> 'chapter_polish'
        GROUP BY book_id, operation
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION
            'duplicate active Novel jobs exist for the same book and operation';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM novel_job
        WHERE status IN ('queued', 'running')
          AND operation = 'chapter_polish'
        GROUP BY book_id, operation, (request_payload->>'chapter_number')
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION
            'duplicate active chapter-polish jobs exist for the same book and chapter';
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_novel_job_active_operation
ON novel_job(book_id, operation)
WHERE status IN ('queued', 'running')
  AND operation <> 'chapter_polish';

CREATE UNIQUE INDEX IF NOT EXISTS uq_novel_job_active_polish_chapter
ON novel_job(book_id, operation, (request_payload->>'chapter_number'))
NULLS NOT DISTINCT
WHERE status IN ('queued', 'running')
  AND operation = 'chapter_polish';
