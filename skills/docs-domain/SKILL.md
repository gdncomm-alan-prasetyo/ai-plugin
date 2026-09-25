---
name: docs-domain
description: >
  Writes docs/domain.md: the business concepts a codebase implements, their relationships and
  cardinality, naming and identity conventions, mutation semantics (replace-vs-merge,
  idempotency, partial success), and behaviour imposed by an external system rather than by
  the domain. Read out of the persisted entities and exposed operations, in business language,
  verified against source. Use when asked to "summarize the domain model", "explain the
  business logic", or what a codebase does at a business level. Companion to
  docs-architecture.
argument-hint: "[repo path]"
allowed-tools: ["Read", "Glob", "Grep", "Write", "Edit"]
---

# Domain Docs

Answers "what is this software actually *for*, in business terms" -- `docs/domain.md`,
written *from evidence gathered in this pass*, not from what a domain of this shape
"usually" looks like. The goal is a document that lets a reader (human or a future AI
agent) reason about business rules and data relationships without re-reading every
controller and entity class from scratch, and without being misled by stale hand-written
docs that have drifted from the code.

This is entirely comprehension-driven -- there is no script that can correctly say "what a
Role hierarchy means to this business" for you. The whole value of this skill is a workflow
and a set of hard-won heuristics for where the non-obvious domain facts tend to hide,
gathered from doing this by hand on a real, unfamiliar codebase.

## Workflow

1. **Read the persisted entities/DTOs and the operations exposed on them**, then ask: what
   are the *nouns* this software's users actually reason about -- not `Repository`,
   `Controller`, `Config` (those are architecture, not domain) -- but the real business
   concepts (an `Order`, a `Role`, a `Permission`). For each one, work out what it means in
   plain language, independent of how it's implemented.

2. **Work out cardinality and hierarchy between the core concepts.** Is a relationship
   one-to-many or many-to-many in practice (not just what the type signature allows)? Is
   there a self-referential hierarchy (a `Role` that can have child `Role`s, forming an
   inheritance/expansion chain)? Is there one entity that bridges two otherwise-separate
   "worlds" the domain deliberately keeps apart (e.g. an assignment/join entity linking an
   externally-owned identity to an internally-owned authorization model)? Naming that split
   explicitly, if one exists, is usually the single most useful sentence in the whole doc.

3. **Chase naming and identity conventions** -- these are where real bugs and real
   surprises hide, and they're almost never written down anywhere else:
   - Case normalization on write (is a name upper-cased, trimmed, slugified before storage?).
   - ID format differences between endpoints -- is a user/entity identified the same way
     everywhere, or does it vary by which subsystem or endpoint generation you're calling?
   - Any documented-as-temporary backward-compatibility shim that silently rewrites input
     (a default value auto-appended, an old field still accepted alongside a new one).
   - Which field is the *real* stable identifier from an API consumer's point of view --
     often a human-meaningful name that's "create if missing, update if present" on every
     write, not an internally-generated ID the consumer never sees or supplies.

4. **Tabulate replace-vs-merge semantics.** For every mutation that touches a list/set
   field, is the new value additive (merged with what's already there) or a full
   replacement -- and is that controlled by an explicit flag, with what default when the
   flag is omitted? This is a recurring shape worth one shared table across entities rather
   than re-describing per-endpoint prose each time it comes up.

5. **Work out idempotency and partial-success behavior on bulk operations.** Does a bulk
   call fail atomically (all-or-nothing), or does it report per-item success/failure -- and
   at what status code, if this is an HTTP API (a real partial-success status like HTTP 207
   is easy to miss if you only read method signatures, since it's often set conditionally at
   a specific call site rather than declared on the endpoint). Is a repeated/duplicate call
   safe to retry, or does it error the second time?

6. **Spell out core business-rule resolution logic as a short numbered sequence** wherever
   there's a non-trivial one (a permission/access check, a routing/matching decision, an
   eligibility calculation) -- and always include the "what happens on failure/unknown"
   branch explicitly (does it error, or silently resolve to a safe default like "not
   allowed"?). This branch is the single most commonly *undocumented* and most commonly
   *load-bearing* fact in a domain doc; don't skip it even under time pressure.

7. **Flag anything shaped by an external system rather than by this domain.** If part of the
   API proxies straight through to a third-party service, that service's own
   pagination/filtering/field-naming conventions often leak through directly into this
   domain's surface and won't match the conventions of the rest of the API (e.g. one part of
   the API supports real page numbers because it's a local query, another only supports
   infinite-scroll tokens because it's proxying an external provider's own search). Calling
   this out saves a future reader from assuming false consistency across the whole API.

8. **Cross-check every non-obvious claim against the code, and report disagreements rather
   than silently resolving them.** If the repo has existing hand-written business-rule docs
   (`documentations/`, a wiki export, a `docs/api/` folder generated from an OpenAPI spec) or
   comments/Javadoc describing domain behavior, treat them as evidence to verify, not ground
   truth to copy -- they drift out of sync with code. For every non-obvious claim (a field is
   optional, a default is applied, an endpoint means X), find the line of code that would
   prove or disprove it before writing it into `docs/domain.md`. When a doc/comment and the
   code disagree, the code wins for what the doc should *say*, but the disagreement itself
   is worth surfacing to the user -- it usually means either the doc is stale or the code has
   a real bug, and that's their call.

9. **Write `docs/domain.md`.** Use the skeleton in `references/example.md`. **Its H2 headings
   are fixed** -- verbatim, in order, every one present. Adapt the *content* to this domain,
   never the heading set: a domain with no bulk endpoints gets a sentence saying so under
   `## Bulk operations`, not a deletion. That is what makes a later reader able to jump to
   `## Replace vs. merge semantics` in any repo. Extra sections go after the fixed set. Full
   rules: `~/.claude/references/doc-output-conventions.md`.
   If a `docs/architecture.md` already exists (see the companion `docs-architecture` skill),
   link to it for "how these concepts are actually implemented and served" instead of
   duplicating technical detail here -- keep this document in business language throughout.

10. **Spot-check the finished doc against source once more before calling it done** -- pick
    a handful of specific claims (a resolution rule, a status code, a naming convention) and
    re-verify each one directly. It's easy to introduce a small error while writing prose
    from notes; catching it now is cheaper than a future reader trusting a wrong claim.

11. **Offer, don't assume, a `CLAUDE.md` pointer.** If the repo doesn't already have a
    `CLAUDE.md` (or equivalent agent-instructions file), ask whether to add one linking to
    `docs/domain.md` (and `docs/architecture.md` if that exists too) so future sessions check
    it before re-deriving business rules from scratch -- this is a repo-root file affecting
    how every future session behaves in this repo, so confirm rather than adding it
    unprompted.

12. **Write the gaps into `## Known gaps`, then report them.** A rule inferred from naming
    rather than traced, an entity whose lifecycle wasn't followed end to end, a business rule
    only fully knowable by asking a human. Putting them in the document rather than only in
    chat is the point: a chat message is gone next session, and a reader who cannot tell a
    verified claim from a plausible one has to re-verify all of them. Then summarize the same
    list for the user -- don't imply full coverage if there are parts you didn't get to.

## Why comprehension-driven, not scripted

Unlike a spec-shaped artifact (an OpenAPI YAML, a database schema doc), "what does this
entity mean to the business" and "what's the real relationship between these two concepts"
require reading code and judging intent -- there is no mechanical transformation from
source text to a correct answer here, not even the partial mechanical grounding that the
companion `docs-architecture` skill gets from dependency-manifest parsing. The entire value
of this skill is the checklist of where non-obvious domain facts hide (naming conventions,
replace-vs-merge flags, the failure branch of a resolution rule) -- gathered from doing this
by hand on a real, unfamiliar codebase -- not any automation.
