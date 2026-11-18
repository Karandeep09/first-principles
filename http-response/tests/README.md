# Tests

Standard library `unittest` only. Run from the `http-response/` folder:

```sh
python3 -m unittest discover -s tests -t . -v     # every stage
python3 -m unittest -v tests.test_stage4          # one stage
python3 -m unittest -v tests.test_stage4.Stage4.test_chunked   # one test
```

A stage whose file doesn't exist yet is **skipped**, not failed.

Each test file starts with a docstring describing its contract. The tests only check
that contract, so how you build each piece is up to you.

## Before anything: make your files importable

The tests `import` your client files. If the last line of a file is a bare
`send_request(sys.argv[1], sys.argv[2])`, it runs on import and crashes. Wrap it:

```python
if __name__ == "__main__":
    send_request(sys.argv[1], sys.argv[2])
```

## Contracts

| Stage | File | You provide |
|---|---|---|
| 1 | `client.1.py` | `fetch_raw(host, path, port=80) -> bytes`: every byte the server sent, unchanged |
| 2 | `client.2.py` | `parse_status_line(line: str) -> (version: str, code: int, reason: str)`. It can be a tuple or a NamedTuple (not a dict). Raises `ValueError` on bad input |
| 3 | `client.3.py` | `parse_headers(data: bytes) -> (headers, body_start)`, or `None` if the header section isn't complete yet. `headers.get(name)` ignores case and returns `None` when the header is missing. `headers.get_all(name)` returns a list |
| 4 | `client.4.py` | `ResponseReader(sock).read_response(method="GET")` reads **one** response and keeps any extra bytes for the next call. The result has `.status` (int), `.headers`, and `.body` (bytes, already de-chunked). Raises an exception if the connection closes too early |
| 5 | `client.5.py` | `request(method, url, body=None, max_redirects=10)` and `get(url, max_redirects=10)`. The result has `.status`, `.headers`, `.body`, and `.url` (the final URL). Also define the exceptions `ClientError` (4xx) and `ServerError` (5xx), each with a `.status`, and `TooManyRedirects` |
| 6 | `client.6.py` | Same as stage 5, but `https://` URLs also work. **Needs internet**, and is skipped when offline |
| 7 | `server.py` | `python3 server.py <port>` listens on 127.0.0.1. The routes are listed in `PATHS` at the top of `test_stage7.py`; edit them to match yours |

Each later stage can import code from earlier ones. For example, `client.4.py` can
reuse `parse_headers`.

## Pointing a stage at a different file

```sh
STAGE5_FILE=client.6.py python3 -m unittest tests.test_stage5   # did HTTPS break redirects?
SERVER_FILE=my_server.py python3 -m unittest tests.test_stage7
```

## What the fake servers do

- **Stages 1 and 5** run a real TCP server on a random local port. Like a real HTTP/1.1
  server, it keeps the connection open unless your request says `Connection: close`.
- **Stage 4** uses `socket.socketpair()`. The test writes response bytes into one end,
  sometimes one byte at a time, and **does not close it**. That way a reader that
  relies on "read until close" times out after a few seconds instead of passing by luck.
- Every call is wrapped in a timeout. A client that hangs fails with a message
  instead of freezing the test run.

Heads-up: the test names answer some of the README's questions (for example
`test_transfer_encoding_beats_content_length`). Try to answer each stage's questions
before you read its tests.
