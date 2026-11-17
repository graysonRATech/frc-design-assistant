"""CDK entry point (see cdk.json). Builds the chat Lambda bundle, then synthesizes the stack."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aws_cdk import App, Environment, Tags  # noqa: E402

from infra.config import ROOT, load  # noqa: E402
from infra.stack import FrcRagStack  # noqa: E402
from scripts.build_lambda import build  # noqa: E402

config = load()
app = App()
FrcRagStack(
    app,
    config.stack_name,
    config=config,
    chat_code=build(),
    backend_dir=ROOT / "backend",
    web_dir=ROOT / "web",
    env=Environment(account=config.account, region=config.region),
    description="FRC design RAG assistant: knowledge base, chat Lambda, audit log, budget guardrails",
)
Tags.of(app).add("project", "frc-rag")
app.synth()
