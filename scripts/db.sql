SELECT 'CREATE DATABASE rag OWNER rag'
WHERE NOT EXISTS (
    SELECT 1 FROM pg_database WHERE datname = 'rag'
)\gexec
