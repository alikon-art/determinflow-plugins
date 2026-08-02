-- 小说生产 API 产品化数据库重构
-- 测试环境直接重构：删除 chapter.version / chapter.is_latest / polish_record。

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- book 补产品化字段
ALTER TABLE book ADD COLUMN IF NOT EXISTS external_ref TEXT;
ALTER TABLE book ADD COLUMN IF NOT EXISTS genre TEXT;
UPDATE book SET status = 'draft' WHERE status IS NULL;
UPDATE book SET style_profile = '{}'::jsonb WHERE style_profile IS NULL;
UPDATE book SET story_plan = '{}'::jsonb WHERE story_plan IS NULL;
UPDATE book SET settings = '{}'::jsonb WHERE settings IS NULL;
ALTER TABLE book ALTER COLUMN status SET DEFAULT 'draft';
ALTER TABLE book ALTER COLUMN status SET NOT NULL;
ALTER TABLE book ALTER COLUMN style_profile SET DEFAULT '{}'::jsonb;
ALTER TABLE book ALTER COLUMN story_plan SET DEFAULT '{}'::jsonb;
ALTER TABLE book ALTER COLUMN settings SET DEFAULT '{}'::jsonb;
ALTER TABLE book ALTER COLUMN settings SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_book_external_ref
ON book(external_ref)
WHERE external_ref IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_book_updated_at ON book(updated_at DESC);

-- world 默认值
UPDATE world SET core_laws = '{}'::jsonb WHERE core_laws IS NULL;
UPDATE world SET space_time = '{}'::jsonb WHERE space_time IS NULL;
UPDATE world SET society = '{}'::jsonb WHERE society IS NULL;
UPDATE world SET history_culture = '{}'::jsonb WHERE history_culture IS NULL;
UPDATE world SET existence = '{}'::jsonb WHERE existence IS NULL;
UPDATE world SET information = '{}'::jsonb WHERE information IS NULL;
ALTER TABLE world ALTER COLUMN core_laws SET DEFAULT '{}'::jsonb;
ALTER TABLE world ALTER COLUMN space_time SET DEFAULT '{}'::jsonb;
ALTER TABLE world ALTER COLUMN society SET DEFAULT '{}'::jsonb;
ALTER TABLE world ALTER COLUMN history_culture SET DEFAULT '{}'::jsonb;
ALTER TABLE world ALTER COLUMN existence SET DEFAULT '{}'::jsonb;
ALTER TABLE world ALTER COLUMN information SET DEFAULT '{}'::jsonb;

-- character 补 true_name 与默认值
ALTER TABLE character ADD COLUMN IF NOT EXISTS true_name TEXT;
UPDATE character SET aliases = '[]'::jsonb WHERE aliases IS NULL;
UPDATE character SET deep_fear = '{}'::jsonb WHERE deep_fear IS NULL;
UPDATE character SET secrets = '[]'::jsonb WHERE secrets IS NULL;
UPDATE character SET bottom_line = '{}'::jsonb WHERE bottom_line IS NULL;
UPDATE character SET traumas = '[]'::jsonb WHERE traumas IS NULL;
UPDATE character SET contradictions = '{}'::jsonb WHERE contradictions IS NULL;
UPDATE character SET arc_description = '{}'::jsonb WHERE arc_description IS NULL;
UPDATE character SET world_position = '{}'::jsonb WHERE world_position IS NULL;
UPDATE character SET beliefs = '{}'::jsonb WHERE beliefs IS NULL;
UPDATE character SET extras = '{}'::jsonb WHERE extras IS NULL;
UPDATE character SET voice = '{}'::jsonb WHERE voice IS NULL;
ALTER TABLE character ALTER COLUMN aliases SET DEFAULT '[]'::jsonb;
ALTER TABLE character ALTER COLUMN voice SET DEFAULT '{}'::jsonb;
CREATE UNIQUE INDEX IF NOT EXISTS idx_character_book_name ON character(book_id, name);
CREATE INDEX IF NOT EXISTS idx_character_book_role ON character(book_id, role);

-- outline 去掉 version，真相表只保存最新状态
ALTER TABLE outline DROP COLUMN IF EXISTS version;
ALTER TABLE outline ALTER COLUMN volume_number SET DEFAULT 1;
UPDATE outline SET volume_number = 1 WHERE volume_number IS NULL;
UPDATE outline SET content = '{}'::jsonb WHERE content IS NULL;
ALTER TABLE outline ALTER COLUMN content SET DEFAULT '{}'::jsonb;
CREATE UNIQUE INDEX IF NOT EXISTS idx_outline_book_type_volume ON outline(book_id, type, volume_number);
CREATE INDEX IF NOT EXISTS idx_outline_book_type ON outline(book_id, type);

-- chapter 去版本化：先保留每个 book/chapter 的最近一行。
-- 注意：本脚本需支持字段删除后重复执行，因此这里不引用 version/is_latest。
DELETE FROM chapter c
USING chapter keep
WHERE c.book_id = keep.book_id
  AND c.chapter_number = keep.chapter_number
  AND c.id <> keep.id
  AND keep.id = (
      SELECT c2.id
      FROM chapter c2
      WHERE c2.book_id = c.book_id
        AND c2.chapter_number = c.chapter_number
      ORDER BY c2.updated_at DESC NULLS LAST, c2.created_at DESC NULLS LAST, c2.id DESC
      LIMIT 1
  );

UPDATE chapter SET status = 'draft' WHERE status IS NULL;
UPDATE chapter SET word_count = COALESCE(length(body), 0) WHERE word_count IS NULL;
UPDATE chapter SET guide = '{}'::jsonb WHERE guide IS NULL;
UPDATE chapter SET storyboard = '{}'::jsonb WHERE storyboard IS NULL;
UPDATE chapter SET world_state = '{}'::jsonb WHERE world_state IS NULL;
UPDATE chapter SET world_events = '{}'::jsonb WHERE world_events IS NULL;
UPDATE chapter SET character_state = '{}'::jsonb WHERE character_state IS NULL;
UPDATE chapter SET character_minor = '{}'::jsonb WHERE character_minor IS NULL;
UPDATE chapter SET world_rulings = '{}'::jsonb WHERE world_rulings IS NULL;
UPDATE chapter SET story_confirmed = '{}'::jsonb WHERE story_confirmed IS NULL;
UPDATE chapter SET character_diff = '{}'::jsonb WHERE character_diff IS NULL;
ALTER TABLE chapter DROP COLUMN IF EXISTS version;
ALTER TABLE chapter DROP COLUMN IF EXISTS is_latest;
ALTER TABLE chapter ALTER COLUMN status SET DEFAULT 'draft';
ALTER TABLE chapter ALTER COLUMN word_count SET DEFAULT 0;
ALTER TABLE chapter ALTER COLUMN guide SET DEFAULT '{}'::jsonb;
ALTER TABLE chapter ALTER COLUMN storyboard SET DEFAULT '{}'::jsonb;
ALTER TABLE chapter ALTER COLUMN world_state SET DEFAULT '{}'::jsonb;
ALTER TABLE chapter ALTER COLUMN world_events SET DEFAULT '{}'::jsonb;
ALTER TABLE chapter ALTER COLUMN character_state SET DEFAULT '{}'::jsonb;
ALTER TABLE chapter ALTER COLUMN character_minor SET DEFAULT '{}'::jsonb;
ALTER TABLE chapter ALTER COLUMN world_rulings SET DEFAULT '{}'::jsonb;
ALTER TABLE chapter ALTER COLUMN story_confirmed SET DEFAULT '{}'::jsonb;
ALTER TABLE chapter ALTER COLUMN character_diff SET DEFAULT '{}'::jsonb;
CREATE UNIQUE INDEX IF NOT EXISTS idx_chapter_book_number_unique ON chapter(book_id, chapter_number);
CREATE INDEX IF NOT EXISTS idx_chapter_book_updated ON chapter(book_id, updated_at DESC);

-- hook/debt 默认值与约束
UPDATE hook SET content = '{}'::jsonb WHERE content IS NULL;
ALTER TABLE hook ALTER COLUMN content SET DEFAULT '{}'::jsonb;
CREATE UNIQUE INDEX IF NOT EXISTS idx_hook_book_item ON hook(book_id, item_id);
CREATE INDEX IF NOT EXISTS idx_hook_book_status ON hook(book_id, status);

UPDATE debt SET content = '{}'::jsonb WHERE content IS NULL;
ALTER TABLE debt ALTER COLUMN content SET DEFAULT '{}'::jsonb;
CREATE UNIQUE INDEX IF NOT EXISTS idx_debt_book_item ON debt(book_id, item_id);
CREATE INDEX IF NOT EXISTS idx_debt_book_status ON debt(book_id, status);

-- 删除旧润色记录表
DROP TABLE IF EXISTS polish_record;

-- 资源状态表
CREATE TABLE IF NOT EXISTS novel_resource_state (
    book_id                 UUID NOT NULL REFERENCES book(id) ON DELETE CASCADE,
    resource_type           TEXT NOT NULL,
    resource_key            TEXT NOT NULL,
    current_version         INTEGER NOT NULL DEFAULT 1,
    current_revision_id     UUID,
    content_hash            TEXT,
    created_at              TIMESTAMPTZ DEFAULT now(),
    updated_at              TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (book_id, resource_type, resource_key)
);
CREATE INDEX IF NOT EXISTS idx_resource_state_book ON novel_resource_state(book_id, resource_type);

-- 资源修订表
CREATE TABLE IF NOT EXISTS novel_resource_revision (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    book_id             UUID NOT NULL REFERENCES book(id) ON DELETE CASCADE,
    resource_type       TEXT NOT NULL,
    resource_key        TEXT NOT NULL,
    version             INTEGER NOT NULL,
    base_version        INTEGER,
    edit_mode           TEXT NOT NULL DEFAULT 'replace',
    source              TEXT NOT NULL,
    source_detail       TEXT,
    edit_intensity      TEXT,
    diff_stats          JSONB NOT NULL DEFAULT '{}',
    actor_ref           TEXT,
    request_id          TEXT,
    job_id              UUID,
    workflow_id         TEXT,
    workflow_task_id    TEXT,
    before_content      JSONB,
    after_content       JSONB,
    diff                JSONB,
    summary             TEXT,
    reason              TEXT,
    metadata            JSONB NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ DEFAULT now(),
    UNIQUE (book_id, resource_type, resource_key, version)
);
CREATE INDEX IF NOT EXISTS idx_revision_book_resource
ON novel_resource_revision(book_id, resource_type, resource_key, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_revision_source
ON novel_resource_revision(book_id, source, created_at DESC);

-- Novel Job 表
CREATE TABLE IF NOT EXISTS novel_job (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    book_id             UUID NOT NULL REFERENCES book(id) ON DELETE CASCADE,
    operation           TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'queued',
    current_stage       TEXT,
    progress            NUMERIC DEFAULT 0,
    workflow_id         TEXT NOT NULL,
    workflow_task_id    TEXT NOT NULL,
    request_payload     JSONB NOT NULL DEFAULT '{}',
    result_payload      JSONB NOT NULL DEFAULT '{}',
    error               JSONB NOT NULL DEFAULT '{}',
    idempotency_key     TEXT,
    actor_ref           TEXT,
    request_id          TEXT,
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_novel_job_book ON novel_job(book_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_novel_job_workflow_task ON novel_job(workflow_id, workflow_task_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_novel_job_idempotency
ON novel_job(book_id, operation, idempotency_key)
WHERE idempotency_key IS NOT NULL;

-- Novel Job 事件表
CREATE TABLE IF NOT EXISTS novel_job_event (
    id              BIGSERIAL PRIMARY KEY,
    job_id          UUID NOT NULL REFERENCES novel_job(id) ON DELETE CASCADE,
    event_type      TEXT NOT NULL,
    stage_id        TEXT,
    stage_name      TEXT,
    progress        NUMERIC,
    payload         JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_novel_job_event_job ON novel_job_event(job_id, id);

COMMIT;
