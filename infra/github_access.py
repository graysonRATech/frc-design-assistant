"""GitHub Actions access via OIDC: short-lived credentials, no AWS keys stored in GitHub.

Two roles, each trusted only for one repository and one context:
- deploy: workflows running in the repo's `production` environment may assume the CDK bootstrap
  roles (which do the actual CloudFormation work). Gate it with required reviewers on the
  environment if more than one person can push to main.
- content: workflows on the main branch may upload chunks and re-index the Knowledge Base, and
  nothing else. Pull requests (including from forks) never get either role.
"""

from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from constructs import Construct

GITHUB_OIDC = "token.actions.githubusercontent.com"
DEPLOY_ENVIRONMENT = "production"  # must match `environment:` in .github/workflows/deploy.yml


class GitHubAccess(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        repo: str,
        content: s3.IBucket,
        knowledge_base_arn: str,
    ):
        super().__init__(scope, construct_id)
        stack = Stack.of(self)
        provider = iam.OidcProviderNative(self, "Provider", url=f"https://{GITHUB_OIDC}", client_ids=["sts.amazonaws.com"])

        def principal(subject: str) -> iam.IPrincipal:
            return iam.WebIdentityPrincipal(
                provider.oidc_provider_arn,
                conditions={"StringEquals": {f"{GITHUB_OIDC}:aud": "sts.amazonaws.com", f"{GITHUB_OIDC}:sub": subject}},
            )

        # Fixed names so workflows can build the ARNs from the account ID alone.
        deploy = iam.Role(
            self,
            "DeployRole",
            role_name=f"{stack.stack_name}-github-deploy",
            assumed_by=principal(f"repo:{repo}:environment:{DEPLOY_ENVIRONMENT}"),
            description=f"cdk deploy from {repo} (GitHub environment {DEPLOY_ENVIRONMENT})",
        )
        deploy.add_to_policy(
            iam.PolicyStatement(
                actions=["sts:AssumeRole"],
                resources=[f"arn:aws:iam::{stack.account}:role/cdk-hnb659fds-*-{stack.account}-{stack.region}"],
            )
        )

        sync = iam.Role(
            self,
            "ContentRole",
            role_name=f"{stack.stack_name}-github-content",
            assumed_by=principal(f"repo:{repo}:ref:refs/heads/main"),
            description=f"kb sync / kb eval from {repo} main",
        )
        sync.add_to_policy(
            iam.PolicyStatement(
                actions=["cloudformation:DescribeStacks"],
                resources=[stack.format_arn(service="cloudformation", resource="stack", resource_name=f"{stack.stack_name}/*")],
            )
        )
        sync.add_to_policy(iam.PolicyStatement(actions=["s3:ListBucket"], resources=[content.bucket_arn]))
        sync.add_to_policy(
            iam.PolicyStatement(actions=["s3:GetObject", "s3:PutObject", "s3:DeleteObject"], resources=[content.arn_for_objects("*")])
        )
        sync.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:StartIngestionJob", "bedrock:GetIngestionJob", "bedrock:Retrieve"],
                resources=[knowledge_base_arn],
            )
        )

        CfnOutput(stack, "GitHubDeployRoleArn", value=deploy.role_arn)
        CfnOutput(stack, "GitHubContentRoleArn", value=sync.role_arn)
