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

if __name__ == "__main__":
    fetch_raw(sys.argv[1], sys.argv[2])
    