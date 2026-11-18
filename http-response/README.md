# HTTP Responses from First Principles

> Goal: understand exactly what comes back over the wire after you send an HTTP request — the status code, the headers, and the body — by building a client (and later a server) that speaks raw HTTP/1.1 over a TCP socket.

You will not use any HTTP library. No `requests`, `urllib`, `fetch`, `axios`, `http.client`, `net/http`, etc. Only a **TCP socket** and **bytes**.

Pick any language that gives you sockets (Python, Go, Rust, C, Node `net`, …).

---

## How to use this doc

- Work through the stages in order. Each one builds on the last.
- Each stage has a **Task**, a **Done when** check, and a few **Questions** to answer in your own notes.
- Hints are hidden. Open one only after you have been stuck for a while. Try the primary sources first (see [References](#references)).
- Keep a `NOTES.md` in this folder with what surprised you at each stage.

Suggested layout (yours to change):

```
http-response/
├── README.md        ← this file
├── NOTES.md         ← your observations
├── client.*         ← stages 1–6
└── server.*         ← stage 7
```

---

## Stage 0 — Observe before you build

**Task:** See a real request and response as raw text.

1. Run `curl -v http://example.com/` and read every line it prints.
2. Open a raw TCP connection with `nc example.com 80` (or `telnet`) and type a request by hand.

**Done when:** You got a response back from a server by typing the request yourself.

**Questions**
- Which lines in `curl -v` were sent and which were received?
- What did the server do when you typed the request slightly wrong?
- What separates the headers from the body?

<details><summary>Hint</summary>

Lines in HTTP/1.1 end with `\r\n`, not just `\n`. Some `nc` versions have a `-C` flag for this. The server also expects a `Host` header.
</details>

---

## Stage 1 — Send a request over a socket

**Task:** Write a program that opens a TCP connection to a host on port 80, sends a `GET` request for a path, and prints **every byte** it receives until the connection ends.

**Done when:** Your program's output matches what `nc` showed you for the same request.

**Questions**
- Is the whole response returned by one `recv`/`read` call? Run it a few times against a large page and check.
- Who closed the connection, and how did your program know?

<details><summary>Hint</summary>

`recv` returning zero bytes (or EOF) means the other side closed. Look up what the `Connection` request header does.
</details>

---

## Stage 2 — Parse the status line

**Task:** Pull out the first line of the response and split it into its parts. Return a structured value (struct/object/tuple), not a string.

**Done when:** For any response you can print the protocol version, the numeric code, and the reason text separately.

**Questions**
- How many parts does the status line have? Can the reason text contain spaces? Can it be empty?
- Does a client need the reason text at all?
- What does the first digit of the code tell you? Write the meaning of each class 1xx–5xx in your own words.

<details><summary>Hint</summary>

Read RFC 9112 §4 (status line) and RFC 9110 §15 (status codes). Split carefully. A naive split on every space will break.
</details>

---

## Stage 3 — Parse the headers

**Task:** Parse every header line after the status line into a data structure, and stop at the end of the header section.

**Done when:** You can look up `content-type` and `Content-Type` and get the same value. You also know the exact byte offset where the body begins.

**Questions**
- Are header names case-sensitive? Are values?
- What should happen when the same header appears twice (`Set-Cookie` is a good one to test)?
- What is your parser's rule for spaces around the `:`?

<details><summary>Hint</summary>

The header section ends at the first empty line, which is `\r\n\r\n` in the byte stream. Bytes after that belong to the body. Some of them may already be in the buffer you read.
</details>

---

## Stage 4 — Read the body correctly

This is the core of the exercise. "Read until the connection closes" works only some of the time. A response can mark where its body ends in **three** different ways, and your client must handle all of them.

**Task:** Find the three ways, then implement each one. Your client must work with `Connection: keep-alive` too, which means it cannot rely on the socket closing.

**Done when:**
- You can fetch a page whose response uses `Content-Length`.
- You can fetch a page whose response uses `Transfer-Encoding: chunked`. Hunt for a server that does this and check with `curl -v`.
- Your client sends **two requests on one connection** and correctly separates the two responses.

**Questions**
- Which header wins if a response has both `Content-Length` and `Transfer-Encoding`? Why does that rule matter for security?
- Some responses must never have a body, whatever their headers say. Which ones? (There are status codes on the list, plus one request method.)
- Why was chunked encoding invented at all?

<details><summary>Hint 1</summary>

RFC 9112 §6.3 ("Message Body Length") is an ordered list. Implement it in that order.
</details>

<details><summary>Hint 2 (chunked)</summary>

Each chunk is a size in **hex**, then CRLF, then that many bytes, then CRLF. A size of `0` ends the body, and trailer headers may follow it.
</details>

---

## Stage 5 — Act on the status code

**Task:** Make your client *behave* differently by status class:

| Class | Your client should… |
|-------|---------------------|
| 2xx   | return the body |
| 3xx   | you decide (see below) |
| 4xx   | raise or return a client error that includes the code |
| 5xx   | raise or return a server error, and maybe retry |

Then add **redirect following** for 301, 302, 303, 307 and 308, with a hop limit.

**Done when:** `GET http://github.com/` ends at the final HTTPS URL. Your client can report the URL but not fetch it until Stage 6. It must also stop cleanly on a redirect loop.

**Questions**
- 301/302 vs 307/308: what changes about the **method** and **body** on the next request?
- Where does the redirect target come from? Can it be a relative URL?
- Is `304 Not Modified` a redirect? What request header makes a server send one?
- Is a `404` with an HTML body a "failure" at the protocol level?
- Which 5xx codes make sense to retry, and which methods are safe to retry?

<details><summary>Hint</summary>

RFC 9110 §15.4 covers the 3xx codes one by one. Read the paragraph on method rewriting for 301/302.
</details>

---

## Stage 6 — HTTPS (optional, recommended)

**Task:** Wrap your TCP socket in TLS so the same client works on port 443. Use your language's TLS library. Writing TLS yourself is out of scope.

**Done when:** The redirect from Stage 5 finishes at the HTTPS URL and you get a `200`.

**Questions**
- Did any of your parsing code have to change? Why or why not?
- What is SNI, and what happens if you skip it?

---

## Stage 7 — Flip sides: build the server

**Task:** Write a minimal server on a local port that answers requests with status codes and bodies you choose, then test it with `curl -v` and with your own client.

Make it return, at minimum:
- `200` with a body using `Content-Length`
- `200` with a **chunked** body
- `204` with no body
- `301` / `302` with a `Location` header
- `404` for unknown paths
- `400` when the request line is malformed
- `500` when your handler throws

**Done when:** `curl -v` shows each response cleanly with no warnings, and your Stage 1–5 client handles every endpoint.

**Questions**
- What does `curl` do if your `Content-Length` is **too large**? Too small?
- What happens if you send a `204` with a body?
- How does your server know a request has ended? Is that the same problem as Stage 4?

---

## Stretch goals

- **Persistent pool:** reuse connections across requests to the same host and measure the speed-up.
- **Streaming:** expose the body as a stream or iterator instead of buffering it all.
- **Compression:** send `Accept-Encoding: gzip` and decode the body. Work out where it sits relative to chunked encoding.
- **Timeouts:** add connect, read and total timeouts, and decide what your client reports for each.
- **Fuzz your parser:** feed it truncated, oversized and malformed responses. It must never hang or crash.
- **Compare with HTTP/2:** read how RFC 9113 represents a status code. (Hint: there is no status line.)

---

## Self-check

You are done when you can answer these without notes:

1. Write out a complete, minimal, valid HTTP/1.1 response byte by byte.
2. Explain the three ways a client knows a response body has ended, and the order of priority.
3. Explain the difference between a status code, a reason phrase and a response body, and which of them a client should actually trust.
4. Explain why 307 exists when 302 already did.
5. Explain how a client tells two responses apart on one keep-alive connection.

---

## References

Primary sources. Read these before the hints.

- **RFC 9110** — HTTP Semantics (status codes: §15, header fields: §5)
- **RFC 9112** — HTTP/1.1 message syntax (status line: §4, body length: §6.3, chunked: §7.1)
- **RFC 9113** — HTTP/2 (stretch goal only)
- `curl -v`, `nc`, and Wireshark for checking against real traffic
