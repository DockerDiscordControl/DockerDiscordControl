# DDC v2.4.1: Security patch

After the v2.4.0 release, GitHub's code scanner (CodeQL) flagged ten places in DDC. Each one was
checked by hand: **four were real and are fixed**, six turned out to be false positives.

Nothing else changes. No config migration, no new settings, no logout. Updating from v2.4.0 is
a plain image update.

**Coming from v2.3.1 or earlier?** Please read the
[v2.4.0 upgrade notes](https://github.com/DockerDiscordControl/DockerDiscordControl/releases/tag/v2.4.0)
first: v2.4.1 includes everything from v2.4.0.

---

## Security

- **Error answers no longer contain internal error text.** Two answers of the Web UI passed the
  raw error message to the browser, and such a message can contain file paths on the host:
  the translation **Test** button when the stored API key cannot be decrypted, and saving admin
  container assignments when the container list cannot be read. Both now give a plain reason,
  and the full details are written to the log.
- **The first-time setup page shows its messages as text.** Messages from the server were
  inserted into the page as HTML. This page is reachable before any password exists, so it is
  the last place that should interpret foreign text as markup.
- **The image build limits its GitHub token.** The workflow that tests and publishes the Docker
  image now gives its jobs read-only access to the repository by default; only the publish step
  gets the rights it needs.

## Under the hood

- 5,722 tests pass in the production image (7 new). Each fix comes with a test that failed
  against the old code.
- The six false positives and why they are not problems are documented in
  `docs/quality/reviews/PASS_E_FIXED.md`.
