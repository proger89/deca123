# Materials publication audit

Audit timestamp: 2026-07-18, before the first `git add` in this workspace.

The supplied bundle contains four PDFs, one Telegram HTML export, eleven STL and eleven STEP files. No explicit redistribution licence was found in the supplied bundle, so the baseline uses conservative publication rules.

| Group | Files | Size | Decision | Reason |
|---|---:|---:|---|---|
| Official PDF | 4 | 26,208,676 bytes | `hash-only` | Organizer documents; no explicit public redistribution licence found |
| Telegram export | 1 | 275,944 bytes | `exclude` | May contain names, handles and chat metadata |
| STL models | 11 | 15,956,119 bytes | `hash-only` | Competition input; licence not stated |
| STEP models | 11 | 35,353,323 bytes | `hash-only` | Competition input; licence not stated |

Controls:

- `.gitignore` excludes `materials/`.
- `assets/source-materials.sha256` records provenance without publishing bodies.
- `docs/official-clarifications.md` contains a sanitized organizer-answer summary.
- Runtime uses ASCII `item_id`; local source names remain provenance only.
- A later explicit licence/private-submission requirement may revise `hash-only` through an ADR.
- No raw material is copied into the bootstrap image.

Privacy check: raw `messages.html` is not staged, and no participant identity/contact detail is copied into tracked documentation.
