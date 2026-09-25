# Worked example: "Notification Gateway"

A fictional service used to show the section structure and level of detail that's worked
well, without tying this skill's reference material to any specific real client codebase.
Imagine: a Spring Boot service that fronts three external providers (Twilio, SendGrid, an
internal push-notification API) and owns its own MongoDB-backed domain of
`Template` / `Campaign` / `Recipient` / `DeliveryRule`. The shapes below generalize --
substitute your repo's real modules/patterns, don't force this exact list of headings onto
a repo that doesn't have the equivalent concept. (For this same fictional service's
`docs/domain.md`, see the companion `docs-domain` skill's `references/example.md`.)

## `docs/architecture.md` skeleton

**The H2 headings below are fixed.** Use them verbatim, in this order, and emit every one
even when a repo has little to say under it -- a section that says "this service has no
scheduled work" is an answer, a missing section is indistinguishable from one nobody looked
at. That is what lets a later reader, human or agent, jump straight to
`## Security posture` in any repo. Extra sections are welcome for a genuinely distinct
concern; put them after the fixed set. Full rules:
`~/.claude/references/doc-output-conventions.md`.

```markdown
# Notification Gateway Architecture

| | |
|---|---|
| Generator | `docs-architecture` |
| Source | `acme/notification-gateway` |
| Verification | Claims carry a file citation. Unverified items are in `## Known gaps`. |

## What this service is
One or two sentences: what it fronts, what it owns, in plain language. Link to
docs/domain.md here instead of re-explaining the business model.

## Module structure
A table: module name -> what it owns. Plus a one-line note on dependency direction
(e.g. "-core has no dependency on -web; -web depends on -core and -providers").

## Tech stack & libraries
Pulled from collect_facts.py's output, not memory. Group by role (web framework, mapping,
provider SDKs, observability, test) rather than a flat alphabetical dump. Call out anything
surprising (mismatched transitive versions, an unusual choice for a common problem).

## Request flow
A short ASCII diagram: entry point -> dispatch -> [global error handler OR normal path] ->
execute-around layer -> service/repository. Name the actual classes.

## Design patterns & conventions
Each bullet cites a real file. E.g.:
- Execute-around logging/timing wrapper at both the controller and service layer
  (`BaseController`, `BaseService`).
- Factory + Adapter for provider selection: `ProviderFactory` picks between
  `TwilioAdapter` / `SendGridAdapter` / `PushApiAdapter`, all implementing one
  `NotificationProvider` interface.
- Layer-scoped mappers (`DtoMapper`, `EntityMapper`) rather than one shared mapper.

## Persistence
Table: domain entity -> collection/table name. Note the ORM/mapping layer used.

## Domain-specific architecture
The one architectural concern that is particular to this service rather than generic.
E.g. multi-provider routing -- how a campaign's target provider is decided (config lookup,
not a runtime DB call, if that's what tracing the code showed). Name the concern in the
first sentence, since the heading is generic. If the service genuinely has none, say so.

## Security posture
State plainly what's actually enforced on inbound requests. If there's no real
authentication, say exactly that, prominently -- don't bury it under a softer heading.

## Configuration & observability
Notable env-driven config, tracing/metrics wiring (only if actually wired, not just a
version pinned in a BOM with nothing configured).

## Build & deployment
CI pipeline shape, containerization/native-image build if present, anything about how
environments differ.

## Known gaps
What this document does not establish, in a short list. Anything inferred rather than
traced, a module skipped for time, a config value whose runtime effect wasn't confirmed.
This is the honest counterpart to every cited claim above -- write "none" only if you
genuinely verified everything.
```

## Notes on level of detail

- Prefer a real code citation (`ClassName.java`, a specific method) over a vague claim in
  every section -- it's what makes the doc verifiable later instead of just plausible-sounding.
- It's fine for a section to be short (2-3 sentences) if that's genuinely all there is to say
  -- don't pad a section to match this skeleton's apparent length. What you must not do is
  drop the heading: say "no scheduled work in this service" under the heading rather than
  leaving the reader to guess whether it was checked.
- Adding a section this skeleton doesn't have is encouraged when the repo has a genuinely
  distinct concern (a plugin system, a multi-region active-active setup). Put it after
  `## Build & deployment` and before `## Known gaps`.
- Security posture is the section most likely to be skipped by a first draft and most
  valuable when present -- don't skip it even under time pressure.
- Keep business/domain explanation out of this document -- link to `docs/domain.md`
  (produced by the companion `docs-domain` skill) instead of duplicating it here.
