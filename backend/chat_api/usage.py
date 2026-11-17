"""Spend tracking and caps, stored in the app's DynamoDB table.

Counters are in micro-dollars so DynamoDB's atomic ADD works on integers. Caps are checked before
a model call and charged after it, so one in-flight request can overshoot a cap by at most
`max_tokens` of output; reserved concurrency bounds how many can be in flight.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Pricing:
    input_usd_per_mtok: float
    output_usd_per_mtok: float

    def micro_usd(self, input_tokens: int, output_tokens: int) -> int:
        # USD per million tokens == micro-dollars per token.
        return round(input_tokens * self.input_usd_per_mtok + output_tokens * self.output_usd_per_mtok)


@dataclass(frozen=True)
class Limits:
    user_daily_usd: float
    monthly_usd: float


class LimitExceeded(Exception):
    def __init__(self, scope: str):
        super().__init__(f"{scope} spending limit reached")
        self.scope = scope


def user_key(user_id: str, now: datetime) -> dict:
    return {"pk": f"USAGE#USER#{user_id}", "sk": f"DAY#{now:%Y-%m-%d}"}


def global_key(now: datetime) -> dict:
    return {"pk": "USAGE#GLOBAL", "sk": f"MONTH#{now:%Y-%m}"}


class UsageLedger:
    def __init__(self, table, limits: Limits, pricing: Pricing):
        self.table = table
        self.limits = limits
        self.pricing = pricing

    def check(self, user_id: str, now: datetime) -> None:
        if self._spent(global_key(now)) >= self.limits.monthly_usd * 1e6:
            raise LimitExceeded("monthly")
        if self._spent(user_key(user_id, now)) >= self.limits.user_daily_usd * 1e6:
            raise LimitExceeded("daily")

    def charge(self, user_id: str, now: datetime, input_tokens: int, output_tokens: int) -> int:
        cost = self.pricing.micro_usd(input_tokens, output_tokens)
        for key in (user_key(user_id, now), global_key(now)):
            self.table.update_item(
                Key=key,
                UpdateExpression="ADD micro_usd :c, input_tokens :i, output_tokens :o, requests :one",
                ExpressionAttributeValues={":c": cost, ":i": input_tokens, ":o": output_tokens, ":one": 1},
            )
        return cost

    def _spent(self, key: dict) -> int:
        item = self.table.get_item(Key=key, ConsistentRead=True).get("Item") or {}
        return int(item.get("micro_usd", 0))
