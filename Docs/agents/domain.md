# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

Layout: **single-context**. This repo uses a capitalized `Docs/` folder (the filesystem is case-sensitive; do not create a lowercase `docs/`).

## Before exploring, read these

- **`CONTEXT.md`** at the repo root: the domain glossary.
- **`Docs/architecture/architecture-decisions.md`**: this repo's ADR record (one file, one section per decision, as required by `AGENTS.md` §2.4). Read the decisions that touch the area you're about to work in.
- Follow `AGENTS.md` §1 routing for the authoritative spec of the area (requirements, data model, module docs, etc.); don't preload everything.

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't suggest creating them upfront. The `/domain-modeling` skill (reached via `/grill-with-docs` and `/improve-codebase-architecture`) creates them lazily when terms or decisions actually get resolved. When it records a decision, append it to `Docs/architecture/architecture-decisions.md` (reason, alternatives, trade-offs, migration impact) rather than creating a `docs/adr/` directory.

## File structure

```
/
├── AGENTS.md
├── CONTEXT.md
└── Docs/
    ├── agents/                          ← this config
    ├── architecture/
    │   └── architecture-decisions.md    ← ADRs
    └── ...                              ← specs routed by AGENTS.md §1
```

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal: either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing decision in `Docs/architecture/architecture-decisions.md`, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0007 (event-sourced orders), but worth reopening because…_
