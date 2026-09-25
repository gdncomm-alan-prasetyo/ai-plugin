---
name: caveman-formatter
description: Compresses skill/command/rule/agent markdown files using caveman technique. Drops articles, fillers, hedging, pleasantries. Keeps technical terms, code blocks, frontmatter exact. Target ~65% token reduction.
---

# Caveman Formatter

Compress markdown file. Keep substance. Drop fluff.

## Scope

Apply to: `skills/*/SKILL.md`, `commands/*.md`, `rules/*.md`, `agents/*.md`.

Single file or whole directory — both supported.

## Drop Rules

| Remove | Examples |
|--------|---------|
| Articles | a, an, the |
| Fillers | just, really, basically, actually, simply |
| Pleasantries | "Note that", "Keep in mind", "Be sure to", "Make sure to" |
| Hedging | "In most cases", "typically", "generally speaking" |
| Preamble | "This skill...", "The purpose of this step is to..." |
| Passive → active | "is used to verify" → "verifies" |
| Redundant qualifiers | "always", "never" when implied by context |

## Keep Exact

- Frontmatter (`---` block) — never touch
- Code blocks (` ``` ... ``` `) — never modify
- Table structure — compress cell text only
- Step numbers and heading hierarchy
- Technical terms: Spring, Kafka, Sonnet, Opus, Haiku, P0, P1, P2, @Annotation, class names, method names, file paths
- Quoted strings and error messages
- Constraint/rule lists (compress prose, keep the rule)

## Compression Patterns

```
Before: "When you hit a genuine ambiguity on a P0 or P1 candidate finding"
After:  "On genuine P0/P1 ambiguity"

Before: "Consult Opus when you cannot confidently determine whether the vulnerability is real"
After:  "Consult Opus if cannot confidently assess vulnerability"

Before: "Each Sonnet sub-agent may call Opus once when it hits a genuine ambiguity"
After:  "Each Sonnet agent calls Opus once on genuine ambiguity"

Before: "All review logic lives in sub-skills — do not re-implement here"
After:  "All logic in sub-skills. No re-implement."

Before: "Read the full .review-context.md from project root using the Read tool"
After:  "Read .review-context.md from root."

Before: "Confirm first line = <!-- review-context: {commit hash} -->. Absent/stale → stop."
After:  "Confirm first line = <!-- review-context: {hash} -->. Absent/stale → stop."

Before: "Do NOT apply skills inline. Spawn all selected skills as parallel sub-agents simultaneously"
After:  "Spawn all skills as parallel sub-agents. No inline."

Before: "Select skill when any trigger matches."
After:  "Select skill when trigger matches."
```

## Process

1. Read file via Read tool.
2. Skip frontmatter — copy exact.
3. Prose sections: apply drop rules, shorten to fragments.
4. Tables: compress cell prose, keep structure.
5. Code blocks: copy exact.
6. Lines already short (<60 chars): skip — no compression needed.
7. Write compressed file via Edit or Write tool.
8. Report: original line count → compressed, estimated % reduction.

## Do NOT Compress

- Security warnings (P0 descriptions where detail = safety)
- Irreversible action warnings
- Lines where compression creates technical ambiguity
- Frontmatter, code blocks, file paths, class/method names
