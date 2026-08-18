# Anki Sync Webhook

Sends deck progress JSON to an arbitrary HTTP endpoint after collection sync finishes.

| Key | Meaning |
| --- | --- |
| `enabled` | Master switch |
| `endpoint_url` | Full URL that receives the payload |
| `method` | `POST` or `PUT` |
| `headers` | Extra request headers (e.g. `Authorization`) |
| `timeout_seconds` | HTTP timeout |
| `identifier` | Stable user id in the payload (e.g. email). Replaces Anki profile name. |
| `decks` | Allowlist of deck names to export. Empty `[]` = all decks. A name matches itself and any child (`Japanese` also matches `Japanese::Kanji`). Use full paths with `::`. |
| `include_subdecks` | Include nested deck nodes in `decks` (when exporting all, or under an allowed parent) |
| `notify_on_success` | Toast on successful delivery |
| `notify_on_error` | Toast / tooltip on failure |

Empty `Authorization` is omitted from the request.

Example allowlist:

```json
"decks": ["Japanese", "Medical::Anatomy"]
```

Use **Tools → Anki Sync Webhook → Send progress now** to test without syncing.
