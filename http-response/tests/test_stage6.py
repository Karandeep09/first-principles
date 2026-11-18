"""Stage 6 — HTTPS.

Contract (client.6.py): the same get()/request() as stage 5, now also for https:// URLs.
These tests use the real internet and are skipped when it isn't reachable.
Run the stage 5 tests against this file too:  STAGE5_FILE=client.6.py
"""
import socket
import unittest

from tests.helpers import load_client, require, run_with_timeout


def online():
    try:
        socket.create_connection(("example.com", 443), timeout=3).close()
        return True
    except OSError:
        return False


class Stage6(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not online():
            raise unittest.SkipTest("no internet connection")
        cls.client = load_client(6, "client.6.py")

    def get(self, url):
        return run_with_timeout(require(self.client, "get"), url, timeout=20)

    def test_https(self):
        r = self.get("https://example.com/")
        self.assertEqual(r.status, 200)
        self.assertIn(b"Example Domain", r.body)

    def test_plain_http_still_works(self):
        self.assertEqual(self.get("http://example.com/").status, 200)

    def test_http_redirects_to_https(self):
        r = self.get("http://github.com/")
        self.assertEqual(r.status, 200)
        self.assertTrue(r.url.startswith("https://github.com"), r.url)

    def test_explicit_port_443(self):
        self.assertEqual(self.get("https://example.com:443/").status, 200)


if __name__ == "__main__":
    unittest.main()
