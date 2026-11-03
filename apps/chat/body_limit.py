"""
ASGI guard for the relay endpoint's request body.

Django's ASGI handler reads the WHOLE request body (spooling to a temp file
past a threshold) before any view runs, so a size check inside the relay view
comes too late: an unauthenticated client could still make us read and store
an arbitrarily large upload (Codex review, 2026-10-09).

This wrapper sits in front of Django for exactly one path. It refuses a
declared Content-Length over the limit without reading anything, counts
bytes as they stream in and stops at the limit, and gives up on uploads that
take too long. Within the limits it hands Django the body it already read.
Every other path passes straight through untouched.
"""

import asyncio
import json

RELAY_PATH = "/internal/chat/events"


class RelayBodyLimit:
    def __init__(self, app, *, path=RELAY_PATH, max_bytes=16 * 1024, timeout=10.0):
        self.app = app
        self.path = path
        self.max_bytes = max_bytes
        self.timeout = timeout

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("path") != self.path:
            await self.app(scope, receive, send)
            return

        for name, value in scope.get("headers", []):
            if name == b"content-length":
                if (
                    not value.isdigit()
                    or len(value) > 12
                    or int(value) > self.max_bytes
                ):
                    await _reject(send, 413)
                    return

        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.timeout
        body = bytearray()
        more = True
        while more:
            remaining = deadline - loop.time()
            if remaining <= 0:
                await _reject(send, 408)
                return
            try:
                message = await asyncio.wait_for(receive(), remaining)
            except TimeoutError:
                await _reject(send, 408)
                return
            if message["type"] == "http.disconnect":
                return
            body += message.get("body", b"")
            if len(body) > self.max_bytes:
                await _reject(send, 413)
                return
            more = message.get("more_body", False)

        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


async def _reject(send, status):
    payload = json.dumps({"error": "rejected"}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(payload)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": payload})
