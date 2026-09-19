import base64
import hashlib
import hmac
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from services.ops.app.main import create_app


class FakeServices:
    def __init__(self):
        self.rollouts = []
        self.deploys = []
        self.removes = []
        self.scales = []

    def list_services(self):
        return [{"name": "brain_inference", "running": 1, "desired": 1, "ports": []}]

    def start(self, service):
        return {"service": service, "action": "start"}

    def stop(self, service):
        return {"service": service, "action": "stop"}

    def scale(self, service, replicas):
        self.scales.append((service, replicas))
        return {"service": service, "action": "scale", "replicas": replicas}

    def rollout(self, service):
        self.rollouts.append(service)
        return {"service": service, "action": "rollout"}

    def deploy_stack(self, target="app"):
        self.deploys.append("stack" if target == "app" else target)
        return {"action": "deploy", "stack": "brain" if target == "app" else "brain_infra"}

    def remove_stack(self, target="app"):
        self.removes.append("stack" if target == "app" else target)
        return {"action": "remove", "stack": "brain" if target == "app" else "brain_infra"}

    def list_tasks(self, service):
        return []

    def logs(self, service, tail=200):
        return ""

    def list_nodes(self):
        return []

    def join_command(self, role):
        return f"docker swarm join --token token-{role} manager:2377"


class FakeConfigs:
    def __init__(self):
        self.content = "embedded:\n  enable: true\n"
        self.service = "brain_inference"
        self.requires_deploy = False

    def list(self):
        return [{"name": "inference", "path": "services/inference/config/inference.yaml", "service": "brain_inference", "requires_deploy": False}]

    def read(self, name):
        return SimpleNamespace(
            name=name,
            path="services/inference/config/inference.yaml",
            service=self.service,
            requires_deploy=self.requires_deploy,
            content=self.content,
        )

    def validate(self, name, content):
        return None

    def write(self, name, content):
        self.content = content
        return self.read(name)


def test_ops_api_requires_admin_jwt(monkeypatch):
    monkeypatch.setenv("RAG_ADMIN_PASSWORD", "secret")
    app = create_app(services=FakeServices(), configs=FakeConfigs())
    client = TestClient(app)

    response = client.get("/api/ops/services")

    assert response.status_code == 401


def test_ops_api_accepts_admin_jwt(monkeypatch):
    monkeypatch.setenv("RAG_ADMIN_PASSWORD", "secret")
    app = create_app(services=FakeServices(), configs=FakeConfigs())
    client = TestClient(app)

    response = client.get("/api/ops/services", headers={"Authorization": f"Bearer {_token('secret')}"})

    assert response.status_code == 200
    assert response.json()["services"][0]["name"] == "brain_inference"


def test_saving_config_only_writes_file(monkeypatch):
    monkeypatch.setenv("RAG_ADMIN_PASSWORD", "secret")
    services = FakeServices()
    app = create_app(services=services, configs=FakeConfigs())
    client = TestClient(app)

    response = client.put(
        "/api/ops/configs/inference",
        headers={"Authorization": f"Bearer {_token('secret')}"},
        json={"content": "tei:\n  enable: true\n"},
    )

    assert response.status_code == 200
    assert response.json()["service"] == "brain_inference"
    assert "rollout" not in response.json()
    assert services.rollouts == []


def test_applying_service_config_rolls_out_owning_service(monkeypatch):
    monkeypatch.setenv("RAG_ADMIN_PASSWORD", "secret")
    services = FakeServices()
    app = create_app(services=services, configs=FakeConfigs())
    client = TestClient(app)

    response = client.post(
        "/api/ops/configs/apply",
        headers={"Authorization": f"Bearer {_token('secret')}"},
        json={"name": "inference"},
    )

    assert response.status_code == 200
    assert response.json()["service"] == "brain_inference"
    assert response.json()["rollout"] == {"service": "brain_inference", "action": "rollout"}
    assert services.rollouts == ["brain_inference"]


def test_saving_deploy_config_only_marks_deploy_required(monkeypatch):
    monkeypatch.setenv("RAG_ADMIN_PASSWORD", "secret")
    services = FakeServices()
    configs = FakeConfigs()
    configs.service = None
    configs.requires_deploy = True
    app = create_app(services=services, configs=configs)
    client = TestClient(app)

    response = client.put(
        "/api/ops/configs/deploy",
        headers={"Authorization": f"Bearer {_token('secret')}"},
        json={"content": "services:\n  rag:\n    image: brain-rag:dev\n"},
    )

    assert response.status_code == 200
    assert response.json()["service"] is None
    assert response.json()["deploy_required"] is True
    assert "deploy" not in response.json()
    assert "rollout" not in response.json()
    assert services.rollouts == []
    assert services.deploys == []


def test_applying_deploy_config_deploys_stack(monkeypatch):
    monkeypatch.setenv("RAG_ADMIN_PASSWORD", "secret")
    services = FakeServices()
    configs = FakeConfigs()
    configs.service = None
    configs.requires_deploy = True
    app = create_app(services=services, configs=configs)
    client = TestClient(app)

    response = client.post(
        "/api/ops/configs/apply",
        headers={"Authorization": f"Bearer {_token('secret')}"},
        json={"name": "deploy"},
    )

    assert response.status_code == 200
    assert response.json()["service"] is None
    assert response.json()["deploy"] == {"action": "deploy", "stack": "brain"}
    assert services.deploys == ["stack"]


def test_stack_deploy_endpoint_deploys_stack(monkeypatch):
    monkeypatch.setenv("RAG_ADMIN_PASSWORD", "secret")
    services = FakeServices()
    app = create_app(services=services, configs=FakeConfigs())
    client = TestClient(app)

    response = client.post(
        "/api/ops/stack/deploy",
        headers={"Authorization": f"Bearer {_token('secret')}"},
    )

    assert response.status_code == 200
    assert response.json() == {"action": "deploy", "stack": "brain"}
    assert services.deploys == ["stack"]


def test_stack_remove_endpoint_removes_stack(monkeypatch):
    monkeypatch.setenv("RAG_ADMIN_PASSWORD", "secret")
    services = FakeServices()
    app = create_app(services=services, configs=FakeConfigs())
    client = TestClient(app)

    response = client.post(
        "/api/ops/stack/remove",
        headers={"Authorization": f"Bearer {_token('secret')}"},
    )

    assert response.status_code == 200
    assert response.json() == {"action": "remove", "stack": "brain"}
    assert services.removes == ["stack"]


def test_scale_endpoint_sets_service_replicas(monkeypatch):
    monkeypatch.setenv("RAG_ADMIN_PASSWORD", "secret")
    services = FakeServices()
    app = create_app(services=services, configs=FakeConfigs())
    client = TestClient(app)

    response = client.post(
        "/api/ops/services/scale",
        headers={"Authorization": f"Bearer {_token('secret')}"},
        json={"service": "inference", "replicas": 3},
    )

    assert response.status_code == 200
    assert response.json() == {"service": "inference", "action": "scale", "replicas": 3}
    assert services.scales == [("inference", 3)]


def test_infra_publish_remove_and_apply_do_not_deploy_apps(monkeypatch):
    monkeypatch.setenv("RAG_ADMIN_PASSWORD", "secret")
    services = FakeServices()
    configs = FakeConfigs()
    configs.service = None
    configs.requires_deploy = True
    client = TestClient(create_app(services=services, configs=configs))
    headers = {"Authorization": f"Bearer {_token('secret')}"}

    response = client.post("/api/ops/stack/deploy?target=infra", headers=headers)
    assert response.status_code == 200
    assert response.json()["stack"] == "brain_infra"
    response = client.post("/api/ops/stack/remove?target=infra", headers=headers)
    assert response.status_code == 200
    assert response.json()["stack"] == "brain_infra"
    response = client.post("/api/ops/configs/apply", headers=headers, json={"name": "infra"})
    assert response.status_code == 200
    assert response.json()["deploy"]["stack"] == "brain_infra"
    assert services.deploys == ["infra", "infra"]
    assert services.removes == ["infra"]


def test_unknown_deployment_target_is_rejected(monkeypatch):
    monkeypatch.setenv("RAG_ADMIN_PASSWORD", "secret")
    services = FakeServices()
    client = TestClient(create_app(services=services, configs=FakeConfigs()))
    response = client.post("/api/ops/stack/deploy?target=unknown", headers={"Authorization": f"Bearer {_token('secret')}"})
    assert response.status_code == 422
    assert services.deploys == []


def _token(password: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"type": "admin", "app_id": ""}
    signing_input = ".".join([_b64_json(header), _b64_json(payload)])
    signature = hmac.new(hashlib.sha256(password.encode("utf-8")).digest(), signing_input.encode("utf-8"), hashlib.sha256).digest()
    return ".".join([signing_input, _b64(signature)])


def _b64_json(value: dict) -> str:
    return _b64(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")
