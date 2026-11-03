# Releasing Wicklight

Wicklight publishes to PyPI via **Trusted Publishing** (OIDC) — no API tokens are
stored anywhere. A version tag drives the release: a release-candidate tag
(`vX.Y.ZrcN`) is a dry run to TestPyPI; a final tag (`vX.Y.Z`) publishes to PyPI
after a manual approval. See `.github/workflows/release.yml`.

The version is a single source of truth: `__version__` in
`src/wicklight/__init__.py` (read by Hatchling at build time). A tag whose base
version (rc suffix stripped) does not match it fails the build.

## One-time setup

Done once per PyPI project, by a maintainer:

1. **TestPyPI trusted publisher.** On <https://test.pypi.org>, add a pending (or
   project) trusted publisher for the project `wicklight`:
   owner `wicklight-agents`, repo `wicklight`, workflow `release.yml`,
   environment `testpypi`.
2. **PyPI trusted publisher.** On <https://pypi.org>, add the same for the
   `release.yml` workflow with environment `release`.
3. **GitHub Environments** (repo → Settings → Environments):
   - `testpypi` — no protection needed.
   - `release` — add yourself as a **required reviewer** so a real release waits
     for a manual approval before publishing.
4. **Remove any account-wide PyPI/TestPyPI API tokens** that were used for
   placeholder uploads — trusted publishing replaces them.

## Cutting a release

1. **Changelog.** Move items from `[Unreleased]` into a new `[X.Y.Z]` section in
   `CHANGELOG.md` with today's date; update the compare links at the bottom.
2. **Version.** Set `__version__` in `src/wicklight/__init__.py` to `X.Y.Z`.
   Commit both on `main` via a PR, and let CI go green.
3. **Dry run (TestPyPI).** Tag and push a release candidate (e.g. `v0.1.0rc1`):
   ```bash
   git tag v0.1.0rc1
   git push origin v0.1.0rc1
   ```
   The Release workflow builds and publishes to TestPyPI. Verify it installs:
   ```bash
   pip install --index-url https://test.pypi.org/simple/ \
     --extra-index-url https://pypi.org/simple/ wicklight
   wicklight --version
   ```
4. **Final release.** Tag and push the final version:
   ```bash
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```
   Approve the paused `pypi` job in the Actions run; it publishes to PyPI.
5. **Docs.** The docs site deploys automatically on merge to `main` (the `check`
   CI's `deploy-docs` job). Confirm <https://wicklight-agents.github.io/wicklight/>
   reflects the release.
6. **Verify on a clean machine.** `pip install wicklight`, follow the
   [Quickstart](docs/getting-started.md), run the injection example, open the
   viewer. (The release gate — DTN-263.)
7. **Announce.** A short note: what Wicklight is, who it's for, the graduation
   story, and links to the docs and the game (if ready).

## Notes

- TestPyPI does not allow re-uploading the same version. Because the built
  version is the static `__version__`, a second RC for the *same* version needs
  the earlier TestPyPI file deleted first (TestPyPI is disposable).
- The wheel bundles the prebuilt viewer assets, so the release build needs no
  Node toolchain.
