from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


class LegacyOfficeConversion:
    def __init__(self, filepath: str, target_suffix: str):
        self.filepath = filepath
        self.target_suffix = target_suffix
        self._tmpdir: tempfile.TemporaryDirectory | None = None

    def __enter__(self) -> Path:
        self._tmpdir = tempfile.TemporaryDirectory()
        output_dir = Path(self._tmpdir.name)
        source = Path(self.filepath)
        target_suffix = self.target_suffix
        subprocess.run(
            [
                "soffice",
                "--headless",
                "--convert-to",
                target_suffix.lstrip("."),
                "--outdir",
                str(output_dir),
                str(source),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        converted = output_dir / f"{source.stem}{target_suffix}"
        if not converted.exists():
            matches = list(output_dir.glob(f"*{target_suffix}"))
            if not matches:
                raise ValueError(f"Failed to convert {source.name} to {target_suffix}")
            converted = matches[0]
        return converted

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._tmpdir is not None:
            self._tmpdir.cleanup()


def convert_legacy_office_file(filepath: str, target_suffix: str) -> LegacyOfficeConversion:
    return LegacyOfficeConversion(filepath, target_suffix)
