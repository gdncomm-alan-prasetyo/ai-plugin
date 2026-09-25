---
name: docs-database
description: >
  Writes docs/database/: an index with a Mermaid ER diagram plus one page per collection or
  table -- fields, types, indexes, relations -- from Java persistence classes (Spring Data
  MongoDB @Document or JPA @Entity) by static analysis. Use when asked to "document the
  database", "document the schema", "generate an ER diagram", or to capture a baseline
  before a schema migration.
argument-hint: "[path to entity/document source, or repo root]"
allowed-tools: ["Bash(python*)", "Read", "Glob", "Grep", "Write", "Edit"]
---

# Database Docs (Mongo/JPA entities -> Markdown + Mermaid ERD)

Bootstraps `docs/database/*.md` from Java `@Document` (Spring Data MongoDB) or `@Entity`
(JPA/Hibernate) classes by reading source text -- no DB connection, no running app, no
migrations to replay. Fields, types, and indexes are close to mechanical to extract this
way; **relations are not** -- the hardest and most valuable part of this skill is telling
apart a real, enforced relation from a same-shape-as-a-relation naming convention that the
database itself knows nothing about. Treat the output the same way as the sibling
`docs-code-to-openapi` skill's: a strong first draft, verified against source before
you trust it, not a finished document.

## Workflow

1. **Run the script** against the module/repo that holds the entity classes:

   ```bash
   python ${CLAUDE_PLUGIN_ROOT}/skills/docs-database/scripts/generate_db_docs.py <path> \
     --output-dir docs/database --title "<Service name> Database Schema"
   ```

   Point it at the repo root (or the specific module that owns the persistence model) --
   it walks the tree (skipping `target/`, `build/`, `node_modules/`, `.git/`, and test
   sources) looking for classes annotated `@Document` or `@Entity`; everything else is
   parsed but silently ignored, so pointing it too broadly costs time, not correctness.

2. **Read every warning on stderr before trusting the output.** In particular:
   - `@Document`/`@Table` collection/table name resolved from a non-literal constant
     reference that isn't a `static final String` in the *same* class -- the script only
     chases same-class constants (the common idiom), not constants imported from another
     class/file, and falls back to a decapitalized-class-name guess when it can't resolve
     one. That guess is frequently wrong; open the file and read the real value.
   - `@Entity` with no explicit `@Table(name=...)` -- the table name in the doc is the bare
     class name, but Hibernate's naming strategy (commonly `CamelCase` -> `snake_case`) may
     mean the actual table is named differently. Verify against a migration file
     (Flyway/Liquibase) or the actual schema if you have access to either.
   - A relation annotation (`@DBRef`/`@OneToMany`/etc.) whose target type isn't among the
     scanned classes -- usually means you pointed the script at too narrow a path (the
     target entity lives in a sibling module) rather than a real problem with the code.

3. **Distinguish hard relations from soft ones, and give the soft ones real scrutiny.**
   The doc marks every relation one of two ways:
   - **Hard reference** -- backed by an actual annotation (`@DBRef`, `@OneToMany`,
     `@ManyToOne`, `@OneToOne`, `@ManyToMany`, JPA `@JoinColumn`). The database or the ORM
     itself understands this relation.
   - **Soft reference** -- inferred purely from a naming convention: a `String` or
     collection-of-`String` field named like `<otherEntity>Name(s)` (e.g. `appName`,
     `roleNames`), optionally prefixed with a hierarchy word (`childrenRoleNames`). This is
     an extremely common pattern in domains where **names, not generated IDs, are the
     stable identifier** a service's own code treats as a foreign key -- but nothing in the
     database enforces it: there's no constraint stopping a document from referencing a
     name that doesn't exist. The doc also flags a **low-confidence** tier for a bare
     plural field with no `Name`/`Names` suffix at all (e.g. `roles: Set<String>` on a
     `UserRole`-shaped entity, almost certainly `Role` names) -- these are guesses from a
     weaker signal and need more scrutiny than the `Name`/`Names`-suffixed ones. For every
     soft reference in the doc, before trusting it: open the service/repository code and
     confirm something actually queries the target collection using that field's value --
     that's the real proof the relation exists, the field name is only a clue.
   - **Soft references the script cannot see at all**: any relation expressed purely in
     application code with no annotation and no name-matching convention (e.g. a field
     called `ownerId` that's actually a foreign key to a `User` collection by a different
     naming scheme, or a lookup keyed by a compound/derived value). Grep the service layer
     for repository/query calls that filter one collection by a field whose value came from
     another collection's document -- that's the general technique for finding these by
     hand when the naming convention doesn't give it away.

4. **Sanity-check the Mermaid diagram renders and reads sensibly** -- paste it into a
   Markdown previewer that supports Mermaid (or the repo host, if it renders `.md` files
   with Mermaid fences) and confirm the cardinality symbols match what you just verified by
   hand in step 3. Mermaid `erDiagram` cardinality notation, if you need to hand-edit an
   edge:

   ```
   A ||--o{ B : "label"     one A has many B (A is the "one" side, on the left)
   A }o--o{ B : "label"     many-to-many
   A ||--|| B : "label"     one-to-one
   ```

   Collections/tables with no detected relations are listed separately below the diagram
   rather than drawn as isolated nodes -- add them into the diagram by hand if a real
   relation exists that this pass didn't catch.

5. **Fill in `## Purpose` on every page.** The script emits the heading with a `_TODO_`
   placeholder and lists every unfilled one on stderr. Write one or two plain-language
   sentences: what a document represents, and when one is created and removed. The script
   only sees field names and types, so this is the part it structurally cannot produce.

   **These sections survive regeneration.** `## Purpose`, `## Query shapes` and `## Notes`
   are harvested from the existing file and carried forward on the next run; everything else
   is rebuilt from source and any hand-edit to it is lost. `--no-preserve` forces a clean
   regeneration. The first sentence of each `## Purpose` becomes the "What it holds" column
   in `docs/database/README.md`, so write it as a standalone sentence.

   Also correct any field whose Java type doesn't tell the full story (a `String` that is
   really a JSON-encoded blob, a `Map<String, Object>` whose shape varies by a discriminator
   elsewhere) -- but note those corrections live in the `Notes` column, which **is**
   regenerated, so record anything you need to keep under `## Notes` instead.

6. **Cross-check against `docs/domain.md` / `docs/architecture.md` if this repo already has
   them** (see the `docs-domain` and `docs-architecture` skills) -- the domain doc's "Core
   concepts" and relationship diagram should agree with what this pass found; if they don't,
   that's a discrepancy worth surfacing (one of the two was written from an incomplete pass,
   or the code changed since).

## What it recognizes

- **MongoDB (Spring Data)**: `@Document(collection = "...")` (including a same-class
  `static final String` constant reference, resolved automatically), `@Id`, `@Field`,
  `@Indexed(unique = ...)`, `@CompoundIndex(def = ..., unique = ...)` /
  `@CompoundIndexes({...})`, `@DBRef`, `@Transient`, `@Version`, and Spring Data auditing
  (`@CreatedDate`/`@LastModifiedDate`/`@CreatedBy`/`@LastModifiedBy`).
- **JPA/Hibernate**: `@Entity`, `@Table(name = "...")`, `@Column(name=..., nullable=...)`,
  `@Id`, `@OneToMany`/`@ManyToOne`/`@OneToOne`/`@ManyToMany` (target entity read from the
  field's own type, unwrapping `List<T>`/`Set<T>`/`Collection<T>`), `@JoinColumn`,
  `@Transient`, `@Version`.
- **Inheritance**: fields declared on a superclass (a common `BaseEntity`/`AbstractEntity`
  pattern carrying `id` + audit fields) are resolved and merged into every subclass that
  extends it, marked "inherited from `X`" -- as long as the superclass is in the same
  scanned path. If it isn't, the doc says so explicitly rather than silently omitting those
  fields.

## Heuristics and limitations worth knowing about

- **Java only.** This is a regex + bracket-depth scanner tuned for Java source, the same
  approach as `openapi-from-controller`. A repo using Prisma, Mongoose/TypeORM, Django ORM,
  SQLAlchemy, ActiveRecord, or raw SQL migration files needs this done by direct
  comprehension instead -- read the schema files, apply the same conceptual checklist
  (fields/types, hard vs. soft relations, indexes), and write the Markdown + Mermaid by
  hand. The doc structure and relation-classification thinking in this skill still applies;
  the script just doesn't parse those formats.
- **One top-level class per file is assumed**, matching normal Java convention. A file with
  multiple top-level classes only has the first one recognized.
- **The soft-reference heuristic is a naming-convention guess, not a fact.** It will both
  miss real relations that don't follow either the `Name(s)`-suffix or bare-plural
  convention, and could in principle flag a coincidental name match that isn't actually a
  reference -- always verify against real query code (step 3 above), never cite it as
  ground truth on its own.
- **Class-level annotations are found by scanning everything between the end of imports and
  the `class` keyword**, since that's the only place Java allows them -- robust to
  annotation ordering and other annotations (`@Data`, `@Builder`, ...) mixed in, but assumes
  a single class declaration per file.
- **Compound/multi-field unique constraints** are surfaced (`@CompoundIndex`), but composite
  *foreign* keys (a relation spanning more than one field) aren't specifically modeled --
  they'll show up as two separate single-field relations if each half happens to match a
  naming convention, which may need manual correction into one compound relation note.

## Why comprehension-driven for relations, mechanical for fields

Field names and declared Java types are a near-direct transcription -- a script extracts
them reliably. Whether a same-named-as-a-reference field is *actually* a relation the rest
of the codebase depends on, versus coincidence, is a judgment call about intent that only
reading the surrounding service/repository code can settle. This mirrors the same
division of labor as `docs-architecture`/`docs-domain`: automate what's genuinely mechanical,
flag everything else as a heuristic guess that needs a human (or an agent reading the
actual query code) to confirm.

## CLI reference

```
python generate_db_docs.py <path> [--output-dir docs/database] [--title TITLE] \
    [--include-tests] [--warnings-json warnings.json]
```
