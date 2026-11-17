"""Write chunks in the layout Bedrock Knowledge Bases expects for pre-chunked S3 data.

    build/kb/<source_id>/<chunk>.md                 one chunk per file (KB chunking strategy: NONE)
    build/kb/<source_id>/<chunk>.md.metadata.json   filterable metadata for that chunk
    build/kb/_manifests/<source_id>.json            audit record: revision, hashes, timestamps

Chunk files are deterministic, so syncing to S3 re-uploads only what changed. Run-specific
data (timestamps) lives in the manifest, outside the prefix the Knowledge Base ingests.
"""

import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

from .chunking import Chunk
from .config import SourceConfig
from .sources.base import FetchResult

MANIFEST_DIR = "_manifests"


def chunk_filename(chunk: Chunk) -> str:
    base = re.sub(r"[^a-z0-9._-]+", "-", chunk.document.doc_id.lower().replace("/", "__")).strip("-")
    return f"{base or 'index'}--{chunk.index:03d}.md"


def write_source(source: SourceConfig, result: FetchResult, chunks: list[Chunk], out_dir: Path) -> Path:
    target = out_dir / source.id
    if target.exists():
        shutil.rmtree(target)  # pages removed upstream must disappear from the KB too
    target.mkdir(parents=True)

    entries = []
    for chunk in chunks:
        name = chunk_filename(chunk)
        _write(target / name, chunk.render())
        # Kept small on purpose: S3 Vectors caps filterable metadata per vector.
        metadata = {
            # Bedrock rejects the whole file if any attribute value is an empty string.
            "metadataAttributes": {
                key: value
                for key, value in {
                    "source_id": source.id,
                    "source_name": source.name,
                    "title": chunk.document.title,
                    "url": chunk.url,
                    "site_section": chunk.document.section,
                }.items()
                if value
            }
        }
        _write(target / f"{name}.metadata.json", json.dumps(metadata, indent=2, ensure_ascii=False) + "\n")
        entries.append(
            {
                "file": name,
                "doc_id": chunk.document.doc_id,
                "url": chunk.url,
                "content_hash": chunk.content_hash,
                "est_tokens": chunk.est_tokens,
            }
        )

    manifest_path = out_dir / MANIFEST_DIR / f"{source.id}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "source_id": source.id,
        "name": source.name,
        "type": source.type,
        "revision": result.revision,
        "attribution": source.attribution,
        "license_status": source.license_status,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "documents": len(result.documents),
        "chunks": entries,
    }
    _write(manifest_path, json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    return manifest_path


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")
