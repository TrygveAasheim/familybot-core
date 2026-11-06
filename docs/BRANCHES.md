# Branch and deployment model

This repository uses a small release/integration split:

- `main` is the stable public release and fork baseline. The new installer is
  currently a development candidate, not yet promoted to main.
- `dev` is the only branch for ongoing work, commits and local deployment.
- Short-lived `feature/<name>` or `fix/<name>` branches are optional for
  risky or easily isolated work and merge back into `dev`.

Normal work and deployment happen on `dev`. Promotion of a verified release to
`main` is an owner-controlled release operation. GitHub branch protection is
intentionally not enabled: external users are expected to fork the repository
for customization rather than contribute changes through the upstream release
branch. CI and CodeQL still run on pushes and pull requests where applicable.

The dev verification and deployment workflow is:

1. work on a dedicated branch and open a reviewed PR into `dev`;
2. run core tests, Python compilation, shell syntax checks and the privacy scan;
3. push the verified commit to `dev`;
4. deploy from `dev` and verify scheduled jobs and health status;
5. promote verified `dev` through an owner-reviewed and approved PR into
   `main` when a new public fork baseline is wanted.

Deployment is a separately authorized action, not an automatic consequence of
a review, commit or PR. PR-only work stops with reviewed open PRs and leaves the
existing installation unchanged.

The deployment workflow defaults to `dev`. Fork maintainers may set
`FAMILYBOT_DEPLOY_BRANCH` to their own reviewed local release branch, for
example `main`. This changes only the branch-name guard; it does not bypass
tests, preflight or acceptance. Private runtime state is never merged into any
branch.
