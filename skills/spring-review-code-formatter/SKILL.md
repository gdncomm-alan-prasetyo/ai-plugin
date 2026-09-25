---
name: spring-review-code-formatter
description: Reviews Java code for BliBli Eclipse formatter compliance. Checks indentation (2 spaces), line length (100), K&R braces, blank lines, spacing, lambda arrows, ternary, annotations, and EOF newline. Reports with file:line. Does NOT auto-fix.
---

# Spring Review — Code Formatter (BliBli Profile)

## Model Guidance

Fast-tier. First output line: `[spring-review-code-formatter] running on: {model} (fast-tier)`
No escalation — all 17 rules binary and deterministic. No reasoning-tier consultation.

---

## Formatter Rules Reference

**Profile name**: BliBli Code Formatter Profile
**Eclipse profile version**: 12

Rules from BliBli Eclipse formatter profile only. No inference from general Java conventions. No external file.

---

## Step 0 — Read Change Set

Read `.review-context.md`. First line must be `<!-- review-context: <hash> -->` — else stop: "Run review-context first."

Extract changed `.java` file paths from Sections 2–3. Read each file directly from disk via Read tool — Section 4 contains diffs only, not full content. Formatter requires full file content to check indentation, blank lines, line length.

---

## Step 1 — Apply Formatter Rules

Check every changed `.java` file against all rules below. Per violation, record:
- File path (relative)
- Line number
- Rule violated
- Actual line content (trimmed to 80 chars if very long)
- What it should look like

---

### Rule 1 — Indentation: 2 Spaces, No Tabs

**Setting**: `tabulation.char=space`, `tabulation.size=2`

- Each indentation level: exactly **2 spaces**.
- **Tab characters (`\t`) never allowed**.
- 4-space indentation is violation.
- Mixed tabs and spaces is violation.

**Check**: Per non-blank line, count leading whitespace. Must be multiple of 2. Any tab at line start is violation.

```java
// BAD — 4 spaces
    return value;
// BAD — tab
	return value;
// GOOD — 2 spaces
  return value;
```

---

### Rule 2 — Line Length: Max 100 Characters

**Setting**: `lineSplit=100`, `comment.line_length=100`

- No line (including comments, imports, annotations) may exceed **100 characters**.
- Count actual character length including leading whitespace.
- Exception: lines that cannot be split (e.g. URL in comment, string literal that would change semantics) — flag but note as "may be intentional".

```java
// BAD — 103 chars
  public ResponseEntity<ApiResponse<LockRevokeResponse>> lockRevokePointV2(@Valid @RequestBody LockRevokeRequest request) {
```

---

### Rule 3 — Brace Position: End of Line (K&R Style)

**Settings**: All `brace_position_for_*=end_of_line`

Opening braces `{` on **same line** as statement/declaration, preceded by single space. Never on new line (Allman style).

Applies to: class, interface, enum, method, constructor, block, switch, lambda, array initializer, annotation type.

```java
// BAD — Allman style
public void process()
{
// GOOD — K&R style
public void process() {
```

---

### Rule 4 — Blank Lines

**Settings**:
- `blank_lines_after_package=1` → exactly 1 blank line after `package`
- `blank_lines_before_imports=0` → no blank line before imports block
- `blank_lines_after_imports=1` → exactly 1 blank line after last import
- `blank_lines_before_method=1` → exactly 1 blank line before each method/constructor
- `blank_lines_before_field=0` → no blank line before field declarations
- `blank_lines_between_type_declarations=2` → exactly 2 blank lines between top-level type declarations
- `blank_lines_between_import_groups=1` → 1 blank line between import groups
- `number_of_blank_lines_at_beginning_of_method_body=0` → no blank line at start of method body
- `number_of_empty_lines_to_preserve=2` → max 2 consecutive blank lines anywhere

Report as: `[BLANK LINE] {file}:{line} — {specific rule violated}`

---

### Rule 5 — `else`, `catch`, `finally` on Same Line as `}`

**Settings**:
- `insert_new_line_before_else_in_if_statement=do not insert`
- `insert_new_line_before_catch_in_try_statement=do not insert`
- `insert_new_line_before_finally_in_try_statement=do not insert`
- `insert_new_line_before_while_in_do_statement=do not insert`

`else`, `catch`, `finally`, `while` (in do-while) must appear on **same line** as preceding `}`.

```java
// BAD
}
else {
// GOOD
} else {
```

---

### Rule 6 — `then` and `else` Statements Must Be on New Line

**Settings**:
- `keep_then_statement_on_same_line=false`
- `keep_else_statement_on_same_line=false`
- `format_guardian_clause_on_one_line=false`

Body of `if`, `else`, `else if` must never be on same line as condition.

```java
// BAD
if (condition) return value;
// GOOD
if (condition) {
  return value;
}
```

---

### Rule 7 — Spaces Around Operators

**Settings**: `insert_space_after_binary_operator=insert`, `insert_space_before_binary_operator=insert`, etc.

- Space **before and after** all binary operators: `+`, `-`, `*`, `/`, `%`, `==`, `!=`, `<`, `>`, `<=`, `>=`, `&&`, `||`, `&`, `|`, `^`, `<<`, `>>`, `>>>`.
- Space **before and after** assignment operators: `=`, `+=`, `-=`, `*=`, `/=`, `%=`, `&=`, `|=`, `^=`, `<<=`, `>>=`, `>>>=`.
- No space around unary operators: `!`, `~`, `++`, `--`, `-` (prefix/postfix).

```java
// BAD
int x=5;
int y = a+b;
// GOOD
int x = 5;
int y = a + b;
```

---

### Rule 8 — No Space Inside Parentheses

**Settings**: All `insert_space_after_opening_paren_in_*=do not insert`, `insert_space_before_closing_paren_in_*=do not insert`

No space after `(` or before `)` in method calls, declarations, `if`/`for`/`while`/`switch`/`catch`/`synchronized`, constructors, casts, annotations, enum constants.

```java
// BAD
if ( condition ) {
method( arg1, arg2 );
// GOOD
if (condition) {
method(arg1, arg2);
```

---

### Rule 9 — Comma and Semicolon Spacing

**Settings**: All `insert_space_before_comma_in_*=do not insert`, `insert_space_after_comma_in_*=insert`, `insert_space_before_semicolon=do not insert`

- No space **before** comma or semicolon.
- Space **after** comma.
- No space before `;` in `for` loops.
- Space after `;` in `for` loops.

```java
// BAD
method(a ,b ,c);
for (int i = 0 ; i < n ; i++)
// GOOD
method(a, b, c);
for (int i = 0; i < n; i++)
```

---

### Rule 10 — No Space Between Method Name and Opening Paren

**Settings**: `insert_space_before_opening_paren_in_method_invocation=do not insert`, `insert_space_before_opening_paren_in_method_declaration=do not insert`, `insert_space_before_opening_paren_in_constructor_declaration=do not insert`

```java
// BAD
public void process () {
method (arg);
// GOOD
public void process() {
method(arg);
```

---

### Rule 11 — Lambda Arrow Spacing

**Settings**: `insert_space_before_lambda_arrow=insert`, `insert_space_after_lambda_arrow=insert`

Exactly one space before and after `->`.

```java
// BAD
list.forEach(x->System.out.println(x));
// GOOD
list.forEach(x -> System.out.println(x));
```

---

### Rule 12 — Ternary Operator Spacing

**Settings**: `insert_space_before_question_in_conditional=insert`, `insert_space_after_question_in_conditional=insert`, `insert_space_before_colon_in_conditional=insert`, `insert_space_after_colon_in_conditional=insert`

Exactly one space before and after both `?` and `:` in ternary expressions.

```java
// BAD
String result = condition?"yes":"no";
// GOOD
String result = condition ? "yes" : "no";
```

---

### Rule 13 — Annotation Placement

**Settings**:
- `insert_new_line_after_annotation_on_type=insert` → annotation on class/interface/enum: own line
- `insert_new_line_after_annotation_on_method=insert` → annotation on method: own line
- `insert_new_line_after_annotation_on_field=insert` → annotation on field: own line
- `insert_new_line_after_annotation_on_local_variable=insert` → annotation on local variable: own line
- `insert_new_line_after_annotation_on_parameter=do not insert` → annotation on method parameter: stays inline

```java
// BAD — method annotation must be on its own line
@Override public void process() {
// GOOD
@Override
public void process() {
// OK — parameter annotation inline is correct
public void save(@Valid @RequestBody Request request) {
```

---

### Rule 14 — File Must End with Newline

**Setting**: `insert_new_line_at_end_of_file_if_missing=insert`

Every `.java` file must end with exactly one newline. Missing or multiple trailing blank lines are violations.

---

### Rule 15 — No Space Before Opening Brace

**Setting**: All `insert_space_before_opening_brace_in_*=insert`

Single space required before every opening `{`. No additional spaces.

```java
// BAD — no space before {
public void process(){
// BAD — multiple spaces
public void process()  {
// GOOD
public void process() {
```

---

### Rule 16 — Compact else-if

**Setting**: `compact_else_if=true`

`else if` must remain on one line. Never:
```java
} else
if (condition) {
```
Must be:
```java
} else if (condition) {
```

---

### Rule 17 — Max 2 Consecutive Blank Lines

**Setting**: `number_of_empty_lines_to_preserve=2`

More than 2 consecutive blank lines anywhere is violation.

---

## Step 2 — Return Format

Group violations by file. One finding per file, sorted by line number. Omit files with no violations.

```
FMT-{n} | P2 | {relative/path/to/File.java} | {count} violations
  [RULE NAME] {file}:{line}
    Actual  : {actual line, trimmed if >80 chars}
    Expected: {what it should look like}
  {repeat per violation in this file}
```

Last line: `checks: files={changed file count} violations={total}` + `Formatter profile: BliBli Code Formatter Profile (Eclipse JDT, version 12)`.

No violations → return `FMT: no findings. All changed files comply with BliBli formatter profile.`

---

## Constraints

- **Changed files only**: Skip files not in diff.
- **Full file context**: Read full file to assess blank lines, indentation, EOF — not diff hunk alone.
- **Do not auto-fix**: Report violations only. Never modify files.
- **@formatter:off blocks**: `use_on_off_tags=false` — `// @formatter:off`/`// @formatter:on` tags disabled. Flag tags found, continue checking violations inside those regions.
- **String content**: Do not check whitespace inside string literals (`"..."`).
- **Line numbers**: Always provide exact line numbers.
- **Self-contained**: All rules embedded. No external formatter XML.

---

## Output

Sub-agent: return findings per Return Format — never write files. Standalone: write same findings to `docs/code-review/CODE-REVIEW-{branch}.md` (branch from `**Branch**` in `.review-context.md`; sanitize `/`, `#`, `(`, `)`, space → `-`); tell user path.
