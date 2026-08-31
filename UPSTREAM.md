# Upstream provenance

- Repository: `https://github.com/TechJam2026/techjam-conversational-search`
- Release tag `participant-kit`: `2a6cc8e776da66ce69b1cbd237838fbc43f32587`
- Later official upstream `main` commit incorporated before participant work:
  `34078351e1c3615e5505a2e829600b56a542e462`
- Catalog archive SHA-256: `07fd142631fd6b03e2b4d09988c3eb7d53720e9d57010c79db48eeaada50a8f8`
- Decompressed catalog SHA-256: `da979b05a68af864cb0dcf9ee6a81c010c7e66a57978ad286c7a2e005fc69a67`
- Participant-kit ZIP SHA-256: `b3d7e283b835343b42c4919ea2ca90f2fb5a2aa2b10537f14dcf42f03e5b38ae`

The tag commit is the original released kit; it is not the same commit as the
later upstream documentation clarifications. `git merge-base --is-ancestor
participant-kit 34078351e1c3615e5505a2e829600b56a542e462` confirms that the tag
is an ancestor of the later incorporated upstream commit.

## Local lineage audit — 31 August 2026

- Fetch-only `upstream`: the official repository above; its push URL is
  deliberately `DISABLED`.
- User-owned `origin`: `git@github.com:khansa-aaa/shopping-copilot-techjam-2026.git`.
- Published `origin/main` observed during this audit:
  `4d7ef88dea0d47cf00c30eadd2affcefa98ae920`.
- Local `HEAD` at the start of this audit matched that commit, with the current
  implementation present as uncommitted working-tree changes.

These remote and working-tree statements are a dated audit snapshot, not a
claim that later commits were already pushed. Re-run `git remote -v`, `git
rev-parse HEAD`, and `git rev-parse origin/main` before final publication.
