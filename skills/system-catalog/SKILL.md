---
name: system-catalog
description: >-
  Build and refresh the IAM multi-system knowledge base (flat references/system-*.md files).
  Scans a mapped repo, regenerates the derivable sections (Exposes, Depends on),
  and preserves the human-authored ones (Consumed by, Owner, Notes). Use when
  asked to refresh the system catalog, add a system, or update cross-system
  knowledge. Read when reasoning about cross-system impact.
---

# System Catalog

## Announce

Print before output:
```
[system-catalog] Phase: <refresh | add>
```

Maintains the multi-system knowledge base — flat files `references/system-<name>.md` plus `references/system-index.md`. Read (via `~/.claude/references/`) when a ticket's blast radius crosses system boundaries.

**Run this skill from inside the iam-agentic-ai skills repo** — it writes the canonical `references/` files there; commit and re-run `install.sh` to ship them. Scans of target repos happen in those repos (by their mapped paths).

## Two kinds of knowledge, maintained differently

| Section | Kind | This skill |
|---|---|---|
| `## Exposes` | derivable — grep the repo | **regenerates** every run |
| `## Depends on` | derivable — grep outbound calls | **regenerates** every run |
| `## Consumed by` | durable — callers live in *other* repos | **preserves**, never overwrites |
| `## Owner`, `## Notes` | durable — intent, not code | **preserves**, never overwrites |

The rule: regenerate what code knows, never touch what it does not. A refresh that wipes a human-written `Consumed by` is a bug.

## Agent behavior

- **Preserve durable sections byte-for-byte.** Read the existing file, keep `Consumed by` / `Owner` / `Notes`, replace only `Exposes` / `Depends on`.
- **Ground every derived line.** An endpoint or dependency with no grep hit does not go in. No guessing a contract.
- **Stamp the sync.** Every refresh writes `_synced: HEAD <sha> at <date>_` so a stale entry is visible.
- **Never invent a system.** Only systems in `references/component-map.md` get a catalog file. Unmapped repo → add it to the map first.
- **Do not edit production code.** This skill writes `references/system-*.md` only.

---

## Refresh a system

`--system <component>` (one) or `--all` (every row in the map).

### Step 1 — Resolve the repo

Read `references/component-map.md` (repo-relative — you run from the skills repo). Get the row's `Repo` and `Type`. Repo not on disk → report it, skip; cannot scan what is not cloned.

### Step 2 — Scan derivable sections

`cd` into the repo. By `Type`:

**backend (Spring/Java):**
```bash
# Exposes — endpoints
grep -rnE "@(Get|Post|Put|Patch|Delete|Request)Mapping" --include="*.java" src 2>/dev/null
grep -rn "@RestController" --include="*.java" src 2>/dev/null
# Exposes — events published
grep -rnE "kafkaTemplate|@SendTo|topic" --include="*.java" src 2>/dev/null
# Depends on — outbound calls
grep -rnE "@FeignClient|WebClient|RestClient|GraphServiceClient" --include="*.java" src 2>/dev/null
grep -rn "@KafkaListener" --include="*.java" src 2>/dev/null   # events consumed
# Depends on — datastores / external config
grep -rnE "@Document|@Entity|application.*\.yml" --include="*.java" --include="*.yml" 2>/dev/null | head
```

**frontend (Vue):**
```bash
# Depends on — backend APIs called
grep -rnE "axios|fetch\(|/api/" --include="*.js" --include="*.ts" --include="*.vue" src 2>/dev/null
# Exposes — routes/pages
grep -rnE "path:|component:" --include="*.js" --include="*.ts" src/router 2>/dev/null
```

Interpret the hits into a clean contract list — group endpoints by controller, name each external dependency once. Raw grep dumps do not go in the file; a curated list does.

### Step 3 — Rewrite, preserving durable

Read the existing `references/system-<component>.md` if present. Replace only `## Exposes` and `## Depends on`. Keep `## Consumed by`, `## Owner`, `## Notes` exactly. Update the sync stamp. New system → scaffold from the template below, leave durable sections as `_to fill_`.

### Step 4 — Update the index

Rewrite the system's one-line entry in `references/system-index.md` (responsibility + type). Keep it to one line — the index is the only always-loaded file.

Report: systems refreshed, HEAD each was synced at, any repo skipped (not cloned).

---

## Per-system template

```markdown
# <component>

<one-sentence responsibility>

_synced: HEAD <sha> at <date>_

## Exposes
<curated endpoints / events — derivable>

## Depends on
<external systems, datastores, config — derivable>

## Consumed by
_to fill — callers live in other repos; add as you learn them_

## Owner
_to fill — squad / person_

## Notes
_to fill — deprecations, gotchas, why. Durable intent code cannot give._
```

## Completing the full catalog

`--all` only reaches repos on disk and rows in the map. To cover every IAM system:

1. Add every system to `references/component-map.md` (component → repo → type).
2. Clone or point at each repo, run `system-catalog --all` from the skills repo.
3. Hand-fill the durable sections — `Consumed by` especially, since a repo cannot see who calls it.

The derivable half fills itself from the scan; the durable half is the team's knowledge and must be written, not generated.

---

## Common Pitfalls

- **Overwriting `Consumed by`.** It is cross-repo knowledge the scan cannot produce. Preserve it always.
- **Guessing a contract.** No grep hit, no line. A fabricated endpoint is worse than a missing one.
- **Skipping the sync stamp.** Without it, no one can tell a fresh entry from a year-stale one.
- **Cataloguing an unmapped repo.** Add it to `component-map.md` first — the map is the driver.
- **Dumping raw grep.** Curate hits into a readable contract; readers want prose, not match lists.
