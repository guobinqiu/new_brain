import os
import socket
import subprocess
import time
from contextlib import contextmanager

import httpx
import yaml

from shared.paths import PROJECT_ROOT


@contextmanager
def cloud_inference_server(workdir, provider, *, rerank=True, sparse=True, dense_model=None):
    raw = yaml.safe_load((PROJECT_ROOT / "services/inference/config/inference.yaml").read_text())
    for name, config in raw.items():
        config["enable"] = name == provider
    if dense_model is not None:
        for model in raw[provider]["dense"].values():
            if model["enable"]:
                model["model_name"] = dense_model
    if not rerank:
        for model in raw[provider].get("rerank", {}).values():
            model["enable"] = False
    if not sparse:
        for model in raw[provider].get("sparse", {}).values():
            model["enable"] = False
    config_path = workdir / "inference.yaml"
    config_path.write_text(yaml.safe_dump(raw))
    env = dict(os.environ, SERVICE_API_KEY="inference-e2e-key")
    log_path = workdir / "inference.log"
    with socket.socket() as listener, log_path.open("w") as log:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        address = f"http://127.0.0.1:{listener.getsockname()[1]}"
        process = subprocess.Popen(
            [str(PROJECT_ROOT / "services/inference/.venv/bin/python"), "-c",
             "import sys; from pathlib import Path; import uvicorn; "
             "from services.inference.app import config; "
             "config.DEFAULT_CONFIG_FILE = Path(sys.argv[1]); "
             "uvicorn.run('services.inference.app.main:app', fd=int(sys.argv[2]), access_log=False)",
             str(config_path), str(listener.fileno())],
            cwd=PROJECT_ROOT, env=env, pass_fds=(listener.fileno(),), stdout=log, stderr=log,
        )
        try:
            with httpx.Client(base_url=address, timeout=1, trust_env=False) as client:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError(f"Inference startup failed: {log_path}")
                    try:
                        if client.get("/ready").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.2)
                else:
                    raise RuntimeError(f"Inference startup timed out: {log_path}")
            yield address
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
