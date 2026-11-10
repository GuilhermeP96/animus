# Animus 0.9.2 — qualification and production verification

Verified on 2026-11-10. This report deliberately excludes infrastructure
addresses, private operational paths, credentials and memory contents.

## Delivered artifacts

Release code: `c0385cca62119e4ebcaf9f7803ae6cc49f9ee5ac`, tag `v0.9.2`.
Deployment configuration follow-up: `ea86067`; snapshot CI follow-up: `188809f`.
These follow-ups change Compose/test infrastructure, not the qualified binaries.

| Artifact | SHA-256 |
| --- | --- |
| Windows EXE | `d54a7fe2a164cceca7a021ab2d4f06e1652a4785c5014061dea2dc4c45e096e4` |
| Desktop ZIP | `d6d6789fbde3994108e01cdf1f5fb99cfd712753c99f40f7b52c775bf601aea6` |
| Python wheel | `1d67c084b62f593152d50acf000c12c6cc785763df3db581b6479ef7b0340693` |

Use the current repository Compose definition for the curl-free image: its
explicit healthcheck must invoke Python, rather than override the image with
an obsolete curl command. The image healthcheck and deployed Compose check
both passed. The first deployment exposed this override mismatch; correcting
only the target service restored its health without changing the image.

## Desktop credits

The final executable embeds the official Datano mark. Its credit cards open
only `https://datano.com.br/animus` and
`https://github.com/GuilhermeP96/animus`. Independent qualification checked the
resource, readable software rendering, accessible link labels, tab focus,
keyboard activation and rejection of destinations outside the fixed allowlist.
The Datano destination returned HTTP 200. The installed desktop executable
matches the qualified bytes and starts in the background; the native Windows
daemon continues to use pythonw, without a separate terminal.

## Issue #2 — dependencies and VPS execution

- Patched setuptools to 84.1.0 with the official wheel hash. GitHub's existing
  Dependabot alert subsequently changed to **fixed**.
- Audited actual installed Python inventories against OSV after maintenance:
  40 hub, 44 Linux peer and 39 Windows peer dependencies, with no reported
  advisories in those snapshots. This is a dated package audit, not a claim
  that software can never contain vulnerabilities.
- Updated vulnerable native dependencies with compatible application behavior
  verified in an isolated candidate runtime. Removed an unused legacy
  sqlitedict installation after checking source use and reverse dependencies;
  it has no patched release. Private runtime backups remain available.
- Removed curl/libcurl from the container instead of introducing a different
  distribution or relaxing its security baseline. Package absence was checked
  in the final image.
- Registered Animus in the existing private VPS CI executor and hourly timer.
  The registered validator passed **456 tests, 5 platform skips and 15
  subtests** at exact source commit `188809f68910bac2706aed209940fda29146091b`.
  It tests a Git archive with ephemeral user state, without production
  credentials, databases or hosted GitHub Actions.
- Recovery packaging still requires real Git provenance. Its test now creates
  an owned Git fixture, so the full suite also runs in a source-only snapshot.
  The executor registration and interpreter selection were covered by the
  private executor's 200-test suite. No new global maintenance schedule or
  automatic deployment was introduced.

## Issue #10 — Turnstile

A human completed the production login with a fresh Turnstile token. The
application returned a successful login and displayed the authenticated admin
page. Reusing that consumed token with dummy credentials returned the
application's JSON **HTTP 403 Turnstile rejection**. User credentials and token
values were neither published nor saved as evidence.

After deployment, the authenticated browser session remained valid. Public
login and liveness requests returned HTTP 200 with CSP, nosniff and framing
protection; the CSP explicitly permits the Turnstile provider. The server's
Siteverify checks and peer authentication boundaries are preserved.

Independent Edge headless tests at a 390×844 viewport passed token rejection,
expiry and SDK-load recovery under the actual CSP, preserving form values and
using a fresh fixture token for the next attempt. These browser scenarios mock
the provider/backend; they complement the real production login/replay proof.
An authenticated mobile viewport was also checked for horizontal overflow.
No physical-phone or real mobile CAPTCHA completion is claimed.

## Production and preservation

The hub and both observed active peers run 0.9.2. Installed wheel RECORD entries
and all 60 packaged application files matched the qualified wheel on each
native peer; dependency checks passed. Authenticated hub requests returned HTTP
200. New connections through each configured MCP consumer exposed 16 tools
and returned fresh statistics. Both peers reached zero pending database sync
items during the final checks.

Consistent before/after database comparisons found no missing memories or
changed content/identity payloads. Configuration and the peer credential
registry remained byte-identical. Normal new collection and timestamp/tag
ordering refreshes were distinguished from content changes. The Datano site,
Academy and fiscal service retained their running images/instances and health.

## Limits

Independent acceptance is **passed-limited** on the available existing hosts,
not a clean-machine or reboot qualification. Upgrade/reinstall preserved an
isolated fixture database/configuration, and deployed data was compared
separately. No Authenticode signature is claimed. The complete Windows Python
suite did not qualify (Unix permission expectations and its deadline); the
desktop delta, installed package and actual Windows MCP consumer did pass.
Existing open MCP sessions may keep previously imported code until reconnect.

Immediately after restart, bounded cold statistics briefly returned the typed
query-timeout response; acceptance was recorded after fresh statistics and
authenticated HTTP 200 recovered. Liveness remained independent of these
counts. Only the two observed active peers are qualified by this report.
