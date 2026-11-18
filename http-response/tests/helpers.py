"""Shared test plumbing: loading your client files, fake servers, timeouts.

Nothing in here solves a stage for you. The fake servers only *write* bytes;
all the response parsing is left to your code.
"""
import importlib.util
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REASONS = {
    200: "OK", 204: "No Content", 300: "Multiple Choices", 301: "Moved Permanently",
    302: "Found", 303: "See Other", 304: "Not Modified", 307: "Temporary Redirect",
    308: "Permanent Redirect", 400: "Bad Request", 404: "Not Found", 418: "I'm a teapot",
    500: "Internal Server Error", 503: "Service Unavailable",
}


# ---------------------------------------------------------------- loading

def load_client(stage, default_file):
    """Import one of your client files (e.g. client.3.py) as a module.

    Set STAGE<n>_FILE to point a stage's tests at another file, e.g.
    STAGE5_FILE=client.6.py to check that stage 6 didn't break stage 5.
    """
    filename = os.environ.get(f"STAGE{stage}_FILE", default_file)
    path = ROOT / filename
    if not path.exists():
        raise unittest.SkipTest(f"{filename} not found yet (or set STAGE{stage}_FILE)")
    spec = importlib.util.spec_from_file_location(f"stage{stage}_client", path)
    module = importlib.util.module_from_spec(spec)
    saved_argv = sys.argv
    sys.argv = [str(path)]
    try:
        spec.loader.exec_module(module)
    except (Exception, SystemExit) as e:
        raise RuntimeError(
            f"importing {filename} failed with {e!r}. If the file sends a request at the "
            f'bottom, wrap that in `if __name__ == "__main__":` so the tests can import it.'
        ) from e
    finally:
        sys.argv = saved_argv
    return module


def require(module, name):
    try:
        return getattr(module, name)
    except AttributeError:
        raise AssertionError(
            f"{Path(module.__file__).name} must define `{name}` (see tests/README.md)"
        ) from None


def run_with_timeout(fn, *args, timeout=5, **kwargs):
    """Call fn, but fail the test instead of hanging forever."""
    result = {}

    def target():
        try:
            result["value"] = fn(*args, **kwargs)
        except BaseException as e:
            result["error"] = e

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise AssertionError(
            f"{getattr(fn, '__name__', fn)} did not return within {timeout}s. "
            "It is probably waiting for bytes, or for a close, that will never come."
        )
    if "error" in result:
        raise result["error"]
    return result["value"]


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------- building responses

def http_response(status, reason=None, headers=(), body=b"", close=True):
    """A complete response framed with Content-Length."""
    lines = [f"HTTP/1.1 {status} {REASONS.get(status, 'Status') if reason is None else reason}"]
    lines += [f"{k}: {v}" for k, v in headers]
    lines.append(f"Content-Length: {len(body)}")
    if close:
        lines.append("Connection: close")
    return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + body


def redirect(status, location):
    return http_response(status, headers=[("Location", location)])


def chunked(*parts, ext=b"", trailers=b""):
    """Encode parts as a chunked body. `trailers` is raw b"Name: value\\r\\n" lines."""
    out = b""
    for p in parts:
        out += f"{len(p):x}".encode() + ext + b"\r\n" + p + b"\r\n"
    return out + b"0\r\n" + trailers + b"\r\n"


# ---------------------------------------------------------------- fake server (stages 1, 5)

class Request:
    """A request as the fake server received it."""

    def __init__(self, head, body):
        self.head = head  # request line + headers + blank line, as raw bytes
        self.body = body
        lines = head.decode("latin-1").split("\r\n")
        self.request_line = lines[0]
        parts = lines[0].split(" ")
        self.method, self.target, self.version = (parts + ["", "", ""])[:3]
        self.path = self.target.split("?")[0]
        self.headers = []
        for line in lines[1:]:
            if line:
                name, _, value = line.partition(":")
                self.headers.append((name.strip().lower(), value.strip()))

    def header(self, name):
        for k, v in self.headers:
            if k == name.lower():
                return v
        return None


def read_request(conn):
    buf = b""
    while b"\r\n\r\n" not in buf:
        data = conn.recv(4096)
        if not data:
            return None
        buf += data
    head, _, rest = buf.partition(b"\r\n\r\n")
    req = Request(head + b"\r\n\r\n", b"")
    length = int(req.header("content-length") or 0)
    while len(rest) < length:
        data = conn.recv(4096)
        if not data:
            break
        rest += data
    req.body = rest[:length]
    return req


class RawServer:
    """Accepts connections on 127.0.0.1, reads one request each, and calls
    handler(conn, request, server). The connection is closed when handler returns."""

    def __init__(self, handler):
        self.handler = handler
        self.requests = []
        self.stopped = threading.Event()
        self.sock = socket.create_server(("127.0.0.1", 0))
        self.sock.settimeout(0.2)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while not self.stopped.is_set():
            try:
                conn, _ = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        with conn:
            conn.settimeout(5)
            try:
                req = read_request(conn)
                if req is None:
                    return
                self.requests.append(req)
                self.handler(conn, req, self)
            except OSError:
                pass

    def close(self):
        self.stopped.set()
        self.sock.close()


def routes_handler(routes):
    """routes: {path: response_bytes | callable(request) -> response_bytes}"""
    def handler(conn, req, server):
        route = routes.get(req.path)
        resp = route(req) if callable(route) else route
        conn.sendall(resp if resp is not None else http_response(404, body=b"no route"))
    return handler


# ---------------------------------------------------------------- socket pair (stage 4)

class Pipe:
    """A connected socket pair. The test writes response bytes into `server`;
    your ResponseReader reads them from `client`."""

    def __init__(self, timeout=3):
        self.client, self.server = socket.socketpair()
        self.client.settimeout(timeout)

    def send(self, *pieces, delay=0.0, close=False):
        """Write pieces in a background thread (so big writes can't deadlock)."""
        def run():
            try:
                for p in pieces:
                    self.server.sendall(p)
                    if delay:
                        time.sleep(delay)
                if close:
                    self.server.shutdown(socket.SHUT_WR)
            except OSError:
                pass

        t = threading.Thread(target=run, daemon=True)
        t.start()
        return t

    def close(self):
        self.client.close()
        self.server.close()


def bytewise(data):
    return [data[i:i + 1] for i in range(len(data))]


# ---------------------------------------------------------------- stage 7

def have_curl():
    return shutil.which("curl") is not None
