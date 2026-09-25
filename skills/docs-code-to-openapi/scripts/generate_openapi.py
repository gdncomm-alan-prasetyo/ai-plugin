#!/usr/bin/env python3
"""
Static-analysis generator: Spring MVC (Java) REST controllers -> OpenAPI 3.0 YAML.

No build tools, no running app, no springdoc. Pure source-text parsing. This is
deliberately heuristic-based (regex + bracket-depth scanning, not a real Java
AST) because it only needs to be "good enough" to bootstrap a spec a human then
edits -- see SKILL.md for how the model should use this script's output and
`warnings` list.

Usage:
    python generate_openapi.py <path> [--output openapi.yaml] [--title TITLE] [--api-version VERSION]

<path> may be a single controller file, a directory, or a repo root. Files are
discovered by scanning for classes annotated @RestController / @Controller
(not just filename pattern), so non-standard naming still works.
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict

HTTP_ANNOTATIONS = {
    "GetMapping": "get",
    "PostMapping": "post",
    "PutMapping": "put",
    "PatchMapping": "patch",
    "DeleteMapping": "delete",
}

JAVA_TO_OPENAPI_TYPE = {
    "String": ("string", None),
    "boolean": ("boolean", None),
    "Boolean": ("boolean", None),
    "int": ("integer", "int32"),
    "Integer": ("integer", "int32"),
    "long": ("integer", "int64"),
    "Long": ("integer", "int64"),
    "double": ("number", "double"),
    "Double": ("number", "double"),
    "float": ("number", "float"),
    "Float": ("number", "float"),
    "BigDecimal": ("number", None),
    "LocalDate": ("string", "date"),
    "LocalDateTime": ("string", "date-time"),
    "Instant": ("string", "date-time"),
    "Date": ("string", "date-time"),
    "UUID": ("string", "uuid"),
    "Object": (None, None),
}

WRAPPER_COLLECTION_TYPES = {"List", "Set", "Collection", "Iterable", "ArrayList", "HashSet"}
WRAPPER_MAP_TYPES = {"Map", "HashMap"}


# ---------------------------------------------------------------------------
# Low-level bracket-aware scanning helpers.
#
# These exist because Java method signatures and annotations nest parens,
# angle brackets and string literals arbitrarily
# (e.g. @Pattern(regexp = "a,b", message = "x,y")) -- naive comma/paren
# regexes silently corrupt these. Every parameter/annotation split in this
# file goes through split_top_level / find_matching_close so that nesting is
# respected exactly once, in one place.
# ---------------------------------------------------------------------------

def find_matching_close(text, open_pos, open_ch="(", close_ch=")"):
    """Given text[open_pos] == open_ch, return the index of its matching close_ch."""
    depth = 0
    i = open_pos
    in_string = False
    while i < len(text):
        c = text[i]
        if in_string:
            if c == "\\":
                i += 1
            elif c == '"':
                in_string = False
        elif c == '"':
            in_string = True
        elif c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def split_top_level(text, sep=","):
    """Split text on sep, but only at bracket-depth 0 (respecting (), <>, [], {}, strings)."""
    parts = []
    depth = 0
    current = []
    in_string = False
    i = 0
    while i < len(text):
        c = text[i]
        if in_string:
            current.append(c)
            if c == "\\":
                i += 1
                if i < len(text):
                    current.append(text[i])
            elif c == '"':
                in_string = False
            i += 1
            continue
        if c == '"':
            in_string = True
            current.append(c)
        elif c in "(<[{":
            depth += 1
            current.append(c)
        elif c in ")>]}":
            depth -= 1
            current.append(c)
        elif c == sep and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(c)
        i += 1
    if current:
        parts.append("".join(current))
    return [p for p in (s.strip() for s in parts) if p]


def strip_comments(src):
    """Remove // and /* */ comments. Leaves string literals alone (good enough for our needs)."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"(?<!:)//.*", "", src)
    return src


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

# Standard Maven/Gradle layout puts test sources under a 'test'-named directory
# (src/test/java, src/integrationTest/java, ...) -- that's the reliable signal.
# The filename suffixes are a secondary, defense-in-depth check for test classes
# that don't live under a conventional test source root.
TEST_PATH_SEGMENT_RE = re.compile(r"test", re.IGNORECASE)
TEST_FILENAME_RE = re.compile(r"(?:Test|Tests|IT|ITCase)\.java$")


def is_test_source(path):
    segments = re.split(r"[\\/]+", path)
    if any(TEST_PATH_SEGMENT_RE.fullmatch(seg) or seg.lower() in ("integrationtest", "integration-test") for seg in segments):
        return True
    return bool(TEST_FILENAME_RE.search(os.path.basename(path)))


def discover_java_files(path, include_tests=False):
    if os.path.isfile(path):
        if not include_tests and is_test_source(path):
            return []
        return [path]
    out = []
    for root, dirs, files in os.walk(path):
        segments = re.split(r"[\\/]+", root)
        if any(seg in segments for seg in ("target", "build", "node_modules", ".git")):
            continue
        if not include_tests:
            dirs[:] = [d for d in dirs if not TEST_PATH_SEGMENT_RE.fullmatch(d) and d.lower() not in ("integrationtest", "integration-test")]
        for f in files:
            if not f.endswith(".java"):
                continue
            full = os.path.join(root, f)
            if not include_tests and is_test_source(full):
                continue
            out.append(full)
    return out


def read(path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def is_controller_source(src):
    """The annotation must appear in real code, not inside a comment. Annotation-definition
    files (`public @interface Foo`) routinely show `@RestController` inside a Javadoc usage
    example -- without stripping comments first, those get mistaken for controllers and
    contribute a phantom tag/path group to the spec."""
    return bool(re.search(r"@(RestController|Controller)\b", strip_comments(src)))


def is_constants_source(src):
    # Heuristic: a class that's just `public static final String X = ...;` fields.
    return bool(re.search(r"public\s+static\s+final\s+String\s+\w+\s*=", src))


# ---------------------------------------------------------------------------
# Constant resolution
#
# Path constants are often built like:
#   public static final String ROOT = "/api";
#   public static final String ROLE = ROOT + "/role";
#   public static final String ROLE_SEARCH = ROLE + SEARCH;
# We resolve these with a simple fixed-point substitution pass so forward
# references and multi-hop chains both work regardless of declaration order.
# ---------------------------------------------------------------------------

CONST_DECL_RE = re.compile(
    r"public\s+static\s+final\s+String\s+(\w+)\s*=\s*([^;]+);"
)


def collect_constants(java_files, warnings):
    """Returns {simple_name: resolved_string} and {ClassName.field: resolved_string}."""
    raw = {}  # "ClassName.FIELD" -> raw expression
    simple = defaultdict(list)  # FIELD -> list of ("ClassName.FIELD")
    class_of_file = {}

    for path in java_files:
        src = strip_comments(read(path))
        if not is_constants_source(src):
            continue
        m = re.search(r"class\s+(\w+)", src)
        if not m:
            continue
        cls = m.group(1)
        class_of_file[path] = cls
        for name, expr in CONST_DECL_RE.findall(src):
            key = f"{cls}.{name}"
            raw[key] = expr.strip()
            simple[name].append(key)

    resolved = {}

    def resolve_expr(expr, seen):
        # expr like: ROOT + "/role"  or  ROLE + SEARCH  or just "/x"
        parts = split_top_level(expr, "+")
        out = []
        for p in parts:
            p = p.strip()
            if p.startswith('"') and p.endswith('"'):
                out.append(p[1:-1])
                continue
            # bare identifier -> could be "ClassName.FIELD" or just "FIELD"
            if p in raw and p not in seen:
                out.append(resolve_key(p, seen))
                continue
            candidates = simple.get(p, [])
            if p in resolved:
                out.append(resolved[p])
            elif len(candidates) == 1 and candidates[0] not in seen:
                out.append(resolve_key(candidates[0], seen))
            elif "." in p and p in raw:
                out.append(resolve_key(p, seen))
            else:
                warnings.append(
                    f"path-constant: could not resolve token '{p}' in expression '{expr}' "
                    "(dynamic construction, unknown import, or reflection) -- left as literal token"
                )
                out.append("{" + p + "}")
        return "".join(out)

    def resolve_key(key, seen):
        if key in resolved:
            return resolved[key]
        if key in seen:
            warnings.append(f"path-constant: circular reference resolving '{key}'")
            return ""
        seen = seen | {key}
        value = resolve_expr(raw[key], seen)
        resolved[key] = value
        return value

    for key in list(raw.keys()):
        resolve_key(key, set())

    # Expose both "ClassName.FIELD" and bare "FIELD" (when unambiguous) as lookup keys.
    flat = dict(resolved)
    for name, keys in simple.items():
        if len(keys) == 1:
            flat[name] = resolved[keys[0]]
        elif name not in flat:
            warnings.append(
                f"path-constant: '{name}' is ambiguous across classes {keys}; "
                "referencing code must use the qualified form (ClassName.FIELD)"
            )
    return flat


def resolve_path_expr(expr, constants, warnings, context):
    """Resolve a @GetMapping(path = ...) value, which may be a literal, a constant
    reference (bare or ClassName.FIELD), or a '+' concatenation of those."""
    expr = expr.strip()
    parts = split_top_level(expr, "+")
    out = []
    for p in parts:
        p = p.strip()
        if p.startswith('"') and p.endswith('"'):
            out.append(p[1:-1])
        elif p in constants:
            out.append(constants[p])
        elif "." in p and p.split(".")[-1] in constants:
            out.append(constants[p.split(".")[-1]])
        else:
            warnings.append(f"path: in {context}, could not resolve path token '{p}' -- using placeholder")
            out.append("{" + p + "}")
    return "".join(out) or "/"


# ---------------------------------------------------------------------------
# Annotation parsing (generic: works for mapping annotations, validation
# annotations, @Operation, @Tag, param annotations -- anything of the shape
# @Name or @Name(args))
# ---------------------------------------------------------------------------

def parse_annotations(text, start=0):
    """Scan text starting at `start` for a run of @Annotation / @Annotation(...) forms.
    Returns (list of (name, raw_args_str_or_None), end_index_after_last_annotation)."""
    anns = []
    i = start
    n = len(text)
    while True:
        while i < n and text[i].isspace():
            i += 1
        if i >= n or text[i] != "@":
            break
        j = i + 1
        m = re.match(r"[A-Za-z_][A-Za-z0-9_.]*", text[j:])
        if not m:
            break
        name = m.group(0).split(".")[-1]
        j += m.end()
        args = None
        k = j
        while k < n and text[k].isspace():
            k += 1
        if k < n and text[k] == "(":
            close = find_matching_close(text, k)
            if close == -1:
                break
            args = text[k + 1:close]
            j = close + 1
        anns.append((name, args))
        i = j
    return anns, i


def parse_annotation_kv(args):
    """Parse annotation args like: value="x", message = "y", min=1  into a dict.
    Also handles a single bare value: @Something("foo") -> {'value': '"foo"'}."""
    if args is None:
        return {}
    parts = split_top_level(args, ",")
    kv = {}
    if len(parts) == 1 and "=" not in parts[0].split("(")[0]:
        # bare positional value, but only if it doesn't look like key=value
        if "=" not in parts[0] or parts[0].strip().startswith('"'):
            kv["value"] = parts[0].strip()
            return kv
    for part in parts:
        if "=" in part:
            k, v = part.split("=", 1)
            kv[k.strip()] = v.strip()
        else:
            kv.setdefault("value", part.strip())
    return kv


def unquote(s):
    if s is None:
        return None
    s = s.strip()
    if s.startswith('"') and s.endswith('"'):
        return s[1:-1]
    return s


def java_text_block_to_str(s):
    """Very rough handling of Java 15+ text blocks (\"\"\"...\"\"\") used in @Operation(description = \"\"\"...\"\"\")."""
    s = s.strip()
    if s.startswith('"""') and s.endswith('"""'):
        inner = s[3:-3]
        lines = [ln.strip() for ln in inner.strip("\n").split("\n")]
        joined = " ".join(lines)
        joined = joined.replace("\\", "")
        return joined.strip()
    return unquote(s)


# ---------------------------------------------------------------------------
# Validation annotation -> OpenAPI constraint mapping
# ---------------------------------------------------------------------------

def apply_validation_constraints(schema, ann_name, kv, warnings, context):
    if ann_name in ("NotNull", "NotBlank", "NotEmpty"):
        schema["_required"] = True
        if ann_name == "NotBlank":
            schema.setdefault("minLength", 1)
    elif ann_name == "Min":
        v = kv.get("value")
        if v is not None:
            schema["minimum"] = _num(v)
    elif ann_name == "Max":
        v = kv.get("value")
        if v is not None:
            schema["maximum"] = _num(v)
    elif ann_name in ("Size",):
        if "min" in kv:
            schema["minLength"] = _num(kv["min"])
            schema["minItems"] = _num(kv["min"])
        if "max" in kv:
            schema["maxLength"] = _num(kv["max"])
            schema["maxItems"] = _num(kv["max"])
    elif ann_name == "Pattern":
        regexp = kv.get("regexp")
        if regexp is not None:
            schema["pattern"] = unquote(regexp)
    elif ann_name in ("Email",):
        schema["format"] = "email"
    elif ann_name in ("Positive", "PositiveOrZero"):
        schema["minimum"] = 0 if ann_name == "PositiveOrZero" else 1
    elif ann_name in ("Negative", "NegativeOrZero"):
        schema["maximum"] = 0 if ann_name == "NegativeOrZero" else -1
    elif ann_name == "Valid":
        pass  # nested validation trigger, not a constraint itself
    elif ann_name in ("RequestParam", "RequestBody", "RequestHeader", "PathVariable", "RequestPart"):
        pass  # handled by caller
    else:
        # Unknown/custom validator (e.g. @NotEmptyList, @RequiresTenantId): mark
        # required-only per the skill's documented fallback, and surface it so a
        # human can double check whether it implies a stronger constraint.
        schema["_required"] = True
        warnings.append(
            f"validation: unrecognized annotation @{ann_name} in {context} -- "
            "treated as 'required' only; review whether it implies additional constraints"
        )


def _num(s):
    s = s.strip().rstrip("Ll fFdD")
    try:
        if "." in s:
            return float(s)
        return int(s)
    except ValueError:
        return s


# ---------------------------------------------------------------------------
# Type parsing: "List<@NotBlank String>" / "Map<String, RoleResponse>" / "RoleResponse" etc.
# ---------------------------------------------------------------------------

def parse_type(type_str):
    """Returns (raw_name, generic_args:list[str]|None). Strips inline annotations."""
    type_str = type_str.strip()
    lt = type_str.find("<")
    if lt == -1:
        return type_str, None
    gt = find_matching_close(type_str, lt, "<", ">")
    if gt == -1:
        return type_str[:lt].strip(), None
    name = type_str[:lt].strip()
    inner = type_str[lt + 1:gt]
    args = split_top_level(inner, ",")
    cleaned_args = []
    for a in args:
        a = re.sub(r"@\w+(\([^()]*\))?\s*", "", a).strip()
        cleaned_args.append(a)
    return name, cleaned_args


def java_type_to_schema(type_str, all_dtos, warnings, generic_binding=None):
    """Map a Java type string to an OpenAPI schema fragment (dict). `all_dtos` is
    the {class_name: parsed_info} map (not just a set of names) because resolving
    a *generic* DTO reference needs its type_param/fields, not just its existence.
    generic_binding maps a type-parameter name (e.g. 'T') to a concrete type
    string, used when substituting into an already-being-built generic class's
    own fields (see build_dto_schema)."""
    name, args = parse_type(type_str)

    if generic_binding and name in generic_binding:
        return java_type_to_schema(generic_binding[name], all_dtos, warnings, generic_binding)

    if name in WRAPPER_COLLECTION_TYPES:
        item_type = args[0] if args else "Object"
        return {"type": "array", "items": java_type_to_schema(item_type, all_dtos, warnings, generic_binding)}

    if name in WRAPPER_MAP_TYPES:
        value_type = args[1] if args and len(args) > 1 else "Object"
        return {"type": "object", "additionalProperties": java_type_to_schema(value_type, all_dtos, warnings, generic_binding)}

    if name in JAVA_TO_OPENAPI_TYPE:
        t, fmt = JAVA_TO_OPENAPI_TYPE[name]
        if t is None:
            return {}  # Object / unknown primitive -> no constraint (accepts anything)
        schema = {"type": t}
        if fmt:
            schema["format"] = fmt
        return schema

    if name in all_dtos:
        dto_info = all_dtos[name]
        if dto_info.get("type_param") and args:
            # A generic DTO instantiated with a concrete argument at this specific
            # reference site (e.g. SearchResponse<RoleResponse>) can't be expressed
            # as one shared $ref -- OpenAPI has no generics, and the same wrapper
            # class may be instantiated with a different type elsewhere in the same
            # API. Inline the substituted schema instead of erasing the type
            # parameter into a dangling, unresolved $ref.
            binding = {dto_info["type_param"]: args[0]}
            return build_dto_schema(name, dto_info, all_dtos, warnings, generic_binding=binding)
        return {"$ref": f"#/components/schemas/{name}"}

    # Unresolved custom type (not found among parsed DTOs) -- emit a generic
    # object rather than failing, but this should be flagged upstream.
    return {"type": "object", "description": f"Unresolved type '{name}' -- verify manually"}


# ---------------------------------------------------------------------------
# DTO parsing
# ---------------------------------------------------------------------------

FIELD_RE = re.compile(
    r"private\s+((?:[\w.]+\s*)+<[^;{}]*?>|[\w.<>\[\],\s]+?)\s+(\w+)\s*(?:=\s*[^;]+)?;"
)


def find_class_body(src, class_name):
    m = re.search(rf"\bclass\s+{re.escape(class_name)}\b[^{{]*\{{", src)
    if not m:
        return None
    open_pos = m.end() - 1
    close = find_matching_close(src, open_pos, "{", "}")
    if close == -1:
        return None
    return src[open_pos + 1:close]


def parse_enum(src, class_name):
    m = re.search(rf"\benum\s+{re.escape(class_name)}\b[^{{]*\{{", src)
    if not m:
        return None
    open_pos = m.end() - 1
    close = find_matching_close(src, open_pos, "{", "}")
    if close == -1:
        return None
    body = src[open_pos + 1:close]
    head = body.split(";")[0]
    values = [v.strip().split("(")[0].strip() for v in head.split(",")]
    return [v for v in values if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", v)]


def extract_annotations_anywhere(s):
    """Like parse_annotations, but scans the whole string rather than requiring
    annotations to run consecutively from a fixed start -- needed because
    modifiers/annotations on a field can interleave in any order
    (`@JsonProperty("x") private final String y;` vs `private @NotBlank String y;`).
    Returns (list of (name, raw_args_or_None), remaining_text_with_annotations_removed).
    Bracket-aware (via find_matching_close) so annotation args containing '(' or '='
    -- like @Pattern(regexp = "a(b)c") -- don't get mis-split."""
    anns = []
    out = []
    i, n = 0, len(s)
    while i < n:
        if s[i] == "@":
            m = re.match(r"[A-Za-z_][A-Za-z0-9_.]*", s[i + 1:])
            if m:
                name = m.group(0).split(".")[-1]
                j = i + 1 + m.end()
                k = j
                while k < n and s[k].isspace():
                    k += 1
                if k < n and s[k] == "(":
                    close = find_matching_close(s, k)
                    if close != -1:
                        anns.append((name, s[k + 1:close]))
                        i = close + 1
                        continue
                anns.append((name, None))
                i = j
                continue
        out.append(s[i])
        i += 1
    return anns, "".join(out)


def strip_inline_annotations(s):
    return extract_annotations_anywhere(s)[1]


MODIFIER_RE = re.compile(r"^\s*(?:public|private|protected|static|final|transient|volatile)\b\s*")


def strip_modifiers(s):
    while True:
        new = MODIFIER_RE.sub("", s, count=1)
        if new == s:
            return s
        s = new


def strip_top_level_initializer(decl):
    """Truncate at the first '=' that sits at bracket-depth 0 (a genuine field
    initializer like '= 5'), ignoring '=' inside annotation args, generics or
    string literals -- e.g. '@Pattern(regexp = "a=b")' must survive intact."""
    depth = 0
    in_string = False
    i = 0
    while i < len(decl):
        c = decl[i]
        if in_string:
            if c == "\\":
                i += 1
            elif c == '"':
                in_string = False
        elif c == '"':
            in_string = True
        elif c in "(<[{":
            depth += 1
        elif c in ")>]}":
            depth -= 1
        elif c == "=" and depth == 0:
            return decl[:i]
        i += 1
    return decl


def split_type_and_name(decl):
    """Split 'List<String, Map<String,Integer>> fieldName' into (type, name) by
    finding the last whitespace at bracket-depth 0. Deliberately not regex-based:
    a regex trying to express "greedy generic type, then an identifier" invites
    nested-quantifier backtracking blowups on malformed/unexpected input."""
    depth = 0
    last_top_level_space = -1
    for i, c in enumerate(decl):
        if c in "<[":
            depth += 1
        elif c in ">]":
            depth = max(0, depth - 1)
        elif c.isspace() and depth == 0:
            last_top_level_space = i
    if last_top_level_space == -1:
        return None, None
    return decl[:last_top_level_space].strip(), decl[last_top_level_space:].strip()


def iter_top_level_members(body):
    """Yield the raw text of each top-level, semicolon-terminated member declaration
    in a class body: field declarations, and any method-ish text that happens to be
    terminated by ';' rather than a body (constructors/methods with a '{...}' body
    are skipped wholesale, since we jump straight past their matching '}' and
    discard whatever text preceded it -- see the module docstring's note on
    bracket-depth scanning). This deliberately does NOT descend into nested
    classes/enums/blocks; those are handled separately (parse_enum runs its own
    text search over the full body)."""
    i, n = 0, len(body)
    start = 0
    while i < n:
        c = body[i]
        if c in ('"', "'"):
            quote = c
            i += 1
            while i < n and body[i] != quote:
                if body[i] == "\\":
                    i += 1
                i += 1
            i += 1
        elif c == "{":
            close = find_matching_close(body, i, "{", "}")
            if close == -1:
                break
            i = close + 1
            start = i
        elif c == ";":
            yield body[start:i]
            i += 1
            start = i
        else:
            i += 1


def try_parse_field(raw_member):
    """Classify one top-level member as a field or not. Returns (annotations, type,
    name) for a field, or None for anything else (a bodyless method signature like
    an interface/abstract method, a stray annotation-only fragment, an unparsable
    line). The type/method distinction hinges on whether a '(' immediately follows
    the identifier -- a field's name is followed only by ';', '=', or '[' (array),
    never '(' -- rather than on brace-scanning, since by this point any '{...}'
    body has already been stripped out by iter_top_level_members."""
    anns, remaining = extract_annotations_anywhere(raw_member)
    remaining = strip_modifiers(remaining)
    remaining = strip_top_level_initializer(remaining).strip()
    if not remaining:
        return None
    raw_type, name = split_type_and_name(remaining)
    if raw_type is None or name is None:
        return None
    if "(" in name or not re.match(r"^\w+$", name):
        return None  # method signature, or something we don't understand -- not a field
    return anns, raw_type, name


def parse_dto_file(path, warnings):
    """Returns list of (class_name, {'type_param': str|None, 'fields': [...], 'enum_values': [...]|None})."""
    src = strip_comments(read(path))
    results = []

    for m in re.finditer(r"\b(?:public\s+)?(?:final\s+)?class\s+(\w+)(?:<(\w+)>)?", src):
        class_name, type_param = m.group(1), m.group(2)
        enum_values = parse_enum(src, class_name)
        body = find_class_body(src, class_name)
        if body is None:
            continue

        fields = []
        # Walk top-level members (fields; method bodies are already skipped by
        # iter_top_level_members) -- covers both `private` and package-private
        # fields, since Lombok-style DTOs commonly omit the access modifier
        # entirely and rely on @Data to generate accessors.
        for raw_member in iter_top_level_members(body):
            if not raw_member.strip():
                continue
            parsed = try_parse_field(raw_member)
            if parsed is None:
                continue
            anns, raw_type, field_name = parsed
            fields.append({
                "name": field_name,
                "type": raw_type,
                "annotations": anns,
            })

        for enum_match in re.finditer(r"\benum\s+(\w+)\b", body):
            nested_name = enum_match.group(1)
            nested_values = parse_enum(body, nested_name)
            if nested_values:
                results.append((nested_name, {"type_param": None, "fields": [], "enum_values": nested_values}))

        results.append((class_name, {
            "type_param": type_param,
            "fields": fields,
            "enum_values": enum_values,
        }))

    return results


def build_dto_schema(dto_name, dto_info, all_dtos, warnings, generic_binding=None):
    if dto_info.get("enum_values"):
        return {"type": "string", "enum": dto_info["enum_values"]}

    props = {}
    required = []
    for f in dto_info["fields"]:
        schema = java_type_to_schema(f["type"], all_dtos, warnings, generic_binding)
        schema = dict(schema)  # copy, since we may mutate with constraints
        is_required = False
        for ann_name, raw_args in f["annotations"]:
            kv = {k: unquote(v) if k != "regexp" else v for k, v in parse_annotation_kv(raw_args).items()}
            apply_validation_constraints(schema, ann_name, kv, warnings, f"{dto_name}.{f['name']}")
            if schema.pop("_required", False):
                is_required = True
        props[f["name"]] = schema
        if is_required:
            required.append(f["name"])

    out = {"type": "object", "properties": props}
    if required:
        out["required"] = required
    return out


# ---------------------------------------------------------------------------
# Controller parsing
# ---------------------------------------------------------------------------

def parse_controller_file(path, constants, warnings):
    src = strip_comments(read(path))
    class_match = re.search(r"class\s+(\w+)", src)
    controller_class = class_match.group(1) if class_match else os.path.basename(path)

    class_prefix = ""
    # Scan for @RequestMapping anywhere before the class declaration rather than
    # requiring it to sit immediately adjacent to `class` -- annotations on a class
    # commonly appear in any order/count (@RestController, @Slf4j,
    # @RequestMapping(...), @RequiredArgsConstructor, ...), and a single adjacency
    # regex silently misses the prefix whenever another annotation follows it.
    search_region = src[:class_match.start()] if class_match else src
    for rm in re.finditer(r"@RequestMapping\b", search_region):
        k = rm.end()
        while k < len(search_region) and search_region[k].isspace():
            k += 1
        if k >= len(search_region) or search_region[k] != "(":
            continue
        close = find_matching_close(search_region, k)
        if close == -1:
            continue
        kv = parse_annotation_kv(search_region[k + 1:close])
        raw_path = kv.get("path") or kv.get("value")
        if raw_path:
            class_prefix = resolve_path_expr(raw_path, constants, warnings, f"{controller_class} class-level @RequestMapping")

    tag_match = re.search(r'@Tag\s*\(([^()]*)\)', src)
    tag_description = None
    if tag_match:
        kv = parse_annotation_kv(tag_match.group(1))
        if "description" in kv:
            tag_description = java_text_block_to_str(kv["description"])

    operations = []

    for mapping_ann in HTTP_ANNOTATIONS:
        for m in re.finditer(rf"@{mapping_ann}\b", src):
            ann_start = m.start()
            args = None
            k = m.end()
            while k < len(src) and src[k].isspace():
                k += 1
            if k < len(src) and src[k] == "(":
                close = find_matching_close(src, k)
                args = src[k + 1:close]

            # Walk backwards from the annotation to gather sibling annotations
            # (e.g. @Operation, @Tag placed above @GetMapping) that belong to
            # the same method.
            preceding = src[:ann_start]
            method_block_start = max(preceding.rfind(";"), preceding.rfind("}"))
            sibling_zone = src[method_block_start + 1:ann_start]

            # Find where the annotation run actually starts (first '@' after the boundary).
            first_at = sibling_zone.find("@")
            sibling_anns = []
            if first_at != -1:
                sibling_anns, _ = parse_annotations(sibling_zone[first_at:], 0)

            # Now find the method signature: from just after this mapping annotation's
            # (optional) args, skip any further annotations, then capture
            # `<modifiers> ReturnType methodName(params) {`
            after = src[k:]
            if args is not None:
                close = find_matching_close(src, k)
                after = src[close + 1:]
            more_anns, consumed = parse_annotations(after, 0)
            sig_zone = after[consumed:]
            sig_match = re.match(
                r"\s*(?:public|private|protected)?\s*[\w<>\[\],\s.]+?\s+(\w+)\s*\(", sig_zone, re.DOTALL
            )
            if not sig_match:
                warnings.append(f"controller: could not locate method signature after @{mapping_ann} near offset {ann_start} in {path}")
                continue
            method_name = sig_match.group(1)
            paren_open = sig_zone.index("(", sig_match.start())
            paren_close = find_matching_close(sig_zone, paren_open)
            params_raw = sig_zone[paren_open + 1:paren_close]

            return_type_match = re.search(
                r"(?:public|private|protected)?\s*([\w<>\[\],\s.?]+?)\s+" + re.escape(method_name) + r"\s*\(",
                sig_zone, re.DOTALL,
            )
            return_type = return_type_match.group(1).strip() if return_type_match else None

            kv = parse_annotation_kv(args)
            raw_path = kv.get("path") or kv.get("value")
            op_path = resolve_path_expr(raw_path, constants, warnings, f"{controller_class}.{method_name}") if raw_path else ""
            full_path = (class_prefix.rstrip("/") + "/" + op_path.lstrip("/")).rstrip("/") if op_path else (class_prefix or "/")
            if not full_path.startswith("/"):
                full_path = "/" + full_path

            all_anns = sibling_anns + more_anns
            operation_ann = next((a for a in all_anns if a[0] == "Operation"), None)
            summary, description = None, None
            if operation_ann:
                op_kv = parse_annotation_kv(operation_ann[1])
                if "summary" in op_kv:
                    summary = java_text_block_to_str(op_kv["summary"])
                if "description" in op_kv:
                    description = java_text_block_to_str(op_kv["description"])
            if not summary:
                summary = humanize_method_name(method_name)

            params = parse_params(params_raw, warnings, f"{controller_class}.{method_name}")
            success_status = detect_success_status(
                all_anns, sig_zone, paren_close, warnings, f"{controller_class}.{method_name}")

            operations.append({
                "http_method": HTTP_ANNOTATIONS[mapping_ann],
                "path": full_path,
                "method_name": method_name,
                "summary": summary,
                "description": description,
                "params": params,
                "return_type": return_type,
                "produces": kv.get("produces"),
                "success_status": success_status,
            })

    return {
        "class_name": controller_class,
        "tag_description": tag_description,
        "operations": operations,
    }


def humanize_method_name(name):
    words = re.sub(r"(?<!^)(?=[A-Z])", " ", name).split()
    if not words:
        return name
    words[0] = words[0].capitalize()
    return " ".join(words)


def parse_params(params_raw, warnings, context):
    params = []
    for p in split_top_level(params_raw, ","):
        p = p.strip()
        if not p:
            continue
        anns, consumed = parse_annotations(p, 0)
        rest = p[consumed:].strip()
        tm = re.match(r"([\w.<>\[\],\s?]+?)\s+(\w+)\s*$", rest, re.DOTALL)
        if not tm:
            warnings.append(f"controller: could not parse parameter '{p}' in {context}")
            continue
        ptype, pname = tm.group(1).strip(), tm.group(2).strip()
        params.append({"name": pname, "type": ptype, "annotations": anns})
    return params


# ---------------------------------------------------------------------------
# OpenAPI assembly
# ---------------------------------------------------------------------------

def unwrap_response_entity(return_type):
    """ResponseEntity<CommonResponse<RoleResponse>> -> ('CommonResponse', ['RoleResponse'])
    or just the inner type if not wrapped in ResponseEntity."""
    if not return_type:
        return None, None
    name, args = parse_type(return_type)
    if name == "ResponseEntity" and args:
        inner_name, inner_args = parse_type(args[0])
        return inner_name, inner_args
    return name, args


HTTP_STATUS_ENUM = {
    "OK": "200", "CREATED": "201", "ACCEPTED": "202", "NO_CONTENT": "204",
    "PARTIAL_CONTENT": "206", "MULTI_STATUS": "207", "ALREADY_REPORTED": "208",
}


def detect_success_status(annotations, sig_zone, paren_close, warnings, context):
    """Work out the success status of one handler, rather than assuming 200.

    Two sources, in order of authority: an explicit `@ResponseStatus`, then an
    `HttpStatus.X` passed as the first argument of whatever helper the method
    delegates to (the `genericHandling(HttpStatus.MULTI_STATUS, ...)` shape).
    The second is a heuristic and says so via a warning, because an `HttpStatus`
    mentioned in a body could be an error path rather than the success one.
    """
    for name, args in annotations:
        if name == "ResponseStatus" and args:
            m = re.search(r"HttpStatus\.(\w+)", args)
            if m:
                code = HTTP_STATUS_ENUM.get(m.group(1))
                if code:
                    return code
                warnings.append(
                    f"responses: {context} has @ResponseStatus(HttpStatus.{m.group(1)}), which is "
                    "not a success status this script maps -- defaulted to 200, set it manually")
                return "200"

    body_start = sig_zone.find("{", paren_close)
    if body_start == -1:
        return "200"
    body = sig_zone[body_start:find_matching_close(sig_zone, body_start, "{", "}") + 1]
    # Only the first argument position: `helper(HttpStatus.X, ...)`. An
    # HttpStatus deeper in an argument list is usually an error/throw path.
    m = re.search(r"\w+\s*\(\s*HttpStatus\.(\w+)\s*,", body)
    if not m:
        return "200"
    code = HTTP_STATUS_ENUM.get(m.group(1))
    if not code:
        return "200"
    if code != "200":
        warnings.append(
            f"responses: {context} passes HttpStatus.{m.group(1)} to a helper as its first "
            f"argument -- inferred success status {code}; confirm this is the success path "
            "and not an error one")
    return code


# Reason phrases exactly as org.springframework.http.HttpStatus spells them, so
# `status` in the envelope matches what getReasonPhrase() actually returns.
HTTP_REASON = {
    "200": "OK", "201": "Created", "202": "Accepted", "203": "Non-Authoritative Information",
    "204": "No Content", "205": "Reset Content", "206": "Partial Content", "207": "Multi-Status",
    "208": "Already Reported", "226": "IM Used",
    "400": "Bad Request", "401": "Unauthorized", "402": "Payment Required", "403": "Forbidden",
    "404": "Not Found", "405": "Method Not Allowed", "406": "Not Acceptable",
    "408": "Request Timeout", "409": "Conflict", "410": "Gone", "412": "Precondition Failed",
    "415": "Unsupported Media Type", "422": "Unprocessable Entity", "429": "Too Many Requests",
    "500": "Internal Server Error", "501": "Not Implemented", "502": "Bad Gateway",
    "503": "Service Unavailable", "504": "Gateway Timeout",
}


def shape_envelope(schema, status):
    """Pin the common envelope's `code`/`status` to one HTTP status, and drop
    `messages` from success responses.

    The envelope class carries every field the app can ever return, so taken
    verbatim it documents a 200 as though it might also carry `messages` and an
    arbitrary `code`. Per-status shaping is what makes the schema say what that
    one response actually looks like. Only touches a schema that really is the
    envelope (an object with `code` and `status` properties); anything else is
    returned untouched.
    """
    props = schema.get("properties") if isinstance(schema, dict) else None
    if not props or "code" not in props or "status" not in props:
        return schema
    props["code"] = dict(props["code"], example=int(status))
    reason = HTTP_REASON.get(status)
    if reason:
        props["status"] = dict(props["status"], example=reason)
    # The two halves of the envelope are mutually exclusive in practice:
    # `messages` is only ever populated by the error handlers, and `data` only
    # by the success path. Documenting both on every response describes a
    # payload the app never actually sends.
    if status.startswith("2"):
        props.pop("messages", None)
    elif status[0] in "45":
        props.pop("data", None)
    return schema


def build_operation_object(op, controller_tag, all_dtos, warnings, context):
    parameters = []
    request_body = None

    for p in op["params"]:
        ann_names = [a[0] for a in p["annotations"]]
        if "RequestBody" in ann_names:
            required = "Valid" in ann_names or True
            request_body = {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": java_type_to_schema(p["type"], all_dtos, warnings)
                    }
                },
            }
            continue
        if "RequestPart" in ann_names:
            request_body = request_body or {"required": True, "content": {}}
            request_body["content"]["multipart/form-data"] = {
                "schema": {"type": "object", "properties": {
                    p["name"]: {"type": "string", "format": "binary"}
                }}
            }
            continue

        location = "query"
        param_ann = None
        for a in p["annotations"]:
            if a[0] in ("RequestParam", "RequestHeader", "PathVariable"):
                param_ann = a
                location = {"RequestParam": "query", "RequestHeader": "header", "PathVariable": "path"}[a[0]]
                break
        if param_ann is None and not any(a[0] in ("RequestBody", "RequestPart") for a in p["annotations"]):
            # Bare param with no Spring annotation, e.g. `MultiValueMap<String,String> allParams`
            # -- can't confidently model this as discrete query params.
            if p["type"].split("<")[0] in ("MultiValueMap", "Map"):
                warnings.append(
                    f"params: {context} has an unannotated map-like parameter '{p['name']}' "
                    f"({p['type']}) representing arbitrary/dynamic query params -- not expressible "
                    "as discrete OpenAPI parameters; omitted, document manually if it matters"
                )
                continue
            location = "query"

        ann_kv = parse_annotation_kv(param_ann[1]) if param_ann else {}
        default_value = ann_kv.get("defaultValue")
        if location == "path":
            required = True
        elif "required" in ann_kv:
            required = ann_kv["required"].strip() == "true"
        elif default_value is not None:
            # Spring treats a @RequestParam/@RequestHeader as implicitly optional
            # once a defaultValue is supplied, even with no explicit `required`.
            required = False
        else:
            required = True

        schema = java_type_to_schema(p["type"], all_dtos, warnings)
        for ann_name, raw_args in p["annotations"]:
            if ann_name in ("RequestParam", "RequestHeader", "PathVariable", "RequestBody", "RequestPart"):
                continue
            kv = {k: unquote(v) if k != "regexp" else v for k, v in parse_annotation_kv(raw_args).items()}
            apply_validation_constraints(schema, ann_name, kv, warnings, f"{context}({p['name']})")
            if schema.pop("_required", False):
                # A bean-validation constraint (e.g. @NotNull) on a param Spring itself
                # treats as optional means the app will 400 on absence anyway -- so it's
                # functionally required from an API-consumer's point of view. Prefer
                # that stricter, functional reading over Spring's raw annotation flag.
                required = True

        if default_value is not None:
            if default_value.startswith('"') and default_value.endswith('"'):
                literal = unquote(default_value)
                if literal != "":
                    schema["default"] = literal
            elif default_value.rsplit(".", 1)[-1] == "EMPTY":
                # Common idiom: org.apache.commons.lang3.StringUtils.EMPTY / log4j's
                # Strings.EMPTY / Guava equivalents all mean "". Resolving this one
                # well-known family avoids a warning on nearly every optional string
                # param in codebases that use it, without guessing at anything else.
                pass
            else:
                warnings.append(
                    f"params: {context}({p['name']}) has a defaultValue expression "
                    f"'{default_value}' that isn't a string literal (likely a constant "
                    "reference) -- could not resolve to an actual default; set schema.default manually if needed"
                )

        param_name = ann_kv.get("value") or ann_kv.get("name")
        param_name = unquote(param_name) if param_name else p["name"]

        parameters.append({
            "name": param_name,
            "in": location,
            "required": required,
            "schema": schema,
        })

    success_status = op.get("success_status") or "200"
    resp_name, resp_args = unwrap_response_entity(op["return_type"])
    response_schema = {"type": "object", "description": "void/unspecified response body"}
    if resp_name:
        # Reconstruct "Name<Arg>" (dropping the ResponseEntity<...> wrapper we just
        # stripped) and let java_type_to_schema's generic-instantiation handling
        # do the substitution -- it applies uniformly to any generic DTO, not just
        # a specially-designated "the" envelope type.
        reconstructed = resp_name if not resp_args else f"{resp_name}<{','.join(resp_args)}>"
        response_schema = java_type_to_schema(reconstructed, all_dtos, warnings)
        response_schema = shape_envelope(response_schema, success_status)

    operation = {
        "tags": [controller_tag],
        "summary": op["summary"],
        "operationId": op["method_name"],
        "parameters": parameters,
        "responses": {
            success_status: {
                "description": "Successful response",
                "content": {"application/json": {"schema": response_schema}},
            }
        },
    }
    if op["description"]:
        operation["description"] = op["description"]
    if request_body:
        operation["requestBody"] = request_body
    if not parameters:
        del operation["parameters"]
    return operation


def merge_paths(spec_paths, path, http_method, operation):
    spec_paths.setdefault(path, {})[http_method] = operation


def generate(root_path, title, api_version, warnings, include_tests=False):
    java_files = discover_java_files(root_path, include_tests=include_tests)
    if not java_files:
        raise SystemExit(f"No .java files found under {root_path}")

    constants = collect_constants(java_files, warnings)

    controller_files = [f for f in java_files if is_controller_source(read(f))]
    if not controller_files:
        warnings.append(f"discovery: no @RestController/@Controller classes found under {root_path}")

    all_dtos = {}
    for f in java_files:
        if f in controller_files:
            continue
        src = strip_comments(read(f))
        if "class" not in src and "enum" not in src:
            continue
        for name, info in parse_dto_file(f, warnings):
            if name in all_dtos:
                continue
            all_dtos[name] = info

    spec_paths = {}
    tags = {}
    schemas = {}

    for cf in controller_files:
        controller = parse_controller_file(cf, constants, warnings)
        tag = controller["class_name"].replace("Controller", "") or controller["class_name"]
        tags[tag] = controller["tag_description"] or f"Operations from {controller['class_name']}"

        for op in controller["operations"]:
            operation_obj = build_operation_object(
                op, tag, all_dtos, warnings,
                f"{controller['class_name']}.{op['method_name']}",
            )
            merge_paths(spec_paths, op["path"], op["http_method"], operation_obj)

    referenced = set()

    def collect_refs(node):
        if isinstance(node, dict):
            if "$ref" in node:
                referenced.add(node["$ref"].rsplit("/", 1)[-1])
            for v in node.values():
                collect_refs(v)
        elif isinstance(node, list):
            for v in node:
                collect_refs(v)

    collect_refs(spec_paths)

    seen = set()
    frontier = set(referenced)
    while frontier:
        name = frontier.pop()
        if name in seen or name not in all_dtos:
            continue
        seen.add(name)
        schema = build_dto_schema(name, all_dtos[name], all_dtos, warnings)
        schemas[name] = schema
        new_refs = set()
        collect_refs(schema)
        # collect_refs above populated the outer `referenced` set; pull only new ones
        for r in list(referenced):
            if r not in seen:
                new_refs.add(r)
        frontier |= new_refs

    spec = {
        "openapi": "3.0.3",
        "info": {"title": title, "version": api_version},
        "tags": [{"name": k, "description": v} for k, v in sorted(tags.items())],
        "paths": dict(sorted(spec_paths.items())),
        "components": {"schemas": dict(sorted(schemas.items()))},
    }
    return spec


# ---------------------------------------------------------------------------
# Minimal YAML emitter (avoids a PyYAML dependency so the skill is self-contained)
# ---------------------------------------------------------------------------

def yaml_scalar(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value)
    if s == "":
        return '""'
    needs_quotes = (
        s != s.strip()
        or s[0] in "!&*-?|>%@`\"'#,[]{}:"
        or ": " in s or s.endswith(":")
        or "\n" in s
        or s.lower() in ("null", "true", "false", "yes", "no", "~")
        or re.match(r"^[-+]?[\d.]+$", s)
    )
    if needs_quotes:
        escaped = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{escaped}"'
    return s


def to_yaml(obj, indent=0):
    lines = []
    pad = "  " * indent
    if isinstance(obj, dict):
        if not obj:
            lines.append(pad + "{}")
        for k, v in obj.items():
            key = yaml_scalar(k) if not re.match(r"^[A-Za-z_][A-Za-z0-9_./-]*$", str(k)) else str(k)
            if isinstance(v, (dict, list)) and v:
                lines.append(f"{pad}{key}:")
                lines.append(to_yaml(v, indent + 1))
            else:
                lines.append(f"{pad}{key}: {yaml_scalar(v) if not isinstance(v, (dict, list)) else ('{}' if isinstance(v, dict) else '[]')}")
    elif isinstance(obj, list):
        if not obj:
            lines.append(pad + "[]")
        for item in obj:
            if isinstance(item, (dict, list)) and item:
                sub = to_yaml(item, indent + 1)
                first_line, _, remainder = sub.partition("\n")
                lines.append(f"{pad}- {first_line.strip()}")
                if remainder:
                    lines.append(remainder)
            else:
                lines.append(f"{pad}- {yaml_scalar(item)}")
    else:
        lines.append(pad + yaml_scalar(obj))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", help="Controller file, directory, or repo root to scan")
    ap.add_argument("--output", default="openapi.yaml", help="Output YAML file (default: openapi.yaml)")
    ap.add_argument("--title", default="API", help="info.title for the generated spec")
    ap.add_argument("--api-version", default="1.0.0", help="info.version for the generated spec")
    ap.add_argument("--warnings-json", default=None, help="Optional path to also dump warnings as JSON")
    ap.add_argument(
        "--include-tests", action="store_true",
        help="Include controllers found under test source roots (src/test/..., *Test.java, "
             "*IT.java) and any DTOs/constants they reference. Excluded by default since test "
             "fixture endpoints (mock controllers, integration-test helpers) aren't part of "
             "the real API surface.",
    )
    args = ap.parse_args()

    warnings = []
    spec = generate(args.path, args.title, args.api_version, warnings, include_tests=args.include_tests)

    with open(args.output, "w", encoding="utf-8") as fh:
        fh.write(to_yaml(spec))
        fh.write("\n")

    print(f"Wrote {args.output} ({len(spec['paths'])} paths, {len(spec['components']['schemas'])} schemas)", file=sys.stderr)
    if warnings:
        print(f"\n{len(warnings)} item(s) need manual review:", file=sys.stderr)
        for w in warnings:
            print(f"  - {w}", file=sys.stderr)
    if args.warnings_json:
        with open(args.warnings_json, "w", encoding="utf-8") as fh:
            json.dump(warnings, fh, indent=2)


if __name__ == "__main__":
    main()
