---
description: Take a Jira ticket to a clean PR, then snapshot-build (skip test) and deploy that PR's branch to qa2/canary-qa2 for pre-merge verification. Never merges, never touches preprod or prod.
argument-hint: <JIRA-KEY or browse URL> [host(s): qa2 | canary-qa2 | both]
---

Invoke the `ai-plugin:jira-pr-deploy-qa2` skill with argument `$ARGUMENTS` and follow it end to end in this session.

No Jira key given → ask for it first. Run from inside the target service repo.
