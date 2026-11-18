"""Stage 5 — act on the status code.

Contract (client.5.py):
    request(method, url, body=None, max_redirects=10) -> response
    get(url, max_redirects=10) -> response        # same as request("GET", url, ...)
response has .status (int), .headers, .body (bytes), and .url (the final URL).
Also define these exception classes:
    ClientError       raised for 4xx, with a .status attribute
    ServerError       raised for 5xx, with a .status attribute
    TooManyRedirects  raised when the hop limit is exceeded

Redirects: follow 301, 302, 303, 307 and 308 when there is a Location header.
Any other 3xx (e.g. 304) is returned as-is, not raised.
"""
import unittest

from tests.helpers import (RawServer, http_response, load_client, redirect, require,
                           routes_handler, run_with_timeout)


class Stage5(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = load_client(5, "client.5.py")

    def serve(self, routes):
        self.server = RawServer(routes_handler(routes))
        self.addCleanup(self.server.close)
        self.base = f"http://127.0.0.1:{self.server.port}"
        return self.base

    def get(self, path, **kw):
        return run_with_timeout(require(self.client, "get"), self.base + path, **kw)

    def request(self, method, path, **kw):
        return run_with_timeout(require(self.client, "request"), method, self.base + path, **kw)

    def error(self, name):
        return require(self.client, name)

    def methods_seen(self):
        return [(r.method, r.path, r.body) for r in self.server.requests]

    # --- 2xx / 4xx / 5xx

    def test_200_returns_body(self):
        self.serve({"/": http_response(200, body=b"hi")})
        r = self.get("/")
        self.assertEqual((r.status, r.body), (200, b"hi"))
        self.assertEqual(r.url, self.base + "/")

    def test_404_raises_client_error(self):
        self.serve({})
        with self.assertRaises(self.error("ClientError")) as cm:
            self.get("/nope")
        self.assertEqual(cm.exception.status, 404)

    def test_any_4xx_is_client_error(self):
        self.serve({"/tea": http_response(418)})
        with self.assertRaises(self.error("ClientError")) as cm:
            self.get("/tea")
        self.assertEqual(cm.exception.status, 418)

    def test_5xx_raises_server_error(self):
        self.serve({"/": http_response(503)})
        with self.assertRaises(self.error("ServerError")) as cm:
            self.get("/")
        self.assertEqual(cm.exception.status, 503)

    def test_client_and_server_errors_are_different(self):
        self.assertIsNot(self.error("ClientError"), self.error("ServerError"))

    # --- following redirects

    def test_301_absolute_location(self):
        base = self.serve({"/old": lambda req: redirect(301, base + "/new"),
                           "/new": http_response(200, body=b"new")})
        r = self.get("/old")
        self.assertEqual((r.status, r.body, r.url), (200, b"new", base + "/new"))

    def test_302_relative_location(self):
        base = self.serve({"/a": redirect(302, "/b"), "/b": http_response(200, body=b"b")})
        r = self.get("/a")
        self.assertEqual((r.body, r.url), (b"b", base + "/b"))

    def test_relative_location_without_leading_slash(self):
        base = self.serve({"/dir/page": redirect(302, "other"), "/dir/other": http_response(200, body=b"o")})
        r = self.get("/dir/page")
        self.assertEqual((r.body, r.url), (b"o", base + "/dir/other"))

    def test_every_redirect_code_is_followed(self):
        for code in (301, 302, 303, 307, 308):
            with self.subTest(code=code):
                self.serve({"/r": redirect(code, "/done"), "/done": http_response(200, body=b"done")})
                self.assertEqual(self.get("/r").body, b"done")

    def test_chain_of_redirects(self):
        self.serve({"/1": redirect(302, "/2"), "/2": redirect(301, "/3"),
                    "/3": redirect(307, "/4"), "/4": http_response(200, body=b"end")})
        self.assertEqual(self.get("/1").body, b"end")

    def test_redirect_to_error_still_raises(self):
        self.serve({"/r": redirect(302, "/gone")})
        with self.assertRaises(self.error("ClientError")):
            self.get("/r")

    # --- method and body on redirect

    def test_303_turns_post_into_get_without_body(self):
        self.serve({"/form": redirect(303, "/result"), "/result": http_response(200, body=b"r")})
        self.request("POST", "/form", body=b"name=x")
        self.assertEqual(self.methods_seen(), [("POST", "/form", b"name=x"), ("GET", "/result", b"")])

    def test_307_keeps_method_and_body(self):
        self.serve({"/a": redirect(307, "/b"), "/b": http_response(200)})
        self.request("POST", "/a", body=b"payload")
        self.assertEqual(self.methods_seen(), [("POST", "/a", b"payload"), ("POST", "/b", b"payload")])

    def test_308_keeps_method_and_body(self):
        self.serve({"/a": redirect(308, "/b"), "/b": http_response(200)})
        self.request("PUT", "/a", body=b"payload")
        self.assertEqual(self.methods_seen(), [("PUT", "/a", b"payload"), ("PUT", "/b", b"payload")])

    def test_post_sends_content_length(self):
        self.serve({"/": http_response(200)})
        self.request("POST", "/", body=b"12345")
        self.assertEqual(self.server.requests[0].header("content-length"), "5")

    # --- stopping

    def test_redirect_loop_stops(self):
        self.serve({"/a": redirect(302, "/b"), "/b": redirect(302, "/a")})
        with self.assertRaises(self.error("TooManyRedirects")):
            self.get("/a")
        self.assertLessEqual(len(self.server.requests), 11)

    def test_hop_limit_is_respected(self):
        routes = {"/1": redirect(302, "/2"), "/2": redirect(302, "/3"),
                  "/3": redirect(302, "/4"), "/4": http_response(200, body=b"end")}
        self.serve(routes)
        self.assertEqual(self.get("/1", max_redirects=3).body, b"end")
        self.serve(routes)
        with self.assertRaises(self.error("TooManyRedirects")):
            self.get("/1", max_redirects=2)

    # --- 3xx that are not redirects

    def test_304_is_returned_not_followed(self):
        self.serve({"/": http_response(304)})
        r = self.get("/")
        self.assertEqual((r.status, r.body), (304, b""))
        self.assertEqual(len(self.server.requests), 1)

    def test_3xx_without_location_is_returned(self):
        self.serve({"/": http_response(300, body=b"pick one")})
        self.assertEqual(self.get("/").status, 300)


if __name__ == "__main__":
    unittest.main()
