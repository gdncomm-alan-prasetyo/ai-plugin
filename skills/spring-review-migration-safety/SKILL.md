---
name: spring-review-migration-safety
description: Reviews migration files for rollout safety during rolling deploys. Checks expand-contract compliance, index blocking, Flyway/Liquibase/Mongock tool risks, and code-before-migration null guard requirements.
---

# Spring Review — Data Migration Rollout Safety

## Model Guidance

Fast-tier. First output line: `[spring-review-migration-safety] running on: {model} (fast-tier)`
No escalation — all checks are binary (nullable column? background flag? checksum modified? changeset reordered?). No reasoning-tier consultation.

---

## Phase 0 — Change Set

Diff slice provided in prompt → use it, skip cache. Read migration files from disk for full content.

Else read `.review-context.md`. Validate: first line = `<!-- review-context: <hash> -->`. Absent/stale → stop: "Run `review-context` first."

Focus on:
- Migrations: `src/main/resources/db/migration/`, `src/main/resources/mongock/`, or similar
- Entities: `*Entity.java`, `*Document.java` (implied schema changes)

---

## Phase 14 — Data Migration Rollout Safety

Database migrations run while application is deploying. During rolling deploy, old and new code versions run simultaneously against same database. Migrations must be safe for both versions.

### 14.1 Expand-Contract Pattern

| Step | What happens |
|------|-------------|
| **Expand** (migration runs first) | Add new column/field as **nullable**. Old code ignores it; new code writes it. |
| **Contract** (after all instances on new code) | Add NOT NULL constraint or remove old column in **separate, later** migration. |

```
MIGRATION ROLLOUT RISK: Non-backward-compatible migration
  Migration: <filename>
  Change: Adding non-nullable column / renaming column / dropping column
  Risk: Old code (still running during rolling deploy) will fail to insert rows without
        new column, or will write to old column name that no longer exists.
  Fix: Split into two migrations:
    Step 1 (this deploy): Add column as nullable. New code writes both old and new fields.
    Step 2 (next deploy): Remove old column / add NOT NULL once all pods are on new code.
```

### 14.2 Index Creation Blocking

| Database | Risk | Safe approach |
|----------|------|--------------|
| **MongoDB** | `db.collection.createIndex(...)` without `{background: true}` (pre-4.2) blocks entire collection. Post-4.4 uses concurrent index builds — verify driver version. | Use `{background: true}` for older versions; on 4.4+ ensure no explicit foreground flag. |
| **PostgreSQL** | `CREATE INDEX` takes `AccessShareLock` that blocks writes. | Use `CREATE INDEX CONCURRENTLY`. |
| **MySQL** | `ALTER TABLE ... ADD INDEX` uses Online DDL by default in InnoDB — verify `ALGORITHM=INPLACE, LOCK=NONE` for large tables. |

Per new index in migration file:

```
INDEX CREATION RISK: Potentially blocking index build
  Migration: <filename>
  Index: <indexName> on <collection/table>
  Risk: Foreground index build on large collection blocks all writes for duration.
  Fix: MongoDB: { background: true } or verify MongoDB ≥ 4.4
       PostgreSQL: CREATE INDEX CONCURRENTLY <indexName> ON <table> (<columns>)
```

### 14.3 Migration Tool–Specific Risks

#### Flyway

| Risk | Check |
|------|-------|
| **Edited existing migration** | Flyway computes checksum of each file. Editing applied migration fails next run with `Validate failed: Migration checksum mismatch`. Never edit applied migrations — create new one. |
| **Missing undo script** | For destructive migrations (DROP COLUMN, DROP TABLE), corresponding undo script should exist. |

#### Liquibase

| Risk | Check |
|------|-------|
| **`runOnChange: true` on large changesets** | Re-runs changeset on any file change — can be slow or destructive on production data. |
| **No `rollback` block** | Changesets for destructive operations should include `<rollback>` block. |

#### Mongock

| Risk | Check |
|------|-------|
| **`@ChangeUnit` order changed** | Mongock executes changesets by order. Moving or renaming applied changeset can cause re-execution or skip. Never reorder applied changesets. |
| **Non-idempotent changeset** | Changeset failing partway through and retried may leave data corrupt. Use `runAlways = false` (default); ensure each changeset is idempotent (check-before-insert pattern). |
| **`failOnMissingTarget`** | If changeset targets collection that doesn't yet exist and `failOnMissingTarget` is `true`, migration aborts. |

### 14.4 Code-Before-Migration Safety

When new code deploys **before** migration runs:
- New code reading new field gets `null` from old schema — verify null handled gracefully.
- New code writing new field to old schema may fail if column/field doesn't exist yet.

```
MIGRATION SEQUENCING RISK: Code may run before migration
  Migration: <filename>
  Field / column: <name>
  Risk: If code deploys before migration runs, reads return null.
  Fix: Add null guard: if (entity.getNewField() == null) { /* handle legacy */ }
```

---

## Return Format

Return findings only — no OK tables, no empty sections, no rows for passed checks.

Per finding:

```
MIG-{n} | P0|P1|P2 | {file:line} | {short title}
  problem: {what + why it matters — 1–2 sentences}
  fix: {concrete fix. P0: verbatim Before/After code blocks mandatory. P1/P2: description enough}
```

Number findings sequentially. P0 = must fix before merge. P1 = should fix before merge. P2 = follow-up.
Body finding templates above define required content — fold their fields into `problem:`/`fix:` lines.

Last line — checks summary over: `expand_contract, index_blocking, tool_risks, code_before_migration`.
`checks: risk=[{failed}] ok=[{passed}] na=[{not applicable}]`

No findings → return `MIG: no findings.` + checks summary.

---

## Constraints

- **Read migration files**: Always read actual migration file content before reporting risk.
- **Never edit applied migrations**: For Flyway/Mongock, editing applied migration is always P0.
- **Expand-contract mandatory**: Adding non-nullable column without nullable step is always P0.
- **Index creation blocking**: Foreground build on large collection can take minutes and block all writes.

---

## Output

Sub-agent: return findings per Return Format — never write files. Standalone: write same findings to `docs/code-review/CODE-REVIEW-{branch}.md` (branch from `**Branch**` in `.review-context.md`; sanitize `/`, `#`, `(`, `)`, space → `-`); tell user path.
