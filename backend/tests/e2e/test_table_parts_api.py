import uuid

import pytest

from api.runtime import runtime


pytestmark = pytest.mark.e2e


class TestTablePartsAPI:
    def test_client_table_parts_api_returns_table_chunks(self, app_api_client):
        file_id = str(uuid.uuid4())
        with runtime.application.store.app_context(app_api_client.app_id):
            runtime.application.store.add_file_chunks(
                [
                    {
                        "id": str(uuid.uuid4()),
                        "content": "表格第二片",
                        "metadata": {
                            "filename": "table.pdf",
                            "chunk_index": 2,
                            "s3_url": "s3://rag/table.pdf",
                            "content_type": "table",
                            "table_id": "table_1",
                            "table_part_index": 1,
                            "table_part_count": 2,
                        },
                    },
                    {
                        "id": str(uuid.uuid4()),
                        "content": "普通文本",
                        "metadata": {
                            "filename": "table.pdf",
                            "chunk_index": 1,
                            "s3_url": "s3://rag/table.pdf",
                            "content_type": "text",
                        },
                    },
                    {
                        "id": str(uuid.uuid4()),
                        "content": "表格第一片",
                        "metadata": {
                            "filename": "table.pdf",
                            "chunk_index": 0,
                            "s3_url": "s3://rag/table.pdf",
                            "content_type": "table",
                            "table_id": "table_1",
                            "table_part_index": 0,
                            "table_part_count": 2,
                        },
                    },
                    {
                        "id": str(uuid.uuid4()),
                        "content": "另一张表",
                        "metadata": {
                            "filename": "table.pdf",
                            "chunk_index": 3,
                            "s3_url": "s3://rag/table.pdf",
                            "content_type": "table",
                            "table_id": "table_2",
                            "table_part_index": 0,
                            "table_part_count": 1,
                        },
                    },
                ],
                file_id=file_id,
            )

        resp = app_api_client.post("/api/open/tables/parts", json={"file_id": file_id, "table_id": "table_1"})

        assert resp.status_code == 200, resp.text
        assert resp.json() == {
            "file_id": file_id,
            "table_id": "table_1",
            "parts": [
                {"table_part_index": 0, "table_part_count": 2, "chunk_index": 0, "content": "表格第一片"},
                {"table_part_index": 1, "table_part_count": 2, "chunk_index": 2, "content": "表格第二片"},
            ],
        }

    def test_table_parts_api_returns_table_chunks(self, app_api_client, api_client):
        file_id = str(uuid.uuid4())
        with runtime.application.store.app_context(app_api_client.app_id):
            runtime.application.store.add_file_chunks(
                [
                    {
                        "id": str(uuid.uuid4()),
                        "content": "表格内容",
                        "metadata": {
                            "filename": "table.pdf",
                            "chunk_index": 0,
                            "s3_url": "s3://rag/table.pdf",
                            "content_type": "table",
                            "table_id": "table_1",
                            "table_part_index": 0,
                            "table_part_count": 1,
                        },
                    },
                ],
                file_id=file_id,
            )

        resp = api_client.post("/api/tables/parts", json={"app_id": app_api_client.app_id, "file_id": file_id, "table_id": "table_1"})

        assert resp.status_code == 200, resp.text
        assert resp.json()["parts"] == [{"table_part_index": 0, "table_part_count": 1, "chunk_index": 0, "content": "表格内容"}]
