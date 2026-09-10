-- Conversations for the chat panel. Messages are stored in OpenAI chat format so a
-- conversation can be replayed to any OpenAI-compatible local model.

CREATE TABLE conversations (
    id          TEXT PRIMARY KEY,
    title       TEXT,
    provider    TEXT,
    model       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE messages (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id  TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role             TEXT NOT NULL,          -- user | assistant | tool
    content          TEXT,
    tool_calls       TEXT,                   -- JSON (assistant)
    tool_call_id     TEXT,                   -- (tool)
    name             TEXT,                   -- tool name (tool)
    usage            TEXT,                   -- JSON {prompt_tokens, completion_tokens}
    created_at       TEXT NOT NULL
);
CREATE INDEX idx_messages_conversation ON messages(conversation_id, id);
