"""Know when answers break: an email alarm on errors, and a daily test question.

- Every function that answers questions (chat, web stream, Slack) logs failures at ERROR. A
  metric filter counts those lines; any in a 5-minute window sets off an alarm that emails
  alert_email (and again when it clears). Confirm the SNS subscription email once.
- Once a day a schedule asks the chat function one question through the streaming pipeline, so
  a problem between deploys (a revoked model, an empty Knowledge Base) shows up the same day
  rather than when a student hits it. It costs about half a cent.
"""

from aws_cdk import Duration, Stack
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_cloudwatch_actions as actions
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_sns as sns
from constructs import Construct

NAMESPACE = "FrcRag"
CHECK_USER = "daily-check"
CHECK_QUESTION = "What size bolts are most common on FRC robots, and why?"
# 12:00 UTC is 7-8 am in Virginia: a failure is in the inbox before the school day.
CHECK_SCHEDULE = events.Schedule.cron(minute="0", hour="12")


class Monitoring(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        alert_email: str,
        chat: lambda_.IFunction,
        log_groups: dict[str, logs.ILogGroup],
    ):
        super().__init__(scope, construct_id)
        stack = Stack.of(self)
        topic = sns.Topic(self, "Alerts", display_name=f"{stack.stack_name} alerts")
        sns.Subscription(self, "Email", topic=topic, protocol=sns.SubscriptionProtocol.EMAIL, endpoint=alert_email)

        metric_name = "AnswerErrors"
        for name, group in log_groups.items():
            logs.MetricFilter(
                self,
                f"{name}Errors",
                log_group=group,
                metric_namespace=NAMESPACE,
                metric_name=metric_name,
                filter_pattern=logs.FilterPattern.any_term("ERROR", "Traceback"),
                metric_value="1",
                default_value=0,
            )
        alarm = cloudwatch.Alarm(
            self,
            "AnswerErrorsAlarm",
            alarm_description="Questions are failing. Check the chat, stream and Slack worker logs.",
            metric=cloudwatch.Metric(namespace=NAMESPACE, metric_name=metric_name, statistic="Sum", period=Duration.minutes(5)),
            threshold=1,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        alarm.add_alarm_action(actions.SnsAction(topic))
        alarm.add_ok_action(actions.SnsAction(topic))

        events.Rule(
            self,
            "DailyCheck",
            description="Ask one question through the streaming pipeline; failures trip the errors alarm",
            schedule=CHECK_SCHEDULE,
            targets=[
                targets.LambdaFunction(
                    chat,
                    event=events.RuleTargetInput.from_object({"user": CHECK_USER, "question": CHECK_QUESTION, "stream": True}),
                    retry_attempts=0,
                )
            ],
        )
        self.topic = topic
