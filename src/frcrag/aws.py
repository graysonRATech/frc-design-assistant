"""AWS side of the `kb` CLI: sync chunks to S3, run Knowledge Base ingestion, ask, and evaluate.

boto3 is imported lazily so the ingest commands work without the `aws` dependency group.
Resource names come from the deployed CloudFormation stack's outputs.
"""

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .writer import MANIFEST_DIR

CHUNKS_PREFIX = "kb/"  # must match infra/stack.py
MANIFESTS_PREFIX = "manifests/"
ROLES = ("student", "mentor", "admin", "blocked")  # must match backend/auth_triggers
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DOMAIN = re.compile(r"^@([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$")


@dataclass(frozen=True)
class StackOutputs:
    bucket: str
    knowledge_base_id: str
    data_source_id: str
    chat_function: str
    table: str
    user_pool_id: str = ""


def session(region: str):
    try:
        import boto3
    except ImportError as error:
        raise SystemExit("boto3 is missing; run `uv sync --group aws`") from error
    return boto3.Session(region_name=region)


def stack_outputs(aws, stack_name: str) -> StackOutputs:
    stack = aws.client("cloudformation").describe_stacks(StackName=stack_name)["Stacks"][0]
    values = {o["OutputKey"]: o["OutputValue"] for o in stack.get("Outputs", [])}
    return StackOutputs(
        bucket=values["ContentBucketName"],
        knowledge_base_id=values["KnowledgeBaseId"],
        data_source_id=values["DataSourceId"],
        chat_function=values["ChatFunctionName"],
        table=values["TableName"],
        user_pool_id=values.get("UserPoolId", ""),
    )


def plan_sync(local: dict[str, str], remote: dict[str, str]) -> tuple[list[str], list[str]]:
    """Given {key: md5} for local files and {key: etag} for S3 objects, return (uploads, deletes)."""
    uploads = sorted(key for key, md5 in local.items() if remote.get(key) != md5)
    deletes = sorted(key for key in remote if key not in local)
    return uploads, deletes


def local_chunk_files(out_dir: Path, source_ids: list[str]) -> dict[str, Path]:
    files = {}
    for source_id in source_ids:
        for path in sorted((out_dir / source_id).glob("*")):
            if path.is_file():
                files[f"{CHUNKS_PREFIX}{source_id}/{path.name}"] = path
    return files


def sync(aws, outputs: StackOutputs, out_dir: Path, source_ids: list[str], *, dry_run: bool = False) -> tuple[int, int]:
    """Mirror build/kb/<source>/ for every configured source to s3://bucket/kb/<source>/.

    Prefixes for sources no longer in sources.yaml are deleted, so the KB forgets them too.
    """
    s3 = aws.client("s3")
    files = local_chunk_files(out_dir, source_ids)
    local = {key: hashlib.md5(path.read_bytes()).hexdigest() for key, path in files.items()}
    remote = {}
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=outputs.bucket, Prefix=CHUNKS_PREFIX):
        for obj in page.get("Contents", []):
            remote[obj["Key"]] = obj["ETag"].strip('"')
    uploads, deletes = plan_sync(local, remote)
    if dry_run:
        return len(uploads), len(deletes)

    for key in uploads:
        content_type = "application/json" if key.endswith(".json") else "text/markdown; charset=utf-8"
        s3.put_object(Bucket=outputs.bucket, Key=key, Body=files[key].read_bytes(), ContentType=content_type)
    for start in range(0, len(deletes), 1000):
        batch = [{"Key": key} for key in deletes[start : start + 1000]]
        s3.delete_objects(Bucket=outputs.bucket, Delete={"Objects": batch, "Quiet": True})
    for source_id in source_ids:
        manifest = out_dir / MANIFEST_DIR / f"{source_id}.json"
        if manifest.exists():
            s3.put_object(
                Bucket=outputs.bucket,
                Key=f"{MANIFESTS_PREFIX}{source_id}.json",
                Body=manifest.read_bytes(),
                ContentType="application/json",
            )
    return len(uploads), len(deletes)


def start_ingestion(aws, outputs: StackOutputs, *, wait: bool, poll_seconds: float = 10) -> dict:
    agent = aws.client("bedrock-agent")
    job = agent.start_ingestion_job(knowledgeBaseId=outputs.knowledge_base_id, dataSourceId=outputs.data_source_id)[
        "ingestionJob"
    ]
    while wait and job["status"] in ("STARTING", "IN_PROGRESS", "STOPPING"):
        time.sleep(poll_seconds)
        job = agent.get_ingestion_job(
            knowledgeBaseId=outputs.knowledge_base_id, dataSourceId=outputs.data_source_id, ingestionJobId=job["ingestionJobId"]
        )["ingestionJob"]
    return job


def ask(aws, outputs: StackOutputs, question: str, user: str, history: list[dict] | None = None) -> tuple[int, dict]:
    payload = {"user": user, "question": question, "history": history or []}
    result = aws.client("lambda").invoke(FunctionName=outputs.chat_function, Payload=json.dumps(payload).encode())
    response = json.loads(result["Payload"].read())
    if "statusCode" not in response:  # unhandled Lambda error
        return 500, {"error": response.get("errorMessage", str(response))}
    return response["statusCode"], json.loads(response["body"])


def ask_streamed(aws, outputs: StackOutputs, question: str, user: str) -> tuple[int, dict]:
    """One question through the streaming pipeline the website and Slack use. The chat function
    answers in full, then deletes the saved chat (backend/chat_api/handler.py, _streamed_check)."""
    payload = {"user": user, "question": question, "stream": True}
    result = aws.client("lambda").invoke(FunctionName=outputs.chat_function, Payload=json.dumps(payload).encode())
    response = json.loads(result["Payload"].read())
    if "statusCode" not in response:
        return 500, {"error": response.get("errorMessage", str(response))}
    return response["statusCode"], json.loads(response["body"])


@dataclass(frozen=True)
class ChatModel:
    id: str
    endpoint: str  # "mantle" or "runtime", as in backend/chat_api/handler.py
    price_input_per_mtok: float
    price_output_per_mtok: float

    def cost(self, usage: dict) -> float:
        return (usage["input_tokens"] * self.price_input_per_mtok + usage["output_tokens"] * self.price_output_per_mtok) / 1e6


def chat_model(aws, outputs: StackOutputs) -> ChatModel:
    """The model the deployed assistant answers with, from the chat function's settings."""
    env = aws.client("lambda").get_function_configuration(FunctionName=outputs.chat_function)["Environment"]["Variables"]
    return ChatModel(
        id=env["MODEL_ID"],
        endpoint=env.get("CLAUDE_ENDPOINT", "mantle"),
        price_input_per_mtok=float(env.get("PRICE_INPUT_PER_MTOK", "2")),
        price_output_per_mtok=float(env.get("PRICE_OUTPUT_PER_MTOK", "10")),
    )


def claude_client(model: ChatModel, region: str):
    try:
        from anthropic import AnthropicBedrock, AnthropicBedrockMantle
    except ImportError as error:
        raise SystemExit("the anthropic package is missing; run `uv sync --group aws`") from error
    client = AnthropicBedrockMantle if model.endpoint == "mantle" else AnthropicBedrock
    # Bedrock quotas on this account are small; back off rather than fail (the SDK's retries are
    # exponential), since students share the same quota.
    return client(aws_region=region, max_retries=6)


def retrieve_urls(aws, outputs: StackOutputs, question: str, top_k: int) -> list[str]:
    results = aws.client("bedrock-agent-runtime").retrieve(
        knowledgeBaseId=outputs.knowledge_base_id,
        retrievalQuery={"text": question},
        retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": top_k}},
    )["retrievalResults"]
    return [r.get("metadata", {}).get("url", "") for r in results]


def score_case(urls: list[str], expect: list[str]) -> int | None:
    """1-based rank of the first result matching any expected URL fragment, or None."""
    for rank, url in enumerate(urls, start=1):
        if any(fragment in url for fragment in expect):
            return rank
    return None


def normalize_email(email: str) -> str:
    """An email address, or a whole domain written as @example.org."""
    email = email.strip().lower()
    if not (_EMAIL.match(email) or _DOMAIN.match(email)):
        raise ValueError(f"not an email address or @domain: {email!r}")
    return email


def allow_users(aws, outputs: StackOutputs, emails: list[str], role: str, added_by: str) -> list[str]:
    if role not in ROLES:
        raise ValueError(f"role must be one of {', '.join(ROLES)}")
    emails = sorted({normalize_email(e) for e in emails})
    if role != "student" and any(e.startswith("@") for e in emails):
        raise ValueError("domain entries can only be students; add mentors and admins by email")
    table = aws.resource("dynamodb").Table(outputs.table)
    now = datetime.now(UTC).isoformat(timespec="seconds")
    with table.batch_writer() as batch:
        for email in emails:
            batch.put_item(Item={"pk": "ALLOW", "sk": email, "role": role, "added_by": added_by, "added_at": now})
    return emails


def list_users(aws, outputs: StackOutputs) -> list[dict]:
    from boto3.dynamodb.conditions import Key

    table = aws.resource("dynamodb").Table(outputs.table)
    items, kwargs = [], {"KeyConditionExpression": Key("pk").eq("ALLOW")}
    while True:
        page = table.query(**kwargs)
        items += page["Items"]
        if "LastEvaluatedKey" not in page:
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def remove_user(aws, outputs: StackOutputs, email: str) -> int:
    """Remove from the allowlist, then sign out and delete their Cognito record(s).

    The allowlist alone blocks them at the next token refresh (at most an hour); deleting the
    Cognito user revokes refresh tokens now and keeps no record of the student behind.
    """
    email = normalize_email(email)
    aws.resource("dynamodb").Table(outputs.table).delete_item(Key={"pk": "ALLOW", "sk": email})
    if email.startswith("@") or not outputs.user_pool_id:
        return 0  # a domain's users lose access at their next token refresh (at most an hour)
    cognito = aws.client("cognito-idp")
    users = cognito.list_users(UserPoolId=outputs.user_pool_id, Filter=f'email = "{email}"')["Users"]
    for user in users:
        cognito.admin_user_global_sign_out(UserPoolId=outputs.user_pool_id, Username=user["Username"])
        cognito.admin_delete_user(UserPoolId=outputs.user_pool_id, Username=user["Username"])
    return len(users)
