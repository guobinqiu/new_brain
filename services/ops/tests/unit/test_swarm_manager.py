import pytest

from services.ops.app.swarm_manager import ServiceUpdate, SwarmManager


class FakeDocker:
    def __init__(self):
        self.updates = []

    def list_services(self):
        return [{
            "Spec": {"Name": "brain_inference", "Labels": {"group": "app"}},
            "Endpoint": {"Ports": [{"PublishedPort": 7001, "TargetPort": 7001}]},
        }]

    def list_tasks(self, service_name):
        return [
            {"DesiredState": "running", "Status": {"State": "running"}},
            {"DesiredState": "shutdown", "Status": {"State": "shutdown"}},
        ]

    def inspect_service(self, name):
        return {
            "ID": "svc1",
            "Version": {"Index": 7},
            "Spec": {
                "Name": name,
                "Labels": {"group": self._group(name)},
                "TaskTemplate": {"ForceUpdate": 2},
                "Mode": {"Replicated": {"Replicas": 1}},
            },
        }

    def _group(self, name):
        if name in {"brain_ctrl_ops", "brain_ctrl_nginx"}:
            return "ctrl"
        if name in {"brain_rag", "brain_parser", "brain_inference", "brain_llm"}:
            return "app"
        if name.startswith("brain_"):
            return "infra"
        return None

    def update_service(self, service_id, version, spec):
        self.updates.append(ServiceUpdate(service_id=service_id, version=version, spec=spec))
        return {"Warnings": None}


class FakeRunner:
    def __init__(self):
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        return None


def test_start_and_stop_scale_allowed_service():
    docker = FakeDocker()
    manager = SwarmManager(docker=docker, stack="brain")

    manager.stop("brain_inference")
    manager.start("brain_inference")

    assert docker.updates[0].spec["Mode"]["Replicated"]["Replicas"] == 0
    assert docker.updates[1].spec["Mode"]["Replicated"]["Replicas"] == 1


def test_scale_sets_requested_replicas():
    docker = FakeDocker()
    manager = SwarmManager(docker=docker, stack="brain")

    result = manager.scale("brain_inference", 3)

    assert result == {"service": "brain_inference", "action": "scale", "replicas": 3}
    assert docker.updates[0].spec["Mode"]["Replicated"]["Replicas"] == 3


def test_scale_rejects_nginx_gateway():
    manager = SwarmManager(docker=FakeDocker(), stack="brain")

    with pytest.raises(ValueError):
        manager.scale("brain_ctrl_nginx", 2)


def test_scale_rejects_control_service():
    manager = SwarmManager(docker=FakeDocker(), stack="brain")

    with pytest.raises(ValueError):
        manager.scale("brain_ctrl_ops", 2)


def test_list_services_counts_tasks_when_service_status_is_absent():
    manager = SwarmManager(docker=FakeDocker(), stack="brain")

    services = manager.list_services()

    assert services[0]["running"] == 1
    assert services[0]["desired"] == 1
    assert services[0]["group"] == "app"


def test_rollout_increments_force_update():
    docker = FakeDocker()
    manager = SwarmManager(docker=docker, stack="brain")

    manager.rollout("brain_inference")

    assert docker.updates[0].spec["TaskTemplate"]["ForceUpdate"] == 3


def test_deploy_stack_runs_docker_cli_with_host_project_root():
    runner = FakeRunner()
    manager = SwarmManager(docker=FakeDocker(), stack="brain", project_root="/app", host_project_root="/srv/new_brain", runner=runner)

    result = manager.deploy_stack()

    assert result == {"action": "deploy", "stack": "brain"}
    assert runner.calls == [(
        ["docker", "stack", "deploy", "--with-registry-auth", "-c", "deploy/deploy.yaml", "brain"],
        {"cwd": "/app", "env": {"PROJECT_ROOT": "/srv/new_brain"}, "timeout": 600},
    )]


def test_remove_stack_runs_docker_cli():
    runner = FakeRunner()
    manager = SwarmManager(docker=FakeDocker(), stack="brain", project_root="/app", runner=runner)

    result = manager.remove_stack()

    assert result == {"action": "remove", "stack": "brain"}
    assert runner.calls == [(
        ["docker", "stack", "rm", "brain"],
        {"cwd": "/app", "env": {}, "timeout": 600},
    )]


def test_rejects_unknown_service():
    manager = SwarmManager(docker=FakeDocker(), stack="brain")

    with pytest.raises(ValueError):
        manager.start("unknown")


def test_control_services_use_real_service_name():
    docker = FakeDocker()
    manager = SwarmManager(docker=docker, stack="brain", ctrl_stack="brain_ctrl")

    manager.start("brain_ctrl_ops")
    manager.rollout("brain_ctrl_nginx")

    assert docker.updates[0].spec["Name"] == "brain_ctrl_ops"
    assert docker.updates[1].spec["Name"] == "brain_ctrl_nginx"
