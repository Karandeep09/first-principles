import sys 
import socket 


def fetch_raw(host, path, port = 80):
    sock = socket.socket()
    try:
        sock.connect((host, port))
        request = f"GET {path} HTTP/1.1\r\nHost: {host}\r\nConnection:close\r\n\r\n"
        sock.sendall(request.encode("utf-8"))
        chunks = []
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break 
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        sock.close()

def parse_headers(data):

    lines = data.split(b"\r\n\r\n", 1)[0].decode().split("\r\n")
    headers = {}
    for i,l in enumerate(lines):
        if i == 0:
            continue
        kv = l.split(": ", maxsplit=1)
        headers[f"{kv[0]}"] = "" if len(kv) < 2 else kv[1]
    return headers

if __name__ == "__main__":
     data = fetch_raw(sys.argv[1], sys.argv[2])
     print(parse_headers(data))

    