"""Build the chat page (web/, React + Astryx) into web/dist for the CDK BucketDeployment.

Installs locked dependencies when package-lock.json has changed since the last install, then runs
`npm run build` (which compiles the Astryx themes and bundles with Vite).
"""

import hashlib
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
STAMP = WEB / "node_modules" / ".lock.sha256"


def _npm() -> str:
    npm = shutil.which("npm")
    if not npm:
        raise SystemExit("npm not found: install Node.js 22+ to build the chat page")
    return npm


def build(web: Path = WEB) -> Path:
    npm = _npm()
    digest = hashlib.sha256((web / "package-lock.json").read_bytes()).hexdigest()
    stamp = web / "node_modules" / ".lock.sha256"
    if not stamp.exists() or stamp.read_text() != digest:
        subprocess.run([npm, "ci", "--no-fund", "--no-audit"], cwd=web, check=True)
        stamp.write_text(digest)
    subprocess.run([npm, "run", "build", "--silent"], cwd=web, check=True)
    dist = web / "dist"
    add_onshape_panel(dist)
    return dist


def add_onshape_panel(dist: Path) -> None:
    """The Onshape panel is the same app at /onshape/index.html: CloudFront lets only that path be
    framed (by Onshape), and the app switches to panel mode there. Asset URLs are absolute."""
    panel = dist / "onshape"
    panel.mkdir(exist_ok=True)
    shutil.copyfile(dist / "index.html", panel / "index.html")


if __name__ == "__main__":
    print(build())
