import sys 
import socket 
def parse_status_line(line):
    parts = line.split(" ", 2)
    version = parts[0] if parts[0].startswith("HTTP") else ValueError
    code = -1 if len(parts) < 2 else int(parts[1])
    reason = "" if len(parts) < 3 else parts[2] 
    if code < 100 or code > 599 or code == ValueError or version == ValueError :
        raise ValueError
    return (
        version,
        code,
        reason
    )

def send_request(host, path):
    port = 80 
    sock = socket.socket()
    try:
        sock.connect((host, port))
        request = f"GET {path} HTTP/1.1\r\nHost: {host}\r\nConnection:close\r\n\r\n"
        sock.sendall(request.encode("utf-8"))
        lines = sock.recv(4096).decode().split("\r\n")
        return parse_status_line(lines[0])
    finally:
        sock.close()

if __name__ == "main":
    send_request(sys.argv[1], sys.argv[2])
    