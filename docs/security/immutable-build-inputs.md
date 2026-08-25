# Immutable build inputs

GitHub Actions are pinned to full commit SHAs in `.github/workflows/ci.yml`.
The adjacent version comments are the reviewed release labels. Container image
references retain their release tags and add the immutable multi-platform
manifest digest selected from the image's registry.

The pins were resolved on 2026-08-25 from each action repository's GitHub tag
reference and each container registry manifest. Dependabot updates the pins by
opening ordinary pull requests; no update is merged automatically, and every
proposal is subject to the normal repository review and CI checks.

## Deliberate exceptions

The `version` inputs for pnpm, uv, Terraform, Node.js, and Python remain exact
release versions rather than digests. These setup actions download tools from
their own release channels and do not accept OCI digests; the actions that
perform those downloads are themselves commit-pinned. The application base and
service images all support registry digests and are pinned accordingly.
