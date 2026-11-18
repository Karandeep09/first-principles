import sys
import socket


class Headers:
    def __init__(self):
        self.items = []

    def add(self, name, value):
        self.items.append((name.lower(), value))

    def get(self, name):
        values = self.get_all(name)
        return values[0] if values else None

    def get_all(self, name):
        name = name.lower()
        return [v for k, v in self.items if k == name]


class Response:
    def __init__(self, version, status, reason, headers, body):
        self.version = version
        self.status = status
        self.reason = reason
        self.headers = headers
        self.body = body


def parse_status_line(line):
    parts = line.split(" ", 2)
    if len(parts) < 2 or not parts[0].startswith("HTTP/"):
        raise ValueError(f"bad status line: {line!r}")
    code = int(parts[1])
    if code < 100 or code > 599:
        raise ValueError(f"bad status code: {code}")
    reason = "" if len(parts) < 3 else parts[2]
    return (parts[0], code, reason)


def parse_head(head):
    lines = head.decode("latin-1").split("\r\n")
    version, code, reason = parse_status_line(lines[0])
    headers = Headers()
    for l in lines[1:]:
        if l == "":
            continue
        name, _, value = l.partition(":")
        headers.add(name.strip(), value.strip())
    return version, code, reason, headers


class ResponseReader:
    def __init__(self, sock):
        self.sock = sock
        self.buf = b""   # bytes received but not consumed yet (may hold the next response)
        self.closed = False

    def _fill(self):
        """Read more bytes into the buffer. Returns False once the peer has closed."""
        if self.closed:
            return False
        data = self.sock.recv(4096)
        if not data:
            self.closed = True
            return False
        self.buf += data
        return True

    def _take(self, n):
        while len(self.buf) < n:
            if not self._fill():
                raise ConnectionError(f"connection closed: wanted {n} bytes, got {len(self.buf)}")
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _read_until(self, sep):
        """Return everything up to and including sep."""
        while True:
            i = self.buf.find(sep)
            if i != -1:
                return self._take(i + len(sep))
            if not self._fill():
                raise ConnectionError(f"connection closed before {sep!r}")

    def _read_chunked(self):
        body = []
        while True:
            size_line = self._read_until(b"\r\n")[:-2]
            size = int(size_line.split(b";", 1)[0].strip(), 16)  # drop chunk extensions
            if size == 0:
                break
            body.append(self._take(size))
            if self._take(2) != b"\r\n":
                raise ValueError("chunk data not followed by CRLF")
        # trailers: header lines until an empty line
        while self._read_until(b"\r\n") != b"\r\n":
            pass
        return b"".join(body)

    def _read_until_close(self):
        while self._fill():
            pass
        out, self.buf = self.buf, b""
        return out

    def read_response(self, method="GET"):
        head = self._read_until(b"\r\n\r\n")
        version, status, reason, headers = parse_head(head)

        # 1xx, 204, 304 and any response to HEAD never have a body
        if method.upper() == "HEAD" or status < 200 or status in (204, 304):
            body = b""
        # Transfer-Encoding wins over Content-Length
        elif headers.get("transfer-encoding") is not None and \
                "chunked" in headers.get("transfer-encoding").lower():
            body = self._read_chunked()
        elif headers.get("content-length") is not None:
            body = self._take(int(headers.get("content-length")))
        else:
            body = self._read_until_close()

        return Response(version, status, reason, headers, body)


def send_request(host, path):
    port = 80
    sock = socket.create_connection((host, port))
    try:
        reader = ResponseReader(sock)
        # two requests on one keep-alive connection
        for _ in range(2):
            request = f"GET {path} HTTP/1.1\r\nHost: {host}\r\n\r\n"
            sock.sendall(request.encode("utf-8"))
            resp = reader.read_response("GET")
            print(resp.status, resp.reason, len(resp.body), "bytes")
        print(resp.body.decode("utf-8", errors="replace"))
    finally:
        sock.close()

if __name__ == "__main__":
    send_request(sys.argv[1], sys.argv[2])
