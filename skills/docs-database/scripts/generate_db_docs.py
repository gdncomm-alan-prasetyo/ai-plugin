#!/usr/bin/env python3
"""
Generates docs/database/*.md (one file per collection/table, plus a README.md index with
a Mermaid entity-relationship diagram) from Java persistence-model source, using pure
static text analysis -- no running app, no build tools, no DB connection.

Recognizes two annotation families:
  - Spring Data MongoDB: @Document, @Id, @Field, @Indexed, @CompoundIndex(es), @DBRef,
    @Transient, @Version, @CreatedDate/@LastModifiedDate/@CreatedBy/@LastModifiedBy.
  - JPA/Hibernate: @Entity, @Table, @Column, @Id, @OneToMany/@ManyToOne/@OneToOne/
    @ManyToMany, @JoinColumn, @Transient, @Version.

This is a regex + bracket-depth scanner, not a real Java parser -- see SKILL.md for its
known heuristics and blind spots (most importantly: it only understands Java, and its
"soft reference" detection is a naming-convention guess that must be verified by eye).
"""
import argparse
import json
import re
import sys
from pathlib import Path

SKIP_DIRS = {".git", "target", "build", "node_modules", "out", "dist"}
TEST_SOURCE_MARKERS = ("/test/", "\\test\\", "/integrationtest/", "\\integrationtest\\",
                        "/generated-test-sources/", "\\generated-test-sources\\")

MODIFIER_RE = re.compile(r'^\s*(private|public|protected|static|final|transient|volatile)\b')
ANNOTATION_RE = re.compile(r'^\s*@(\w+(?:\.\w+)*)((?:\([^()]*(?:\([^()]*\)[^()]*)*\))?)')
CLASS_RE = re.compile(
    r'\bclass\s+(\w+)(?:\s*<[^{}]*?>)?(?:\s+extends\s+([\w.]+)(?:<[^{}]*?>)?)?'
    r'(?:\s+implements\s+([\w.,\s<>]+?))?\s*\{'
)
HIERARCHY_PREFIXES = ("children", "child", "parents", "parent")
COLLECTION_TYPE_RE = re.compile(r'^(?:List|Set|Collection|SortedSet|LinkedHashSet)\s*<\s*(\w+)\s*>$')

warnings = []


def warn(msg):
    warnings.append(msg)
    print(f"WARNING: {msg}", file=sys.stderr)


def is_test_source(path_str):
    lower = path_str.lower()
    return any(m in lower for m in TEST_SOURCE_MARKERS) or "test" in Path(path_str).stem.lower()


def discover_java_files(root, include_tests=False):
    for p in sorted(root.rglob("*.java")):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if not include_tests and is_test_source(str(p)):
            continue
        yield p


def skip_literal(text, i):
    q = text[i]
    i += 1
    n = len(text)
    while i < n:
        if text[i] == '\\':
            i += 2
            continue
        if text[i] == q:
            return i + 1
        i += 1
    return n


def find_matching_brace(text, open_idx):
    """text[open_idx] must be '{'. Returns index of its matching '}'."""
    depth = 0
    i = open_idx
    n = len(text)
    while i < n:
        c = text[i]
        if c in '"\'':
            i = skip_literal(text, i)
            continue
        if text[i:i + 2] == '//':
            j = text.find('\n', i)
            i = n if j < 0 else j
            continue
        if text[i:i + 2] == '/*':
            j = text.find('*/', i + 2)
            i = n if j < 0 else j + 2
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return n - 1


def iter_field_candidates(body):
    """Yields raw top-level statement text (fields, or junk to be filtered later) -- any
    top-level statement that opened a brace block (a method/constructor/initializer) is
    consumed and discarded, never yielded."""
    i, n = 0, len(body)
    depth = 0
    buf = []
    saw_block = False
    while i < n:
        c = body[i]
        if c in '"\'':
            j = skip_literal(body, i)
            buf.append(body[i:j])
            i = j
            continue
        if body[i:i + 2] == '//':
            j = body.find('\n', i)
            j = n if j < 0 else j
            i = j
            continue
        if body[i:i + 2] == '/*':
            j = body.find('*/', i + 2)
            j = n if j < 0 else j + 2
            i = j
            continue
        if c in '([{':
            if c == '{':
                saw_block = True
            depth += 1
            buf.append(c)
            i += 1
            continue
        if c in ')]}':
            depth -= 1
            buf.append(c)
            i += 1
            if depth == 0 and c == '}':
                buf = []
                saw_block = False
            continue
        if c == ';' and depth == 0:
            chunk = ''.join(buf).strip()
            buf = []
            local_saw_block = saw_block
            saw_block = False
            if chunk and not local_saw_block:
                yield chunk
            i += 1
            continue
        buf.append(c)
        i += 1


def strip_modifiers(text):
    while True:
        m = MODIFIER_RE.match(text)
        if not m:
            return text.lstrip()
        text = text[m.end():]


def split_type_and_name(decl):
    depth = 0
    last_space = -1
    for idx, ch in enumerate(decl):
        if ch == '<':
            depth += 1
        elif ch == '>':
            depth -= 1
        elif ch == ' ' and depth == 0:
            last_space = idx
    if last_space == -1:
        return None, None
    return decl[:last_space].strip(), decl[last_space + 1:].strip()


def parse_annotations(text):
    """Repeatedly strips leading @Annotation(...) from text. Returns (annotations, rest)
    where annotations is a list of (name, raw_args_including_parens_or_empty)."""
    annotations = []
    while True:
        m = ANNOTATION_RE.match(text)
        if not m:
            return annotations, text.lstrip()
        annotations.append((m.group(1), m.group(2) or ""))
        text = text[m.end():]


def parse_field_candidate(chunk):
    annotations, rest = parse_annotations(chunk)
    if re.match(r'^\s*(?:\w+\s+)*static\b', rest):
        return None  # static fields are class-level constants, never persisted instance data
    rest = strip_modifiers(rest)
    # split off initializer at the first top-level '='
    depth = 0
    eq_idx = -1
    for idx, ch in enumerate(rest):
        if ch in '<([':
            depth += 1
        elif ch in '>)]':
            depth -= 1
        elif ch == '=' and depth <= 0:
            eq_idx = idx
            break
    decl = rest[:eq_idx] if eq_idx != -1 else rest
    decl = decl.strip()
    if not decl:
        return None
    field_type, name = split_type_and_name(decl)
    if not field_type or not name or not re.match(r'^\w+$', name):
        return None
    return {"annotations": annotations, "type": field_type, "name": name}


def annotation_arg(raw_args, key):
    m = re.search(rf'{key}\s*=\s*"([^"]*)"', raw_args)
    if m:
        return m.group(1)
    m = re.search(rf'{key}\s*=\s*(true|false)', raw_args)
    if m:
        return m.group(1) == "true"
    return None


def find_class_level_annotations(prefix_text):
    """Finds @Document/@Entity/@Table/@CompoundIndex(es) occurring anywhere before the
    class keyword (i.e. after imports -- the only place they can legally be in Java)."""
    found = []
    i = 0
    n = len(prefix_text)
    while i < n:
        m = re.compile(r'@(\w+(?:\.\w+)*)').search(prefix_text, i)
        if not m:
            break
        name = m.group(1)
        start = m.end()
        args = ""
        j = start
        while j < n and prefix_text[j] in " \t\n":
            j += 1
        if j < n and prefix_text[j] == '(':
            depth = 0
            k = j
            while k < n:
                if prefix_text[k] == '(':
                    depth += 1
                elif prefix_text[k] == ')':
                    depth -= 1
                    if depth == 0:
                        k += 1
                        break
                k += 1
            args = prefix_text[j:k]
            i = k
        else:
            i = start
        found.append((name, args))
    return found


def parse_file(path, root):
    text = path.read_text(encoding="utf-8", errors="replace")
    m = CLASS_RE.search(text)
    if not m:
        return None
    class_name = m.group(1)
    extends = m.group(2)
    open_brace = m.end() - 1
    close_brace = find_matching_brace(text, open_brace)
    body = text[open_brace + 1:close_brace]
    prefix = text[:m.start()]
    class_annotations = find_class_level_annotations(prefix)

    fields = []
    for chunk in iter_field_candidates(body):
        f = parse_field_candidate(chunk)
        if f:
            fields.append(f)

    return {
        "class_name": class_name,
        "extends": extends,
        "annotations": class_annotations,
        "fields": fields,
        "file": str(path.relative_to(root)).replace("\\", "/"),
        "body": body,
    }


def resolve_local_constant(body_text, expr):
    """expr is a non-literal @Document/@Table argument value like 'Foo.COLLECTION_NAME' or
    a bare 'COLLECTION_NAME' -- looks for a 'static final String NAME = "value";' field
    declared in the same class body (the common idiom for this). Doesn't chase constants
    defined in a different class/file -- flag those as unresolved instead of guessing."""
    const_name = expr.strip().split(".")[-1]
    m = re.search(rf'static\s+final\s+String\s+{re.escape(const_name)}\s*=\s*"([^"]*)"', body_text)
    return m.group(1) if m else None


def collection_or_table_name(cls):
    ann_names = {n: a for n, a in cls["annotations"]}
    if "Document" in ann_names:
        name = annotation_arg(ann_names["Document"], "collection")
        if name:
            return name, "mongodb"
        m = re.search(r'collection\s*=\s*([\w.]+)', ann_names["Document"])
        if m:
            resolved = resolve_local_constant(cls["body"], m.group(1))
            if resolved:
                return resolved, "mongodb"
            warn(f"{cls['class_name']} ({cls['file']}): @Document(collection = {m.group(1)}) references a "
                 f"constant that couldn't be resolved (not a local 'static final String' in this class) -- "
                 f"defaulting to decapitalized class name, which is likely WRONG. Verify by hand.")
        default = cls["class_name"][0].lower() + cls["class_name"][1:]
        return default, "mongodb"
    if "Entity" in ann_names:
        if "Table" in ann_names:
            name = annotation_arg(ann_names["Table"], "name")
            if name:
                return name, "jpa"
        warn(f"{cls['class_name']} ({cls['file']}): @Entity with no explicit @Table(name=...) -- "
             f"assumed table name '{cls['class_name']}', but Hibernate's naming strategy may "
             f"convert this (e.g. to snake_case) -- verify against actual DB/migration scripts.")
        return cls["class_name"], "jpa"
    return None, None


def is_persisted_root(cls):
    ann_names = {n for n, _ in cls["annotations"]}
    return "Document" in ann_names or "Entity" in ann_names


def resolve_inherited_fields(cls, classes_by_name, seen=None):
    """Walks the extends chain (only through classes found in this scan) and returns the
    full field list: ancestor fields first (marked inherited), then this class's own."""
    seen = seen or set()
    if cls["class_name"] in seen:
        return []
    seen.add(cls["class_name"])
    fields = []
    if cls["extends"]:
        parent = classes_by_name.get(cls["extends"].split(".")[-1])
        if parent:
            for pf in resolve_inherited_fields(parent, classes_by_name, seen):
                fields.append({**pf, "inherited_from": pf.get("inherited_from") or parent["class_name"]})
        else:
            warn(f"{cls['class_name']} ({cls['file']}): extends '{cls['extends']}', which wasn't "
                 f"found among scanned files -- its fields (if any) are not reflected below.")
    for f in cls["fields"]:
        fields.append({**f})
    return fields


def field_notes(f, classes_by_slug):
    ann_names = {n: a for n, a in f["annotations"]}
    notes = []
    if f.get("inherited_from"):
        notes.append(f"inherited from `{f['inherited_from']}`")
    if "Id" in ann_names:
        notes.append("**primary key**")
    if "Version" in ann_names:
        notes.append("optimistic-lock version")
    if "Transient" in ann_names:
        notes.append("not persisted")
    if "CreatedDate" in ann_names or "LastModifiedDate" in ann_names or \
       "CreatedBy" in ann_names or "LastModifiedBy" in ann_names:
        notes.append("audit metadata (auto-managed)")
    if "Indexed" in ann_names:
        notes.append("unique index" if annotation_arg(ann_names["Indexed"], "unique") else "indexed")
    if "Column" in ann_names:
        nullable = annotation_arg(ann_names["Column"], "nullable")
        if nullable is False:
            notes.append("required (not-null column)")
    for rel_ann in ("DBRef", "OneToMany", "ManyToOne", "OneToOne", "ManyToMany"):
        if rel_ann in ann_names:
            target = resolve_relation_target(f["type"])
            cardinality = {
                "DBRef": "reference",
                "OneToMany": "one-to-many",
                "ManyToOne": "many-to-one",
                "OneToOne": "one-to-one",
                "ManyToMany": "many-to-many",
            }[rel_ann]
            notes.append(f"**hard reference** ({cardinality}) -> `{target}`")
    return notes


def resolve_relation_target(field_type):
    m = COLLECTION_TYPE_RE.match(field_type)
    return m.group(1) if m else field_type


SIMPLE_STRING_TYPES = {"String"}


def is_scalar_string(t):
    return t in SIMPLE_STRING_TYPES


def is_string_collection(t):
    m = COLLECTION_TYPE_RE.match(t)
    return bool(m) and m.group(1) in SIMPLE_STRING_TYPES


def entity_slug(class_name):
    return class_name[0].lower() + class_name[1:]


def _match_slug(candidates, roots_by_slug):
    for cand in candidates:
        for slug in roots_by_slug:
            if slug.lower() == cand.lower():
                return slug
    return None


def find_soft_references(entity_name, fields, roots_by_slug):
    """Naming-convention heuristics for unenforced references (no @DBRef/@JoinColumn):

    High confidence: a String/collection-of-String field named '<otherEntity>Name' /
    '<otherEntity>Names' (optionally prefixed with a hierarchy word like 'children') --
    e.g. `appName` -> App, `roleNames` -> Role, `childrenRoleNames` -> Role (self).

    Low confidence: a collection-of-String field whose bare name is just the plural of
    another entity's slug, with no 'Name'/'Names' suffix at all -- e.g. `roles` (Set<String>)
    on UserRole almost certainly holds Role names, but the field name alone doesn't say so
    as clearly. Flagged separately so it gets extra scrutiny before being trusted.
    """
    results = []
    for f in fields:
        if f.get("inherited_from"):
            continue
        name = f["name"]
        is_scalar = is_scalar_string(f["type"])
        is_plural_collection = is_string_collection(f["type"])
        if not (is_scalar or is_plural_collection):
            continue

        matched_slug = None
        confidence = None
        stripped = None
        if name.lower().endswith("names"):
            stripped = name[:-5]
        elif name.lower().endswith("name"):
            stripped = name[:-4]
        if stripped:
            candidates = [stripped]
            low = stripped.lower()
            for prefix in HIERARCHY_PREFIXES:
                if low.startswith(prefix) and len(low) > len(prefix):
                    candidates.append(stripped[len(prefix):])
            matched_slug = _match_slug(candidates, roots_by_slug)
            confidence = "high"

        if not matched_slug and is_plural_collection:
            bare_candidates = []
            if name.lower().endswith("es"):
                bare_candidates.append(name[:-2])
            if name.lower().endswith("s"):
                bare_candidates.append(name[:-1])
            matched_slug = _match_slug(bare_candidates, roots_by_slug)
            confidence = "low"

        if not matched_slug:
            continue
        is_self = matched_slug.lower() == entity_name.lower()
        many = is_plural_collection or (stripped is not None and name.lower().endswith("names"))
        results.append({
            "field": name,
            "target_slug": matched_slug,
            "self": is_self,
            "many": many,
            "confidence": confidence,
        })
    return results


def to_snake_upper(name):
    s = re.sub(r'(?<!^)(?=[A-Z])', '_', name)
    return s.upper()


def build_mermaid(roots, soft_refs_by_entity, hard_refs_by_entity):
    lines = ["erDiagram"]
    seen_edges = set()
    connected = set()

    def add_edge(a, b, left, right, label):
        key = (a, b, label)
        if key in seen_edges:
            return
        seen_edges.add(key)
        connected.add(a)
        connected.add(b)
        lines.append(f"    {to_snake_upper(a)} {left}--{right} {to_snake_upper(b)} : \"{label}\"")

    for name, refs in hard_refs_by_entity.items():
        for r in refs:
            card = r["cardinality"]
            if card in ("many-to-one", "reference"):
                add_edge(r["target"], name, "||", "o{", f"{r['field']} ({card})")
            elif card == "one-to-many":
                add_edge(name, r["target"], "||", "o{", f"{r['field']} ({card})")
            elif card == "one-to-one":
                add_edge(name, r["target"], "||", "||", f"{r['field']} ({card})")
            elif card == "many-to-many":
                add_edge(name, r["target"], "}o", "o{", f"{r['field']} ({card})")

    for name, refs in soft_refs_by_entity.items():
        for r in refs:
            conf = ", low-confidence" if r.get("confidence") == "low" else ""
            label = f"{r['field']} (soft" + (f", hierarchy{conf})" if r["self"] else f"{conf})")
            if r["self"]:
                add_edge(name, name, "||", "o{", label)
            elif r["many"]:
                add_edge(name, r["target_slug"], "}o", "o{", label)
            else:
                add_edge(r["target_slug"], name, "||", "o{", label)

    orphans = [n for n in roots if n not in connected]
    return "\n".join(lines), orphans


def slugify(name):
    return re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')


def cell(text):
    """Escape a value for a Markdown table cell.

    An unescaped `|` ends the cell early, growing the row a column. It breaks
    GitHub's renderer and the Confluence converter merges the surplus into the
    last column with a warning. A preserved hand-written Purpose sentence is
    the most likely source of one here.
    """
    return str(text).replace("|", "\\|")


PURPOSE_PLACEHOLDER = (
    "_TODO: one or two sentences on what this collection represents and when a document is "
    "created and removed. This section is preserved across regeneration -- see the "
    "`docs-database` skill, step 5._"
)

# H2 sections a person or agent fills in that the generator must not destroy.
# Everything else in the file is rebuilt from source on every run.
PRESERVED_SECTIONS = ("Purpose", "Query shapes", "Notes")

_H2_RE = re.compile(r'^##\s+(.*?)\s*$', re.M)


def harvest_sections(path, names):
    """Read back the H2 sections of an existing generated file.

    A generator that overwrites its own output destroys anything a human
    added to it. The sections listed in PRESERVED_SECTIONS exist precisely
    because static analysis cannot produce them, so they have to survive the
    next run or asking for them is pointless.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}

    found = {}
    matches = list(_H2_RE.finditer(text))
    for i, m in enumerate(matches):
        title = m.group(1).strip()
        if title not in names:
            continue
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.end():end].strip()
        if body and body != PURPOSE_PLACEHOLDER:
            found[title] = body
    return found


def first_sentence(text):
    """First sentence of a Purpose body, for the index's summary column."""
    if not text:
        return ""
    text = " ".join(text.split())
    m = re.search(r'(.+?[.!?])(\s|$)', text)
    return (m.group(1) if m else text).strip()


def render_collection_doc(name, kind, cls, all_fields, soft_refs, incoming_soft, hard_refs,
                          incoming_hard, classes_by_slug, preserved=None):
    preserved = preserved or {}
    noun = "collection" if kind == "mongodb" else "table"
    lines = [f"# `{name}` {noun}", ""]
    lines.append("> Generated by `docs-database` from "
                 f"`{cls['file']}`. Do not hand-edit except the sections marked as preserved "
                 "-- regenerate instead.")
    lines.append("")
    lines.append(f"Backing class: `{cls['class_name']}` (`{cls['file']}`)"
                 + (f", extends `{cls['extends']}`" if cls['extends'] else "") + ".")
    lines.append("")

    lines.append("## Purpose")
    lines.append("")
    lines.append(preserved.get("Purpose") or PURPOSE_PLACEHOLDER)
    lines.append("")

    lines.append("## Fields")
    lines.append("")
    lines.append("| Field | Type | Notes |")
    lines.append("|---|---|---|")
    for f in all_fields:
        notes = "; ".join(field_notes(f, classes_by_slug))
        lines.append(f"| `{cell(f['name'])}` | `{cell(f['type'])}` | {cell(notes)} |")
    lines.append("")

    # Always emitted, even when empty. A missing section cannot be told apart
    # from a section nobody looked at; an explicit "none" is an answer.
    lines.append("## Relations")
    lines.append("")
    rel_rows = []
    for r in hard_refs:
        rel_rows.append(("references", r["target"], r["field"], r["cardinality"],
                         "hard", "certain"))
    for r in soft_refs:
        card = "self-referential" if r["self"] else ("many-to-many" if r["many"] else "many-to-one")
        rel_rows.append(("references", r["target_slug"], r["field"], card,
                         "soft", r.get("confidence") or "low"))
    for r in incoming_hard:
        rel_rows.append(("referenced by", r["from"], r["field"], r["cardinality"],
                         "hard", "certain"))
    for r in incoming_soft:
        rel_rows.append(("referenced by", r["from"], r["field"], "",
                         "soft", r.get("confidence") or "low"))

    if rel_rows:
        lines.append(f"| Direction | Related {noun} | Via field | Cardinality | Kind | Confidence |")
        lines.append("|---|---|---|---|---|---|")
        for direction, target, field, card, kindtag, conf in rel_rows:
            lines.append(f"| {direction} | `{cell(target)}` | `{cell(field)}` | {cell(card)} "
                         f"| {kindtag} | {conf} |")
        lines.append("")
        if any(r[4] == "soft" for r in rel_rows):
            lines.append("A soft relation is by value and is not enforced by the database. "
                         "`certain` means an annotation declares it; `high` means it was "
                         "inferred and corroborated; `low` means it was inferred from naming "
                         "alone -- verify before relying on it.")
            lines.append("")
    else:
        lines.append(f"No relation to another {noun} was detected -- no reference annotation on "
                     f"`{cls['class_name']}`, and no field name matches another "
                     f"{noun} in this schema. A relation carried purely in application code "
                     "would not be visible here.")
        lines.append("")

    lines.append("## Indexes")
    lines.append("")
    indexes = []
    for f in all_fields:
        ann_names = {n: a for n, a in f["annotations"]}
        if "Indexed" in ann_names:
            unique = annotation_arg(ann_names["Indexed"], "unique")
            indexes.append(f"- `{f['name']}`" + (" (unique)" if unique else ""))
    compound = [a for n, a in cls["annotations"] if n == "CompoundIndex"]
    for args in compound:
        d = annotation_arg(args, "def")
        unique = annotation_arg(args, "unique")
        if d:
            indexes.append(f"- compound: `{d}`" + (" (unique)" if unique else ""))
    if indexes:
        lines.extend(indexes)
    else:
        lines.append(f"No index is declared in code for this {noun} -- no `@Indexed` or "
                     f"`@CompoundIndex` on `{cls['class_name']}`. Any index that exists was "
                     "created outside this repository.")
    lines.append("")

    for title in PRESERVED_SECTIONS:
        if title == "Purpose" or title not in preserved:
            continue
        lines.append(f"## {title}")
        lines.append("")
        lines.append(preserved[title])
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--output-dir", default="docs/database")
    ap.add_argument("--title", default="Database Schema")
    ap.add_argument("--include-tests", action="store_true")
    ap.add_argument("--no-preserve", action="store_true",
                    help="regenerate from scratch, discarding the hand-written sections "
                         "(Purpose, Query shapes, Notes) carried over from a previous run")
    ap.add_argument("--warnings-json")
    args = ap.parse_args()

    root = Path(args.path).resolve()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    classes_by_name = {}
    for f in discover_java_files(root, include_tests=args.include_tests):
        parsed = parse_file(f, root)
        if parsed:
            classes_by_name[parsed["class_name"]] = parsed

    roots = {name: c for name, c in classes_by_name.items() if is_persisted_root(c)}
    if not roots:
        warn("No @Document or @Entity classes found under the given path.")

    roots_by_slug = {entity_slug(name): name for name in roots}

    entity_data = {}
    for class_name, cls in roots.items():
        table_name, kind = collection_or_table_name(cls)
        all_fields = resolve_inherited_fields(cls, classes_by_name)
        entity_data[class_name] = {
            "table_name": table_name, "kind": kind, "cls": cls, "fields": all_fields,
        }

    slug_to_table = {entity_slug(n): d["table_name"] for n, d in entity_data.items()}
    table_to_class = {d["table_name"]: n for n, d in entity_data.items()}

    soft_refs_by_entity = {}
    for class_name, data in entity_data.items():
        slug = entity_slug(class_name)
        refs = find_soft_references(slug, data["fields"], roots_by_slug)
        for r in refs:
            r["target_slug"] = slug_to_table.get(r["target_slug"], r["target_slug"])
        soft_refs_by_entity[class_name] = refs

    incoming_soft = {name: [] for name in entity_data}
    for class_name, refs in soft_refs_by_entity.items():
        for r in refs:
            target_class = table_to_class.get(r["target_slug"])
            if target_class and target_class in incoming_soft:
                incoming_soft[target_class].append({
                    "from": entity_data[class_name]["table_name"], "field": r["field"],
                    "confidence": r.get("confidence"),
                })

    hard_refs_by_entity = {name: [] for name in entity_data}
    incoming_hard = {name: [] for name in entity_data}
    for class_name, data in entity_data.items():
        for f in data["fields"]:
            if f.get("inherited_from"):
                continue
            ann_names = {n for n, _ in f["annotations"]}
            rel_ann = next((a for a in ("DBRef", "OneToMany", "ManyToOne", "OneToOne", "ManyToMany") if a in ann_names), None)
            if not rel_ann:
                continue
            target_type = resolve_relation_target(f["type"])
            cardinality = {
                "DBRef": "reference", "OneToMany": "one-to-many", "ManyToOne": "many-to-one",
                "OneToOne": "one-to-one", "ManyToMany": "many-to-many",
            }[rel_ann]
            target_class = target_type if target_type in entity_data else None
            if not target_class:
                warn(f"{class_name}.{f['name']}: {rel_ann} target type '{target_type}' isn't among "
                     f"the scanned @Document/@Entity classes -- relation left unresolved.")
                continue
            hard_refs_by_entity[class_name].append({
                "field": f["name"], "target": entity_data[target_class]["table_name"], "cardinality": cardinality,
            })
            incoming_hard[target_class].append({
                "from": data["table_name"], "field": f["name"], "cardinality": cardinality,
            })

    classes_by_slug = {entity_slug(n): c for n, c in roots.items()}

    is_mongo = any(d["kind"] == "mongodb" for d in entity_data.values())
    noun = "Collection" if is_mongo else "Table"

    # Harvest before writing anything: the per-collection Purpose feeds this
    # index's summary column, so it has to be read back even on a run where
    # nothing else changed.
    preserved_by_class = {}
    for class_name, data in entity_data.items():
        doc_path = out_dir / f"{slugify(data['table_name'])}.md"
        preserved_by_class[class_name] = ({} if args.no_preserve
                                          else harvest_sections(doc_path, PRESERVED_SECTIONS))

    index_lines = [f"# {args.title}", ""]
    index_lines.append("> Generated by `docs-database`. Do not hand-edit except the sections "
                       "marked as preserved -- regenerate instead.")
    index_lines.append("")
    index_lines.append(f"## {noun}s")
    index_lines.append("")
    index_lines.append(f"| {noun} | What it holds | Backing class | File |")
    index_lines.append("|---|---|---|---|")
    for class_name, data in sorted(entity_data.items(), key=lambda kv: kv[1]["table_name"] or ""):
        table_name = data["table_name"]
        summary = first_sentence(preserved_by_class.get(class_name, {}).get("Purpose", ""))
        link = f"[`{cell(table_name)}`]({slugify(table_name)}.md)"
        index_lines.append(f"| {link} | {cell(summary)} | `{cell(class_name)}` "
                           f"| `{cell(data['cls']['file'])}` |")
    index_lines.append("")
    index_lines.append("## Entity-relationship diagram")
    index_lines.append("")
    index_lines.append("```mermaid")
    hard_refs_by_table = {entity_data[n]["table_name"]: v for n, v in hard_refs_by_entity.items()}
    soft_refs_by_table = {entity_data[n]["table_name"]: refs for n, refs in soft_refs_by_entity.items()}
    diagram, orphans = build_mermaid(
        [d["table_name"] for d in entity_data.values()], soft_refs_by_table, hard_refs_by_table,
    )
    index_lines.append(diagram)
    index_lines.append("```")
    index_lines.append("")
    if orphans:
        index_lines.append(f"_No detected relations for: {', '.join(f'`{o}`' for o in orphans)} "
                            f"-- not shown in the diagram above, see their own pages for fields._")
        index_lines.append("")
    (out_dir / "README.md").write_text("\n".join(index_lines), encoding="utf-8")

    for class_name, data in entity_data.items():
        name = data["table_name"]
        doc = render_collection_doc(
            name, data["kind"], data["cls"], data["fields"],
            soft_refs_by_entity[class_name], incoming_soft[class_name],
            hard_refs_by_entity[class_name], incoming_hard[class_name],
            classes_by_slug, preserved_by_class.get(class_name),
        )
        (out_dir / f"{slugify(name)}.md").write_text(doc, encoding="utf-8")

    unfilled = [entity_data[c]["table_name"] for c, p in preserved_by_class.items()
                if not p.get("Purpose")]
    if unfilled:
        print("Purpose not yet written for: " + ", ".join(sorted(unfilled))
              + " -- fill each one in; it is preserved on the next run and feeds the index.",
              file=sys.stderr)

    print(f"Wrote {len(entity_data) + 1} files to {out_dir}", file=sys.stderr)
    if args.warnings_json:
        Path(args.warnings_json).write_text(json.dumps(warnings, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
