"""The Slack bot (backend/chat_api/slack.py): a receiver behind a public function URL that Slack's
Events API posts to, and a worker that streams answers back into Slack threads.

The receiver only checks Slack's signature, de-duplicates retries and starts the worker; it has
no Bedrock access. The worker shares the chat role, so it has the same rights, caps and Budgets
kill switch as the website's chat functions.
"""

from pathlib import Path

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct

from .config import DeployConfig


class SlackBot(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: DeployConfig,
        chat_code: Path,
        table: dynamodb.ITableV2,
        chat_role: iam.IRole,
        chat_environment: dict[str, str],
    ):
        super().__init__(scope, construct_id)
        secret = secretsmanager.Secret.from_secret_name_v2(self, "Secret", config.slack_secret_name)
        slack_environment = {"SLACK_SECRET_NAME": config.slack_secret_name, "SLACK_TEAM_ID": config.slack_team_id}

        worker_logs = logs.LogGroup(self, "WorkerLogs", retention=logs.RetentionDays.THREE_MONTHS, removal_policy=RemovalPolicy.DESTROY)
        events_logs = logs.LogGroup(self, "EventsLogs", retention=logs.RetentionDays.THREE_MONTHS, removal_policy=RemovalPolicy.DESTROY)
        worker = lambda_.Function(
            self,
            "Worker",
            runtime=lambda_.Runtime.PYTHON_3_13,
            architecture=lambda_.Architecture.ARM_64,
            handler="chat_api.slack.worker_handler",
            code=lambda_.Code.from_asset(str(chat_code)),
            role=chat_role,
            memory_size=512,
            timeout=Duration.seconds(180),
            reserved_concurrent_executions=config.lambda_reserved_concurrency or None,
            retry_attempts=0,  # a retry would post the answer twice
            log_group=worker_logs,
            environment={**chat_environment, **slack_environment},
        )
        secret.grant_read(chat_role)

        receiver = lambda_.Function(
            self,
            "Events",
            runtime=lambda_.Runtime.PYTHON_3_13,
            architecture=lambda_.Architecture.ARM_64,
            handler="chat_api.slack.events_handler",
            code=lambda_.Code.from_asset(str(chat_code)),
            memory_size=256,
            timeout=Duration.seconds(10),
            log_group=events_logs,
            environment={**slack_environment, "TABLE_NAME": table.table_name, "WORKER_FUNCTION": worker.function_name},
        )
        secret.grant_read(receiver)
        worker.grant_invoke(receiver)
        receiver.add_to_role_policy(iam.PolicyStatement(actions=["dynamodb:PutItem"], resources=[table.table_arn]))
        # Public, like Slack needs; every request is checked against Slack's signing secret.
        url = receiver.add_function_url(auth_type=lambda_.FunctionUrlAuthType.NONE)

        self.log_groups = {"SlackWorker": worker_logs, "SlackEvents": events_logs}
        CfnOutput(Stack.of(self), "SlackEventsUrl", value=url.url)
