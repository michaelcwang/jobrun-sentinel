# Review Bundle

The review bundle is a redacted zip for external review of the current JobRun Sentinel build.

Run it from the backend directory:

```bash
python -m app.cli review-bundle
```

CI-safe mode:

```bash
python -m app.cli review-bundle --skip-screenshots --skip-commands --output-dir review_bundles
```

The bundle contains:

- `app_metadata.json`
- `test_results/`
- `api_snapshots/`
- `screenshots/`
- `page_inventory.json`
- `diagnostics_review.json`
- `design_review_notes.md`
- `README.md`
- `manifest.json`

When the API or frontend is not running, the command still writes capture-error artifacts and warnings. This is intentional so CI can upload a review bundle without starting a live browser.

Redaction covers secret-like keys such as password, token, secret, DSN, wallet, and authorization fields. Long raw SQL-like strings are replaced with a redaction marker. The bundle should contain hashes, metadata, or sanitized samples rather than raw customer SQL or credentials.

Screenshots use `npx playwright screenshot` and require a running frontend. If Playwright or the frontend is unavailable, the command records warnings and continues.
