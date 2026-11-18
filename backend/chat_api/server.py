"""Streaming chat endpoint: a small HTTP server run by the Lambda Web Adapter behind a Lambda
function URL (invoke mode RESPONSE_STREAM). Python Lambdas can't stream on their own; the adapter
forwards each invocation to this server and streams its response body back to the browser.

The function URL is public (API Gateway can't stream), so this server checks the Cognito ID
token itself: signature against the pool's published keys, issuer, audience (the web client),
expiry, and token_use. The allowlist role is in `cognito:groups`, set at sign-in.
"""

import json
import logging
import os
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .handler import ALLOWED_GROUPS, _default_dependencies
from .streaming import Disconnected, Rejected, prepare, run

log = logging.getLogger(__name__)
MAX_BODY_BYTES = 16_384


class Unauthorized(Exception):
    pass


class TokenVerifier:
    def __init__(self, region: str, user_pool_id: str, client_id: str, jwks_client=None):
        import jwt

        self.issuer = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"
        self.client_id = client_id
        self.jwks = jwks_client or jwt.PyJWKClient(f"{self.issuer}/.well-known/jwks.json", cache_keys=True, lifespan=3600)

    def verify(self, authorization: str) -> tuple[str, list[str]]:
        import jwt

        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise Unauthorized("missing bearer token")
        try:
            key = self.jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self.client_id,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "iss", "aud", "token_use"]},
            )
        except jwt.PyJWTError as error:
            raise Unauthorized(str(error)) from error
        if claims.get("token_use") != "id":
            raise Unauthorized("not an ID token")
        groups = claims.get("cognito:groups") or []
        return claims.get("email") or claims["sub"], list(groups) if isinstance(groups, list) else [str(groups)]


class App:
    def __init__(self, deps, verifier: TokenVerifier):
        self.deps = deps
        self.verifier = verifier

    @classmethod
    def from_env(cls) -> "App":
        env = os.environ
        deps = _default_dependencies(claude_timeout=100.0)
        return cls(deps, TokenVerifier(env.get("AWS_REGION", "us-east-1"), env["USER_POOL_ID"], env["WEB_CLIENT_ID"]))


class ChatRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    app: App  # set by serve()

    def do_GET(self):  # the adapter's readiness check
        self._json(200, {"ok": True})

    def do_POST(self):
        request_id = _request_id(self.headers.get("x-amzn-lambda-context"))
        # Read the body before any reply, so an early error doesn't reset the connection.
        length = int(self.headers.get("content-length") or 0)
        if length > MAX_BODY_BYTES:
            self.close_connection = True
            return self._json(413, {"error": "Request too large"})
        raw = self.rfile.read(length)

        try:
            user_id, groups = self.app.verifier.verify(self.headers.get("authorization", ""))
        except Unauthorized as error:
            log.info("rejected token: %s", error)
            return self._json(401, {"error": "Your session ended. Please sign in again."})
        if not ALLOWED_GROUPS.intersection(groups):
            return self._json(403, {"error": "Your account doesn't have access. Ask a mentor."})

        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"error": "Body must be JSON"})
        if not isinstance(body, dict):
            return self._json(400, {"error": "Body must be a JSON object"})

        try:
            prepared = prepare(self.app.deps, request_id, user_id, groups, body)
        except Exception:
            log.exception("prepare failed")
            return self._json(500, {"error": "Something went wrong. Try again."})
        if isinstance(prepared, Rejected):
            return self._json(prepared.status, {"error": prepared.error, **prepared.extra})

        self.send_response(200)
        self.send_header("content-type", "application/x-ndjson; charset=utf-8")
        self.send_header("cache-control", "no-store")
        self.send_header("transfer-encoding", "chunked")
        self.end_headers()
        run(prepared, self._emit, lambda: prepared.chats.stop_requested(user_id, request_id))
        try:
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except OSError:
            pass

    def _emit(self, event: dict) -> None:
        data = (json.dumps(event, default=str) + "\n").encode()
        try:
            self.wfile.write(b"%X\r\n%s\r\n" % (len(data), data))
            self.wfile.flush()
        except OSError as error:  # BrokenPipe / ConnectionReset
            raise Disconnected from error

    def _json(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):  # noqa: A002 - signature from BaseHTTPRequestHandler
        pass  # outcomes go to the audit log; errors are logged explicitly


def _request_id(context_header: str | None) -> str:
    try:
        return str(json.loads(context_header)["request_id"])
    except (TypeError, ValueError, KeyError):
        return str(uuid.uuid4())


def serve() -> None:
    logging.basicConfig(level=logging.INFO)
    ChatRequestHandler.app = App.from_env()
    ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("AWS_LWA_PORT", "8080"))), ChatRequestHandler).serve_forever()


if __name__ == "__main__":
    serve()
