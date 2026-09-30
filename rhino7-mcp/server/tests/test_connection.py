import json
import socket
import threading
import time

import pytest

from rhino_mcp.connection import RhinoConnection, RhinoError


class FakeListener:
    """Tiny newline-JSON server. handler(req) -> response dict, or None to drop the connection."""

    def __init__(self, handler, split=False):
        self.handler = handler
        self.split = split
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.port = self.sock.getsockname()[1]
        self.connections = 0
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while self.running:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            self.connections += 1
            threading.Thread(target=self._client, args=(conn,), daemon=True).start()

    def _client(self, conn):
        buf = b""
        with conn:
            while True:
                try:
                    data = conn.recv(4096)
                except OSError:
                    return
                if not data:
                    return
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    resp = self.handler(json.loads(line))
                    if resp is None:
                        return  # drop connection without answering
                    out = (json.dumps(resp) + "\n").encode()
                    if self.split:
                        for i in range(0, len(out), 5):
                            conn.sendall(out[i:i + 5])
                            time.sleep(0.002)
                    else:
                        conn.sendall(out)

    def stop(self):
        self.running = False
        self.sock.close()


def echo(req):
    if req["command"] == "boom":
        return {"id": req["id"], "status": "error", "message": "it broke"}
    return {"id": req["id"], "status": "ok", "result": {"cmd": req["command"], "params": req["params"]}}


@pytest.fixture
def listener():
    l = FakeListener(echo)
    yield l
    l.stop()


def test_request_response(listener):
    c = RhinoConnection("127.0.0.1", listener.port, timeout=5)
    assert c.send("ping") == {"cmd": "ping", "params": {}}
    assert c.send("x", {"a": [1, 2], "u": "ñ"}) == {"cmd": "x", "params": {"a": [1, 2], "u": "ñ"}}
    assert listener.connections == 1  # connection reused
    c.close()


def test_split_responses():
    l = FakeListener(echo, split=True)
    try:
        c = RhinoConnection("127.0.0.1", l.port, timeout=5)
        assert c.send("ping")["cmd"] == "ping"
        assert c.send("again", {"k": "v" * 200})["params"]["k"] == "v" * 200
    finally:
        l.stop()


def test_error_propagation(listener):
    c = RhinoConnection("127.0.0.1", listener.port, timeout=5)
    with pytest.raises(RhinoError, match="it broke"):
        c.send("boom")
    assert c.send("ping")["cmd"] == "ping"  # still usable


def test_connection_refused_message():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    c = RhinoConnection("127.0.0.1", port, timeout=2)
    with pytest.raises(RhinoError, match="listener"):
        c.send("ping")


def test_reconnect_after_drop():
    state = {"drop": True}

    def handler(req):
        if state["drop"] and req["command"] == "flaky":
            state["drop"] = False
            return None
        return echo(req)

    l = FakeListener(handler)
    try:
        c = RhinoConnection("127.0.0.1", l.port, timeout=5)
        assert c.send("ping")["cmd"] == "ping"
        assert c.send("flaky")["cmd"] == "flaky"  # dropped once, retried transparently
        assert l.connections == 2
    finally:
        l.stop()


def test_reconnect_after_server_restart(listener):
    c = RhinoConnection("127.0.0.1", listener.port, timeout=5)
    c.send("ping")
    c._sock.close()  # simulate a broken socket on our side
    assert c.send("ping")["cmd"] == "ping"
    assert listener.connections == 2


def test_timeout():
    l = FakeListener(lambda req: (time.sleep(1.0), echo(req))[1])
    try:
        c = RhinoConnection("127.0.0.1", l.port, timeout=0.2)
        with pytest.raises(RhinoError, match="Timed out"):
            c.send("slow")
    finally:
        l.stop()


def test_env_defaults(monkeypatch):
    monkeypatch.setenv("RHINO_MCP_HOST", "127.0.0.2")
    monkeypatch.setenv("RHINO_MCP_PORT", "4242")
    monkeypatch.setenv("RHINO_MCP_TIMEOUT", "7")
    c = RhinoConnection()
    assert (c.host, c.port, c.timeout) == ("127.0.0.2", 4242, 7.0)
