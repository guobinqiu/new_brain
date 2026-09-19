from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[4]


def test_app_and_infra_deployments_are_separate():
    app = yaml.safe_load((ROOT / "deploy/deploy.yaml").read_text())
    infra = yaml.safe_load((ROOT / "deploy/infra.yaml").read_text())
    assert set(app["services"]) == {"rag", "parser", "inference", "llm"}
    assert set(infra["services"]) == {
        "postgres", "qdrant", "minio", "loki", "promtail", "etcd", "milvus",
        "tei_dense", "tei_rerank", "vllm_dense", "vllm_rerank",
    }
    for document, group in ((app, "app"), (infra, "infra")):
        assert all(service["deploy"]["labels"]["group"] == group for service in document["services"].values())
        assert document["networks"]["default"] == {"name": "brain-net", "external": True}
