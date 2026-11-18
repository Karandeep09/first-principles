"""Stage 1 — send a request over a socket.

Contract (client.1.py):  fetch_raw(host, path, port=80) -> bytes
Returns every byte the server sent, unchanged.
"""
import time
import unittest

from tests.helpers import RawServer, free_port, load_client, require, run_with_timeout

RESPONSE = b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 5\r\n\r\nhello"


def respond(response, pieces=1, delay=0.0):
    """Send `response` in `pieces` separate writes. Like a real HTTP/1.1 server,
    only close straight away if the client asked for that."""
    def handler(conn, req, server):
        size = max(1, -(-len(response) // pieces))
        for i in range(0, len(response), size):
            conn.sendall(response[i:i + size])
            if delay:
                time.sleep(delay)
        if (req.header("connection") or "").lower() != "close":
            server.stopped.wait(30)
    return handler


class Stage1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = load_client(1, "client.1.py")

    def serve(self, response=RESPONSE, **kw):
        server = RawServer(respond(response, **kw))
        self.addCleanup(server.close)
        return server

    def fetch(self, server, path="/"):
        fetch_raw = require(self.client, "fetch_raw")
        return run_with_timeout(fetch_raw, "127.0.0.1", path, port=server.port)

    # --- what comes back

    def test_returns_exact_bytes(self):
        self.assertEqual(self.fetch(self.serve()), RESPONSE)

    def test_returns_bytes_not_str(self):
        self.assertIsInstance(self.fetch(self.serve()), bytes)

    def test_does_not_hang_when_server_keeps_connection_open(self):
        # Fails if the client waits for a close that HTTP/1.1 never promised.
        self.assertEqual(self.fetch(self.serve()), RESPONSE)

    def test_response_split_across_many_writes(self):
        body = b"x" * 200_000
        response = b"HTTP/1.1 200 OK\r\nContent-Length: 200000\r\n\r\n" + body
        self.assertEqual(self.fetch(self.serve(response, pieces=50, delay=0.005)), response)

    def test_binary_body_unchanged(self):
        body = bytes(range(256)) * 4  # not valid UTF-8
        response = b"HTTP/1.1 200 OK\r\nContent-Length: 1024\r\n\r\n" + body
        self.assertEqual(self.fetch(self.serve(response)), response)

    def test_empty_body(self):
        response = b"HTTP/1.1 204 No Content\r\n\r\n"
        self.assertEqual(self.fetch(self.serve(response)), response)

    # --- what was sent

    def test_request_line(self):
        server = self.serve()
        self.fetch(server, "/some/path?x=1")
        self.assertEqual(server.requests[0].request_line, "GET /some/path?x=1 HTTP/1.1")

    def test_host_header(self):
        server = self.serve()
        self.fetch(server)
        # Strictly, a non-default port belongs in Host too ("127.0.0.1:8080").
        self.assertIn(server.requests[0].header("host"), ("127.0.0.1", f"127.0.0.1:{server.port}"))

    def test_lines_end_with_crlf(self):
        server = self.serve()
        self.fetch(server)
        head = server.requests[0].head
        self.assertTrue(head.endswith(b"\r\n\r\n"), head)
        self.assertNotIn(b"\n", head.replace(b"\r\n", b""), "found a bare \\n line ending")

    def test_one_request_per_call(self):
        server = self.serve()
        self.fetch(server)
        self.assertEqual(len(server.requests), 1)

    # --- failure

    def test_nothing_listening_raises(self):
        fetch_raw = require(self.client, "fetch_raw")
        with self.assertRaises(OSError):
            run_with_timeout(fetch_raw, "127.0.0.1", "/", port=free_port())


if __name__ == "__main__":
    unittest.main()
