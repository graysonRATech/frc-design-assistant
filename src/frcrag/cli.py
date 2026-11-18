"""`kb` command line: ingest and preview sources locally, then sync, ask and evaluate on AWS."""

import argparse
import getpass
import json
import logging
import statistics
import sys
from pathlib import Path

import yaml

from . import sources as source_fetchers
from .chunking import chunk_document
from .config import ConfigError, load_sources
from .writer import MANIFEST_DIR, write_source

log = logging.getLogger("kb")

DEFAULT_OUT = Path("build/kb")
DEFAULT_CACHE = Path(".cache/sources")


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(prog="kb", description="Manage the FRC design knowledge base.")
    parser.add_argument("--config", type=Path, default=Path("sources.yaml"), help="sources file (default: sources.yaml)")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("sources", help="list configured sources")

    ingest = commands.add_parser("ingest", help="fetch, normalize and chunk sources into the build directory")
    ingest.add_argument("--source", action="append", dest="source_ids", metavar="ID", help="source id (repeatable; default: all)")
    ingest.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ingest.add_argument("--cache", type=Path, default=DEFAULT_CACHE)

    preview = commands.add_parser("preview", help="print chunks from the build directory")
    preview.add_argument("source_id", metavar="ID")
    preview.add_argument("--match", default="", help="only chunks whose file name or URL contains this text")
    preview.add_argument("--limit", type=int, default=3, help="number of chunks to print (default: 3)")
    preview.add_argument("--out", type=Path, default=DEFAULT_OUT)

    stack_name, region = _deploy_defaults()
    aws_options = argparse.ArgumentParser(add_help=False)
    aws_options.add_argument("--stack", default=stack_name, help=f"CloudFormation stack (default: {stack_name})")
    aws_options.add_argument("--region", default=region, help=f"AWS region (default: {region})")

    sync = commands.add_parser("sync", parents=[aws_options], help="upload built chunks to S3 and re-index the Knowledge Base")
    sync.add_argument("--out", type=Path, default=DEFAULT_OUT)
    sync.add_argument("--dry-run", action="store_true", help="show what would change without uploading")
    sync.add_argument("--no-wait", action="store_true", help="start the ingestion job without waiting for it")

    ask = commands.add_parser("ask", parents=[aws_options], help="ask the deployed assistant a question")
    ask.add_argument("question")
    ask.add_argument("--user", default=getpass.getuser(), help="name recorded in the audit log (default: OS user)")

    evaluate = commands.add_parser("eval", parents=[aws_options], help="measure retrieval quality against evals/retrieval.yaml")
    evaluate.add_argument("--file", type=Path, default=Path("evals/retrieval.yaml"))
    evaluate.add_argument("--top-k", type=int, default=6)

    users = commands.add_parser("users", parents=[aws_options], help="manage who can sign in")
    user_commands = users.add_subparsers(dest="user_command", required=True)
    add = user_commands.add_parser(
        "add", help="allow emails, or a whole domain as @school.org, to sign in (re-adding changes the role)"
    )
    add.add_argument("emails", nargs="*", metavar="EMAIL")
    add.add_argument("--file", type=Path, help="text file with one email per line (keep it out of git)")
    add.add_argument(
        "--role",
        choices=("student", "mentor", "admin", "blocked"),
        default="student",
        help="blocked: deny one address that an allowed domain would let in",
    )
    remove = user_commands.add_parser("remove", help="revoke access and delete the sign-in record")
    remove.add_argument("emails", nargs="+", metavar="EMAIL")
    user_commands.add_parser("list", help="show the allowlist")

    args = parser.parse_args(argv)
    try:
        configured = load_sources(args.config)
    except (ConfigError, OSError) as error:
        log.error("error: %s", error)
        return 2

    if args.command == "sources":
        for s in configured:
            print(f"{s.id:<16} {s.type:<12} refresh={s.refresh:<8} license={s.license_status:<11} {s.name}")
        return 0
    if args.command == "ingest":
        return _ingest(configured, args.source_ids, args.out, args.cache)
    if args.command == "preview":
        return _preview(args.source_id, args.match, args.limit, args.out)

    from . import aws as aws_ops

    session = aws_ops.session(args.region)
    outputs = aws_ops.stack_outputs(session, args.stack)
    if args.command == "sync":
        return _sync(aws_ops, session, outputs, [s.id for s in configured], args.out, args.dry_run, not args.no_wait)
    if args.command == "ask":
        return _ask(aws_ops, session, outputs, args.question, args.user)
    if args.command == "users":
        return _users(aws_ops, session, outputs, args)
    return _eval(aws_ops, session, outputs, args.file, args.top_k)


def _deploy_defaults() -> tuple[str, str]:
    """Stack name and region from config.local.yaml / config.example.yaml, when run from the repo."""
    stack_name, region = "FrcRag", "us-east-1"
    for path in (Path("config.example.yaml"), Path("config.local.yaml")):
        if path.exists():
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            stack_name, region = data.get("stack_name", stack_name), data.get("region", region)
    return stack_name, region


def _sync(aws_ops, session, outputs, source_ids, out_dir: Path, dry_run: bool, wait: bool) -> int:
    missing = [i for i in source_ids if not (out_dir / MANIFEST_DIR / f"{i}.json").exists()]
    if missing:
        # Syncing mirrors every configured source; an unbuilt one would be wiped from the KB.
        log.error("error: no build for %s; run `kb ingest` first", ", ".join(missing))
        return 2
    uploads, deletes = aws_ops.sync(session, outputs, out_dir, source_ids, dry_run=dry_run)
    print(f"{'would upload' if dry_run else 'uploaded'} {uploads} files, {'would delete' if dry_run else 'deleted'} {deletes}")
    if dry_run:
        return 0
    # Always re-index, even with no file changes: a previous ingestion may have failed. Bedrock
    # only re-embeds changed files, so this is cheap.
    job = aws_ops.start_ingestion(session, outputs, wait=wait)
    print(f"ingestion job {job['ingestionJobId']}: {job['status']}")
    if stats := job.get("statistics"):
        print("  " + ", ".join(f"{k}={v}" for k, v in stats.items()))
    for reason in job.get("failureReasons", []):
        log.error("  %s", reason)
    return 0 if job["status"] in ("COMPLETE", "STARTING", "IN_PROGRESS") else 1


def _ask(aws_ops, session, outputs, question: str, user: str) -> int:
    status, body = aws_ops.ask(session, outputs, question, user)
    if status != 200:
        log.error("error (%s): %s", status, body.get("error"))
        return 1
    print(body["answer"])
    if body["sources"]:
        print("\nSources:")
        for source in body["sources"]:
            print(f"  [{source['number']}] {source['title']}: {source['url']}")
    usage = body["usage"]
    print(f"\n({usage['input_tokens']} in / {usage['output_tokens']} out tokens, ${usage['cost_usd']:.4f}; request {body['request_id']})")
    return 0


def _users(aws_ops, session, outputs, args) -> int:
    try:
        if args.user_command == "list":
            entries = sorted(aws_ops.list_users(session, outputs), key=lambda i: (i["role"], i["sk"]))
            for item in entries:
                print(f"{item['role']:<8} {item['sk']:<40} added {item.get('added_at', '?')} by {item.get('added_by', '?')}")
            print(f"{len(entries)} allowed")
        elif args.user_command == "add":
            emails = list(args.emails)
            if args.file:
                lines = args.file.read_text(encoding="utf-8").splitlines()
                emails += [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]
            if not emails:
                log.error("error: give emails or --file")
                return 2
            added = aws_ops.allow_users(session, outputs, emails, args.role, getpass.getuser())
            print(f"allowed {len(added)} as {args.role}")
        else:
            for email in args.emails:
                deleted = aws_ops.remove_user(session, outputs, email)
                print(f"removed {email.strip().lower()} (signed out {deleted} session record(s))")
    except ValueError as error:
        log.error("error: %s", error)
        return 2
    return 0


def _eval(aws_ops, session, outputs, path: Path, top_k: int) -> int:
    cases = yaml.safe_load(path.read_text(encoding="utf-8"))["cases"]
    ranks = []
    for case in cases:
        rank = aws_ops.score_case(aws_ops.retrieve_urls(session, outputs, case["question"], top_k), case["expect"])
        ranks.append(rank)
        print(f"{'miss' if rank is None else f'@{rank}':>5}  {case['question']}")
    hits = [r for r in ranks if r is not None]
    mrr = sum(1 / r for r in hits) / len(ranks)
    print(f"\nhit@1 {sum(r == 1 for r in hits)}/{len(ranks)}, hit@{top_k} {len(hits)}/{len(ranks)}, MRR {mrr:.2f}")
    return 0


def _ingest(configured, source_ids, out_dir: Path, cache_dir: Path) -> int:
    by_id = {s.id: s for s in configured}
    unknown = [i for i in source_ids or [] if i not in by_id]
    if unknown:
        log.error("error: unknown source id(s): %s", ", ".join(unknown))
        return 2

    for source in [by_id[i] for i in source_ids] if source_ids else configured:
        result = source_fetchers.fetch(source, cache_dir)
        chunks = [c for doc in result.documents for c in chunk_document(doc)]
        empty_docs = sum(1 for doc in result.documents if not any(c.document is doc for c in chunks))
        manifest = write_source(source, result, chunks, out_dir)

        tokens = sorted(c.est_tokens for c in chunks) or [0]
        print(
            f"{source.id}: {len(result.documents)} documents -> {len(chunks)} chunks "
            f"({empty_docs} documents had no indexable text)\n"
            f"  est. tokens per chunk: min {tokens[0]}, median {int(statistics.median(tokens))}, max {tokens[-1]}; "
            f"total ~{sum(tokens):,}\n"
            f"  revision {result.revision}\n"
            f"  manifest {manifest}"
        )
    return 0


def _preview(source_id: str, match: str, limit: int, out_dir: Path) -> int:
    manifest_path = out_dir / MANIFEST_DIR / f"{source_id}.json"
    if not manifest_path.exists():
        log.error("error: no build for %r; run `kb ingest --source %s` first", source_id, source_id)
        return 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = [e for e in manifest["chunks"] if match.lower() in (e["file"] + e["url"]).lower()]

    for entry in entries[:limit]:
        print(f"===== {entry['file']}  (~{entry['est_tokens']} tokens)")
        print((out_dir / source_id / entry["file"]).read_text(encoding="utf-8"))

    buckets = [(0, 200), (200, 400), (400, 600), (600, 800), (800, 10**9)]
    print(f"{len(entries)} matching chunks of {len(manifest['chunks'])}; revision {manifest['revision']}")
    for low, high in buckets:
        count = sum(1 for e in entries if low <= e["est_tokens"] < high)
        label = f"{low}-{high}" if high < 10**9 else f"{low}+"
        print(f"  {label:>8} tokens: {count:>4} {'#' * min(count, 60)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
