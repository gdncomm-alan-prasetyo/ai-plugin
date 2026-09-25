---
name: api-documentation-helper
description: >-
  Entry point for Spring API documentation. Asks the developer to choose
  Lite Mode (partner/third-party-facing) or Full Mode (complete internal docs),
  then delegates to the matching skill. Use this skill when you are unsure
  which mode is needed. If you already know — invoke api-documentation-lite
  or api-documentation-full directly.
---

# API Documentation Helper - Mode Selector

## Step 1 - Ask the Developer

> Which documentation mode do you need?
>
> **[1] Lite Mode** - Partner / Third-Party Integration Guide
> Covers: Endpoint, Request (headers, params, body), Response, Error Responses, Backward Compatibility.
> Output: copy-paste Markdown printed to chat (no file written).
>
> **[2] Full Mode** - Complete Internal Documentation
> Covers: Everything in Lite Mode + Changelog, Auth & Authorization, Rate Limiting, Business Purpose (Why) per field, PII, Idempotency & Concurrency, Async/Kafka contracts, Mermaid sequence diagram, Git-based change detection.
> Output: writes a Markdown file (asks where to save).

## Step 2 - Delegate

| Choice | Skill |
|--------|-------|
| 1 - Lite | `api-documentation-lite` |
| 2 - Full | `api-documentation-full` |

Hand off immediately. Do not scan code or produce documentation here.
