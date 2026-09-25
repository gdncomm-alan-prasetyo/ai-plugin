---
name: api-documentation-full
description: >-
  Generates Full Mode API documentation for Spring applications - complete
  internal docs - and WRITES it to a Markdown file. Covers everything in Lite
  Mode plus: Changelog, Auth & Authorization, Rate Limiting, Business Purpose
  (Why) per field, PII, Idempotency & Concurrency, Async/Kafka contracts,
  Mermaid sequence diagram, and Git-based change detection. The file is
  Confluence-safe Markdown.
---

# API Documentation - Full Mode (Complete Internal Documentation)

This skill **writes a file** — it does not just print to chat. The deliverable is a Markdown file on disk. After writing, confirm the path; do not echo the whole document back.

## Output Format

Standard Markdown only: `#` headers, `|` tables, triple-backtick code blocks, `---`. No HTML, no GitHub extensions. Emoji OK in tables. Mermaid blocks need Confluence Mermaid macro (if unavailable: `> Render with Confluence Mermaid app or draw.io.`).

---

## Phase 0 - Output Location (do FIRST, before scanning)

The whole point of Full Mode is a persisted file, so settle where it goes before doing any work.

1. **Path in the request?** Scan the user's message for a destination — "save to X", "put it in Y", "output dir Z", or any explicit folder/path. If found, that is the target folder. Filename = `{ControllerName}.md` unless the user gave a full filename.
2. **No path given?** Ask once, then wait:
   > Where should I write the spec? (e.g. `docs/api/` → `docs/api/{ControllerName}.md`)
   Do not guess a folder and do not fall back to a silent default — the user wants to choose. Proceed only after they answer.
3. Record the resolved target path. Use it in Phase 3.

---

## Phase 1 - Deep Scan & Change Detection

### 1.1 Trace the Vertical Slice

- **Controller**: method, URI, DTOs, `@Valid`/constraints, `@PreAuthorize`/`@Secured`/`@RolesAllowed`.
- **Service**: logic, branching, orchestration.
- **Middleware**: Redis (`@Cacheable`, `redisTemplate` — key, TTL, eviction), Kafka (`kafkaTemplate.send` — topic, event class, key, partition).
- **External clients**: Feign/RestTemplate/WebClient — target, endpoint, timeout.
- **Persistence**: repo, entity, table, unique indexes, DB constraints.
- **Error handlers (mandatory)**: Read every `@RestControllerAdvice`/`@ControllerAdvice`. Extract: (1) actual error response class — field names, types, structure; (2) how `status` is populated: `HttpStatus.name()` → `"BAD_REQUEST"`, `HttpStatus.getReasonPhrase()` → `"Bad Request"`, or custom string/enum; (3) all `@ExceptionHandler`-mapped exception types and their HTTP status codes. Ground truth for Section 11 — never use template status strings.
- **Security config**: `SecurityFilterChain`, JWT filter, claim extraction.
- **Rate limiting**: `@RateLimiter`, `BucketConfiguration`, Bucket4j/Resilience4j config.

### 1.2 Git Analysis (cheap commands — never `git log -p` on full history)

`git log -p` dumps every patch across all history and burns tens of thousands of tokens for data you mostly don't need. Use scoped, metadata-first commands instead:

```bash
git log -1 --format=%H                              # source commit hash (Section 1)
git log --oneline -10 -- {controller} {dto...}      # recent changes → changelog rows
git log --since="6 months" --stat -- {dto...}       # which files/fields churned, no patch text
```

Only when you need to confirm a specific field-level change (rename, type change, optional→required) for the changelog, run a **scoped** diff capped in size:

```bash
git log -p -L :{fieldOrClass}:{file}                # one symbol's history, not the whole file
# or: git diff {lastDocumentedCommit}..HEAD -- {dto}   # delta since last doc, not all history
```

If a doc already exists (Phase 3), diff only since its recorded **Source Commit** — not the whole repo history.

### 1.3 Identify the "Why"

Per critical field, header, or logic branch: record business purpose (why it exists, not what it is).

**Description rule**: shortest plain-language business statement, max ~6 words.
**Business Purpose (Why) rule**: explain why field/header exists — do not restate Description.

---

## Phase 2 - Build the Document

Read `references/template.md` (in this skill folder) for the 13 section shapes. Fill each from the Phase 1 scan + git analysis, in order:

1. Title (incl. Source Commit hash) 2. Endpoint 3. Changelog 4. Backward Compatibility 5. Auth & Authorization 6. Rate Limiting 7. Request Headers 8. Request Parameters 9. Request Body (idempotency + fields + example) 10. Response 11. Error Responses (all codes) 12. Async/Kafka (skip if no Kafka) 13. Sequence Diagram

---

## Phase 3 - Write the File

Target path resolved in Phase 0. Group all APIs from the same controller into one file.

1. If the file already exists: read it, then `git`-diff Controller/Service/DTO since its recorded **Source Commit** (not full history). On changes: append a changelog row, re-evaluate backward compatibility, update date and commit hash. Add a Table of Contents if the file holds more than one API.
2. **Write** the document to the resolved path using the Write tool. This step is mandatory — the deliverable is the file, not chat output.
3. Confirm to the user: "Wrote API spec → `{path}`." Give a 2-3 line summary (endpoint, version, breaking changes). Do **not** paste the full document back — it is already on disk and re-printing wastes tokens.

---

## Phase 4 - Quality Checklist

- [ ] File written to the resolved path; path confirmed to user.
- [ ] Endpoint method and full URI correct.
- [ ] All request fields: type, required, format/constraint, Description (~6 words), Business Purpose (Why), PII flag.
- [ ] Description: plain business statement. Business Purpose: why, not what.
- [ ] Enum values fully listed — no "etc."
- [ ] All error codes from `@RestControllerAdvice` covered (400, 401, 403, 404, 409, 418, 429, 500).
- [ ] Backward compatibility stated; every BREAKING has Migration Guide.
- [ ] Changelog up to date with commit hash.
- [ ] Kafka section present if `kafkaTemplate.send(...)` found.
- [ ] Rate limiting section present if Bucket4j/Resilience4j config found.
- [ ] Sequence diagram includes all actors.
- [ ] Output: standard Markdown, no HTML, no GitHub extensions.

---

## Constraints

- **Always write the file** — Phase 3 is not optional. Print to chat only the confirmation + short summary.
- **Never `git log -p` on full history** — scoped/metadata-first git only (Phase 1.2).
- Read actual code before documenting. Do not infer field types or error codes.
- Description: plain business statement, max ~6 words.
- Business Purpose (Why): business reason for existence — not a restatement of Description.
- PII: flag email, name, phone, national ID, device ID, IP address.
- Confluence export: ready via **Edit → Insert → Markup → Markdown**. Mermaid requires Confluence Mermaid macro.
