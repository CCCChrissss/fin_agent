# Experiment archive and publication privacy

`experiment-artifacts.zip` contains the project's experiment outputs, evaluation results, model requests/responses, traces, historical reports, freeze packages and relevant runtime review records, at their original project-relative paths.

Excluded: virtual environments, package caches, pytest temporary trees, spreadsheet build intermediates, render QA images/PDFs, process logs, lock files and compiled Python. These are local execution or rendering artifacts, not required research outputs. The source Gold workbook is stored under `data/` unchanged.

Personal absolute paths and email addresses have been replaced in publication copies. Original local evidence was not overwritten. **Redacted records are not byte-identical original evidence.** Historical hashes remain historical provenance values; they must not be interpreted as successful integrity verification of redacted trace records or redacted frozen packages. Fresh runs create their own manifests and hashes. Runtime versions, model tags/digests, sampling controls and aggregate metrics are retained.

Restore into a fresh clone from PowerShell at the repository root:

```powershell
Expand-Archive -LiteralPath .\research_archive\experiment-artifacts.zip -DestinationPath .
New-Item -ItemType Directory -Force .\artifacts\runtime | Out-Null
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 derive
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 test -q
```

Install the locked Python dependencies according to the main README first. Restore into a fresh clone so existing local output files are not overwritten. Do not automatically rerun live experiments or treat historical review labels as human review. Sanitized historical scripts that refer to `[LOCAL_PATH]` are archival references and require explicit local paths before execution.

The publication check recursively inspects text and Office/ZIP members for common provider token formats, private-key headers, credential-bearing URLs and literal credential assignments; personal-path and email patterns are checked as well. This is a bounded local inspection, not a guarantee that every possible secret format can be recognized. No actual provider key is intentionally included. The new publication commit uses the account's GitHub noreply email. Existing remote commit history is retained and is not rewritten by this upload.
