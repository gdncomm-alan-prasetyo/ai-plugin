# ai-plugin

Placeholder Claude Code plugin.

## Layout

```
.claude-plugin/
  plugin.json        # plugin manifest
  marketplace.json   # local marketplace entry (for /plugin install)
skills/jira-to-pr/SKILL.md            # Jira → PR flow (source of truth)
skills/snapshot-deploy-qa2/SKILL.md   # snapshot build (skip test) → deploy qa2/canary-qa2
skills/jira-pr-deploy-qa2/SKILL.md    # jira-to-pr + snapshot-deploy-qa2, chained
commands/hello.md                     # /ai-plugin:hello (placeholder)
commands/jira-pr.md                   # /ai-plugin:jira-pr <KEY> → jira-to-pr skill
commands/snapshot-qa2.md              # /ai-plugin:snapshot-qa2 → snapshot-deploy-qa2 skill
commands/jira-pr-qa2.md               # /ai-plugin:jira-pr-qa2 <KEY> → jira-pr-deploy-qa2 skill
agents/jira-to-pr.md                  # main-thread agent wrapper → jira-to-pr skill
hooks/hooks.json
```

## Try it locally

```bash
claude --plugin-dir .
```

Or add as a marketplace: `/plugin marketplace add ./` then `/plugin install ai-plugin@ai-plugin-marketplace`.
