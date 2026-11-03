import asyncio

import pytest

from apps.chat.body_limit import RELAY_PATH, RelayBodyLimit

pytestmark = pytest.mark.asyncio


class Recorder:
    """A stand-in for Django: records what it was called with."""

    def __init__(self):
        self.called = False
        self.body = None

    async def __call__(self, scope, receive, send):
        self.called = True
        message = await receive()
        self.body = message["body"]
        await send({"type": "http.response.start", "status": 202, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


def scope(path=RELAY_PATH, headers=()):
    return {"type": "http", "path": path, "headers": list(headers)}


def feeder(chunks, delay=0.0):
    queue = list(chunks)

    async def receive():
        if delay:
            await asyncio.sleep(delay)
        if not queue:
            return {"type": "http.disconnect"}
        chunk, more = queue.pop(0)
        return {"type": "http.request", "body": chunk, "more_body": more}

    return receive


def collector():
    sent = []

    async def send(message):
        sent.append(message)

    return sent, send


def status_of(sent):
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


async def test_declared_oversize_is_refused_without_reading():
    app = Recorder()
    sent, send = collector()
    read = []

    async def receive():
        read.append(1)
        return {"type": "http.request", "body": b"x", "more_body": False}

    await RelayBodyLimit(app, max_bytes=100)(
        scope(headers=[(b"content-length", b"5000")]), receive, send
    )
    assert status_of(sent) == 413
    assert not app.called and not read


async def test_streamed_oversize_stops_at_the_limit():
    app = Recorder()
    sent, send = collector()
    chunks = [(b"x" * 60, True), (b"x" * 60, True), (b"x" * 60, False)]
    await RelayBodyLimit(app, max_bytes=100)(scope(), feeder(chunks), send)
    assert status_of(sent) == 413
    assert not app.called


async def test_slow_upload_times_out():
    app = Recorder()
    sent, send = collector()
    await RelayBodyLimit(app, max_bytes=100, timeout=0.05)(
        scope(), feeder([(b"x", True), (b"x", False)], delay=0.2), send
    )
    assert status_of(sent) == 408
    assert not app.called


@pytest.mark.parametrize("value", [b"abc", b"\xc2\xb2", b"9" * 40])
async def test_malformed_content_length_is_refused(value):
    app = Recorder()
    sent, send = collector()
    await RelayBodyLimit(app)(
        scope(headers=[(b"content-length", value)]), feeder([]), send
    )
    assert status_of(sent) == 413


async def test_small_body_is_replayed_to_the_app():
    app = Recorder()
    sent, send = collector()
    await RelayBodyLimit(app, max_bytes=100)(
        scope(), feeder([(b'{"a":', True), (b"1}", False)]), send
    )
    assert app.called
    assert app.body == b'{"a":1}'
    assert status_of(sent) == 202


async def test_other_paths_pass_straight_through():
    app = Recorder()
    sent, send = collector()
    await RelayBodyLimit(app, max_bytes=1)(
        scope(path="/api/share-links/x"), feeder([(b"x" * 50, False)]), send
    )
    assert app.called and app.body == b"x" * 50
