---
name: first-principles
description: Create a self-guided "build it from first principles" helper doc for a topic in the first-principles repo. Use when the user runs /first-principles <topic> or asks for a first-principles guide/exercise on a topic.
argument-hint: <topic to build from first principles>
---

# First-principles helper doc

Topic: $ARGUMENTS

If no topic was given, ask for one and stop.

## Where

- Repo: the project root (the folder containing this `.claude/` directory)
- Create a new folder named after the topic in kebab-case (e.g. `http-response`, `hash-map`, `tcp-handshake`). If it already exists, read what's there and extend it rather than overwrite.
- Write the doc as `<folder>/README.md`.
- Use `http-response/README.md` in the repo as the reference for tone, structure and hint density.

## What the doc is

A guide for a developer working **independently**, with **minimum hints**, to implement the topic from first principles. It teaches by making them build it, not by explaining it.

## Required structure

1. **Title + one-line goal**: what they will understand by building what.
2. **Ground rules**: which libraries/abstractions are banned and which primitive they build on (e.g. raw sockets, arrays, numpy only). Language-agnostic unless the topic implies one.
3. **How to use this doc**: stages in order, hints hidden, keep a `NOTES.md`, and a suggested file layout.
4. **Stage 0 — Observe before you build**: poke at the real thing with existing tools before writing code.
5. **Stages 1..N**, building from the smallest primitive up to the full thing. Each stage has:
   - **Task**: what to build. Say *what*, never *how*.
   - **Done when**: an objective, checkable criterion.
   - **Questions**: 2–5 probing questions for their notes, including edge cases and "why does this exist?".
   - **Hints**: in collapsed `<details><summary>Hint</summary>` blocks, at most 1–2 per stage. Prefer pointing to a primary source (RFC section, paper section, spec) over giving the answer. Never include solution code.
6. **A "flip sides" or integration stage** where it fits, e.g. build the server after the client, or the decoder after the encoder.
7. **Stretch goals**.
8. **Self-check**: about 5 questions they should be able to answer without notes.
9. **References**: primary sources only (RFCs, papers, specs, man pages), with section numbers where possible.

## Rules

- Be technically precise. Check RFC and paper section numbers against what you know; leave out any you are unsure of.
- No solution code anywhere. Small illustrative snippets of *input/output data* are fine.
- After writing, update the repo's root `README.md` with a one-line entry linking the new folder (add an index list if there isn't one).
- Reply with a short summary of the stages and the file path.
