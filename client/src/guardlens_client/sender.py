"""HTTP client that posts screenshot frames to the GuardianLens server."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

UPLOAD_TIMEOUT = 30.0
RETRY_DELAYS = (2.0, 5.0, 10.0)


class FrameSender:
    """Sends PNG frames to ``POST /api/frames`` on the GuardianLens server."""

    def __init__(self, server_url: str) -> None:
        base = server_url.rstrip("/")
        if not base.startswith("http"):
            base = f"http://{base}"
        self._url = f"{base}/api/frames"
        self._client = httpx.Client(timeout=UPLOAD_TIMEOUT)

    def send(self, path: Path) -> bool:
        """Upload *path* to the server. Returns True on success.

        Retries up to 3 times with exponential back-off on transient errors.
        """
        for attempt, delay in enumerate((*RETRY_DELAYS, None), start=1):
            try:
                with path.open("rb") as fh:
                    resp = self._client.post(
                        self._url,
                        files={"file": (path.name, fh, "image/png")},
                    )
                resp.raise_for_status()
                logger.info("Frame sent: %s → %s", path.name, resp.json().get("file", "?"))
                return True
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "Server rejected frame (HTTP %d): %s", exc.response.status_code, path.name
                )
                return False
            except httpx.RequestError as exc:
                logger.warning("Send attempt %d failed (%s): %s", attempt, exc, path.name)
                if delay is None:
                    break
                time.sleep(delay)

        logger.error("Frame dropped after %d attempts: %s", len(RETRY_DELAYS) + 1, path.name)
        return False

    def check_server(self) -> bool:
        """Return True if the server is reachable and healthy."""
        health_url = self._url.replace("/api/frames", "/healthz")
        try:
            resp = self._client.get(health_url, timeout=5.0)
            return resp.status_code == 200
        except httpx.RequestError:
            return False

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> FrameSender:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
