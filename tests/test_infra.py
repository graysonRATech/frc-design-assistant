import json
from pathlib import Path

import pytest

pytest.importorskip("aws_cdk", reason="install with: uv sync --group infra")

from aws_cdk import App, Environment  # noqa: E402
from aws_cdk.assertions import Match, Template  # noqa: E402

from infra.config import load  # noqa: E402
from infra.stack import FrcRagStack  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
WEB_FIXTURE = ROOT / "tests" / "fixtures" / "web"  # stands in for web/dist, which needs an npm build


@pytest.fixture(scope="module")
def template() -> Template:
    config = load(ROOT / "config.example.yaml")
    app = App()
    stack = FrcRagStack(
        app,
        "Test",
        config=config,
        chat_code=ROOT / "backend",
        backend_dir=ROOT / "backend",
        web_dir=WEB_FIXTURE,
        env=Environment(account="123456789012", region="us-east-1"),
    )
    return Template.from_stack(stack)


def test_knowledge_base_uses_s3_vectors_and_unchunked_files(template):
    template.has_resource_properties(
        "AWS::Bedrock::KnowledgeBase",
        {"StorageConfiguration": {"Type": "S3_VECTORS", "S3VectorsConfiguration": Match.any_value()}},
    )
    template.has_resource_properties(
        "AWS::Bedrock::DataSource",
        {
            "DataSourceConfiguration": {"S3Configuration": {"InclusionPrefixes": ["kb/"]}},
            "VectorIngestionConfiguration": {"ChunkingConfiguration": {"ChunkingStrategy": "NONE"}},
        },
    )
    template.has_resource_properties(
        "AWS::S3Vectors::Index",
        {
            "Dimension": 1024,
            "MetadataConfiguration": {"NonFilterableMetadataKeys": ["AMAZON_BEDROCK_TEXT", "AMAZON_BEDROCK_METADATA"]},
        },
    )
    template.resource_count_is("AWS::OpenSearchServerless::Collection", 0)


def test_chat_lambda_is_configured_with_caps(template):
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "Handler": "chat_api.handler.lambda_handler",
            "Architectures": ["arm64"],
            "Environment": {
                "Variables": Match.object_like(
                    {"MODEL_ID": "anthropic.claude-sonnet-5-5", "MONTHLY_LIMIT_USD": "20.0", "USER_DAILY_LIMIT_USD": "0.5"}
                )
            },
        },
    )


def test_budget_alerts_and_bedrock_kill_switch(template):
    budget = next(iter(template.find_resources("AWS::Budgets::Budget").values()))
    thresholds = sorted(n["Notification"]["Threshold"] for n in budget["Properties"]["NotificationsWithSubscribers"])
    assert thresholds == [50, 80, 100, 100]
    template.has_resource_properties(
        "AWS::Budgets::BudgetsAction",
        {"ActionType": "APPLY_IAM_POLICY", "ActionThreshold": {"Type": "PERCENTAGE", "Value": 120}, "ApprovalModel": "AUTOMATIC"},
    )
    template.has_resource_properties(
        "AWS::IAM::ManagedPolicy",
        {
            "PolicyDocument": {
                "Statement": [Match.object_like({"Effect": "Deny", "Action": ["bedrock:*", "bedrock-mantle:*"]})]
            }
        },
    )


def test_audit_table_is_retained_with_ttl(template):
    template.has_resource(
        "AWS::DynamoDB::GlobalTable",
        {"DeletionPolicy": "Retain", "Properties": Match.object_like({"TimeToLiveSpecification": {"AttributeName": "expires_at", "Enabled": True}})},
    )


def test_config_rejects_app_cap_above_budget(tmp_path):
    local = tmp_path / "config.local.yaml"
    local.write_text("monthly_budget_usd: 10\nlimits:\n  monthly_usd: 15\n")
    with pytest.raises(ValueError):
        load(local)


def test_api_requires_cognito_jwt_on_every_route(template):
    routes = template.find_resources("AWS::ApiGatewayV2::Route")
    assert {r["Properties"]["RouteKey"] for r in routes.values()} == {
        "POST /chat",
        "POST /feedback",
        "GET /chats",
        "GET /chats/{id}",
        "PATCH /chats/{id}",
        "DELETE /chats/{id}",
        "POST /chats/stop",
        "GET /settings",
        "PUT /settings",
    }
    assert all(r["Properties"]["AuthorizationType"] == "JWT" for r in routes.values())
    template.has_resource_properties("AWS::ApiGatewayV2::Authorizer", {"AuthorizerType": "JWT"})


def test_user_pool_is_invite_only_with_allowlist_triggers(template):
    template.has_resource_properties(
        "AWS::Cognito::UserPool",
        {
            "AdminCreateUserConfig": {"AllowAdminCreateUserOnly": True},
            "LambdaConfig": {"PreSignUp": Match.any_value(), "PreTokenGeneration": Match.any_value()},
        },
    )
    template.has_resource_properties(
        "AWS::Cognito::UserPoolClient", {"GenerateSecret": False, "IdTokenValidity": 60, "AllowedOAuthFlows": ["code"]}
    )


def test_google_provider_only_when_configured(template, tmp_path):
    template.resource_count_is("AWS::Cognito::UserPoolIdentityProvider", 0)
    local = tmp_path / "config.local.yaml"
    local.write_text("web:\n  google_client_id: abc.apps.googleusercontent.com\n")
    stack = FrcRagStack(
        App(),
        "WithGoogle",
        config=load(local),
        chat_code=ROOT / "backend",
        backend_dir=ROOT / "backend",
        web_dir=WEB_FIXTURE,
        env=Environment(account="123456789012", region="us-east-1"),
    )
    google = Template.from_stack(stack)
    google.has_resource_properties("AWS::Cognito::UserPoolIdentityProvider", {"ProviderName": "Google"})
    google.has_resource_properties("AWS::Cognito::UserPoolClient", {"SupportedIdentityProviders": ["Google"]})


def test_site_is_private_behind_cloudfront_with_csp(template):
    template.has_resource_properties(
        "AWS::CloudFront::ResponseHeadersPolicy",
        {"ResponseHeadersPolicyConfig": {"SecurityHeadersConfig": Match.object_like({"ContentSecurityPolicy": Match.any_value()})}},
    )
    template.resource_count_is("AWS::CloudFront::OriginAccessControl", 1)


def _stack_with_repo(tmp_path, repo: str) -> Template:
    local = tmp_path / "config.local.yaml"
    local.write_text(f"github:\n  repo: {repo}\n", encoding="utf-8")
    app = App()
    stack = FrcRagStack(
        app,
        "Test",
        config=load(local),
        chat_code=ROOT / "backend",
        backend_dir=ROOT / "backend",
        web_dir=WEB_FIXTURE,
        env=Environment(account="123456789012", region="us-east-1"),
    )
    return Template.from_stack(stack)


def _stack_from(tmp_path, local_yaml: str) -> Template:
    local = tmp_path / "config.local.yaml"
    local.write_text(local_yaml, encoding="utf-8")
    stack = FrcRagStack(
        App(),
        "Test",
        config=load(local),
        chat_code=ROOT / "backend",
        backend_dir=ROOT / "backend",
        web_dir=WEB_FIXTURE,
        env=Environment(account="123456789012", region="us-east-1"),
    )
    return Template.from_stack(stack)


CERT = "arn:aws:acm:us-east-1:123456789012:certificate/abc"


def test_streaming_function_url_streams_and_shares_the_chat_role(template):
    url = next(iter(template.find_resources("AWS::Lambda::Url").values()))["Properties"]
    assert url["InvokeMode"] == "RESPONSE_STREAM" and url["AuthType"] == "NONE"
    assert url["Cors"]["AllowMethods"] == ["POST"] and "authorization" in url["Cors"]["AllowHeaders"]
    functions = template.find_resources("AWS::Lambda::Function", {"Properties": {"Handler": "run.sh"}})
    stream = next(iter(functions.values()))["Properties"]
    assert stream["Layers"] == ["arn:aws:lambda:us-east-1:753240598075:layer:LambdaAdapterLayerArm64:30"]
    env = stream["Environment"]["Variables"]
    assert env["AWS_LAMBDA_EXEC_WRAPPER"] == "/opt/bootstrap" and env["AWS_LWA_INVOKE_MODE"] == "response_stream"
    assert {"USER_POOL_ID", "WEB_CLIENT_ID", "MODEL_ID", "CHAT_RETENTION_DAYS"} <= set(env)
    chat = next(iter(template.find_resources("AWS::Lambda::Function", {"Properties": {"Handler": "chat_api.handler.lambda_handler"}}).values()))
    assert stream["Role"] == chat["Properties"]["Role"]  # same rights, same Budgets kill switch


def test_csp_allows_the_streaming_url(template):
    policy = next(iter(template.find_resources("AWS::CloudFront::ResponseHeadersPolicy").values()))
    csp = policy["Properties"]["ResponseHeadersPolicyConfig"]["SecurityHeadersConfig"]["ContentSecurityPolicy"]["ContentSecurityPolicy"]
    assert "https://*.lambda-url.us-east-1.on.aws" in csp


def test_custom_domain_is_served_and_allowed_for_sign_in(tmp_path):
    template = _stack_from(tmp_path, f"web:\n  domain_name: FRC.Example.org\n  certificate_arn: {CERT}\n")
    template.has_resource_properties(
        "AWS::CloudFront::Distribution",
        {"DistributionConfig": Match.object_like({"Aliases": ["frc.example.org"], "ViewerCertificate": Match.object_like({"AcmCertificateArn": CERT})})},
    )
    client = next(iter(template.find_resources("AWS::Cognito::UserPoolClient").values()))["Properties"]
    assert client["CallbackURLs"][0] == "https://frc.example.org/" and len(client["CallbackURLs"]) == 2
    api = next(iter(template.find_resources("AWS::ApiGatewayV2::Api").values()))["Properties"]
    assert "https://frc.example.org" in api["CorsConfiguration"]["AllowOrigins"]
    assert template.to_json()["Outputs"]["WebUrl"]["Value"] == "https://frc.example.org/"


def test_no_alias_without_custom_domain(template):
    distribution = next(iter(template.find_resources("AWS::CloudFront::Distribution").values()))
    assert "Aliases" not in distribution["Properties"]["DistributionConfig"]


@pytest.mark.parametrize(
    "web",
    [
        "domain_name: frc.example.org",
        f"certificate_arn: {CERT}",
        f"domain_name: frc.example.org\n  certificate_arn: {CERT.replace('us-east-1', 'us-west-2')}",
        f"domain_name: https://frc.example.org\n  certificate_arn: {CERT}",
    ],
)
def test_custom_domain_settings_are_validated(tmp_path, web):
    local = tmp_path / "config.local.yaml"
    local.write_text(f"web:\n  {web}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="domain_name|certificate_arn"):
        load(local)


def test_no_github_access_without_repo(template):
    template.resource_count_is("AWS::IAM::OIDCProvider", 0)
    assert not [k for k in template.to_json()["Outputs"] if k.startswith("GitHub")]


def test_github_roles_are_scoped_to_repo_and_context(tmp_path):
    template = _stack_with_repo(tmp_path, "team/frc-rag")
    template.has_resource_properties(
        "AWS::IAM::OIDCProvider", {"Url": "https://token.actions.githubusercontent.com", "ClientIdList": ["sts.amazonaws.com"]}
    )

    def subject(role_name: str) -> str:
        role = next(
            r["Properties"] for r in template.find_resources("AWS::IAM::Role").values() if r["Properties"].get("RoleName") == role_name
        )
        condition = role["AssumeRolePolicyDocument"]["Statement"][0]["Condition"]["StringEquals"]
        assert condition["token.actions.githubusercontent.com:aud"] == "sts.amazonaws.com"
        return condition["token.actions.githubusercontent.com:sub"]

    assert subject("Test-github-deploy") == "repo:team/frc-rag:environment:production"
    assert subject("Test-github-content") == "repo:team/frc-rag:ref:refs/heads/main"

    # The content role can't touch anything but the bucket, the KB and reading stack outputs.
    policies = [p["Properties"] for p in template.find_resources("AWS::IAM::Policy").values()]
    content_policy = next(p for p in policies if "ContentRole" in str(p["Roles"]))
    actions = {a for s in content_policy["PolicyDocument"]["Statement"] for a in ([s["Action"]] if isinstance(s["Action"], str) else s["Action"])}
    assert actions == {
        "cloudformation:DescribeStacks",
        "s3:ListBucket",
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "bedrock:StartIngestionJob",
        "bedrock:GetIngestionJob",
        "bedrock:Retrieve",
    }


def test_github_roles_accept_immutable_repo_subjects(tmp_path):
    template = _stack_with_repo(tmp_path, "team@42/frc-rag@7")
    roles = template.find_resources("AWS::IAM::Role", {"Properties": {"RoleName": "Test-github-content"}})
    condition = next(iter(roles.values()))["Properties"]["AssumeRolePolicyDocument"]["Statement"][0]["Condition"]["StringEquals"]
    assert condition["token.actions.githubusercontent.com:sub"] == "repo:team@42/frc-rag@7:ref:refs/heads/main"


def test_github_repo_must_be_owner_slash_name(tmp_path):
    with pytest.raises(ValueError):
        _stack_with_repo(tmp_path, "'team/frc-rag:*'")


def test_runtime_endpoint_grants_invoke_model_on_the_inference_profile(tmp_path):
    local = tmp_path / "config.local.yaml"
    local.write_text(
        "model:\n  id: us.anthropic.claude-haiku-4-5-20251001-v1:0\n  endpoint: runtime\n  effort: ''\n", encoding="utf-8"
    )
    stack = FrcRagStack(
        App(),
        "Test",
        config=load(local),
        chat_code=ROOT / "backend",
        backend_dir=ROOT / "backend",
        web_dir=WEB_FIXTURE,
        env=Environment(account="123456789012", region="us-east-1"),
    )
    policies = json.dumps(Template.from_stack(stack).find_resources("AWS::IAM::Policy"))
    assert "inference-profile/us.anthropic.claude-haiku-4-5-20251001-v1:0" in policies
    assert "arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0" in policies
    assert "bedrock:InvokeModelWithResponseStream" in policies  # the streaming functions need it
    assert "bedrock-mantle:CreateInference" not in policies


def test_no_slack_bot_without_team_id(template):
    assert not template.find_resources("AWS::Lambda::Function", {"Properties": {"Handler": "chat_api.slack.events_handler"}})


def test_slack_bot_receiver_is_signed_public_url_and_worker_shares_chat_role(tmp_path):
    t = _stack_from(tmp_path, "slack:\n  team_id: T0TORCH01\n")
    functions = t.find_resources("AWS::Lambda::Function")
    by_handler = {f["Properties"]["Handler"]: f["Properties"] for f in functions.values()}
    receiver, worker = by_handler["chat_api.slack.events_handler"], by_handler["chat_api.slack.worker_handler"]
    chat = by_handler["chat_api.handler.lambda_handler"]
    assert worker["Role"] == chat["Role"] and receiver["Role"] != chat["Role"]
    assert receiver["Environment"]["Variables"]["SLACK_TEAM_ID"] == "T0TORCH01"
    assert "KNOWLEDGE_BASE_ID" not in receiver["Environment"]["Variables"]
    t.has_resource_properties("AWS::Lambda::Url", {"AuthType": "NONE", "InvokeMode": Match.absent()})
    t.has_resource_properties("AWS::Lambda::EventInvokeConfig", {"MaximumRetryAttempts": 0})
    # The receiver can start the worker and read the Slack secret, but can't call Bedrock.
    policies = json.dumps(
        [p for p in t.find_resources("AWS::IAM::Policy").values() if receiver["Role"]["Fn::GetAtt"][0] in json.dumps(p["Properties"]["Roles"])]
    )
    assert "lambda:InvokeFunction" in policies and "secretsmanager:GetSecretValue" in policies and "bedrock" not in policies


def test_slack_team_id_is_validated(tmp_path):
    local = tmp_path / "config.local.yaml"
    local.write_text("slack:\n  team_id: torch\n", encoding="utf-8")
    with pytest.raises(ValueError, match="slack.team_id"):
        load(local)
