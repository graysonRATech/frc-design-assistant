"""Bundle the chat Lambdas into build/lambda without Docker.

uv installs Linux arm64 wheels for the Lambda runtime's Python, then the handler package is copied
in. Dependencies are reinstalled only when backend/requirements.txt changes.

The streaming function also needs `run.sh` (started by the Lambda Web Adapter) to be executable.
Zips made on Windows drop Unix permissions, so `build_stream_zip` writes the zip itself with
explicit modes, and with fixed timestamps so an unchanged bundle keeps the same asset hash.
"""

import hashlib
import shutil
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = ROOT / "backend" / "requirements.txt"
PACKAGE = ROOT / "backend" / "chat_api"
ALLOWLIST = ROOT / "backend" / "auth_triggers"  # the Slack worker checks the same allowlist
OUT = ROOT / "build" / "lambda" / "chat"
STREAM_ZIP = ROOT / "build" / "lambda" / "chat-stream.zip"
PYTHON_VERSION = "3.13"  # matches lambda_.Runtime.PYTHON_3_13 in infra/
PLATFORM = "aarch64-manylinux_2_28"  # Architecture.ARM_64
STAMP = ".requirements.sha256"
RUN_SH = """#!/bin/sh
# Started by the Lambda Web Adapter (AWS_LAMBDA_EXEC_WRAPPER=/opt/bootstrap); see chat_api/server.py.
export PYTHONPATH="$LAMBDA_TASK_ROOT"
exec python3 -m chat_api.server
"""
_EPOCH = (1980, 1, 1, 0, 0, 0)


def build(out: Path = OUT) -> Path:
    stamp = out / STAMP
    digest = hashlib.sha256(REQUIREMENTS.read_bytes() + PLATFORM.encode() + PYTHON_VERSION.encode()).hexdigest()
    if not stamp.exists() or stamp.read_text() != digest:
        shutil.rmtree(out, ignore_errors=True)
        out.mkdir(parents=True)
        subprocess.run(
            [
                "uv", "pip", "install", "--quiet",
                "--target", str(out),
                "--python-version", PYTHON_VERSION,
                "--python-platform", PLATFORM,
                "--only-binary", ":all:",
                "-r", str(REQUIREMENTS),
            ],
            check=True,
        )  # fmt: skip
        stamp.write_text(digest)
    for package in (PACKAGE, ALLOWLIST):
        shutil.rmtree(out / package.name, ignore_errors=True)
        shutil.copytree(package, out / package.name, ignore=shutil.ignore_patterns("__pycache__"))
    return out


def build_stream_zip(bundle: Path, out: Path = STREAM_ZIP) -> Path:
    files = sorted(
        (p.relative_to(bundle).as_posix(), p)
        for p in bundle.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.name != STAMP
    )
    fingerprint = hashlib.sha256(RUN_SH.encode())
    for name, path in files:
        fingerprint.update(name.encode() + b"\0" + path.read_bytes())
    stamp = out.with_suffix(".sha256")
    if out.exists() and stamp.exists() and stamp.read_text() == fingerprint.hexdigest():
        return out
    tmp = out.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as archive:
        _add(archive, "run.sh", RUN_SH.encode(), 0o755)
        for name, path in files:
            _add(archive, name, path.read_bytes(), 0o644)
    tmp.replace(out)
    stamp.write_text(fingerprint.hexdigest())
    return out


def _add(archive: zipfile.ZipFile, name: str, data: bytes, mode: int) -> None:
    info = zipfile.ZipInfo(name, date_time=_EPOCH)
    info.create_system = 3  # Unix, so Lambda honours the permission bits below
    info.external_attr = (0o100000 | mode) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, data)


if __name__ == "__main__":
    print(build_stream_zip(build()))
