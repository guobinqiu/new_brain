from __future__ import annotations

import re


APP_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{1,63}$")


def validate_app_id(app_id: str) -> str:
    if not APP_ID_PATTERN.fullmatch(app_id):
        raise ValueError("app_id must start with a letter and contain only letters, numbers, or underscore")
    return app_id
