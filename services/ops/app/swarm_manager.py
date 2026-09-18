from __future__ import annotations

import os
import subprocess
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path


COMMAND_TIMEOUT_SECONDS = 600


@dataclass(frozen=True)
class ServiceUpdate:
    service_id: str
    version: int
    spec: dict


class SwarmManager:
    def __init__(
        self,
        docker,
        stack: str = "brain",
        ctrl_stack: str = "brain_ctrl",
        project_root: str | Path = "/app",
        host_project_root: str | None = None,
        command_timeout: int = COMMAND_TIMEOUT_SECONDS,
        runner=None,
    ):
        self.docker = docker
        self.stack = stack
        self.ctrl_stack = ctrl_stack
        self.project_root = str(project_root)
        self.host_project_root = host_project_root or self.project_root
        self.command_timeout = command_timeout
        self.runner = runner or _run_command

    def list_services(self) -> list[dict]:
        summaries = []
        for service in self.docker.list_services():
            summary = _service_summary(service)
            if summary["running"] is None or summary["desired"] is None:
                tasks = self.docker.list_tasks(summary["name"])
                summary["running"] = sum(1 for task in tasks if (task.get("Status") or {}).get("State") == "running")
                summary["desired"] = sum(1 for task in tasks if task.get("DesiredState") == "running")
            summaries.append(summary)
        return summaries

    def start(self, service: str) -> dict:
        self._require_managed_service(service)
        return self._scale(service, 1)

    def stop(self, service: str) -> dict:
        self._require_managed_service(service)
        return self._scale(service, 0)

    def scale(self, service: str, replicas: int) -> dict:
        if self._service_group(service) != "app":
            raise ValueError(f"service does not support explicit scale: {service}")
        return self._scale(service, replicas, action="scale")

    def rollout(self, service: str) -> dict:
        self._require_managed_service(service)
        data = self.docker.inspect_service(service)
        spec = deepcopy(data["Spec"])
        spec.setdefault("TaskTemplate", {})
        spec["TaskTemplate"]["ForceUpdate"] = int(spec["TaskTemplate"].get("ForceUpdate", 0)) + 1
        self.docker.update_service(data["ID"], int(data["Version"]["Index"]), spec)
        return {"service": service, "action": "rollout"}

    def deploy_stack(self) -> dict:
        self.runner(
            ["docker", "stack", "deploy", "--with-registry-auth", "-c", "deploy/deploy.yaml", self.stack],
            cwd=self.project_root,
            env={"PROJECT_ROOT": self.host_project_root},
            timeout=self.command_timeout,
        )
        return {"action": "deploy", "stack": self.stack}

    def remove_stack(self) -> dict:
        self.runner(
            ["docker", "stack", "rm", self.stack],
            cwd=self.project_root,
            env={},
            timeout=self.command_timeout,
        )
        return {"action": "remove", "stack": self.stack}

    def list_tasks(self, service: str) -> list[dict]:
        self._require_managed_service(service)
        return [_task_summary(task) for task in self.docker.list_tasks(service)]

    def logs(self, service: str, tail: int = 50) -> str:
        self._require_managed_service(service)
        return self.docker.service_logs(service, tail=tail)

    def list_nodes(self) -> list[dict]:
        return [_node_summary(node) for node in self.docker.list_nodes()]

    def join_command(self, role: str) -> str:
        if role not in {"worker", "manager"}:
            raise ValueError("role must be worker or manager")
        swarm = self.docker.inspect_swarm()
        token = swarm["JoinTokens"]["Worker" if role == "worker" else "Manager"]
        addr = swarm.get("RemoteManagers", [{}])[0].get("Addr", "<manager-ip>:2377")
        return f"docker swarm join --token {token} {addr}"

    def _scale(self, service: str, replicas: int, action: str | None = None) -> dict:
        data = self.docker.inspect_service(service)
        spec = deepcopy(data["Spec"])
        spec["Mode"] = {"Replicated": {"Replicas": replicas}}
        self.docker.update_service(data["ID"], int(data["Version"]["Index"]), spec)
        return {"service": service, "action": action or ("start" if replicas else "stop"), "replicas": replicas}

    def _require_managed_service(self, service: str) -> None:
        if not self._service_group(service):
            raise ValueError(f"unsupported service: {service}")

    def _service_group(self, service: str) -> str | None:
        data = self.docker.inspect_service(service)
        return (data.get("Spec", {}).get("Labels") or {}).get("group")


def _service_summary(service: dict) -> dict:
    status = service.get("ServiceStatus") or {}
    endpoint = service.get("Endpoint") or {}
    labels = service.get("Spec", {}).get("Labels") or {}
    return {
        "id": service.get("ID"),
        "name": service.get("Spec", {}).get("Name"),
        "group": labels.get("group"),
        "image": service.get("Spec", {}).get("TaskTemplate", {}).get("ContainerSpec", {}).get("Image"),
        "running": status.get("RunningTasks"),
        "desired": status.get("DesiredTasks"),
        "ports": endpoint.get("Ports") or [],
    }


def _task_summary(task: dict) -> dict:
    status = task.get("Status") or {}
    return {
        "id": task.get("ID"),
        "name": task.get("Name"),
        "node_id": task.get("NodeID"),
        "desired_state": task.get("DesiredState"),
        "state": status.get("State"),
        "message": status.get("Message"),
        "error": status.get("Err"),
        "updated_at": status.get("Timestamp"),
    }


def _node_summary(node: dict) -> dict:
    status = node.get("Status") or {}
    manager = node.get("ManagerStatus") or {}
    spec = node.get("Spec") or {}
    return {
        "id": node.get("ID"),
        "hostname": node.get("Description", {}).get("Hostname"),
        "role": spec.get("Role"),
        "availability": spec.get("Availability"),
        "state": status.get("State"),
        "addr": status.get("Addr"),
        "leader": manager.get("Leader", False),
        "manager_addr": manager.get("Addr"),
    }


def _run_command(command: list[str], *, cwd: str, env: dict[str, str], timeout: int) -> None:
    merged_env = os.environ.copy()
    merged_env.update(env)
    subprocess.run(command, cwd=cwd, env=merged_env, check=True, capture_output=True, text=True, timeout=timeout)
