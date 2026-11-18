"""Stage 3 — parse the headers.

Contract (client.3.py):  parse_headers(data: bytes) -> (headers, body_start) | None
`data` is the response from its first byte (status line included).
Return None if `data` doesn't contain the whole header section yet.
`body_start` is the index in `data` where the body begins.
`headers` must support:
    headers.get(name)      -> str value, or None. Name lookup ignores case.
    headers.get_all(name)  -> list of every value for that name, in order ([] if none).
"""
import unittest

from tests.helpers import load_client, require


class Stage3(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = load_client(3, "client.3.py")

    def parse(self, data):
        return require(self.client, "parse_headers")(data)

    def headers(self, *lines, body=b""):
        data = b"HTTP/1.1 200 OK\r\n" + b"".join(l + b"\r\n" for l in lines) + b"\r\n" + body
        result = self.parse(data)
        self.assertIsNotNone(result, "returned None for a complete header section")
        return result[0]

    # --- lookup

    def test_lookup_ignores_case(self):
        h = self.headers(b"Content-Type: text/html")
        self.assertEqual(h.get("content-type"), "text/html")
        self.assertEqual(h.get("Content-Type"), "text/html")
        self.assertEqual(h.get("CONTENT-TYPE"), "text/html")

    def test_missing_header_is_none(self):
        self.assertIsNone(self.headers(b"A: 1").get("b"))

    def test_value_case_preserved(self):
        self.assertEqual(self.headers(b"X-Token: AbC").get("x-token"), "AbC")

    # --- whitespace and colons

    def test_no_space_after_colon(self):
        self.assertEqual(self.headers(b"Content-Length:42").get("content-length"), "42")

    def test_surrounding_whitespace_stripped(self):
        self.assertEqual(self.headers(b"X-A:   spaced   ").get("x-a"), "spaced")
        self.assertEqual(self.headers(b"X-B:\ttabbed\t").get("x-b"), "tabbed")

    def test_inner_whitespace_kept(self):
        self.assertEqual(self.headers(b"Server: Apache 2 (Unix)").get("server"), "Apache 2 (Unix)")

    def test_value_containing_colons(self):
        h = self.headers(b"Location: http://example.com:8080/a:b")
        self.assertEqual(h.get("location"), "http://example.com:8080/a:b")

    def test_empty_value(self):
        self.assertEqual(self.headers(b"X-Empty:").get("x-empty"), "")

    def test_non_ascii_value_does_not_crash(self):
        self.assertIsNotNone(self.headers(b"X-Name: caf\xe9").get("x-name"))

    # --- duplicates

    def test_repeated_header_keeps_every_value_in_order(self):
        h = self.headers(b"Set-Cookie: a=1", b"Content-Type: text/plain", b"set-cookie: b=2")
        self.assertEqual(h.get_all("Set-Cookie"), ["a=1", "b=2"])

    def test_get_all_missing_is_empty_list(self):
        self.assertEqual(self.headers(b"A: 1").get_all("b"), [])

    def test_get_all_single(self):
        self.assertEqual(self.headers(b"A: 1").get_all("a"), ["1"])

    # --- where the body starts

    def test_body_start_offset(self):
        data = b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nhello"
        _, start = self.parse(data)
        self.assertEqual(start, len(data) - 5)
        self.assertEqual(data[start:], b"hello")

    def test_no_body_bytes_yet(self):
        data = b"HTTP/1.1 200 OK\r\nA: 1\r\n\r\n"
        _, start = self.parse(data)
        self.assertEqual(start, len(data))

    def test_no_headers_at_all(self):
        data = b"HTTP/1.1 204 No Content\r\n\r\n"
        h, start = self.parse(data)
        self.assertEqual(start, len(data))
        self.assertIsNone(h.get("content-length"))

    def test_body_that_looks_like_headers_is_ignored(self):
        body = b"Fake: header\r\n\r\nmore\r\n\r\n"
        data = b"HTTP/1.1 200 OK\r\nReal: yes\r\n\r\n" + body
        h, start = self.parse(data)
        self.assertEqual(data[start:], body)
        self.assertIsNone(h.get("fake"))
        self.assertEqual(h.get("real"), "yes")

    def test_binary_body_does_not_break_parsing(self):
        body = bytes(range(256))
        data = b"HTTP/1.1 200 OK\r\nA: 1\r\n\r\n" + body
        _, start = self.parse(data)
        self.assertEqual(data[start:], body)

    # --- incomplete input

    def test_incomplete_header_section_returns_none(self):
        for data in [b"", b"HTTP/1.1 200 OK", b"HTTP/1.1 200 OK\r\nA: 1\r\n", b"HTTP/1.1 200 OK\r\nA: 1\r\n\r"]:
            with self.subTest(data=data):
                self.assertIsNone(self.parse(data))


if __name__ == "__main__":
    unittest.main()
