CREATE DATABASE rag OWNER rag;
CREATE DATABASE rag_test OWNER rag;

\connect rag

CREATE TABLE IF NOT EXISTS apps (
    app_id VARCHAR(64) PRIMARY KEY,
    api_key VARCHAR(128) NOT NULL UNIQUE,
    presign_config TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 已有应用表增加下载地址请求模板
ALTER TABLE apps ADD COLUMN IF NOT EXISTS presign_config TEXT;
