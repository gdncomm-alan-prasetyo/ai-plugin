---
description: Build a SNAPSHOT with SKIP_ANALYSIS_AND_TEST_FOR_BUILD=YES, then deploy it to qa2 and/or canary-qa2. Never touches preprod or prod.
argument-hint: [owner/repo] [host(s): qa2 | canary-qa2 | both]
---

Invoke the `ai-plugin:snapshot-deploy-qa2` skill with argument `$ARGUMENTS` and follow it end to end in this session.

No repo given → auto-detect from `git remote` if run inside a checkout, else ask for `owner/repo`. No host given → assume both qa2 and canary-qa2 were meant, but let `deploy-qa2`'s own Step 2 confirm it.
