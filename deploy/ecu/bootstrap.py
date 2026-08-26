from __future__ import annotations

import os
import sys

import uvicorn


def init_ecu() -> None:
    import torch_ecu

    torch_ecu.is_transfer_to_ecu = True


if __name__ == "__main__":
    os.chdir("/app/backend")
    sys.path.insert(0, "/app/backend")
    init_ecu()
    uvicorn.run("main:app", host="0.0.0.0", port=6000)
