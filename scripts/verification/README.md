# Fortress Legal Verification Scripts

## Authenticated Production UI Checker

`check-crog-fortress-ui.mjs` verifies the authenticated production Fortress Legal matter page at `https://crog-ai.com/legal/cases/fortress-legal-production-review`.

The checker requires an externally provisioned Playwright storage state file. By default it looks for:

```text
.auth/crog-ai-gary.json
```

Operational rules:

- `.auth/` must remain untracked and ignored.
- The storage state file must remain local-only and mode `600`.
- Do not print, commit, copy, or upload auth storage state.
- Do not print cookies, tokens, passwords, auth headers, or session values.
- The checker is evidence for authenticated UI visibility only.
- The checker does not record counsel signoff.
- The checker does not create final legal conclusions.
- The checker does not authorize filing, service, email, sending, or external submission.

Run from the repository root after provisioning auth state:

```bash
node scripts/verification/check-crog-fortress-ui.mjs
```

To reuse an auth state from another governed local worktree without copying it:

```bash
CROG_AUTH_STATE=/path/to/.auth/crog-ai-gary.json node scripts/verification/check-crog-fortress-ui.mjs
```

The checker suppresses page text samples by default to avoid exposing legal content in logs. Set `FORTRESS_CHECKER_INCLUDE_TEXT_SAMPLE=1` only for an explicitly authorized local diagnostic run.
