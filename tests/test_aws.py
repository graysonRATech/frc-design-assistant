import hashlib
import json
import sys

import pytest

from frcrag import aws
from frcrag.aws import StackOutputs, plan_sync, score_case

OUTPUTS = StackOutputs("bucket", "KB", "DS", "chat-fn", "table")


class FakeS3:
    def __init__(self, objects: dict[str, bytes]):
        self.objects = dict(objects)

    def get_paginator(self, name):
        s3 = self

        class Paginator:
            def paginate(self, Bucket, Prefix):
                yield {
                    "Contents": [
                        {"Key": k, "ETag": f'"{hashlib.md5(v).hexdigest()}"'} for k, v in s3.objects.items() if k.startswith(Prefix)
                    ]
                }

        return Paginator()

    def put_object(self, Bucket, Key, Body, ContentType):
        self.objects[Key] = Body

    def delete_objects(self, Bucket, Delete):
        for obj in Delete["Objects"]:
            del self.objects[obj["Key"]]


class FakeSession:
    def __init__(self, **clients):
        self.clients = clients

    def client(self, name):
        return self.clients[name]


def test_plan_sync_uploads_changed_and_deletes_stale():
    uploads, deletes = plan_sync({"a": "1", "b": "2", "c": "3"}, {"a": "1", "b": "old", "gone": "x"})
    assert uploads == ["b", "c"] and deletes == ["gone"]


def test_sync_mirrors_sources_and_uploads_manifests(tmp_path):
    (tmp_path / "frcdesign").mkdir()
    (tmp_path / "frcdesign" / "gears--000.md").write_bytes(b"new gears")
    (tmp_path / "frcdesign" / "belts--000.md").write_bytes(b"same belts")
    (tmp_path / "_manifests").mkdir()
    (tmp_path / "_manifests" / "frcdesign.json").write_text(json.dumps({"revision": "x"}))

    s3 = FakeS3(
        {
            "kb/frcdesign/gears--000.md": b"old gears",
            "kb/frcdesign/belts--000.md": b"same belts",
            "kb/frcdesign/removed--000.md": b"page deleted upstream",
            "kb/old-source/page--000.md": b"source removed from sources.yaml",
        }
    )
    session = FakeSession(s3=s3)
    assert aws.sync(session, OUTPUTS, tmp_path, ["frcdesign"], dry_run=True) == (1, 2)
    assert aws.sync(session, OUTPUTS, tmp_path, ["frcdesign"]) == (1, 2)
    assert sorted(s3.objects) == ["kb/frcdesign/belts--000.md", "kb/frcdesign/gears--000.md", "manifests/frcdesign.json"]
    assert s3.objects["kb/frcdesign/gears--000.md"] == b"new gears"


def test_sync_refuses_when_a_configured_source_is_unbuilt(tmp_path, monkeypatch, capsys):
    from frcrag import cli

    monkeypatch.setattr(aws, "session", lambda region: FakeSession())
    monkeypatch.setattr(aws, "stack_outputs", lambda session, name: OUTPUTS)
    assert cli.main(["sync", "--out", str(tmp_path)]) == 2


def test_score_case_returns_first_matching_rank():
    urls = ["https://x/gears/", "https://x/belts/#center", "https://x/chain/"]
    assert score_case(urls, ["belts/", "chain/"]) == 2
    assert score_case(urls, ["swerve/"]) is None


def test_ask_surfaces_unhandled_lambda_errors():
    class Payload:
        def read(self):
            return json.dumps({"errorMessage": "boom", "errorType": "KeyError"}).encode()

    class FakeLambda:
        def invoke(self, FunctionName, Payload_=None, **kwargs):
            return {"Payload": Payload()}

    assert aws.ask(FakeSession(**{"lambda": FakeLambda()}), OUTPUTS, "q", "coach") == (500, {"error": "boom"})


def test_ingest_commands_do_not_need_boto3(monkeypatch):
    monkeypatch.setitem(sys.modules, "boto3", None)
    from frcrag import cli

    assert cli.main(["sources"]) == 0


def test_normalize_email_rejects_junk():
    import pytest

    assert aws.normalize_email("  Student@Example.ORG ") == "student@example.org"
    with pytest.raises(ValueError):
        aws.normalize_email("not-an-email")


def test_allow_users_writes_lowercased_deduped_entries():
    import pytest

    written = []

    class Batch:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def put_item(self, Item):
            written.append(Item)

    class Table:
        def batch_writer(self):
            return Batch()

    class Resource:
        def Table(self, name):
            return Table()

    class Session:
        def resource(self, name):
            return Resource()

    added = aws.allow_users(Session(), OUTPUTS, ["A@x.org", "a@x.org", "b@x.org"], "mentor", "coach")
    assert added == ["a@x.org", "b@x.org"]
    assert {(i["pk"], i["sk"], i["role"]) for i in written} == {("ALLOW", "a@x.org", "mentor"), ("ALLOW", "b@x.org", "mentor")}
    with pytest.raises(ValueError):
        aws.allow_users(Session(), OUTPUTS, ["a@x.org"], "owner", "coach")
    assert aws.allow_users(Session(), OUTPUTS, ["@School.org "], "student", "coach") == ["@school.org"]
    with pytest.raises(ValueError, match="domain entries"):
        aws.allow_users(Session(), OUTPUTS, ["@school.org"], "admin", "coach")


@pytest.mark.parametrize("entry", ["@", "@school", "@-x.org", "@school.org/x", "a@b@c.org"])
def test_normalize_email_rejects_bad_domains(entry):
    with pytest.raises(ValueError):
        aws.normalize_email(entry)
