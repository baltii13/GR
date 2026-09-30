"""TCP client for the Rhino listener (newline-delimited JSON)."""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import uuid
from typing import Any

log = logging.getLogger("rhino_mcp")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 1999
DEFAULT_TIMEOUT = 60.0


class RhinoError(Exception):
    """Error reported by the Rhino listener, or a connection problem."""


class RhinoConnection:
    """Lazy, thread-safe connection to the Rhino listener.

    Host, port and timeout default to the RHINO_MCP_HOST, RHINO_MCP_PORT and
    RHINO_MCP_TIMEOUT environment variables (127.0.0.1, 1999, 60 s).
    """

    def __init__(self, host: str | None = None, port: int | None = None,
                 timeout: float | None = None) -> None:
        self.host = host or os.environ.get("RHINO_MCP_HOST", DEFAULT_HOST)
        self.port = int(port if port is not None else os.environ.get("RHINO_MCP_PORT", DEFAULT_PORT))
        self.timeout = float(timeout if timeout is not None
                             else os.environ.get("RHINO_MCP_TIMEOUT", DEFAULT_TIMEOUT))
        self._sock: socket.socket | None = None
        self._buf = b""
        self._lock = threading.Lock()

    # -- socket management -------------------------------------------------
    def _connect(self) -> None:
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except ConnectionRefusedError as exc:
            raise RhinoError(
                f"Could not connect to Rhino at {self.host}:{self.port}. "
                "Open Rhino 7 and run the listener script "
                "(rhino_plugin/rhino_mcp_listener.py) with _RunPythonScript, then retry."
            ) from exc
        except (OSError, socket.timeout) as exc:
            raise RhinoError(f"Could not connect to Rhino at {self.host}:{self.port}: {exc}") from exc
        sock.settimeout(self.timeout)
        self._sock = sock
        self._buf = b""

    def close(self) -> None:
        with self._lock:
            self._close()

    def _close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock = None
        self._buf = b""

    # -- protocol ------------------------------------------------------------
    def _read_line(self) -> bytes:
        assert self._sock is not None
        while b"\n" not in self._buf:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise ConnectionError("Rhino closed the connection")
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        return line

    def _roundtrip(self, payload: bytes, rid: str) -> dict[str, Any]:
        if self._sock is None:
            self._connect()
        assert self._sock is not None
        self._sock.sendall(payload)
        while True:
            line = self._read_line()
            if not line.strip():
                continue
            try:
                resp = json.loads(line.decode("utf-8"))
            except ValueError as exc:
                raise RhinoError(f"Invalid response from Rhino listener: {exc}") from exc
            # Ignore stale responses from an earlier timed-out request.
            if resp.get("id") in (rid, None):
                return resp

    def send(self, command: str, params: dict[str, Any] | None = None) -> Any:
        """Send a command and return its result; raise RhinoError on failure."""
        rid = uuid.uuid4().hex
        payload = (json.dumps({"id": rid, "command": command, "params": params or {}}) + "\n").encode("utf-8")
        with self._lock:
            try:
                resp = self._roundtrip(payload, rid)
            except RhinoError:
                self._close()
                raise
            except socket.timeout as exc:
                self._close()
                raise RhinoError(
                    f"Timed out after {self.timeout:g}s waiting for Rhino to answer '{command}'. "
                    "Rhino may be busy or showing a dialog."
                ) from exc
            except (ConnectionError, OSError) as first:
                # Broken socket: reconnect once and retry.
                log.info("Connection to Rhino lost (%s); reconnecting", first)
                self._close()
                try:
                    resp = self._roundtrip(payload, rid)
                except RhinoError:
                    self._close()
                    raise
                except socket.timeout as exc:
                    self._close()
                    raise RhinoError(f"Timed out waiting for Rhino to answer '{command}'.") from exc
                except (ConnectionError, OSError) as exc:
                    self._close()
                    raise RhinoError(f"Lost connection to Rhino: {exc}") from exc
        if resp.get("status") == "ok":
            return resp.get("result")
        raise RhinoError(str(resp.get("message", "Unknown error from Rhino")))
