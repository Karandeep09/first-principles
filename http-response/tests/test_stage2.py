"""Stage 2 — parse the status line.

Contract (client.2.py):  parse_status_line(line: str) -> (version, code, reason)
`line` has no trailing CRLF. Return anything that unpacks to three values,
e.g. a tuple or NamedTuple: version str, code int, reason str.
Raise ValueError for a line that isn't a valid status line.
"""
import unittest

from tests.helpers import load_client, require


class Stage2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = load_client(2, "client.2.py")

    def parse(self, line):
        return tuple(require(self.client, "parse_status_line")(line))

    # --- valid lines

    def test_simple(self):
        self.assertEqual(self.parse("HTTP/1.1 200 OK"), ("HTTP/1.1", 200, "OK"))

    def test_code_is_int(self):
        self.assertIsInstance(self.parse("HTTP/1.1 200 OK")[1], int)

    def test_reason_with_spaces(self):
        self.assertEqual(self.parse("HTTP/1.1 404 Not Found"), ("HTTP/1.1", 404, "Not Found"))
        self.assertEqual(self.parse("HTTP/1.1 500 Internal Server Error")[2], "Internal Server Error")

    def test_reason_whitespace_kept_exactly(self):
        self.assertEqual(self.parse("HTTP/1.1 299 Odd  but  legal")[2], "Odd  but  legal")

    def test_empty_reason(self):
        self.assertEqual(self.parse("HTTP/1.1 204 "), ("HTTP/1.1", 204, ""))

    def test_reason_is_not_trusted(self):
        # The code is what matters; the reason text can say anything.
        self.assertEqual(self.parse("HTTP/1.1 200 Not Found"), ("HTTP/1.1", 200, "Not Found"))

    def test_http_1_0(self):
        self.assertEqual(self.parse("HTTP/1.0 302 Found"), ("HTTP/1.0", 302, "Found"))

    def test_every_class(self):
        for code in (100, 201, 304, 418, 503):
            self.assertEqual(self.parse(f"HTTP/1.1 {code} X")[1], code)

    # --- invalid lines

    def test_invalid_lines_raise_value_error(self):
        bad = [
            "",
            "HTTP/1.1",
            "HTTP/1.1 OK",          # no code
            "HTTP/1.1 20 OK",       # code must be 3 digits
            "HTTP/1.1 2000 OK",
            "HTTP/1.1 abc OK",
            "HTTP/1.1 +20 OK",      # int("+20") works; it still isn't 3 digits
            "XTTP/1.1 200 OK",      # not an HTTP version
            "hello world",
        ]
        parse_status_line = require(self.client, "parse_status_line")
        for line in bad:
            with self.subTest(line=line), self.assertRaises(ValueError):
                parse_status_line(line)


if __name__ == "__main__":
    unittest.main()
