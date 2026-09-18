import os
import uuid

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from services.rag.clients.db.postgres import PgClient


@pytest.fixture
def isolated_pg():
    url = os.environ.get("TEST_DATABASE_URL", "postgresql://rag:rag@127.0.0.1:5432/rag_test")
    schema = "presign_" + uuid.uuid4().hex
    with psycopg.connect(url, autocommit=True, connect_timeout=3) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        client = PgClient(make_conninfo(url, options=f"-c search_path={schema}"))
        try:
            client.initialize()
            yield client
        finally:
            client.close()
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
