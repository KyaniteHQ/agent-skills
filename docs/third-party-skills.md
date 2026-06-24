# Third-party skills (not vendored here)

This repo holds **only KyaniteHQ-authored skills**. The downloaded third-party skills used alongside
them are intentionally **not committed** — they are managed by the [`skills`](https://github.com/mattpocock/skills)
CLI, which records every install in `~/.agents/.skill-lock.json` and keeps them auto-updating from
upstream. Vendoring copies here would fork them and lose those updates.

This file is the **re-install list**: on a fresh machine, run the commands below to pull every
upstream source back. Each is re-added by its `owner/repo` source:

```bash
skills add <owner/repo>
```

(`skills add` resolves the GitHub repo, installs every skill it ships, and writes the lock entry.)

## Sources

| Source | Skills it provides |
|---|---|
| [`mattpocock/skills`](https://github.com/mattpocock/skills) | `grill-me`, `grill-with-docs`, `to-issues`, `to-prd`, `triage`, `handoff`, `prototype`, `tdd`, `diagnose`, `zoom-out`, `improve-codebase-architecture` |
| [`pbakaus/impeccable`](https://github.com/pbakaus/impeccable) | `impeccable` + its design sub-skills (`adapt`, `animate`, `arrange`, `audit`, `bolder`, `clarify`, `colorize`, `critique`, `delight`, `distill`, `extract`, `frontend-design`, `harden`, `normalize`, `onboard`, `optimize`, `overdrive`, `polish`, `quieter`, `teach-impeccable`, `typeset`, `layout`, `shape`) |
| [`google-labs-code/stitch-skills`](https://github.com/google-labs-code/stitch-skills) | `stitch-design`, `stitch-loop`, `design-md`, `enhance-prompt`, `react:components`, `remotion`, `shadcn-ui` |
| [`vercel-labs/agent-browser`](https://github.com/vercel-labs/agent-browser) | `agent-browser`, `dogfood` |
| [`vercel-labs/skills`](https://github.com/vercel-labs/skills) | `find-skills` |
| [`browserbase/skills`](https://github.com/browserbase/skills) | `ui-test` |
| [`cocoindex-io/cocoindex-code`](https://github.com/cocoindex-io/cocoindex-code) | `ccc` |
| [`plastic-labs/honcho`](https://github.com/plastic-labs/honcho) | `honcho-integration` |
| [`brianlovin/claude-config`](https://github.com/brianlovin/claude-config) | `simplify` |

## Re-install everything

```bash
skills add mattpocock/skills
skills add pbakaus/impeccable
skills add google-labs-code/stitch-skills
skills add vercel-labs/agent-browser
skills add vercel-labs/skills
skills add browserbase/skills
skills add cocoindex-io/cocoindex-code
skills add plastic-labs/honcho
skills add brianlovin/claude-config
```

The authoritative list (with pinned commit hashes and install timestamps) is always
`~/.agents/.skill-lock.json` — regenerate this table from it with:

```bash
jq -r '.skills | to_entries | group_by(.value.sourceUrl)[]
  | "| [`\(.[0].value.source)`](\(.[0].value.sourceUrl | rtrimstr(".git"))) | "
    + ([.[].key] | map("`\(.)`") | join(", ")) + " |"' ~/.agents/.skill-lock.json
```
