# Worked example: "Notification Gateway"

Continues the same fictional service used in the companion `docs-architecture` skill's
reference example, to show what this skill's output looks like for the domain side.
Imagine: a Spring Boot service that fronts three external providers (Twilio, SendGrid, an
internal push-notification API) and owns its own MongoDB-backed domain of
`Template` / `Campaign` / `Recipient` / `DeliveryRule`. The shapes below generalize --
substitute your repo's real domain concepts, don't force this exact list of headings onto a
domain that doesn't have the equivalent shape.

## `docs/domain.md` skeleton

**The H2 headings below are fixed.** Use them verbatim, in this order, and emit every one
even when there is little to say -- a section stating "no bulk endpoint exists" is an answer,
a missing section is indistinguishable from one nobody looked at. That is what lets a later
reader, human or agent, jump straight to `## Replace vs. merge semantics` in any repo. Extra
sections are welcome; put them after the fixed set, before `## Known gaps`. Full rules:
`~/.claude/references/doc-output-conventions.md`.

```markdown
# Notification Gateway Domain Model

| | |
|---|---|
| Generator | `docs-domain` |
| Source | `acme/notification-gateway` |
| Verification | Claims carry a file citation. Unverified items are in `## Known gaps`. |

## Framing
The one or two core distinctions worth understanding up front, stated as the very first
thing. E.g. "this splits provider-specific delivery mechanics from this service's own
campaign/targeting model" -- whatever the actual conceptual split is.

## Core concepts
One bullet per real domain noun, in business language:
- **Template** -- a reusable message body with named placeholders...
- **Campaign** -- a scheduled send of one Template to a Recipient list...
- **DeliveryRule** -- which provider handles a Campaign, and retry/fallback policy...

## Relationships
An ASCII diagram of cardinality: `Template 1──*Campaign *──*Recipient`, hierarchy if any
(self-referential parent/child), and which entity is the one that bridges two otherwise
separate "worlds" if the domain has that shape (like a join/bridge entity).

## Business-rule resolution
The domain's one non-trivial decision, spelled out as a short numbered sequence. E.g. how a
permission check or a delivery-routing decision actually resolves. Include the "what happens
on failure/unknown" branch explicitly -- does it error, or resolve to a safe default? If the
domain genuinely has no such rule, say so in a sentence.

## Naming and identity conventions
- Case normalization, ID format differences between endpoints, backward-compat shims
  (and whether the code itself flags them as temporary).
- Which fields are the real stable identifier from an API consumer's point of view
  (often a human-meaningful name, not an internal generated ID).

## Replace vs. merge semantics
A table if more than one entity has this shape: entity | list field | controlling flag |
default when omitted.

## Bulk operations: idempotency and partial success
Which bulk endpoints are atomic-fail-all vs. per-item partial-success (and at what status
code, if HTTP), and whether repeated calls are safe to retry.

## External-system-shaped behaviour
Anything whose semantics come from an external system rather than from this domain. E.g.
search/pagination that differs per provider because the API proxies straight through to it
rather than normalizing it. Say "none" if the domain owns all of its own semantics.

## Known gaps
What this document does not establish, in a short list. A rule inferred from naming rather
than traced, an entity whose lifecycle wasn't followed end to end, a branch never confirmed
against a real call site. The honest counterpart to every cited claim above.
```

## Notes on level of detail

- Prefer a real code citation (`ClassName.java`, a specific method) over a vague claim in
  every section -- it's what makes the doc verifiable later instead of just plausible-sounding.
- It's fine for a section to be short (2-3 sentences) if that's genuinely all there is to say
  -- don't pad a section to match this skeleton's apparent length. What you must not do is
  drop the heading: say "no bulk endpoints exist" under the heading rather than leaving the
  reader to guess whether it was checked.
- Adding a section this skeleton doesn't have is encouraged when the domain has a genuinely
  distinct concept (a multi-step approval workflow, say). Put it after
  `## External-system-shaped behaviour` and before `## Known gaps`.
- The "what happens on failure/unknown" branch of core business logic is the thing most
  likely to be skipped by a first draft and most valuable when present -- don't skip it even
  under time pressure.
- Keep technical/implementation detail out of this document -- link to `docs/architecture.md`
  (produced by the companion `docs-architecture` skill) for "how this is actually built and
  served" instead of duplicating it here.
