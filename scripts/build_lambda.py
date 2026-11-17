"""Bundle the chat Lambda into build/lambda/chat without Docker.

uv installs Linux arm64 wheels for the Lambda runtime's Python, then the handler package is copied
in. Dependencies are reinstalled only when backend/requirements.txt changes.
"""

import hashlib
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = ROOT / "backend" / "requirements.txt"
PACKAGE = ROOT / "backend" / "chat_api"
OUT = ROOT / "build" / "lambda" / "chat"
PYTHON_VERSION = "3.13"  # matches lambda_.Runtime.PYTHON_3_13 in infra/stack.py
PLATFORM = "aarch64-manylinux_2_28"  # Architecture.ARM_64


def build(out: Path = OUT) -> Path:
    stamp = out / ".requirements.sha256"
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
    shutil.rmtree(out / PACKAGE.name, ignore_errors=True)
    shutil.copytree(PACKAGE, out / PACKAGE.name, ignore=shutil.ignore_patterns("__pycache__"))
    return out


if __name__ == "__main__":
    print(build())
