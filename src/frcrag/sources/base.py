from dataclasses import dataclass
from fnmatch import fnmatchcase


@dataclass(frozen=True)
class Document:
    source_id: str
    doc_id: str  # stable within a source, e.g. "design-handbook/structure/fasteners"
    url: str
    title: str
    section: str  # top-level site section slug, e.g. "design-handbook"
    markdown: str  # normalized body, without the page title
    description: str = ""
    min_body_chars: int | None = None  # override chunking's minimum, for sources with short documents


@dataclass(frozen=True)
class FetchResult:
    documents: list[Document]
    revision: str  # what was fetched, e.g. "owner/repo@<commit sha>", recorded for auditability


def path_matches(path: str, include: list[str], exclude: list[str]) -> bool:
    return any(fnmatchcase(path, p) for p in include) and not any(fnmatchcase(path, p) for p in exclude)
