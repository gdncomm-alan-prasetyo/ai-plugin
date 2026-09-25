# Get Deployment Version — User Guide

Compare deployment versions across multiple repositories between dev, QA, and prod environments.

## Usage

```
/get-deployment-version          # Normal pipeline only (default)
/get-deployment-version normal   # Normal pipeline only
/get-deployment-version canary   # Canary pipeline only
/get-deployment-version both     # Normal + canary pipelines
```

## Authentication (one-time setup)

```bash
gh auth login
gh auth status   # verify
```

## Configuration (config.yml)

```yaml
repos:
  - name: my-service
    owner: gdncomm
    repo: my-service-repo

dev_branch: dev         # default: dev
qa_branch: qa           # default: qa
prod_branch: prd        # default: prd

dev_canary_branch: dev-canary
qa_canary_branch: qa-canary
prod_canary_branch: prd-canary

file_path: deployment/{branch}/values.yaml   # {branch} replaced dynamically
tag_key: tag
```

## Status Meanings

| Status | Meaning |
|--------|---------|
| All Sync | All environments on same version |
| Ready for QA | Dev is ahead of QA |
| Ready for Prod | QA is ahead of Prod |
| Fetch Error | Could not retrieve version |

## Troubleshooting

```bash
gh api rate_limit                                                     # check rate limit
gh api repos/{owner}/{repo}/contents/deployment/dev/values.yaml      # verify file exists
```

## Version
- 1.1 — 2026-04-22 — Optimized token usage; default mode changed to normal-only
- 1.0 — 2026-04-08 — Initial release
