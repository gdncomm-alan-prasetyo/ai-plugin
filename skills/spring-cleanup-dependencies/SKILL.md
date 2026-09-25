---
name: spring-cleanup-dependencies
description: Analyzes Maven dependencies (dependency:analyze + dependency:tree -Dverbose), classifies unused candidates conservatively, removes targeted unused imports, test-applies all removal candidates against mvn clean compile to pre-verify safety, measures JAR size before and after, always reverts pom.xml after testing, saves progress state to disk for resume after token exhaustion, and generates a developer-friendly report + apply script. The project is never left in a broken state.
---

# Spring — Dependency Cleanup

**Design principle — analyze first, clean second, test-verify, revert always.**

Goal: identify and safely remove unused dependencies to reduce fat JAR size and improve startup time.

Order of operations:
1. Scan pom.xml and analyze dependencies (bytecode + tree) to find unused candidates.
2. Classify candidates conservatively (KEEP is the default).
3. **Save progress to disk** — resume safely if the session ends before completion.
4. Remove unused imports targeted at SAFE candidate packages.
5. **Temporarily apply all candidates → `mvn clean compile` → measure JAR → always revert pom.xml.**
6. Write a developer report (JAR size before/after) and a safe apply script.

The skill **never permanently modifies pom.xml**. Imports are the only code change made automatically.

---

## Startup — Check for Existing Progress

Derive branch: `git rev-parse --abbrev-ref HEAD`. Replace every `/` with `-`.

Check if `docs/dependency-cleanup/.cleanup-state-{branch}.json` exists (Read tool).

**File exists** → read it. Print:
```
[cleanup-deps] Saved progress found — branch: {branch}, last completed phase: {last_completed_phase}
```
Ask the user: "Resume from saved state? (yes = continue from Phase {next}, no = start fresh)"
- **yes** → load all fields from the state file. Skip every phase whose number ≤ `last_completed_phase`. Jump directly to the first incomplete phase.
- **no** → delete the state file, proceed from Phase 0.

**File does not exist** → proceed from Phase 0.

---

## Phase 0 — Detect Project Structure + Baseline JAR Size

### Step 0.1 — Detect Project Structure

```bash
find . -name "pom.xml" -not -path "*/target/*" | sort
```

- **Single-module**: one `pom.xml` at root.
- **Multi-module**: root `pom.xml` contains `<modules>`. Read it to extract the full module list.

Read the root `pom.xml` for `<groupId>`, `<artifactId>`, `<version>`.

Record: `project.type`, `project.modules[]`, `project.root_artifact`.

### Step 0.2 — Measure Baseline JAR Size

First check for existing Spring Boot fat JARs (prefer ones without `.original` or `-plain` suffix):

```bash
find . -name "*.jar" -path "*/target/*" \
  -not -name "*-sources.jar" \
  -not -name "*-javadoc.jar" \
  -not -name "*.original" \
  -not -path "*/dependency/*" \
  2>/dev/null | sort
```

- **JARs found**: record each as `{ path, size_bytes }`. Convert to human-readable (KB / MB). These are the baseline sizes.
- **No JARs found**: note `"baseline: no JAR built yet — will compare against post-apply build only"`. Do not run a build here; the first measurement happens during Phase 5.

Save to state: `baseline_jars[]`.

---

## Phase 1 — Dependency Analysis

### Step 1.1 — Run `dependency:analyze`

```bash
mvn dependency:analyze -DfailOnWarning=false 2>&1
```

Capture the **full** output — do not truncate.

If the project uses Maven profiles and no default profile is active (check root `pom.xml` for `<profiles>`), ask the user which profile to activate before running.

For each module in the output, extract:

- **`used_undeclared_set`** — "Used undeclared dependencies": present in bytecode but only sourced transitively. Format: `Set<groupId:artifactId>`.
- **`unused_declared_candidates[]`** — "Unused declared dependencies": declared in `pom.xml` but absent from bytecode. These are the starting candidates for removal.

Parse each entry as `groupId:artifactId:type:version:scope`. Record the module it came from.

### Step 1.2 — Run `dependency:tree`

```bash
mvn dependency:tree -Dverbose 2>&1
```

Capture the **full** output. For multi-module projects, keep sections per module separate.

For each `unused_declared_candidate`:

1. Find it in the dependency tree. Collect all transitive children (nodes indented deeper under it).
2. Does any transitive child appear in `used_undeclared_set`?
   - **Yes** → pre-classify as VERIFY MANUALLY with reason `"provides transitive dep {child} which is used undeclared"`. Remove from candidates for SAFE promotion.
   - **No** → carry forward to Phase 2 classification.
3. If the candidate also appears at depth > 1 in the tree (available transitively elsewhere) AND is explicitly declared → may be a version pin. Note `transitive_depth: N`.

Record `transitive_children_count` for each candidate.

### Step 1.3 — Parse Verbose Conflict/Duplicate Markers

Scan the full `dependency:tree -Dverbose` output for lines containing `(omitted for conflict with` or `(omitted for duplicate)`.

**Conflict-pin candidates**: A declared dependency whose tree entry includes `(omitted for conflict with X.Y.Z)` means Maven is **already ignoring it** in favor of another version pulled in transitively. These are strong removal candidates — the explicit declaration has no effect on the resolved classpath.

For each such dep:
- If it is in `unused_declared_candidates` → add to `conflict_pin_candidates[]` with field `winning_version: X.Y.Z` (the version Maven chose instead).
- If it is **not** in `unused_declared_candidates` (bytecode analysis says it's "used") → keep as-is; bytecode analysis may be detecting the transitively-resolved version.

**Duplicate-pin candidates**: A declared dep whose every tree occurrence is marked `(omitted for duplicate)` is fully redundant — another path already brings the exact same artifact at the same version.

For each such dep:
- If it is in `unused_declared_candidates` → add to `conflict_pin_candidates[]` with field `winning_version: "same (duplicate)"`.

Save to state: `used_undeclared_set`, `unused_declared_candidates[]`, `conflict_pin_candidates[]`.

---

## Phase 2 — Classify Candidates

**The default is KEEP. Promotion to SAFE requires all five conditions.**

### KEEP — Auto-Classified, Never Tested, Never Removed

Immediately classify as KEEP when any pattern matches:

| Pattern | Examples |
|---------|---------|
| Scope is not `compile` | `runtime`, `provided`, `test`, `import` |
| JDBC / database drivers | `mysql:mysql-connector-java`, `org.postgresql:postgresql`, `com.microsoft.sqlserver:mssql-jdbc`, `com.h2database:h2`, `com.oracle.database.jdbc:ojdbc*` |
| Logging and bridges | `ch.qos.logback:logback-*`, `org.apache.logging.log4j:log4j-*`, `org.slf4j:*` |
| Any Spring or Spring Boot artifact | `org.springframework.*:*`, `org.springframework.boot.*:*` |
| Annotation processors | `org.projectlombok:lombok`, `org.mapstruct:mapstruct-processor`, any ending in `-processor`, `-generator`, `-apt` |
| Jakarta / Java EE | `jakarta.*:*`, `javax.*:*` |
| Testcontainers | `org.testcontainers:*` |
| Reactor / Netty | `io.projectreactor:*`, `io.netty:*` |
| Jackson | `com.fasterxml.jackson.*:*` |
| AOP / proxy infrastructure | `org.aspectj:*`, `cglib:*`, `org.objenesis:*`, `net.bytebuddy:*` |
| Micrometer | `io.micrometer:*` |
| Agent JARs | any with classifier `javaagent` |
| BOM / dependency-management-only artifacts | any ending in `-bom`, `-dependencies` |
| Referenced in `src/main/resources` | found by grep in `.properties`, `.yaml`, `.xml`, `spring.factories` |

### VERIFY MANUALLY

Apply when any condition is true:

- Pre-classified in Phase 1.2 (provides a used-undeclared transitive).
- Possible reflective use: `Class.forName(...)` or `ServiceLoader.load(...)` found anywhere in `src/main/`.
- Declared in parent pom's `<dependencyManagement>` section (version management only).
- Artifact's known purpose is runtime despite `compile` scope declaration.

For each VERIFY MANUALLY entry, run a targeted grep and record results:

```bash
grep -r "{artifactId-base}" src/main/ \
  --include="*.java" --include="*.properties" \
  --include="*.yaml" --include="*.xml" 2>/dev/null | head -20
```

Any grep hit → reclassify as **KEEP** with reason `found in: <file:line>`.

### SAFE TO REVIEW — Promoted When ALL Five Pass

1. Scope is `compile`.
2. Not matched by any KEEP pattern above.
3. `dependency:analyze` lists it as "Unused declared".
4. No transitive child is in `used_undeclared_set` (Phase 1.2 passed).
5. Grep across `src/main/` (`.java`, `.properties`, `.yaml`, `.xml`) finds **zero** references.

**Conflict-pin fast-track**: Any entry in `conflict_pin_candidates[]` that is not matched by KEEP patterns and has zero grep hits is **automatically promoted to SAFE** — it does not need the 5-condition check. Maven has already stopped using it (conflict resolution chose another version). Record it with tag `conflict_pin: true` and `winning_version: {X}`. These go through the same compile test in Phase 5 as all other SAFE candidates.

**API/SPI artifacts** (ending in `-api`, `-spi`): these are no longer auto-KEEP. They go through the normal five-condition check. If all five pass, promote to SAFE and test them in Phase 5.

**When in doubt → VERIFY MANUALLY.** A conservative miss costs one review cycle. A wrong SAFE breaks the build.

Save to state: `safe_candidates[]`, `keep_candidates[]`, `verify_manually[]`.

---

## Phase 2.5 — Transitive Exclusion Candidates

**Purpose**: find unused transitive deps (pulled in by direct deps) that can be excluded via `<exclusions>` to reduce fat JAR size without removing a direct dependency.

### Step 2.5.1 — Collect All Transitive Deps

From `dependency:tree` output (Phase 1.2), collect every node at depth ≥ 2. For each record: `groupId:artifactId`, `version`, `scope`, `parent` (depth-1 ancestor), `depth`.

Skip `(omitted for duplicate)` and `(omitted for conflict)` nodes.

### Step 2.5.2 — Filter to Exclusion Candidates

A transitive dep is a candidate only when **all** conditions are true:

1. Scope is `compile`.
2. Not in `used_undeclared_set`.
3. Not matched by the KEEP patterns from Phase 2.
4. Grep across `src/main/` finds zero references.

Assign confidence:
- **HIGH**: leaf node (no further transitive children). Safest.
- **MEDIUM**: has transitive children, but none are in `used_undeclared_set` and none have grep hits.
- **LOW**: has transitive children where some children have other dependents in the tree, but still zero grep hits in `src/main/`. **Do not discard** — include in testing. Phase 5 compile test is the safety net.

Rationale for including LOW: if grep finds zero references in source and the dep is not in `used_undeclared_set`, the compile test will catch any actual usage. Excluding a LOW candidate from testing means missing real fat-JAR savings.

### Step 2.5.3 — Group by Parent

Group HIGH/MEDIUM/LOW candidates by their depth-1 parent `<dependency>`. This parent is where the `<exclusions>` block will be added.

For each parent, read its `<dependency>` block in pom.xml. Capture:
- `old_block`: exact current XML.
- `new_block`: same XML with `<exclusions>` inserted before `</dependency>`.

If an `<exclusions>` block already exists — append `<exclusion>` entries inside it rather than creating a new one.

Save to state: `exclusion_candidates[]`.

---

## Phase 3 — Save Progress State

Write `docs/dependency-cleanup/.cleanup-state-{branch}.json`:

```json
{
  "schema_version": 1,
  "branch": "{branch}",
  "saved_at": "{ISO datetime}",
  "last_completed_phase": "2.5",
  "project": {
    "type": "single-module | multi-module",
    "modules": ["{module paths}"],
    "root_artifact": "{groupId}:{artifactId}:{version}"
  },
  "baseline_jars": [
    { "path": "{jar path}", "size_bytes": 0, "size_human": "0 MB" }
  ],
  "used_undeclared_set": ["{groupId:artifactId}"],
  "conflict_pin_candidates": [
    {
      "module": "{module}",
      "groupId": "{groupId}",
      "artifactId": "{artifactId}",
      "winning_version": "{X.Y.Z or 'same (duplicate)'}",
      "scope": "compile"
    }
  ],
  "safe_candidates": [
    {
      "module": "{module}",
      "groupId": "{groupId}",
      "artifactId": "{artifactId}",
      "version": "{version}",
      "scope": "compile",
      "transitive_children_count": 0
    }
  ],
  "keep_candidates": [],
  "verify_manually": [],
  "exclusion_candidates": [],
  "import_cleanup": { "cleaned_files": [], "skipped_files": [] },
  "test_results": {
    "compile_verified_removals": [],
    "compile_verified_exclusions": [],
    "compile_failed": []
  },
  "after_jars": []
}
```

Print:
```
[cleanup-deps] Progress saved → docs/dependency-cleanup/.cleanup-state-{branch}.json
                Last phase: 2.5 | Safe candidates: {N} (incl. {N} conflict-pins) | Exclusion candidates: {N} (HIGH: {N}, MEDIUM: {N}, LOW: {N})
```

> If this session ends before Phase 5 completes, re-run `/cleanup-deps` — progress will be offered for resumption.

---

## Phase 4 — Remove Unused Imports (Targeted)

**Scope**: only process Java files with imports from packages associated with SAFE TO REVIEW candidates. This avoids touching unrelated code and keeps the cleanup focused.

### Step 4.1 — Derive Package Prefixes

For each SAFE TO REVIEW candidate, derive its Java package prefix:
- Extract `artifactId` base (strip version, remove hyphens, lowercase). Example: `commons-lang3` → `commons.lang3`, `lang3`.
- Grep `src/main/java` for import lines containing the artifactId-base string to discover the actual package (e.g. `import org.apache.commons.lang3.`).
- Record `package_prefix` for each candidate.

### Step 4.2 — Find and Remove Unused Imports Per File

For each Java file that contains an import from one of the identified package prefixes:

Check each matching import line:

| Import type | Check |
|-------------|-------|
| Wildcard `import com.example.*` | **SKIP always** — cannot verify safely |
| Regular `import com.example.Foo` | Extract `Foo`. Check `\bFoo\b` in file body (content after last consecutive `import` line). |
| Static `import static com.example.Foo.bar` | Extract `bar`. Check `\bbar\b` in file body. |

**Safety guards — never remove:**
- Simple class name ≤ 3 characters.
- Common Java names: `Map`, `List`, `Set`, `Optional`, `String`, `Object`, `Class`, `Type`, `Entry`, `Key`, `Value`, `Error`, `Exception`, `Builder`.
- Class name ends in `Annotation` or `Generated`.
- Package is `javax.*` or `jakarta.*`.
- Any doubt → **SKIP**.

### Step 4.3 — Apply Per File with Immediate Compile Check

Process **one file at a time**. Never batch across files.

For each file with at least one unused import candidate:

1. Store the original file content in memory.
2. Remove the unused import lines (Edit tool, or Write if removing multiple).
3. Run immediately:

```bash
mvn clean compile -q 2>&1 | grep -E "error:" | head -20
```

4. **Compile passes** → keep the changes. Record in `import_cleanup.cleaned_files[]`.
5. **Compile fails** → write the entire original file back using the Write tool. Record in `import_cleanup.skipped_files[]`. Do not try to identify the specific failing import — restore the whole file and move on.

After all files are processed, run a final check:

```bash
mvn clean compile -q 2>&1 | tail -5
```

`mvn clean` ensures no cached `.class` files mask the result. If this fails, stop and report. Do not proceed to Phase 5.

Update state: `import_cleanup`, `last_completed_phase: "4"`. Rewrite the state file.

---

## Phase 5 — Test-Apply, Compile-Verify, Measure JAR, Always Revert

This phase temporarily applies all SAFE TO REVIEW and transitive exclusion candidates, tests with `mvn clean compile`, measures the fat JAR size, then **unconditionally reverts every pom.xml**.

The developer never sees a modified pom.xml. They see a pre-verified report with real size numbers.

### Step 5.1 — Backup All Affected pom.xml Files

For every pom.xml that will be touched:
- Read the full file content.
- Store in `backup = { "relative/path/pom.xml": "<original content>" }`.

### Step 5.2 — Apply All Candidates Temporarily

For each SAFE TO REVIEW entry:
- Read its pom.xml (already backed up).
- Find and remove the exact `<dependency>` block.
- Write the modified file.

For each HIGH/MEDIUM exclusion candidate:
- Find its parent `<dependency>` block.
- Replace with the `new_block` (with `<exclusions>` added).
- Write the modified file.

Log each change: `[TEST-APPLY] {module}/pom.xml — removed <artifactId>` or `[TEST-EXCLUSION] {module}/pom.xml — excluded {artifactId} from <parent>`.

### Step 5.3 — Compile Test

```bash
mvn clean compile -q 2>&1
```

Capture the complete output.

### Step 5.4 — Evaluate Results and Isolate Failures

**If compile PASSES:**
- Mark all applied candidates as `COMPILE-VERIFIED`.
- Proceed to Step 5.5 (JAR measurement).

**If compile FAILS:**

Use **binary-search isolation** to find all valid removals rather than one-by-one removal. This is critical when many candidates are tested: a single bad dep should not block the rest from being confirmed safe.

1. Parse error output for missing class names (`cannot find symbol`, `package ... does not exist`, `error:`).
2. For each missing class, identify which removed dependency provided it (by groupId/artifactId patterns or known class-to-library mappings).
3. Re-add that `<dependency>` block to its pom.xml (Edit tool). Move that candidate: SAFE TO REVIEW → COMPILE-FAILED with reason `"compile failure: missing {ClassName}"`.
4. Re-run `mvn clean compile -q 2>&1`.
5. Repeat steps 1–4 until compile passes.
6. **Individual fallback sweep**: if after removing all identified failing candidates there are still more than 5 remaining SAFE candidates not yet individually verified, split the remaining candidates into two halves. Revert one half, test compile. If compile passes, the kept half is COMPILE-VERIFIED; re-apply the reverted half and repeat on it. If compile fails again, recurse on each half. This binary search ensures every valid candidate is confirmed even when causes are hard to attribute from error messages.
7. Remaining confirmed candidates = `COMPILE-VERIFIED`.

### Step 5.5 — Measure JAR Size After Apply (Before Reverting)

With the COMPILE-VERIFIED changes still applied, build the fat JAR:

```bash
mvn clean package -DskipTests -q 2>&1
```

Then find the resulting JARs:

```bash
find . -name "*.jar" -path "*/target/*" \
  -not -name "*-sources.jar" \
  -not -name "*-javadoc.jar" \
  -not -name "*.original" \
  -not -path "*/dependency/*" \
  2>/dev/null | sort
```

Record `after_jars[]` with `{ path, size_bytes, size_human }`.

Compute reduction per JAR:
- `reduction_bytes = baseline_size - after_size`
- `reduction_pct = (reduction_bytes / baseline_size) * 100`

If no baseline JAR was found in Phase 0, the "after" build IS the first measurement — note `"before: not available (no prior build found)"`.

### Step 5.6 — ALWAYS REVERT ALL POM.XML CHANGES

Restore **every** backed-up pom.xml to its original content, regardless of compile outcome:

For each entry in `backup`:
- Use Write tool to restore the original content exactly.

Log: `[REVERT] {module}/pom.xml — restored to original`.

Run a final compile to confirm the project is fully back to its pre-test state:

```bash
mvn clean compile -q 2>&1 | tail -5
```

Log: `[REVERT COMPLETE] All pom.xml files restored. Project is back to original state.`

If this final compile fails (unexpected), stop and report. Do not proceed to Phase 6.

### Step 5.7 — Record Final Results

- `compile_verified_removals[]` = direct dependencies confirmed safe to remove.
- `compile_verified_exclusions[]` = transitive exclusions confirmed safe to add.
- `compile_failed[]` = candidates that caused compile failure during testing.
- `verify_manually[]` = candidates not tested.

Update state: all `test_results`, `after_jars`, `last_completed_phase: "5"`. Rewrite the state file.

---

## Phase 6 — Generate Apply Script

Generate `docs/dependency-cleanup/apply-cleanup-{branch}.py`.

The script applies **only** entries in `compile_verified_removals[]` and `compile_verified_exclusions[]`.

### Script template

```python
#!/usr/bin/env python3
"""
Dependency Cleanup — Apply Script
Branch   : {branch}
Generated: {date}

All changes below were pre-verified: mvn clean compile passed with them applied.
Estimated JAR reduction: {reduction_human} ({reduction_pct:.1f}%)

Safety: backs up every pom.xml before modifying, runs mvn clean compile after
all changes, and automatically restores all files if the build breaks.

Usage:
  python3 apply-cleanup-{branch}.py             # apply + compile-verify
  python3 apply-cleanup-{branch}.py --dry-run   # preview only, nothing written
"""
import sys, os, re, subprocess

DRY_RUN = "--dry-run" in sys.argv
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

changes_applied = 0
_backups = {}   # pom_path -> original content, populated on first write per file


def resolve(rel):
    return os.path.join(PROJECT_ROOT, rel)


def _label(block):
    m = re.search(r"<artifactId>([^<]+)</artifactId>", block)
    return m.group(1) if m else block.strip()[:60]


def _restore_all():
    for path, original in _backups.items():
        with open(resolve(path), "w", encoding="utf-8") as f:
            f.write(original)
    print()
    print("[ROLLBACK] All pom.xml files restored to original state.")


def apply_changes(pom_path, removals=None, exclusion_replacements=None):
    global changes_applied
    abs_path = resolve(pom_path)
    if not os.path.exists(abs_path):
        print(f"  [ERROR]  {pom_path} not found — skipping")
        return

    with open(abs_path, "r", encoding="utf-8") as f:
        content = f.read()

    if pom_path not in _backups:
        _backups[pom_path] = content

    modified = content

    for block in (removals or []):
        if block in modified:
            modified = modified.replace(block, "", 1)
            while "\n\n\n" in modified:
                modified = modified.replace("\n\n\n", "\n\n")
            print(f"  [REMOVED]   {pom_path}  <{_label(block)}>")
            changes_applied += 1
        else:
            print(f"  [SKIP]      {pom_path}  <{_label(block)}> not found (already removed?)")

    for old_block, new_block in (exclusion_replacements or []):
        if old_block in modified:
            modified = modified.replace(old_block, new_block, 1)
            print(f"  [EXCLUSION] {pom_path}  <{_label(old_block)}>")
            changes_applied += 1
        else:
            print(f"  [SKIP]      {pom_path}  <{_label(old_block)}> not found (already updated?)")

    if modified == content:
        return
    if DRY_RUN:
        print(f"  [DRY-RUN]   Would write {pom_path}")
        return
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(modified)


# ── Changes (all pre-verified: mvn clean compile passed during analysis) ──────

{INSERT: one apply_changes() call per pom.xml that has at least one verified change}

# ── Compile verification + auto-rollback on failure ───────────────────────────

print()
if DRY_RUN:
    print(f"[DRY-RUN] {changes_applied} change(s) previewed. Run without --dry-run to apply.")
    sys.exit(0)

if changes_applied == 0:
    print("[DONE] Nothing to apply — all blocks already removed/updated.")
    sys.exit(0)

print(f"[DONE] {changes_applied} change(s) applied.")
print("Verifying build with mvn clean compile ...")

result = subprocess.run(
    ["mvn", "clean", "compile", "-q", "--no-transfer-progress"],
    capture_output=True, text=True, cwd=PROJECT_ROOT,
)

if result.returncode == 0:
    print("[COMPILE OK] Build is green.")
    print()
    print("Next steps:")
    print("  mvn clean package -DskipTests          # verify packaging + check JAR size")
    print("  mvn clean install                      # full test suite (requires Docker / local services)")
else:
    output = (result.stdout + result.stderr).strip()
    print("[COMPILE FAILED] Unexpected failure — reverting all changes.")
    print()
    for line in output.splitlines():
        if any(k in line for k in ("ERROR", "error:", "cannot find symbol", "does not exist")):
            print(" ", line)
    _restore_all()
    print()
    print("These changes were pre-verified during analysis, so this failure likely means")
    print("the project was modified since the report was generated.")
    print("Re-run /cleanup-deps to get a fresh report and script.")
    sys.exit(1)
```

### How to populate `apply_changes()` calls

Use **exact bytes** from the pom.xml as captured in Phase 5 Step 5.2. Do not reformat or reconstruct XML. The script relies on exact string matching — any whitespace deviation produces `[SKIP]`.

```python
apply_changes(
    "{module}/pom.xml",
    removals=[
        """\
{exact <dependency>...</dependency> block — indentation and newlines character-for-character}""",
    ],
    exclusion_replacements=[
        (
            """\
{exact old <dependency> block}""",
            """\
{exact new <dependency> block with <exclusions> inserted}""",
        ),
    ],
)
```

Omit `removals=` if the file has no removals. Omit `exclusion_replacements=` if it has no exclusions.

---

## Report

Derive branch: `git rev-parse --abbrev-ref HEAD`. Replace every `/` with `-`.
Create `docs/dependency-cleanup/` if it does not exist.
Write both files and tell the user their paths:

1. `docs/dependency-cleanup/CLEANUP-{branch}.md`
2. `docs/dependency-cleanup/apply-cleanup-{branch}.py`

````markdown
# Dependency Cleanup Report

> **Date**: {today's date}
> **Branch**: `{branch}`
> **Project**: {single-module | multi-module — modules: A, B, C, ...}

---

## JAR Size Impact

| Metric | Value |
|--------|-------|
| Fat JAR before (baseline) | {X.XX MB — or "not available (no prior build)"} |
| Fat JAR after (estimated, pre-apply test) | {X.XX MB} |
| Estimated reduction | {X.XX MB ({X}%)} |

> "After" size was measured by temporarily applying all confirmed-safe changes and running `mvn clean package -DskipTests`, then reverting. The actual post-apply size should match this estimate.

---

## How to Apply

Review the sections below, then apply when ready:

```bash
# 1 — Preview all changes (nothing written to disk)
python3 docs/dependency-cleanup/apply-cleanup-{branch}.py --dry-run

# 2 — Apply all pre-verified changes (auto-rolls back if build breaks)
python3 docs/dependency-cleanup/apply-cleanup-{branch}.py

# 3 — Verify packaging and confirm JAR size
mvn clean package -DskipTests

# 4 — Full test suite (requires Docker / local services to be running)
mvn clean install
```

---

## Summary

| | Count |
|-|-------|
| Direct dependencies — confirmed safe to remove | {N} |
| Transitive exclusions — confirmed safe to add | {N} |
| Candidates that failed compile test (kept) | {N} |
| Dependencies needing manual review | {N} |
| Dependencies kept (runtime / auto-config) | {N} |
| Unused imports removed | {N} |
| Import cleanup — files skipped (compile failed) | {N} |

---

## ✓ Confirmed Safe — Direct Dependency Removals

These were **temporarily applied and `mvn clean compile` passed**. They are not referenced by the project.

| Module | Dependency | Version | Transitive Children | Note |
|--------|-----------|---------|---------------------|------|
{one row per compile_verified removal; add "⚡ conflict-pin (Maven already ignored this)" in Note column for conflict_pin: true entries, or "> No safe removals found."}

{For each entry, show the exact XML block to be removed:}

### `{module}/pom.xml` — `{groupId}:{artifactId}`

```xml
{exact <dependency>...</dependency> block that will be removed}
```

---

## ✓ Confirmed Safe — Transitive Exclusions

These transitive dependencies are unused and were excluded during testing — `mvn clean compile` and `mvn clean package` passed. Excluding them reduces fat JAR size.

| Module | Add exclusion to | Exclude | Confidence |
|--------|----------------|---------|-----------|
{one row per compile_verified exclusion; include LOW-confidence entries that passed the compile test, or "> No safe exclusions found."}

{For each parent dependency with exclusions:}

### `{module}/pom.xml` — exclusion in `{parent groupId}:{parent artifactId}`

Replace the current block with:

```xml
{updated <dependency>...</dependency> block with <exclusions> inserted}
```

---

## ✗ Failed Compile Test — Project Uses These

These were applied during testing and **caused `mvn clean compile` to fail**. The project depends on them. Do not remove.

| Module | Dependency | Missing Class During Test |
|--------|-----------|--------------------------|
{one row per compile_failed entry, or "> None — all candidates compiled cleanly."}

---

## ⚠ Needs Manual Review — Not Tested

These were excluded from the compile test because they may be needed via reflection, Spring auto-configuration, or runtime loading. Investigate before removing.

| Module | Dependency | Version | Reason |
|--------|-----------|---------|--------|
{one row per verify_manually entry, or "> None."}

---

## ✓ Unused Imports — Already Cleaned

These import statements were removed from packages of SAFE candidates and verified by `mvn clean compile`. No further action needed.

| File | Imports Removed |
|------|----------------|
{one row per cleaned file, or "> No unused imports found."}

{If any files were skipped:}

### Skipped Files — Imports Restored

| File | Reason |
|------|--------|
{one row per skipped file}

---

## ℹ Used Undeclared — Consider Declaring Explicitly

These classes are used in bytecode but sourced only via transitive dependencies. They work today but may break silently if the providing dependency changes scope or version.

| Module | Dependency | Version | Provided Via |
|--------|-----------|---------|-------------|
{rows, or "> None found."}

---
````

---

## Post-Report — Guide Next Steps

After writing both files, print:

```
Dependency cleanup analysis complete.

  Report : docs/dependency-cleanup/CLEANUP-{branch}.md
  Script : docs/dependency-cleanup/apply-cleanup-{branch}.py

  JAR size before : {X.XX MB}
  JAR size after  : {X.XX MB} (estimated)
  Reduction       : {X.XX MB} ({X}%)

Review the report, then:
  python3 docs/dependency-cleanup/apply-cleanup-{branch}.py --dry-run   # preview
  python3 docs/dependency-cleanup/apply-cleanup-{branch}.py             # apply

After applying, run mvn clean install to verify the full test suite.
NOTE: mvn clean install requires Docker and local services (DB, Kafka, etc.) to be running.
```

Do **not** automatically run `mvn clean install`. The developer must apply the script first and confirm their environment is ready.

Delete the progress state file after the report is successfully written:
- `docs/dependency-cleanup/.cleanup-state-{branch}.json` → delete (work is complete).

---

## Constraints

- **pom.xml is never permanently modified by this skill.** Phase 5 applies changes temporarily for testing only, then always reverts every file. The only path to permanent pom.xml changes is the developer running the apply script.
- **Phase 5 must always revert — even if compile passes.** Revert is unconditional. The developer must consciously run the apply script.
- **Always use `mvn clean compile`, never bare `mvn compile`.** pom.xml dependency removals do not modify any `.java` source file, so Maven's incremental compiler reuses cached `.class` files in `target/` and silently skips recompilation — making a broken build appear to pass. `mvn clean` wipes `target/` first, forcing a full recompile from scratch. This applies to Phase 4 (imports), Phase 5 (test-apply), and the apply script.
- **Import removal is targeted.** Only remove imports from packages associated with SAFE TO REVIEW candidates. Never scan unrelated files.
- **Import removal: compile per file, restore whole file on failure.** Never batch across multiple files. Never try to identify the specific failing import — restore the entire file and skip it.
- **KEEP is the default.** A dependency must satisfy all five SAFE conditions before being tested. When uncertain, use VERIFY MANUALLY.
- **Spring, Reactor, Netty, Jackson, SLF4J, Logback, JDBC drivers are always KEEP.** Bytecode analysis cannot detect auto-configuration, SPI, or runtime class loading.
- **`-api` and `-spi` artifacts are not auto-KEEP.** They go through the normal five-condition check. Only `-bom` and `-dependencies` artifacts are auto-KEEP (they exist solely for version management).
- **Conflict-pin candidates (omitted for conflict) are fast-tracked to SAFE** — Maven has already excluded them from the resolved classpath. Still tested via compile in Phase 5.
- **LOW confidence transitive exclusion candidates are included in Phase 5 testing.** The compile test is the safety net. A dep with zero grep hits and zero `used_undeclared_set` membership is worth testing even if it has transitive children.
- **Phase 5 uses binary-search isolation when batch compile fails.** A single bad removal candidate does not block all other candidates from being confirmed safe.
- **Progress is saved after Phase 2.5 and after Phase 5.** If the session ends mid-run, the next invocation offers to resume from the saved state rather than re-running all Maven commands.
- **Apply script uses exact byte matching.** Embed XML blocks character-for-character as read from the file. Any whitespace change causes a `[SKIP]`.
- **Apply script always backup + compile + rollback.** Even though changes are pre-verified, the project may have changed since the report was generated. The script never leaves the project in a broken state.
- **Never run `mvn clean install` automatically.** Always require the developer to confirm their environment (Docker, DB, Kafka) is ready first.
