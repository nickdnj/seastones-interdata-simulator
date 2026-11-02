# licenses/: upstream licence files for the self-hosted typefaces (CT-12)

Each file is the family's own licence file, byte for byte, as published in the Google Fonts
repository (which is where the page's .woff2 files were fetched from, see
`src/web/assets/fonts/MANIFEST.txt`). It carries the family's copyright line. Fetched
2026-11-01 by the kiosk lane's overnight run. `scripts/notices.py` copies them verbatim into
`THIRD-PARTY-NOTICES`; `tests/deploy/test_notices.py` checks these hashes.

| File | Family | Licence | Source | SHA-256 |
|---|---|---|---|---|
| `Apache-2.0-roboto-slab.txt` | Roboto Slab | Apache License 2.0 | https://raw.githubusercontent.com/google/fonts/main/apache/robotoslab/LICENSE.txt | `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30` |
| `OFL-1.1-oswald.txt` | Oswald | SIL OFL 1.1 | https://raw.githubusercontent.com/google/fonts/main/ofl/oswald/OFL.txt | `0fd731a904b729a4e02eaf5e8ebd06783edd9abe400e8882760160230675b652` |
| `OFL-1.1-ibm-plex-sans.txt` | IBM Plex Sans | SIL OFL 1.1 (Reserved Font Name "Plex") | https://raw.githubusercontent.com/google/fonts/main/ofl/ibmplexsans/OFL.txt | `7e6b2818edbd8f6a01ae80641cc8f16a51080d08fb4e532be3a0b6f74adb07da` |
| `OFL-1.1-jetbrains-mono.txt` | JetBrains Mono | SIL OFL 1.1 | https://raw.githubusercontent.com/google/fonts/main/ofl/jetbrainsmono/OFL.txt | `b2fe5e8987594e9ffd1d2ca52a2f5d73eb8335243893c5d6254b5ad69269591d` |

Roboto Slab is **Apache 2.0, not OFL**: Google Fonts keeps it under `apache/` (the `ofl/`
path does not exist), and the font file's own licence URL (name table ID 14) is
`http://www.apache.org/licenses/LICENSE-2.0`. The fonts MANIFEST and the About page's notices
line say OFL for all four; that is flagged for review in THIRD-PARTY-NOTICES section 6.
The Apache text is identical to https://www.apache.org/licenses/LICENSE-2.0.txt (same hash).
