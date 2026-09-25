---
name: docs-openapi-to-markdown
description: >
  Converts an OpenAPI 3.0 spec into readable Markdown under docs/api/ -- one file per tag
  plus an index. Every request and response body gets a flattened field table and a sample
  JSON payload. Use when asked for "API docs" or "markdown docs" from an existing
  openapi.yaml or swagger.yaml. The natural follow-up to docs-code-to-openapi, which
  produces the spec.
argument-hint: "[path to openapi.yaml] [output dir, default docs/api]"
allowed-tools: ["Bash(python*)", "Read", "Glob", "Grep", "Write", "Edit"]
---

# OpenAPI YAML to Markdown (grouped by tag) -> docs/api/

Deterministically converts an OpenAPI 3.0 document into Markdown: one file per tag under
**`docs/api/`** -- that's the fixed target folder for this skill's output, not just a
default to override lightly -- plus a `docs/api/README.md` index. The conversion is
mechanical (structured YAML -> structured Markdown), so the bundled script does the whole
job -- there's no draft/review split like `docs-code-to-openapi`'s source-analysis
heuristics.

## Workflow

1. **Run the script** against the spec, writing into `docs/api/`:

   ```bash
   python ${CLAUDE_PLUGIN_ROOT}/skills/docs-openapi-to-markdown/scripts/generate_markdown_docs.py \
     docs/openapi/openapi.yaml --output-dir docs/api
   ```

   Run it from the target repo's root (or pass an absolute path as the first argument) so
   `docs/openapi/openapi.yaml` and `--output-dir docs/api` resolve relative to that repo,
   not to this skill's own directory. `--output-dir` defaults to `docs/api` already --
   only pass a different value if the user explicitly asks for the docs to live somewhere
   else; otherwise always let it land in `docs/api/`.

   Requires PyYAML (`pip install pyyaml` if the environment doesn't already have it --
   `docs-code-to-openapi` doesn't need it since it only emits YAML, but reading it back
   needs a real parser).

2. **Read stderr.** The script prints one `wrote <file> (N endpoints)` line per tag and a
   final warning for any tag declared in the spec's top-level `tags:` list that has zero
   operations using it (these are skipped rather than written as empty files -- usually a
   sign the spec itself mis-tagged something, worth a glance upstream).

3. **Skim the generated files, not just the endpoint count.** Specifically:
   - Every field table is fully flattened and self-contained -- there is no separate
     schemas appendix to cross-reference, and no dangling `$ref` links. A `$ref`, wherever
     it occurs (a top-level body, a nested field, an array item), is resolved and its
     fields inlined right there using a dotted path (`data.paging.pageNumber`) or a
     bracketed array-item path (`data.result[].id`).
   - A schema that refers back to itself (directly or through another schema) is cut off
     with a `(circular — not expanded further)` note in that one row instead of recursing
     forever -- if you see that note, decide by hand whether the reader needs the nested
     shape spelled out anyway.
   - Enum-like `pattern` fields (some generators, including `docs-code-to-openapi`,
     write informal values like `pattern: NAME|HOST` that aren't real regexes) are surfaced
     verbatim in the Notes column -- reword by hand if that reads as confusing to an API
     consumer.
   - The JSON example under each table is placeholder data (see "How example values are
     picked" below), not a real captured payload -- don't present it to consumers as a
     verified example without a glance at whether the placeholders make sense (e.g. an
     `enum` or `pattern` field where the guess is misleading).

4. **Re-run any time `docs/openapi/openapi.yaml` changes.** Output is fully regenerated
   (each file is overwritten, not merged), so there's nothing to hand-reconcile -- treat
   `docs/api/` as a build artifact of the YAML spec, not a place to hand-edit. Each
   generated file starts with a "Do not hand-edit" note as a reminder.

## What the output looks like

Shape and heading/column contracts: `~/.claude/references/doc-output-conventions.md`.

Per tag file (`docs/api/<tag-slug>.md`): H1 + the tag's `description`, an **Endpoints**
table for scanning a large tag, then one `##` per operation containing `### Parameters`,
`### Request body`, and one `### Response <status>` per status. Descriptive text sits under
each heading, never inside it, so rewording a description does not move an anchor.

Each body is one merged block: a flattened field table immediately followed by a fenced
```json``` sample. There's no bottom-of-file schemas appendix -- every table is fully
expanded.

Plus `docs/api/README.md`: `info.description`, the **Response envelope** section (below), a
**Servers** table, and a table of every tag with its endpoint count and a link. `info` and
`servers` are root-level and have no per-tag home, so the index is the only place they can
land.

## The response envelope is documented once, not per response

Most specs express a shared response envelope by repeating the same properties on every
response schema. Rendered literally that is enormous: on a 6-endpoint spec the envelope was
**96 of 210 field rows**, so the payload each operation actually returns was buried under
five identical rows repeated eighteen times.

`detect_envelope` finds fields that repeat identically -- same name, type, description and
constraints -- across at least `--envelope-min` (default 3) response schemas, and hoists
them into a single `## Response envelope` table in the index. Each response then lists its
own `data` payload and a one-line pointer.

**A field is only collapsed when its whole signature matches.** This is the part that keeps
it honest: `code` and `status` usually carry a per-status example (`200`/`OK` on success,
`403`/`FORBIDDEN` on an error schema), so collapsing by name alone would tell a reader the
500 response returns `code: 200`. Those rows differ, so they stay inline and override the
canonical table. `data` is never a candidate -- it is the payload.

The JSON sample is never collapsed. Trimming the table removes repetition a reader can look
up; trimming the sample would produce a payload that is not a payload.

Escape hatches: `--no-envelope-collapse` restores a fully self-contained table per response,
`--envelope-fields a,b,c` pins the set for a spec the detector reads wrongly.

## How the field table is flattened

`build_schema_rows` walks the schema and emits one row per field as `(path, type,
required, description, constraints)`:
- **Description and constraints are separate columns.** Joining them produced cells like
  "...rather than failing.; example: `10001`" -- bad to read and impossible to split back
  apart.
- A named object field becomes its own row (type `object`) *and* each of its properties
  becomes a child row with a dotted path (`data.paging`, then `data.paging.pageNumber`).
- An array of primitives is a single row: `messages` -- `array of string`.
- An array field's own `description` populates its Description column exactly like a scalar
  field's -- so a documented `roleNames` reads the same as a documented `name`.
- An array of objects/`$ref`s gets one row naming the item type (`data.result` -- `array
  of \`AppResponse\``), then each of the item's fields as `data.result[].<field>` rows --
  the intermediate "array item is an object" row is skipped for named `$ref`s (the parent
  row already says the type name) but kept for anonymous inline array items (there's no
  name to point to otherwise).
- A top-level array body (no wrapping object) roots its item fields at `[]` (e.g.
  `[].filterBy`) instead of a named path, since there's no field name to prefix with.
- `$ref` is always resolved and inlined; a `visited` set is threaded through the
  recursion *per branch* (not globally), so the same schema reused in two unrelated
  fields is expanded fully both times, and only an actual cycle along one branch gets cut
  off.

## How example values are picked

For **any** schema, in order: its own `example` if given, else its `default`, else -- for a
leaf -- the first `enum` value, else a Swagger-UI-style placeholder by type (`"string"`, `0`,
`true`; `date`/`date-time`/`uuid` formats get a plausible literal instead of the bare
`"string"`).

`example` is consulted on objects and arrays too, not just leaves. That is the only way a
spec can say "this object is always null": write `example: null` on it and the sample renders
`null` instead of `{}`. Without it a field documented as always-null still appeared as `{}` in
the sample, contradicting the table directly above it.

Objects and arrays otherwise recurse the same way, with `$ref`s expanded inline and the
same per-branch circular-reference guard as the field table (independently implemented --
`build_example` doesn't reuse `build_schema_rows`'s traversal, so a change to one's
flattening logic doesn't silently change the other's payload shape).

## Design choices worth knowing before you extend the script

- **Tables, flattened by dotted path, for everything -- including nested bodies.**
  Markdown tables can't represent nesting directly, so depth is encoded in the `Field`
  column's path instead of indentation or sub-tables. This keeps every body to one table
  (easy to scan, easy to grep) at the cost of repeating a path prefix on every descendant
  row -- an accepted trade-off for a flat, appendix-free file.
- **No schemas appendix -- full inline expansion everywhere a schema is used.** A schema
  referenced by three different operations gets flattened into three different tables
  (and three different JSON examples) rather than defined once and linked to. This
  duplicates content across a tag file, but means every operation section is
  self-contained: a reader never has to jump to the bottom of the file to see what a
  field actually contains.
- **Per-branch cycle guard, not a global one.** `visited` is a set passed down through
  recursion, extended (not mutated) at each `$ref` hop, so it only prevents a schema from
  containing *itself* along one path -- it doesn't block the same schema from appearing
  fully expanded in two unrelated fields of the same body.
