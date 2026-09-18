SELECT 'CREATE DATABASE rag OWNER rag'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'rag')\gexec

SELECT 'CREATE DATABASE rag_test OWNER rag'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'rag_test')\gexec

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

INSERT INTO apps (app_id, api_key, presign_config)
VALUES (
    'imsdom',
    'bk_sOximdu9G4KyfSXklZvp4SPPe2iZLSu3Gh6AJLQ2a_E',
    '{
  "url": "http://127.0.0.1:6000/api/v1/rag/presign",
  "method": "POST",
  "headers": {
    "Content-Type": "application/json",
    "Authorization": "Bearer bk_sOximdu9G4KyfSXklZvp4SPPe2iZLSu3Gh6AJLQ2a_E"
  },
  "params": {},
  "body": {
    "s3_url": {{ s3_url | tojson }}
  },
  "response_url_path": "presigned_url"
}'
)
ON CONFLICT (app_id) DO UPDATE
SET api_key = EXCLUDED.api_key,
    presign_config = CASE
        WHEN apps.presign_config IS NULL OR apps.presign_config = '' THEN EXCLUDED.presign_config
        ELSE apps.presign_config
    END,
    updated_at = now();
