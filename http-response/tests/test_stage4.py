"""Stage 4 — read the body correctly.

Contract (client.4.py):
    reader = ResponseReader(sock)            # sock: a connected socket
    resp = reader.read_response(method="GET")
reads exactly ONE response and leaves any bytes after it for the next call.
`resp` has:
    resp.status   int
    resp.headers  same lookup as stage 3 (.get / .get_all)
    resp.body     bytes, already de-chunked
`method` is the method of the request this response answers.
If the connection closes before the body is complete, raise an exception.

Every test here uses a socket that stays OPEN after the response
(keep-alive), unless the test says otherwise.
"""
import unittest

from tests.helpers import Pipe, bytewise, chunked, load_client, require, run_with_timeout


def resp(head, body=b""):
    return head.replace(b"\n", b"\r\n") + b"\r\n" + body


OK = resp(b"HTTP/1.1 200 OK\nContent-Length: 2\n", b"ok")


class Stage4(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = load_client(4, "client.4.py")

    def setUp(self):
        self.pipe = Pipe()
        self.addCleanup(self.pipe.close)
        self.reader = require(self.client, "ResponseReader")(self.pipe.client)

    def read(self, method="GET"):
        return run_with_timeout(self.reader.read_response, method=method)

    def send(self, *pieces, **kw):
        self.pipe.send(*pieces, **kw)

    # --- 1. Content-Length

    def test_content_length(self):
        self.send(resp(b"HTTP/1.1 200 OK\nContent-Length: 5\n", b"hello"))
        r = self.read()
        self.assertEqual((r.status, r.body), (200, b"hello"))

    def test_content_length_zero(self):
        self.send(resp(b"HTTP/1.1 200 OK\nContent-Length: 0\n"))
        self.assertEqual(self.read().body, b"")

    def test_headers_available(self):
        self.send(resp(b"HTTP/1.1 200 OK\nContent-Type: text/plain\nContent-Length: 0\n"))
        self.assertEqual(self.read().headers.get("content-type"), "text/plain")

    def test_large_body(self):
        body = bytes(range(256)) * 4096  # 1 MiB, not UTF-8
        self.send(resp(b"HTTP/1.1 200 OK\nContent-Length: %d\n" % len(body), body))
        self.assertEqual(self.read().body, body)

    def test_one_byte_at_a_time(self):
        self.send(*bytewise(resp(b"HTTP/1.1 200 OK\nContent-Length: 5\n", b"hello")), delay=0.001)
        self.assertEqual(self.read().body, b"hello")

    def test_blank_line_split_across_reads(self):
        data = resp(b"HTTP/1.1 200 OK\nContent-Length: 5\n", b"hello")
        cut = data.index(b"\r\n\r\n") + 2
        self.send(data[:cut], data[cut:], delay=0.05)
        self.assertEqual(self.read().body, b"hello")

    # --- 2. chunked

    def test_chunked(self):
        self.send(resp(b"HTTP/1.1 200 OK\nTransfer-Encoding: chunked\n", chunked(b"hello ", b"world")))
        self.assertEqual(self.read().body, b"hello world")

    def test_chunk_size_is_hex(self):
        part = b"x" * 26  # "1a"
        self.send(resp(b"HTTP/1.1 200 OK\nTransfer-Encoding: chunked\n", chunked(part, part)))
        self.assertEqual(self.read().body, part * 2)

    def test_chunk_size_uppercase_hex(self):
        self.send(resp(b"HTTP/1.1 200 OK\nTransfer-Encoding: chunked\n", b"1A\r\n" + b"y" * 26 + b"\r\n0\r\n\r\n"))
        self.assertEqual(self.read().body, b"y" * 26)

    def test_chunk_extensions_ignored(self):
        self.send(resp(b"HTTP/1.1 200 OK\nTransfer-Encoding: chunked\n", chunked(b"abc", ext=b";name=value")))
        self.assertEqual(self.read().body, b"abc")

    def test_chunk_data_containing_crlf_and_zero(self):
        tricky = b"line1\r\n0\r\n\r\nline2"
        self.send(resp(b"HTTP/1.1 200 OK\nTransfer-Encoding: chunked\n", chunked(tricky)))
        self.assertEqual(self.read().body, tricky)

    def test_chunked_binary(self):
        data = bytes(range(256))
        self.send(resp(b"HTTP/1.1 200 OK\nTransfer-Encoding: chunked\n", chunked(data, data)))
        self.assertEqual(self.read().body, data * 2)

    def test_chunked_one_byte_at_a_time(self):
        data = resp(b"HTTP/1.1 200 OK\nTransfer-Encoding: chunked\n", chunked(b"hello", b" there"))
        self.send(*bytewise(data), delay=0.001)
        self.assertEqual(self.read().body, b"hello there")

    def test_chunked_with_trailers(self):
        body = chunked(b"data", trailers=b"X-Checksum: 123\r\n")
        self.send(resp(b"HTTP/1.1 200 OK\nTransfer-Encoding: chunked\n", body), OK)
        self.assertEqual(self.read().body, b"data")
        self.assertEqual(self.read().body, b"ok", "trailers were not fully consumed")

    def test_chunked_empty_body(self):
        self.send(resp(b"HTTP/1.1 200 OK\nTransfer-Encoding: chunked\n", b"0\r\n\r\n"))
        self.assertEqual(self.read().body, b"")

    def test_transfer_encoding_beats_content_length(self):
        self.send(resp(b"HTTP/1.1 200 OK\nContent-Length: 3\nTransfer-Encoding: chunked\n", chunked(b"hello")), OK)
        self.assertEqual(self.read().body, b"hello")
        self.assertEqual(self.read().body, b"ok")

    # --- 3. read until close

    def test_no_length_reads_until_close(self):
        self.send(resp(b"HTTP/1.1 200 OK\nConnection: close\n", b"until "), b"the end", delay=0.05, close=True)
        self.assertEqual(self.read().body, b"until the end")

    def test_http_1_0_reads_until_close(self):
        self.send(resp(b"HTTP/1.0 200 OK\n", b"old school"), close=True)
        self.assertEqual(self.read().body, b"old school")

    # --- responses that never have a body

    def test_204_has_no_body(self):
        self.send(resp(b"HTTP/1.1 204 No Content\n"), OK)
        self.assertEqual(self.read().body, b"")
        self.assertEqual(self.read().body, b"ok")

    def test_304_ignores_content_length(self):
        self.send(resp(b"HTTP/1.1 304 Not Modified\nContent-Length: 50\n"), OK)
        self.assertEqual(self.read().body, b"")
        self.assertEqual(self.read().body, b"ok")

    def test_head_ignores_content_length(self):
        self.send(resp(b"HTTP/1.1 200 OK\nContent-Length: 1000\n"), OK)
        self.assertEqual(self.read(method="HEAD").body, b"")
        self.assertEqual(self.read().body, b"ok")

    def test_head_ignores_chunked(self):
        self.send(resp(b"HTTP/1.1 200 OK\nTransfer-Encoding: chunked\n"), OK)
        self.assertEqual(self.read(method="HEAD").body, b"")
        self.assertEqual(self.read().body, b"ok")

    # --- two responses on one connection

    def test_two_responses_sent_one_after_another(self):
        self.send(resp(b"HTTP/1.1 200 OK\nContent-Length: 5\n", b"first"))
        self.assertEqual(self.read().body, b"first")
        self.send(resp(b"HTTP/1.1 404 Not Found\nContent-Length: 6\n", b"second"))
        r = self.read()
        self.assertEqual((r.status, r.body), (404, b"second"))

    def test_two_responses_in_one_packet(self):
        one = resp(b"HTTP/1.1 200 OK\nContent-Length: 5\n", b"first")
        two = resp(b"HTTP/1.1 201 Created\nContent-Length: 6\n", b"second")
        self.send(one + two)
        self.assertEqual(self.read().body, b"first")
        r = self.read()
        self.assertEqual((r.status, r.body), (201, b"second"))

    def test_mixed_framings_back_to_back(self):
        self.send(
            resp(b"HTTP/1.1 200 OK\nTransfer-Encoding: chunked\n", chunked(b"a", b"b")),
            resp(b"HTTP/1.1 204 No Content\n"),
            resp(b"HTTP/1.1 200 OK\nContent-Length: 1\n", b"c"),
        )
        self.assertEqual([self.read().body for _ in range(3)], [b"ab", b"", b"c"])

    # --- broken servers

    def test_close_before_body_complete_raises(self):
        self.send(resp(b"HTTP/1.1 200 OK\nContent-Length: 100\n", b"short"), close=True)
        with self.assertRaises(Exception):
            self.read()

    def test_close_mid_chunked_raises(self):
        self.send(resp(b"HTTP/1.1 200 OK\nTransfer-Encoding: chunked\n", b"5\r\nhel"), close=True)
        with self.assertRaises(Exception):
            self.read()

    def test_close_before_headers_complete_raises(self):
        self.send(b"HTTP/1.1 200 OK\r\nContent-Le", close=True)
        with self.assertRaises(Exception):
            self.read()


if __name__ == "__main__":
    unittest.main()
