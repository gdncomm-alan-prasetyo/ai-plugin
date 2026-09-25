#!/usr/bin/env python3
"""Convert an OpenAPI 3.0 YAML spec into human-readable Markdown, grouped by tag.

One Markdown file is written per tag (plus an index README). No external
dependencies beyond PyYAML.
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict

import yaml

HTTP_METHODS = ["get", "post", "put", "patch", "delete", "options", "head", "trace"]


def load_spec(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def slugify(text):
    """Approximate GitHub's heading-to-anchor algorithm."""
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9_\- ]", "", text)
    text = text.replace(" ", "-")
    return text


def ref_name(ref):
    return ref.rsplit("/", 1)[-1]


def resolve_ref(spec, ref):
    parts = ref.lstrip("#/").split("/")
    node = spec
    for part in parts:
        node = node[part]
    return node


def type_label(schema, fmt=None):
    t = schema.get("type", "object")
    fmt = fmt or schema.get("format")
    if fmt:
        return f"{t} ({fmt})"
    return t


def constraints_label(schema):
    parts = []
    if "enum" in schema:
        parts.append("one of: " + ", ".join(str(v) for v in schema["enum"]))
    if "default" in schema:
        parts.append(f"default: `{schema['default']}`")
    # Sits alongside `default`/`enum` as a stated value for the field. Matters
    # most for a response envelope pinned to one status, where `code`/`status`
    # carry a fixed value that would otherwise show as an empty Notes cell.
    if "example" in schema and not isinstance(schema["example"], (dict, list)):
        parts.append(f"example: `{schema['example']}`")
    if "minimum" in schema:
        parts.append(f"min {schema['minimum']}")
    if "maximum" in schema:
        parts.append(f"max {schema['maximum']}")
    if "minLength" in schema:
        parts.append(f"min length {schema['minLength']}")
    if "maxLength" in schema:
        parts.append(f"max length {schema['maxLength']}")
    # `minItems`/`maxItems` are the array-cardinality keywords (`minLength` is
    # the string one and says nothing about a list), so an array that bounds
    # its length has it recorded here or nowhere.
    if "minItems" in schema:
        parts.append(f"min {schema['minItems']} items")
    if "maxItems" in schema:
        parts.append(f"max {schema['maxItems']} items")
    if "pattern" in schema:
        parts.append(f"pattern: `{schema['pattern']}`")
    return "; ".join(parts)


def build_schema_rows(spec, schema):
    """Flatten a request/response body schema into table rows:
    (dotted field path, type label, required, description, constraints).
    Description and constraints stay in separate columns -- joining them
    produced cells like "...rather than failing.; example: `10001`", which
    reads badly and is not machine-separable. Objects get a row
    for the container plus one row per property (dotted path); arrays of
    objects/$refs get a `field[]` row for the item; every $ref is resolved
    and expanded inline (there's no appendix to link out to). A schema
    that refers back to itself along the same branch is cut off with a
    "circular" note instead of recursing forever -- tracked per branch
    (a `visited` set threaded through the recursion), not globally, so
    the same schema used in two unrelated fields is expanded fully both
    times.
    """
    rows = []
    _add_rows(spec, rows, "", schema, False, frozenset())
    return rows


def _add_rows(spec, rows, path, schema, required, visited):
    if "$ref" in schema:
        name = ref_name(schema["$ref"])
        if name in visited:
            rows.append((path or "(root)", f"`{name}` (circular — not expanded further)", required, "", ""))
            return
        resolved = resolve_ref(spec, schema["$ref"])
        _add_rows(spec, rows, path, resolved, required, visited | {name})
        return

    t = schema.get("type", "object")

    if t == "array":
        items = schema.get("items", {}) or {}
        item_ref = ref_name(items["$ref"]) if "$ref" in items else None
        resolved_items = resolve_ref(spec, items["$ref"]) if item_ref else items
        item_is_object = bool(resolved_items.get("properties"))
        # Same composition as the scalar branch at the bottom of this function:
        # an array field's own `description` is as much a part of its
        # documentation as a string field's, so don't drop it here.
        array_desc = schema.get("description") or ""
        array_constraints = constraints_label(schema)

        if item_is_object:
            label = f"array of `{item_ref}`" if item_ref else "array of object"
            if path:
                rows.append((path, label, required, array_desc, array_constraints))
            item_path = f"{path}[]" if path else "[]"
            if item_ref and item_ref in visited:
                rows.append((item_path, f"`{item_ref}` (circular — not expanded further)", False, "", ""))
            elif item_ref:
                # Skip an extra "path[] -> object" row here: the parent row
                # above already names the item type, so go straight to its
                # fields instead of repeating "object" with no new info.
                next_visited = visited | {item_ref}
                req_names = set(resolved_items.get("required") or [])
                for name, prop in (resolved_items.get("properties") or {}).items():
                    _add_rows(spec, rows, f"{item_path}.{name}", prop, name in req_names, next_visited)
            else:
                _add_rows(spec, rows, item_path, resolved_items, False, visited)
        else:
            inner = type_label(resolved_items) if resolved_items else "unknown"
            label = f"array of {inner}"
            rows.append((path or "(root)", label, required, array_desc, array_constraints))
        return

    if t == "object":
        props = schema.get("properties") or {}
        req_names = set(schema.get("required") or [])
        if path:
            rows.append((path, "object", required, schema.get("description") or "",
                         constraints_label(schema)))
        for name, prop in props.items():
            child_path = f"{path}.{name}" if path else name
            _add_rows(spec, rows, child_path, prop, name in req_names, visited)
        if not props and schema.get("additionalProperties") and path:
            rows.append((path + ".*", "any", False, "free-form object", ""))
        return

    rows.append((path or "(root)", type_label(schema), required,
                 schema.get("description") or "", constraints_label(schema)))


def cell(text):
    """Escape a value for use inside a Markdown table cell.

    An unescaped `|` ends the cell, so a description like
    "App type (`INTERNAL`|`EXTERNAL`)" or a `pattern: NAME|HOST` silently
    grows the row an extra column -- broken in GitHub's renderer and in any
    downstream converter. Backslash-escaping is the only fix that works
    inside backticks too, since GFM has no code-span exemption here.
    """
    return str(text).replace("|", "\\|")


def render_schema_table(rows):
    if not rows:
        return ["_No fields._"]
    lines = ["| Field | Type | Required | Description | Constraints |",
             "|---|---|---|---|---|"]
    for path, type_str, required, desc, constraints in rows:
        lines.append(
            f"| `{cell(path)}` | {cell(type_str)} | {'Yes' if required else 'No'} "
            f"| {cell(desc)} | {cell(constraints)} |")
    return lines


def build_example(spec, schema):
    """Build a plausible sample payload for a body schema, for embedding as
    a fenced ```json``` block. $refs are always expanded inline here
    (unlike build_schema_rows there's no notion of "the appendix already
    has it" -- an example needs real nested values to look like real JSON)
    with the same per-branch circular-reference guard.
    """
    try:
        return _build_example(spec, schema, frozenset())
    except RecursionError:
        return "<example omitted: schema nests too deeply>"


def _build_example(spec, schema, stack):
    if "$ref" in schema:
        name = ref_name(schema["$ref"])
        if name in stack:
            return f"<circular reference to {name}>"
        resolved = resolve_ref(spec, schema["$ref"])
        return _build_example(spec, resolved, stack | {name})

    # A schema that states its own value wins over one synthesised from its
    # members -- including `example: null`, which is the only way a spec can
    # say "this object is always null". Without this the object branch below
    # renders `{}`, which contradicts the field table sitting right above it.
    if "example" in schema:
        return schema["example"]
    if "default" in schema:
        return schema["default"]

    t = schema.get("type", "object")

    if t == "array":
        item = _build_example(spec, schema.get("items", {}), stack)
        return [item]

    if t == "object":
        props = schema.get("properties") or {}
        if not props:
            return {}
        return {name: _build_example(spec, prop, stack) for name, prop in props.items()}

    return _leaf_example(schema)


def _leaf_example(schema):
    if "example" in schema:
        return schema["example"]
    if "default" in schema:
        return schema["default"]
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]

    t = schema.get("type", "string")
    fmt = schema.get("format")
    if t == "string":
        if fmt == "date-time":
            return "2024-01-01T00:00:00Z"
        if fmt == "date":
            return "2024-01-01"
        if fmt == "uuid":
            return "3fa85f64-5717-4562-b3fc-2c963f66afa6"
        return "string"
    if t == "integer":
        return schema.get("minimum", 0)
    if t == "number":
        return schema.get("minimum", 0.0)
    if t == "boolean":
        return True
    return None


def explicit_example(media):
    """The example the spec states for this body, if it states one.

    OpenAPI lets a media type carry `example`, or `examples` as a named map.
    Either is authoritative -- a hand-written payload beats one synthesised
    from the schema, which is the whole reason for writing one. Returns a
    (found, value) pair so an explicit `null` is distinguishable from absence.
    """
    if not isinstance(media, dict):
        return False, None
    if "example" in media:
        return True, media["example"]
    examples = media.get("examples")
    if isinstance(examples, dict):
        for entry in examples.values():
            if isinstance(entry, dict) and "value" in entry:
                return True, entry["value"]
    return False, None


ENVELOPE_NOTE = (
    "Envelope fields {} are as described in [Response envelope](./README.md)."
)


def response_schemas(spec):
    """Every response body schema in the spec, in document order."""
    found = []
    for path_item in (spec.get("paths") or {}).values():
        for method in HTTP_METHODS:
            operation = path_item.get(method)
            if not operation:
                continue
            for response in (operation.get("responses") or {}).values():
                for media in (response.get("content") or {}).values():
                    schema = media.get("schema")
                    if schema:
                        found.append(schema)
    return found


def top_level_rows(rows):
    """Rows for direct members of the body -- no dots, no `[]`."""
    return [r for r in rows if "." not in r[0] and "[" not in r[0] and r[0] != "(root)"]


def detect_envelope(spec, min_count, forced=None):
    """Fields that every response repeats identically, worth documenting once.

    A response envelope is usually expressed by repeating the same properties
    on every response schema, with no `allOf` to key off -- so the only handle
    is the structural signature: same name, same type, same description, same
    constraints, in at least `min_count` distinct response schemas.

    Returns {name: (type, description, constraints)} in first-seen order.
    `data` is never a candidate: it is the payload, and its description and
    type are exactly what differs per operation.
    """
    schemas = response_schemas(spec)
    if len(schemas) < min_count:
        return {}

    seen = defaultdict(lambda: defaultdict(int))
    order = []
    for schema in schemas:
        for name, type_str, _req, desc, constraints in top_level_rows(build_schema_rows(spec, schema)):
            if name == "data":
                continue
            if name not in seen:
                order.append(name)
            seen[name][(type_str, desc, constraints)] += 1

    envelope = {}
    for name in order:
        if forced is not None and name not in forced:
            continue
        signature, count = max(seen[name].items(), key=lambda kv: kv[1])
        if count >= min_count:
            envelope[name] = signature
    return envelope


def collapse_envelope(rows, envelope):
    """Drop rows the envelope already documents identically.

    A field is only dropped when its whole signature matches the canonical
    one. That override rule is what keeps this honest: in a typical spec
    `code` and `status` carry per-status examples (`200`/`OK` on success,
    `403`/`FORBIDDEN` on the error schema), so collapsing them by name alone
    would tell a reader the 500 response returns `code: 200`. Those rows
    differ, so they stay.

    Children of a dropped field go with it -- keeping `paging.page` after
    dropping `paging` would leave an orphan.
    """
    if not envelope:
        return rows, []

    dropped = []
    for name, type_str, _req, desc, constraints in top_level_rows(rows):
        if envelope.get(name) == (type_str, desc, constraints):
            dropped.append(name)
    if not dropped:
        return rows, []

    child_prefixes = tuple(f"{p}." for p in dropped) + tuple(f"{p}[" for p in dropped)
    kept = [r for r in rows
            if r[0] not in dropped and not r[0].startswith(child_prefixes)]
    return kept, dropped


def render_body_block(spec, schema, media=None, envelope=None):
    """Render the merged schema-table + JSON-example block for a body."""
    rows = build_schema_rows(spec, schema)
    rows, dropped = collapse_envelope(rows, envelope or {})
    lines = list(render_schema_table(rows))
    if dropped:
        lines.append("")
        lines.append(ENVELOPE_NOTE.format(", ".join(f"`{d}`" for d in dropped)))
    lines.append("")
    found, example = explicit_example(media)
    if not found:
        example = build_example(spec, schema)
    # The sample is never collapsed. Trimming the table removes repetition a
    # reader can look up; trimming the sample would produce a payload that is
    # not a payload.
    lines.append("```json")
    lines.append(json.dumps(example, indent=2, ensure_ascii=False))
    lines.append("```")
    return lines


def render_parameters_table(parameters):
    if not parameters:
        return []
    lines = [
        "| Name | In | Type | Required | Description | Constraints |",
        "|---|---|---|---|---|---|",
    ]
    for p in parameters:
        schema = p.get("schema", {})
        lines.append(
            f"| `{cell(p['name'])}` | {cell(p.get('in', ''))} | {cell(type_label(schema))} | "
            f"{'Yes' if p.get('required') else 'No'} | {cell(p.get('description') or '')} "
            f"| {cell(constraints_label(schema))} |"
        )
    return lines


def render_operation(spec, method, path, operation, envelope=None):
    method_upper = method.upper()
    summary = operation.get("summary", "")
    heading = f"{method_upper} {path}"
    if summary:
        heading += f" — {summary}"

    lines = [f"## {heading}", ""]

    description = operation.get("description")
    if description:
        lines.append(description)
        lines.append("")

    op_id = operation.get("operationId")
    if op_id:
        lines.append(f"_Operation ID: `{op_id}`_")
        lines.append("")

    params = operation.get("parameters")
    if params:
        # Parameters may be $ref'd into components/parameters (common for params that a
        # global interceptor requires on every operation, rather than declared per-method).
        params = [resolve_ref(spec, p["$ref"]) if "$ref" in p else p for p in params]
        lines.append("### Parameters")
        lines.append("")
        lines.extend(render_parameters_table(params))
        lines.append("")

    request_body = operation.get("requestBody")
    if request_body:
        required = request_body.get("required", False)
        content = request_body.get("content", {})
        schema = media = None
        for media_type in ("application/json", *content.keys()):
            if media_type in content:
                media = content[media_type]
                schema = media.get("schema")
                break
        lines.append("### Request body")
        lines.append("")
        lines.append(f"_{'Required' if required else 'Optional'}._")
        lines.append("")
        if schema:
            # A request body is the operation's own payload, never the shared
            # envelope -- pass no envelope so nothing is collapsed out of it.
            lines.extend(render_body_block(spec, schema, media))
        lines.append("")

    responses = operation.get("responses") or {}
    for status, response in responses.items():
        # Descriptive text goes under the heading, not in it: a reworded
        # description must not move the anchor.
        lines.append(f"### Response {status}")
        lines.append("")
        desc = response.get("description", "")
        if desc:
            lines.append(desc)
            lines.append("")
        content = response.get("content") or {}
        schema = media = None
        for media_type in ("application/json", *content.keys()):
            if media_type in content:
                media = content[media_type]
                schema = media.get("schema")
                break
        if schema:
            lines.extend(render_body_block(spec, schema, media, envelope))
        else:
            lines.append("No response body.")
        lines.append("")

    lines.append("---")
    lines.append("")
    return lines


def build_tag_index(spec):
    """Return {tag_name: [(path, method, operation), ...]} in path order."""
    by_tag = defaultdict(list)
    for path, path_item in (spec.get("paths") or {}).items():
        for method in HTTP_METHODS:
            operation = path_item.get(method)
            if not operation:
                continue
            tags = operation.get("tags") or ["Untagged"]
            for tag in tags:
                by_tag[tag].append((path, method, operation))
    return by_tag


def provenance(source_path):
    """One stable line -- deliberately no date and no commit sha.

    These files are published to Confluence behind a content checksum. A
    timestamp would change that checksum on every run, so every regeneration
    would rewrite every page and `unchanged` would never be reported again.
    Provenance that costs you change detection is not worth having; git
    already carries the history.
    """
    return (f"> Generated by `docs-openapi-to-markdown` from `{source_path}`. "
            f"Do not hand-edit — regenerate instead.")


def render_tag_file(spec, tag_name, tag_description, operations, source_path, envelope=None):
    lines = [f"# {tag_name} API", ""]
    if tag_description:
        lines.append(tag_description)
        lines.append("")
    lines.append(provenance(source_path))
    lines.append("")

    lines.append("## Endpoints")
    lines.append("")
    lines.append("| Method | Path | Summary |")
    lines.append("|---|---|---|")
    for path, method, operation in operations:
        summary = operation.get("summary", "")
        heading = f"{method.upper()} {path}"
        if summary:
            heading += f" — {summary}"
        anchor = slugify(heading)
        lines.append(f"| {method.upper()} | `{path}` | [{summary or '—'}](#{anchor}) |")
    lines.append("")
    lines.append("---")
    lines.append("")

    for path, method, operation in operations:
        lines.extend(render_operation(spec, method, path, operation, envelope))

    return "\n".join(lines).rstrip() + "\n"


def render_index(tag_files, source_path, info=None, servers=None, envelope=None):
    lines = ["# API Documentation", ""]
    description = (info or {}).get("description")
    if description:
        lines.append(description.strip())
        lines.append("")
    lines.append(provenance(source_path))
    lines.append("")

    if envelope:
        lines.append("## Response envelope")
        lines.append("")
        lines.append(
            "Every response below is wrapped in a shared envelope. This table is the shape "
            "most of them use; an operation that points here uses exactly this. Operations "
            "list their own `data` payload, and any envelope field that differs for that "
            "response is documented in the operation's own table instead — so a response "
            "showing its own `code` row means that row, not this one, is authoritative."
        )
        lines.append("")
        lines.append("| Field | Type | Description | Constraints |")
        lines.append("|---|---|---|---|")
        for name, (type_str, desc, constraints) in envelope.items():
            lines.append(f"| `{cell(name)}` | {cell(type_str)} | {cell(desc)} "
                         f"| {cell(constraints)} |")
        lines.append("")

    # `servers` lives only in the spec root, so no per-tag file has anywhere to
    # put it -- the index is the one place a reader can find out where to send
    # the requests the rest of these docs describe.
    if servers:
        lines.append("## Servers")
        lines.append("")
        lines.append("| Environment | URL |")
        lines.append("|---|---|")
        for server in servers:
            env = server.get("description") or ""
            lines.append(f"| {cell(env)} | `{cell(server.get('url', ''))}` |")
        lines.append("")

    lines.append("## Endpoints by tag")
    lines.append("")
    lines.append("| Tag | Endpoints | File |")
    lines.append("|---|---|---|")
    for tag_name, filename, count in tag_files:
        lines.append(f"| {cell(tag_name)} | {count} | [{filename}](./{filename}) |")
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input", nargs="?", default="docs/openapi/openapi.yaml", help="Path to the OpenAPI YAML spec"
    )
    parser.add_argument(
        "--output-dir", default="docs/api", help="Directory to write per-tag Markdown files into"
    )
    parser.add_argument(
        "--no-envelope-collapse", action="store_true",
        help="document every envelope field on every response instead of hoisting the "
             "identical ones into a single 'Response envelope' section in the index",
    )
    parser.add_argument(
        "--envelope-min", type=int, default=3, metavar="N",
        help="a field must repeat identically across at least N response schemas to count "
             "as part of the envelope (default 3)",
    )
    parser.add_argument(
        "--envelope-fields", default=None, metavar="a,b,c",
        help="restrict envelope detection to these field names, for a spec whose shape the "
             "detector reads wrongly",
    )
    args = parser.parse_args()

    spec = load_spec(args.input)
    tag_descriptions = {t["name"]: t.get("description", "") for t in spec.get("tags", [])}
    by_tag = build_tag_index(spec)

    if not by_tag:
        print("No operations found in spec.", file=sys.stderr)
        return 1

    envelope = {}
    if not args.no_envelope_collapse:
        forced = None
        if args.envelope_fields:
            forced = {f.strip() for f in args.envelope_fields.split(",") if f.strip()}
        envelope = detect_envelope(spec, args.envelope_min, forced)
        if envelope:
            print("envelope fields hoisted to the index: "
                  + ", ".join(envelope), file=sys.stderr)

    os.makedirs(args.output_dir, exist_ok=True)

    tag_files = []
    skipped_tags = [t for t in tag_descriptions if t not in by_tag]
    for tag_name in sorted(by_tag):
        operations = by_tag[tag_name]
        filename = slugify(tag_name) + ".md"
        content = render_tag_file(spec, tag_name, tag_descriptions.get(tag_name, ""),
                                  operations, args.input, envelope)
        out_path = os.path.join(args.output_dir, filename)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(content)
        tag_files.append((tag_name, filename, len(operations)))
        print(f"wrote {out_path} ({len(operations)} endpoints)", file=sys.stderr)

    index_path = os.path.join(args.output_dir, "README.md")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(render_index(tag_files, args.input, spec.get("info"),
                             spec.get("servers"), envelope))
    print(f"wrote {index_path}", file=sys.stderr)

    if skipped_tags:
        print(
            f"warning: tags declared with no operations, skipped: {', '.join(skipped_tags)}",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
