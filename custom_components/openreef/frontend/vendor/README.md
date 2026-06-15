# Vendored third-party assets

## pdf.js (`pdf.min.mjs`, `pdf.worker.min.mjs`)

Mozilla [pdf.js](https://github.com/mozilla/pdf.js), **pinned to v4.7.76**, ESM build.
Used by the ICP importer to extract selectable text from lab PDF reports (ATI, Fauna
Marin, Oceamo, …) entirely in the browser — no Python/pip dependency is added to the
integration (`manifest.json` `requirements` stays empty).

It is **lazy-loaded** (`_icpLoadPdfJs()` in `openreef-panel.js`) only when a user
imports a PDF, so the ~1.7 MB never loads for anyone else. Served same-origin from
`/openreef_static/vendor/…`. License: Apache-2.0 (Mozilla).

To update, re-pin the version and re-download:

```bash
V=4.7.76
cd custom_components/openreef/frontend/vendor
for f in pdf.min.mjs pdf.worker.min.mjs; do
  curl -fsSL "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/$V/$f" -o "$f"
done
```

If these files are absent, the importer still works for CSV; PDF import shows a clear
"PDF support isn't installed — paste the text or import a CSV" message.
