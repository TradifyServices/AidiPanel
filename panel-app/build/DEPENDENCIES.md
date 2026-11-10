# Frontend dependency verification

Verified on 2026-11-10 against the npm registry's `dist-tags.latest` and the
corresponding published tarballs. Direct versions are exact; `npm ci` consumes
the integrity-pinned lockfile. Run `npm run build`, `npm test`, and
`npm audit --audit-level=high` from `panel-app`.

| Package | Selected stable version | License |
| --- | --- | --- |
| @fontsource/jetbrains-mono | 5.3.0 | OFL-1.1 |
| @fontsource/plus-jakarta-sans | 5.3.0 | OFL-1.1 |
| @fontsource/space-grotesk | 5.3.0 | OFL-1.1 |
| @tabler/icons | 3.51.0 | MIT |
| alpinejs | 3.17.5 | MIT |
| tailwindcss, @tailwindcss/cli | 4.3.5 | MIT |
| codemirror | 6.0.2 | MIT |
| @codemirror/state | 6.7.6 | MIT |
| @codemirror/view | 6.43.15 | MIT |
| @codemirror/language | 6.13.1 | MIT |
| @codemirror/commands | 6.11.1 | MIT |
| @codemirror/lang-css | 6.3.1 | MIT |
| @codemirror/lang-html | 6.4.12 | MIT |
| @codemirror/lang-javascript | 6.2.5 | MIT |
| @codemirror/lang-json | 6.0.2 | MIT |
| @codemirror/lang-markdown | 6.5.2 | MIT |
| @codemirror/lang-php | 6.0.2 | MIT |
| @codemirror/lang-python | 6.2.1 | MIT |
| @codemirror/lang-sql | 6.10.0 | MIT |
| @codemirror/lang-xml | 6.1.0 | MIT |
| @codemirror/legacy-modes | 6.5.5 | MIT |
| @codemirror/theme-one-dark | 6.1.3 | MIT |
| qrcode-generator | 2.0.4 | MIT |
| esbuild | 0.28.2 | MIT |
| jsdom (tests only) | 31.0.0 | MIT |
| apexcharts | 4.7.0 retained; latest 8.8.1 blocked | MIT for 4.7.0 |

Registry metadata is available at `https://registry.npmjs.org/PACKAGE/VERSION`.
`npm outdated` is expected to report only ApexCharts.

## ApexCharts licensing blocker

The [8.8.1 published tarball](https://registry.npmjs.org/apexcharts/-/apexcharts-8.8.1.tgz)
declares `SEE LICENSE IN LICENSE.md`. Its license prohibits Community-license
"Embedding in a product or platform used by other people, which needs the OEM
License below whatever your size" and says "continued redistribution requires
an active subscription" for OEM licenses. It also restricts Community use to
organizations below $2M in annual revenue, budget, or funding. See the
[upstream license](https://apexcharts.com/license).

No commercial/OEM entitlement was supplied. The existing
[4.7.0 tarball](https://registry.npmjs.org/apexcharts/-/apexcharts-4.7.0.tgz)
contains an unrestricted MIT `LICENSE`. Keep its exact pin and unchanged chart
API until licensing is resolved or a chart-library replacement is approved.
The asset build rejects a version/license change before copying the chart bundle.

## Migrations and local assets

[Tailwind 4's upgrade guide](https://github.com/tailwindlabs/tailwindcss.com/blob/main/src/docs/upgrade-guide.mdx)
requires the separate CLI and CSS import/config directives. Explicit PHP sources
avoid scanning generated assets or node_modules. Compatibility declarations retain
the previous small radius/shadow, default border color, pointer cursor, and hidden
outline behavior. Tailwind 4 requires Safari 16.4+, Chrome 111+, and Firefox 128+;
older browser support is a compatibility limitation of this major upgrade.

[CodeMirror 6's migration guide](https://codemirror.net/docs/migration/) replaces
the CodeMirror 5 constructor/modes with EditorState, EditorView, and extensions.
`editor.mjs` bundles all supported languages into one self-hosted IIFE, including
legacy stream parsers for nginx, Dockerfile, properties, YAML, shell, and C-like
languages. Styles are included by CodeMirror itself; the obsolete CodeMirror 5
stylesheet is removed. Dirty-state callbacks, line numbers, two-space indentation,
dark styling, history, search, Unicode text, SHA-conflict saves, and destruction
are covered by executable DOM tests. The prior bundle's Dockerfile parser failed
at startup because its `defineSimpleMode` addon was missing.

QR 2 moves the browser-compatible `qrcode()` implementation to `dist/qrcode.js`.
The existing enrollment view's API remains compatible and emits a data URI.
All JavaScript, icons, and fonts remain local. The build emits third-party
license notices, including licenses for bundled CodeMirror and chart dependencies.

Alpine and QR npm tarballs omit standalone licenses. The checked-in copies come
from the exact registry `gitHead` revisions:

- [Alpine 3.17.5 license](https://github.com/alpinejs/alpine/blob/8d3d9a2f98385d4c879f4b5be080a0221279ed4d/LICENSE.md)
- [QR 2.0.4 license](https://github.com/kazuhikoarase/qrcode-generator/blob/83b7e8fe3fddd3b0368dbafd6ce56995bd25e3c8/LICENSE)

## CI actions and runtime

Verified each release through the upstream GitHub releases/tag APIs, peeling the
annotated PHP tag to its commit. CI uses Node 26.13.0, listed as Lithium LTS in
the [official Node release index](https://nodejs.org/dist/index.json).

| Action | Release | Immutable commit |
| --- | --- | --- |
| actions/checkout | v7.0.1 | 3d3c42e5aac5ba805825da76410c181273ba90b1 |
| actions/setup-node | v7.1.0 | 949feb2413d6458794dcd2491c4babbbce0c15c1 |
| actions/upload-artifact | v7.0.2 | cf430e030ddbb5b0abf93d22962f4752f3646cd9 |
| shivammathur/setup-php | 2.40.0 | eb7c497e18156a6bbabfef1d3a82760b9eda3962 |

The existing `tests/unit/ci_release_contract_test.sh` hard-codes earlier action
SHAs and must be updated by its owner alongside this change. That existing test
is outside the frontend implementation's assigned file ownership.

## Verification results

- `npm ci`, `npm run build`, and `npm test`: passed on Node 24.15.0 and
  Node 26.13.0; final frontend suite has seven passing tests.
- SHA-256 comparisons: all 133 asset files match across clean Node 24/26 builds
  and repeated builds, including the final license-notice update.
- `npm audit --audit-level=high`: zero vulnerabilities, including dev dependencies.
- `npm run icons -- --strict`: all 115 requested icons available.
- `npm ls --all --depth=0`, JavaScript syntax checks, changed-view PHP lint, and
  `git diff --check`: passed.
- Registry recheck: all 27 direct pins equal current stable `latest`, except
  intentionally retained ApexCharts 4.7.0.
- `bash tests/unit/ci_release_contract_test.sh`: fails at its obsolete checkout
  v7.0.0 SHA expectation; no change to that out-of-scope test was made.

DOM tests exercise the actual vendored editor and rendered PHP file-manager
integration. Interactive visual testing in a real browser was not performed.
