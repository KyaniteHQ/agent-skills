# kyanite-skills

KyaniteHQ's marketplace of [Agent Skills](https://code.claude.com/docs/en/skills) for Claude Code and compatible agents.

A "marketplace" here is just this Git repo plus a manifest at [`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json). Adding it to Claude Code lets you install any listed skill in one command.

## Install

In Claude Code:

```
/plugin marketplace add KyaniteHQ/agent-skills
/plugin install modern-seo@kyanite-skills
```

Then run `/skills` to confirm it loaded. Update later with `/plugin marketplace update`.

## Skills in this marketplace

| Skill | Description |
|---|---|
| [`modern-seo`](https://github.com/KyaniteHQ/modern-seo) | Primary-source SEO and agentic-web guidance grounded in Google's AI optimization guide and Chrome's agentic-browsing docs. Covers ranking in Google Search/AI features and making a site usable by AI agents (WebMCP, Lighthouse agentic-browsing, UCP). |

## How this marketplace tracks skills

Each entry points at a standalone skill repo via a `github` source. Sources are **unpinned** — they track the skill repo's `main` branch, so `/plugin marketplace update` pulls the latest released version. Each skill repo owns its own version (in its `plugin.json` and git tags); this marketplace stays a thin index.

## Adding a skill (maintainers)

1. Publish the skill as its own repo with a `.claude-plugin/plugin.json` and a `SKILL.md`.
2. Add an entry to the `plugins` array in [`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json):
   ```json
   {
     "name": "<skill-name>",
     "source": { "source": "github", "repo": "KyaniteHQ/<skill-repo>" },
     "description": "<one-line description>"
   }
   ```
3. Commit and push. Users get it on their next `/plugin marketplace update`.
