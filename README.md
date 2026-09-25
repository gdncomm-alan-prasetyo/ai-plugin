# ai-plugin

Placeholder Claude Code plugin.

## Layout

```
.claude-plugin/
  plugin.json        # plugin manifest
  marketplace.json   # local marketplace entry (for /plugin install)
skills/<name>/SKILL.md   # 62 skills copied from ~/.claude/skills
commands/hello.md    # /ai-plugin:hello
agents/example-agent.md
hooks/hooks.json
```

## Try it locally

```bash
claude --plugin-dir .
```

Or add as a marketplace: `/plugin marketplace add ./` then `/plugin install ai-plugin@ai-plugin-marketplace`.
