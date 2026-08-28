# Manual-QA evidence template

Copy one short row per test into an ignored local evidence file. Record the commit, date,
host, provider mode, and operator once above the table. Do not commit tokens,
cookies, passwords, provider keys/bodies, prompts, raw agreement text, personal browser
chrome, local filesystem paths, or real user/customer data.

```markdown
Commit: <sha> | Date: <UTC> | Host: <OS/Docker> | Mode: <mode> | Operator: <initials>

| Test | Result | Safe evidence | Cleanup |
| --- | --- | --- | --- |
| 01 | Pass / Fail / Partial / Blocked | command count or cropped synthetic screenshot | Done / N/A |
```

## Evidence naming

```text
<commit-short>/<test-id>/<utc-timestamp>-<kind>.<extension>
```

Examples: `d5eb988/03/20260827T090000Z-repository.png` and
`d5eb988/11/20260827T101500Z-manifest.sha256.txt`.

## Status definitions

- **Pass:** every step executed against the recorded commit and every expected visible,
  persisted, authorization, and cleanup result matched.
- **Fail:** execution completed but at least one expected result did not match. Preserve
  minimum safe evidence and report through the existing issue/PR process.
- **Partial:** the main journey completed, but one stated expectation did not match. Record
  the exact mismatch without presenting the test as Pass.
- **Blocked:** a prerequisite, authorization, external provider, or owner-only action
  prevented execution. Record the exact blocker; do not convert it to Pass.

## Screenshot review

Before retaining an image:

1. inspect the full frame at original size;
2. crop tabs, bookmarks, extensions, downloads, address-bar query secrets, and host paths;
3. confirm only synthetic parties and `.example.test` identities are present;
4. confirm no token, cookie, provider key, client secret, queue URL, or document from
   outside the generated fixtures is visible; and
5. use meaningful alt text when the image is linked from Markdown.

## Artifact integrity

Record checksums rather than copying artifact content:

```bash
shasum -a 256 <safe-synthetic-artifact>
```

For secret scans, record only tool/version, commit range, exit code, and finding count. If
a finding exists, stop and use the private [security policy](../../SECURITY.md); never paste
the detected value.

[Back to top](#manual-qa-evidence-template)
