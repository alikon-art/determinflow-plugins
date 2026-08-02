-- Foundational tables required before the historical product-schema upgrades.
-- Keep this migration additive: existing installations are adopted separately
-- and are never treated as valid merely because CREATE IF NOT EXISTS succeeds.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS book (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    status TEXT DEFAULT 'draft',
    style_profile JSONB NOT NULL DEFAULT '{}'::jsonb,
    story_plan JSONB NOT NULL DEFAULT '{}'::jsonb,
    settings JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS world (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    book_id UUID NOT NULL REFERENCES book(id) ON DELETE CASCADE UNIQUE,
    core_laws JSONB NOT NULL DEFAULT '{}'::jsonb,
    space_time JSONB NOT NULL DEFAULT '{}'::jsonb,
    society JSONB NOT NULL DEFAULT '{}'::jsonb,
    history_culture JSONB NOT NULL DEFAULT '{}'::jsonb,
    existence JSONB NOT NULL DEFAULT '{}'::jsonb,
    information JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS character (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    book_id UUID NOT NULL REFERENCES book(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    gender TEXT,
    age TEXT,
    aliases JSONB NOT NULL DEFAULT '[]'::jsonb,
    surface_goal TEXT,
    deep_desire TEXT,
    deep_fear JSONB DEFAULT '{}'::jsonb,
    secrets JSONB DEFAULT '[]'::jsonb,
    bottom_line JSONB DEFAULT '{}'::jsonb,
    traumas JSONB DEFAULT '[]'::jsonb,
    contradictions JSONB DEFAULT '{}'::jsonb,
    arc_description JSONB DEFAULT '{}'::jsonb,
    world_position JSONB DEFAULT '{}'::jsonb,
    beliefs JSONB DEFAULT '{}'::jsonb,
    extras JSONB DEFAULT '{}'::jsonb,
    voice JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (book_id, name)
);

CREATE TABLE IF NOT EXISTS outline (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    book_id UUID NOT NULL REFERENCES book(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    volume_number INTEGER NOT NULL DEFAULT 1,
    chapter_start INTEGER,
    chapter_end INTEGER,
    content JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (book_id, type, volume_number)
);

CREATE TABLE IF NOT EXISTS chapter (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    book_id UUID NOT NULL REFERENCES book(id) ON DELETE CASCADE,
    chapter_number INTEGER NOT NULL,
    title TEXT,
    body TEXT,
    word_count INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'draft',
    guide JSONB DEFAULT '{}'::jsonb,
    world_state JSONB DEFAULT '{}'::jsonb,
    world_events JSONB DEFAULT '{}'::jsonb,
    storyboard JSONB DEFAULT '{}'::jsonb,
    character_state JSONB DEFAULT '{}'::jsonb,
    character_minor JSONB DEFAULT '{}'::jsonb,
    world_rulings JSONB DEFAULT '{}'::jsonb,
    story_confirmed JSONB DEFAULT '{}'::jsonb,
    character_diff JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (book_id, chapter_number)
);

CREATE TABLE IF NOT EXISTS hook (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    book_id UUID NOT NULL REFERENCES book(id) ON DELETE CASCADE,
    item_id TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    chapter_created INTEGER,
    chapter_resolved INTEGER,
    expected_payoff TEXT,
    last_advanced INTEGER,
    source TEXT,
    content JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (book_id, item_id)
);

CREATE TABLE IF NOT EXISTS debt (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    book_id UUID NOT NULL REFERENCES book(id) ON DELETE CASCADE,
    item_id TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    chapter_created INTEGER,
    chapter_resolved INTEGER,
    expected_payoff TEXT,
    last_advanced INTEGER,
    source TEXT,
    from_char TEXT,
    to_char TEXT,
    content JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (book_id, item_id)
);
