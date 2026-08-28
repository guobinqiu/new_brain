from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass
from pathlib import Path

from auth.app_id import validate_app_id


@dataclass(frozen=True)
class AppCredential:
    app_id: str
    access_key: str
    secret_key: str


class AppRegistry:
    def __init__(self, path: str | Path | None):
        self.path = Path(path) if path is not None else Path(__file__).resolve().parents[1] / "data" / "apps.json"

    def create_app(self, app_id: str) -> AppCredential:
        validate_app_id(app_id)
        data = self._read()
        if app_id in data:
            raise ValueError("app_id already exists")
        credential = AppCredential(
            app_id=app_id,
            access_key=secrets.token_hex(16),
            secret_key=secrets.token_hex(32),
        )
        data[app_id] = asdict(credential)
        self._write(data)
        return credential

    def get_app(self, app_id: str) -> AppCredential | None:
        data = self._read().get(app_id)
        if not data:
            return None
        return AppCredential(
            app_id=str(data["app_id"]),
            access_key=str(data["access_key"]),
            secret_key=str(data["secret_key"]),
        )

    def list_apps(self) -> list[AppCredential]:
        return [self.get_app(app_id) for app_id in sorted(self._read())]

    def delete_app(self, app_id: str) -> bool:
        validate_app_id(app_id)
        data = self._read()
        if app_id not in data:
            return False
        del data[app_id]
        self._write(data)
        return True

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        with self.path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
        tmp_path.replace(self.path)
