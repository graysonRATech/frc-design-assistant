"""Check a deployed stack actually answers questions. Run after every deploy (deploy.yml).

1. The chat page loads, with its Content-Security-Policy header.
   The Onshape panel page loads, and its policy lets only Onshape frame it.
2. The streaming URL refuses a request without a sign-in token (it's up, and it checks).
3. One real question through the streaming pipeline, by invoking the chat function directly with
   {"stream": true}. It runs under the same role and makes the same Bedrock calls as the web page
   and the Slack bot, so a missing permission or model access shows up here, not for a student.
   The answer must have text and cite at least one retrieved source. Costs about half a cent.

Needs AWS credentials that may read the stack outputs and invoke the chat function (the GitHub
deploy role can). Exits non-zero on the first failure.
"""

import json
import sys
import urllib.error
import urllib.request

STACK = "FrcRag"
REGION = "us-east-1"
USER = "deploy-smoke-test"
QUESTION = "What size bolts are most common on FRC robots, and why?"


class SmokeFailed(Exception):
    pass


def http_status(url: str, method: str = "GET", data: bytes | None = None) -> tuple[int, dict]:
    request = urllib.request.Request(url, method=method, data=data, headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, dict(response.headers)
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers)


def check(outputs: dict[str, str], invoke, status=http_status) -> list[str]:
    """Run the checks; `invoke(function_name, payload) -> dict` calls Lambda. Returns a report."""
    report = []
    code, headers = status(outputs["WebUrl"])
    if code != 200 or "content-security-policy" not in {k.lower() for k in headers}:
        raise SmokeFailed(f"chat page: HTTP {code}, CSP header {'present' if headers else 'missing'}")
    report.append(f"chat page loads ({outputs['WebUrl']})")

    panel = outputs["WebUrl"].rstrip("/") + "/onshape/index.html"
    code, headers = status(panel)
    csp = next((v for k, v in headers.items() if k.lower() == "content-security-policy"), "")
    if code != 200 or "frame-ancestors https://cad.onshape.com" not in csp:
        raise SmokeFailed(f"Onshape panel page: HTTP {code}, frame-ancestors not limited to Onshape")
    report.append("Onshape panel page loads and only Onshape may frame it")

    code, _ = status(outputs["StreamUrl"], "POST", b'{"question": "hi"}')
    if code != 401:
        raise SmokeFailed(f"streaming URL without a token: expected 401, got {code}")
    report.append("streaming URL refuses requests without a sign-in")

    response = invoke(outputs["ChatFunctionName"], {"user": USER, "question": QUESTION, "stream": True})
    body = json.loads(response.get("body") or "{}")
    if response.get("statusCode") != 200:
        raise SmokeFailed(f"test question: HTTP {response.get('statusCode')}: {body.get('error', response)}")
    if len(body.get("answer", "")) < 40 or not body.get("sources"):
        raise SmokeFailed(f"test question: answer too short or uncited: {body}")
    cost = body.get("usage", {}).get("cost_usd", 0)
    report.append(f"test question answered with {len(body['sources'])} cited source(s), ${cost:.4f}")
    return report


def main() -> int:
    import boto3

    stack = boto3.client("cloudformation", region_name=REGION).describe_stacks(StackName=STACK)["Stacks"][0]
    outputs = {o["OutputKey"]: o["OutputValue"] for o in stack.get("Outputs", [])}
    client = boto3.client("lambda", region_name=REGION)

    def invoke(name: str, payload: dict) -> dict:
        result = client.invoke(FunctionName=name, Payload=json.dumps(payload).encode())
        if result.get("FunctionError"):
            raise SmokeFailed(f"chat function crashed: {result['Payload'].read().decode()[:500]}")
        return json.loads(result["Payload"].read())

    try:
        for line in check(outputs, invoke):
            print(f"ok   {line}")
    except SmokeFailed as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
