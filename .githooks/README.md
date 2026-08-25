# .githooks

Git hooks for this repo, tracked so they survive a reclone.

**Enable once per clone:**

```bash
git config core.hooksPath .githooks
```

Git does not pick these up on its own — `core.hooksPath` is per-clone local
config, never inherited from the remote. A fresh clone is unprotected until that
line is run.

## `pre-commit` — private names

This repo is **public**. The character bibles under
`servers/character-panel-mcp/characters/` are gitignored, so the data is safe —
but that protects the data files, not a name typed into tracked prose. A rule is
most naturally written by naming the character it came from, and that copies a
private name into a published file where `.gitignore` cannot help.

The hook refuses any commit that **adds** a private character name, character
id, or project slug to a tracked file.

- **Added lines only.** The tree already carries a project name or two from
  before this existed, and a whole-file check would refuse every commit until
  they were scrubbed — which is how a hook gets disabled.
- **Blocks, rather than reporting.** At commit time, reporting and shipping are
  the same thing.
- **Fails open on its own errors.** If the checker cannot run, the commit
  proceeds with a warning. A guard that fails closed on internal bugs just
  teaches you to pass `--no-verify` by reflex.

The name list is read from the bibles **at run time**, so a character registered
today is covered today, nothing needs maintaining, and no private name is stored
in this directory.

When it fires, the fix is almost always to rewrite the line with a neutral
descriptor — "one character", "another character's costume" — rather than delete
it. The rule usually reads fine without the name, and deleting the sentence
loses hard-won information.

Genuinely need a name in a commit? `git commit --no-verify`. That should be
close to never, and worth saying out loud.

## Relationship to the Claude Code hook

`~/.claude/hooks/private_names.py` checks the same thing on `Write`/`Edit`. It is
advisory and machine-local, and it only sees those two tools — prose written by
script, `sed`, or a heredoc goes straight past it. This hook is the backstop that
nothing can route around. Where that file is present, its loader is imported so
both share one definition of "private"; on a fresh clone an equivalent loader is
embedded here.
