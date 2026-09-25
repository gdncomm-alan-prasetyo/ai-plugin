---
name: api-documentation-lite
description: >-
  Generates Lite Mode API documentation for Spring applications - partner and
  third-party-facing. Covers endpoint, request (headers, params, body),
  response, error responses, and backward compatibility. Output is
  Confluence-safe Markdown printed to chat (copy-paste ready, not written to a file).
---

# API Documentation - Lite Mode (Partner Integration Guide)

Output is **copy-paste Markdown printed to the chat** — Lite does not write a file. (Need a written file? Use `api-documentation-full`.)

## Output Format

Standard Markdown only: `#` headers, `|` tables, triple-backtick code blocks, `---`. No HTML, no GitHub extensions. Emoji OK in tables. Code blocks need language tag.

---

## Phase 1 - Deep Scan

Trace: Controller (method, URI, DTOs, `@Valid`/constraints), Service (logic, branching), Persistence (repo, entity, indexes), External clients (Feign/RestTemplate/WebClient).

**Error handler scan (mandatory)**: Read every `@RestControllerAdvice`/`@ControllerAdvice` class. Extract:
1. Actual error response class — field names, types, structure.
2. How `status` field is populated: `HttpStatus.name()` → `"BAD_REQUEST"`, `HttpStatus.getReasonPhrase()` → `"Bad Request"`, or custom string/enum.
3. All `@ExceptionHandler`-mapped exception types and their HTTP status codes.

Ground truth for all error examples. Never use template status strings — use the actual value the code produces.

**Description field rule** (all sections): shortest plain-language business statement, max ~6 words. What it is for, not a technical definition.

---

## Phase 2 - Build the Document

Read `references/template.md` (in this skill folder) for the section shapes. It holds the 8 section templates. Fill each from the Phase 1 scan, in order:

1. Title
2. Endpoint
3. Backward Compatibility
4. Request Headers
5. Request Parameters
6. Request Body (field table + example)
7. Response (headers, body fields, success example)
8. Error Responses (all codes from the error-handler scan)

Print the finished document to the chat.

---

## Phase 3 - Quality Checklist

- [ ] Endpoint method and full URI correct.
- [ ] All request fields: type, required, format/constraint, Description (plain, max ~6 words), PII flag.
- [ ] Enum values fully listed — no "etc." or truncation.
- [ ] All error codes from `@RestControllerAdvice` covered (400, 401, 403, 404, 409, 418, 429, 500).
- [ ] Backward compatibility stated for latest version; every BREAKING has migration note.
- [ ] Output: standard Markdown, no HTML, no GitHub extensions.

---

## Constraints

- Read actual code before documenting. Do not infer field types or error codes.
- Description: plain business statement, max ~6 words.
- PII: flag email, name, phone, national ID, device ID, IP address.
- Confluence export: ready via **Edit → Insert → Markup → Markdown**.
