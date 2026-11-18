"""Stage 7 — build the server.

Contract (server.py):  python3 server.py <port>
Listens on 127.0.0.1:<port>. Edit PATHS below if your routes are named differently.
These tests check your server with raw sockets, with curl, and with your
stage 4 ResponseReader if client.4.py has one.
"""
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest

from tests.helpers import ROOT, free_port, have_curl, load_client

PATHS = {
    "ok": "/",                      # 200 with Content-Length
    "chunked": "/chunked",          # 200 with Transfer-Encoding: chunked
    "no_content": "/empty",         # 204
    "moved": "/moved",              # 301 + Location
    "found": "/found",              # 302 + Location
    "crash": "/crash",              # handler raises -> 500
    "missing": "/does-not-exist",   # 404
}
EXPECTED = {"ok": 200, "chunked": 200, "no_content": 204, "moved": 301,
            "found": 302, "crash": 500, "missing": 404}


def request(path, method="GET"):
    return f"{method} {path} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n".encode()


def split(raw):
    head, sep, body = raw.partition(b"\r\n\r\n")
    assert sep, f"no blank line ending the headers in {raw[:200]!r}"
    lines = head.decode("latin-1").split("\r\n")
    headers = {}
    for line in lines[1:]:
        name, _, value = line.partition(":")
        headers.setdefault(name.strip().lower(), value.strip())
    return lines[0], headers, body


def status_of(status_line):
    return int(status_line.split(" ")[1])


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = ROOT / os.environ.get("SERVER_FILE", "server.py")
        if not path.exists():
            raise unittest.SkipTest(f"{path.name} not found yet")
        cls.port = free_port()
        cls.log = tempfile.TemporaryFile()
        cls.proc = subprocess.Popen([sys.executable, str(path), str(cls.port)],
                                    stdout=cls.log, stderr=cls.log, cwd=ROOT)
        deadline = time.time() + 5
        while time.time() < deadline:
            if cls.proc.poll() is not None:
                break
            try:
                socket.create_connection(("127.0.0.1", cls.port), timeout=0.2).close()
                return
            except OSError:
                time.sleep(0.1)
        cls.tearDownClass()
        raise RuntimeError(f"`python3 {path.name} {cls.port}` never started listening:\n{cls.output()}")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(5)
        cls.log.close()

    @classmethod
    def output(cls):
        cls.log.seek(0)
        return cls.log.read().decode(errors="replace")

    def exchange(self, data):
        """Send raw bytes, return everything until the server closes."""
        with socket.create_connection(("127.0.0.1", self.port), timeout=3) as s:
            s.sendall(data)
            chunks = []
            while True:
                try:
                    chunk = s.recv(65536)
                except socket.timeout:
                    self.fail("server didn't close the connection after `Connection: close` "
                              f"(got {b''.join(chunks)[:200]!r})")
                if not chunk:
                    return b"".join(chunks)
                chunks.append(chunk)

    def fetch(self, name):
        return split(self.exchange(request(PATHS[name])))


class RawSocket(ServerTest):
    def test_status_codes(self):
        for name, code in EXPECTED.items():
            with self.subTest(path=PATHS[name]):
                status_line, _, _ = self.fetch(name)
                self.assertRegex(status_line, r"^HTTP/1\.1 \d{3} ")
                self.assertEqual(status_of(status_line), code)

    def test_content_length_matches_body(self):
        _, headers, body = self.fetch("ok")
        self.assertIn("content-length", headers)
        self.assertEqual(int(headers["content-length"]), len(body))
        self.assertGreater(len(body), 0)

    def test_chunked_framing(self):
        _, headers, body = self.fetch("chunked")
        self.assertEqual(headers.get("transfer-encoding", "").lower(), "chunked")
        self.assertNotIn("content-length", headers)
        self.assertTrue(body.endswith(b"\r\n\r\n"), body[-20:])
        self.assertIn(b"0\r\n", body)

    def test_204_has_no_body_and_no_content_length(self):
        _, headers, body = self.fetch("no_content")
        self.assertEqual(body, b"")
        self.assertNotIn("content-length", headers)

    def test_redirects_have_location(self):
        for name in ("moved", "found"):
            with self.subTest(path=PATHS[name]):
                _, headers, _ = self.fetch(name)
                self.assertTrue(headers.get("location"))

    def test_error_responses_are_framed(self):
        for name in ("missing", "crash"):
            with self.subTest(path=PATHS[name]):
                _, headers, body = self.fetch(name)
                if "content-length" in headers:
                    self.assertEqual(int(headers["content-length"]), len(body))

    def test_malformed_request_line_gets_400(self):
        for bad in [b"NONSENSE\r\n\r\n", b"GET /\r\n\r\n", b"GET / HTTP/1.1 extra\r\nHost: x\r\n\r\n"]:
            with self.subTest(request=bad):
                status_line, _, _ = split(self.exchange(bad))
                self.assertEqual(status_of(status_line), 400)

    def test_still_serving_after_500(self):
        self.fetch("crash")
        status_line, _, _ = self.fetch("ok")
        self.assertEqual(status_of(status_line), 200)

    def test_still_serving_after_client_disconnects_early(self):
        socket.create_connection(("127.0.0.1", self.port), timeout=3).close()
        with socket.create_connection(("127.0.0.1", self.port), timeout=3) as s:
            s.sendall(b"GET / HTTP/1.1\r\nHo")
        status_line, _, _ = self.fetch("ok")
        self.assertEqual(status_of(status_line), 200)


@unittest.skipUnless(have_curl(), "curl not installed")
class Curl(ServerTest):
    def test_curl_reads_every_endpoint_cleanly(self):
        for name, path in PATHS.items():
            with self.subTest(path=path):
                p = subprocess.run(
                    ["curl", "-sS", "--max-time", "5", "-o", "/dev/null", "-w", "%{http_code}",
                     f"http://127.0.0.1:{self.port}{path}"],
                    capture_output=True, text=True)
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual(p.stderr, "")
                self.assertEqual(int(p.stdout), EXPECTED[name])

    def test_curl_verbose_has_no_warnings(self):
        for name, path in PATHS.items():
            with self.subTest(path=path):
                p = subprocess.run(["curl", "-v", "--max-time", "5", "-o", "/dev/null",
                                    f"http://127.0.0.1:{self.port}{path}"],
                                   capture_output=True, text=True)
                for word in ("Excess", "Leftovers", "transfer closed", "Illegal", "Weird"):
                    self.assertNotIn(word, p.stderr)


class YourStage4Client(ServerTest):
    @classmethod
    def setUpClass(cls):
        try:
            cls.reader_class = load_client(4, "client.4.py").ResponseReader
        except (unittest.SkipTest, RuntimeError, AttributeError) as e:
            raise unittest.SkipTest(f"no usable ResponseReader in client.4.py ({e})")
        super().setUpClass()

    def test_reader_handles_every_endpoint(self):
        for name, path in PATHS.items():
            with self.subTest(path=path), socket.create_connection(("127.0.0.1", self.port), timeout=3) as s:
                s.sendall(request(path))
                self.assertEqual(self.reader_class(s).read_response().status, EXPECTED[name])


if __name__ == "__main__":
    unittest.main()
