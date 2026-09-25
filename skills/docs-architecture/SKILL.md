---
name: docs-architecture
description: >
  Writes docs/architecture.md: module structure, tech stack with versions read from the real
  build manifest rather than guessed, design patterns cited to actual files, request flow,
  persistence, and security posture. Use when asked to "document the architecture", "explain
  the tech stack", or to onboard a human or an agent to an unfamiliar repo. Companion to
  docs-domain, which covers the business side.
argument-hint: "[repo path]"
allowed-tools: ["Bash(python*)", "Read", "Glob", "Grep", "Write", "Edit"]
---

# Architecture Docs

Answers "how is this built, and how do requests/data actually move through it" --
`docs/architecture.md`, written *from evidence gathered in this pass*, not from what a
framework/library "usually" looks like. Two audiences at once: a human developer skimming
it to get oriented, and a future AI agent that needs load-bearing facts (real dependency
versions, the actual error-handling paths, whether auth really exists) to avoid re-deriving
or guessing them from scratch every session.

This is comprehension-driven, not mechanically generated -- there is no script that can
correctly name "the design patterns in use" for you. The bundled `collect_facts.py` script
exists only to ground the one subsection that *is* mechanically checkable (dependency
versions) so you never write a version number from memory. Everything else in this skill
is a workflow and a set of hard-won heuristics for where the non-obvious architectural
facts tend to hide, gathered from doing this by hand on a real, unfamiliar codebase.

## Workflow

1. **Map the module structure first.** Find every build manifest (`pom.xml`,
   `build.gradle(.kts)`, `package.json`, or language equivalent) with Glob, and run:

   ```bash
   python ${CLAUDE_PLUGIN_ROOT}/skills/docs-architecture/scripts/collect_facts.py <repo-root>
   ```

   This reports every manifest found, multi-module structure (Maven `<modules>` /
   npm `workspaces`), and every declared dependency with its **actual** version string
   pulled from the manifest (including resolving a parent pom's `<properties>` block, since
   child-module `pom.xml` files commonly reference a version by property name, not literal).
   For Gradle it's a best-effort regex scan (Groovy/Kotlin DSL isn't really parseable with
   regex) -- read the flagged files by hand to confirm anything that matters. For anything
   the script doesn't recognize (`requirements.txt`, `Cargo.toml`, `go.mod`, ...) it just
   tells you the file exists; read it yourself.

   From this, work out: what are the modules, what does each own, and what's the
   *dependency direction* between them (which module can import from which) -- this alone
   is usually the fastest way to understand a codebase's intended layering, and violations
   of it (a "core" module importing from a "web" module) are worth calling out as findings.

2. **Build the Tech Stack section from what step 1 actually found** -- every version number
   in the doc should trace back to a line in a manifest file you can point to, not to what
   you remember that library's latest version being. Note *why* a library is there when it's
   not obvious from the name (e.g. a `-native-image` module implies GraalVM AOT compilation;
   a `kiota`-family dependency implies a Microsoft Graph SDK client; mismatched versions of
   the same underlying library pulled transitively by two different BOMs is itself worth a
   one-line callout, not silently smoothed over).

3. **Trace the request/data flow end to end**, from entry point to persistence, and back.
   Concretely: find the framework's routing/dispatch entry (controllers, handlers, route
   files), the layer(s) beneath them (services, use-cases), and the persistence layer
   (repositories/DAOs, ORM entities/schemas). While tracing, actively hunt for the parts that
   a shallow read misses -- these are almost always where the real behavior differs from the
   "obvious" architecture:
   - **More than one error-handling code path is common.** A base-class/decorator that
     catches app-thrown business errors is often *not* the only one -- framework-level
     failures (bad input, failed validation, routing 404s) are frequently caught by a
     separate global handler that builds its response independently, even if it reuses the
     same envelope shape. Find and trace both; don't assume error responses are only what the
     "main" handler produces.
   - **Success/error status can be runtime-conditional**, decided by an argument passed at
     a specific call site rather than fixed by an annotation or return type. If there's a
     shared response-building helper, grep its call sites for an explicit status argument
     that overrides the default -- these are invisible to anything that only reads method
     signatures.
   - **Enumerate every cross-cutting interceptor/middleware/filter**, not just the ones a
     README happens to mention, and check what each one's scope actually covers (path
     include/exclude patterns). Some short-circuit with a hand-rolled response that bypasses
     the app's normal response envelope entirely -- these can have a subtly different shape
     (e.g. missing a field every other response has) that's worth documenting explicitly.
     Watch for naming collisions between inbound middleware (intercepts requests to this
     service) and outbound/client-side interceptors (decorates calls this service makes to
     others) -- same word, opposite direction, easy to conflate.
   - **A stale comment or docstring is itself a finding.** If a comment claims behavior that
     the current code doesn't have, that's worth reporting the same way a stale standalone
     doc file would be -- don't silently work around it and say nothing.

4. **Identify design patterns and coding conventions only with a specific source citation
   per pattern** -- name the actual class/file that demonstrates it, not "this looks like it
   probably uses X." Look for: a repeated "wrapper that adds logging/timing/error-handling
   around a call" shape across multiple layers (execute-around); a factory/registry that
   picks between multiple implementations of one interface at runtime (factory + the
   interface itself is usually an adapter/strategy); multiple narrowly-scoped mapper classes
   rather than one big one (layer-scoped mapping); a repository/service subclass that adds
   one cross-cutting concern (decoration, e.g. automatic audit logging on write); consistent
   project-wide conventions worth a new contributor or agent knowing (a required base class
   for all controllers/services, a naming convention for DTOs vs. entities). If a "pattern"
   would only have one real example in the whole repo and it's a stretch to name it a
   pattern rather than just "a function," leave it out -- padding this section with generic
   pattern names nobody would recognize in the actual code is worse than a shorter, accurate
   list.

5. **Determine the security posture explicitly -- do not assume auth exists.** Check whether
   inbound requests are actually authenticated/authorized (a real auth framework wired in,
   a JWT/API-key check, mTLS) versus merely *attributed* (e.g. a required parameter that
   identifies the caller for logging but proves nothing about identity) versus nothing at
   all. This is one of the highest-value, most commonly-undocumented facts about a codebase
   and is worth its own prominent subsection regardless of how the answer looks -- "there is
   no inbound authentication" is a legitimate and important thing to write down plainly, not
   something to soften or bury.

6. **Cross-check every non-obvious claim against the code, and report disagreements rather
   than silently resolving them.** If the repo has existing hand-written docs (`documentations/`,
   a wiki export) or comments/Javadoc describing the architecture, treat them as evidence to
   verify, not ground truth to copy -- they drift out of sync with code. When a doc/comment
   and the code disagree, the code wins for what `docs/architecture.md` should *say*, but the
   disagreement itself is worth surfacing to the user -- it usually means either the doc is
   stale or the code has a real bug, and that's their call.

7. **Write `docs/architecture.md`.** Use the skeleton in `references/example.md`. **Its H2
   headings are fixed** -- verbatim, in order, every one present. Adapt the *content* to this
   repo, never the heading set: a repo with nothing to say under a heading gets a sentence
   saying so, not a deletion. That is what makes a later reader able to jump to
   `## Security posture` in any repo. Extra sections for a genuinely distinct concern go
   after the fixed set. Full rules: `~/.claude/references/doc-output-conventions.md`.
   If a `docs/domain.md` already exists (see the companion `docs-domain` skill), link to it
   from `## What this service is` rather than re-explaining the business model here.

8. **Spot-check the finished doc against source once more before calling it done** -- pick
   a handful of specific claims (a version number, a pattern's cited file, a status code) and
   re-verify each one directly. It's easy to introduce a small error while writing prose from
   notes; catching it now is cheaper than a future reader trusting a wrong claim.

9. **Offer, don't assume, a `CLAUDE.md` pointer.** If the repo doesn't already have a
   `CLAUDE.md` (or equivalent agent-instructions file), ask whether to add one linking to
   `docs/architecture.md` (and `docs/domain.md` if that exists too) so future sessions check
   it before re-deriving everything from source -- this is a repo-root file affecting how
   every future session behaves in this repo, so confirm rather than adding it unprompted.

10. **Write the gaps into `## Known gaps`, then report them.** Anything inferred rather than
    traced, a module skipped for time, a config value whose runtime effect wasn't confirmed.
    Putting them in the document rather than only in chat is the point: a chat message is
    gone next session, and a reader who cannot tell a verified claim from a plausible one has
    to re-verify all of them. Then summarize the same list for the user -- don't imply full
    coverage if there are parts you didn't get to.

## Why comprehension-driven, not scripted

The companion skill `docs-code-to-openapi` generates its output almost entirely by
mechanical parsing because an OpenAPI spec's shape (paths, params, schemas) is a near-direct
transcription of annotations and signatures. An architecture doc isn't -- "what design
pattern is this" requires reading code and judging intent, which is exactly the kind of
task a static script can't do reliably. Resist the urge to over-automate this skill; the
value it adds is the *checklist of where non-obvious architectural facts hide* (learned by
tracing a real, unfamiliar codebase end to end) plus the one place automation genuinely
helps without judgment calls: dependency versions.
