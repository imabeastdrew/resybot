# GitHub App Permissions & Webhooks

## Permissions
- Pull requests: Read & Write
- Contents: Read & Write
- Metadata: Read

## Webhooks
- Subscribed events: `pull_request`, `issue_comment`

## Installation
- Install on target organization/repositories.
- Capture App ID and download the private key (PEM).
- Store in host secrets: `GITHUB_APP_ID`, `GITHUB_PRIVATE_KEY`, `GITHUB_WEBHOOK_SECRET`.
