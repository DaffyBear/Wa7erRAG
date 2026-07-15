CREATE TABLE IF NOT EXISTS sessions (
    session_id VARCHAR(64) PRIMARY KEY,
    title VARCHAR(255) NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS messages (
    message_id VARCHAR(64) PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL,
    query TEXT NOT NULL,
    rewritten_query TEXT NOT NULL,
    answer TEXT NOT NULL,
    retrieved_documents JSONB NOT NULL DEFAULT '[]'::jsonb,
    timings_ms JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_messages_session_created ON messages(session_id, created_at);

CREATE TABLE IF NOT EXISTS feedback (
    feedback_id VARCHAR(64) PRIMARY KEY,
    message_id VARCHAR(64) NOT NULL REFERENCES messages(message_id),
    value SMALLINT NOT NULL CHECK (value IN (-1, 1)),
    reason TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_feedback_message ON feedback(message_id);