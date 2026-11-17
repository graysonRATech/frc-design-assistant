"""Minimal HTTP GET with retries and an identifying User-Agent."""

import os
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "frc-design-rag-ingest/0.1 (educational FRC team knowledge base)"
_GITHUB_HOSTS = {"api.github.com", "codeload.github.com"}


def get(url: str, *, accept: str | None = None, timeout: float = 30, retries: int = 3) -> bytes:
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    token = os.environ.get("GITHUB_TOKEN")
    if token and urllib.parse.urlparse(url).hostname in _GITHUB_HOSTS:
        headers["Authorization"] = f"Bearer {token}"

    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            # Client errors won't fix themselves; only retry throttling and server errors.
            if error.code < 500 and error.code != 429:
                raise
            last_error = error
        except urllib.error.URLError as error:
            last_error = error
        time.sleep(2**attempt)
    raise last_error
