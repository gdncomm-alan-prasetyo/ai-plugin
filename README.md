# ai-plugin

Placeholder Claude Code plugin.

## Layout

```
.claude-plugin/
  plugin.json        # plugin manifest
  marketplace.json   # local marketplace entry (for /plugin install)
skills/jira-to-pr/SKILL.md   # Jira → PR flow (source of truth)
commands/hello.md           # /ai-plugin:hello (placeholder)
commands/jira-pr.md         # /ai-plugin:jira-pr <KEY> → skill
agents/jira-to-pr.md        # main-thread agent wrapper → skill
hooks/hooks.json
```

## Try it locally

```bash
claude --plugin-dir .
```

Or add as a marketplace: `/plugin marketplace add ./` then `/plugin install ai-plugin@ai-plugin-marketplace`.
