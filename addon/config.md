# Anki Sync Webhook

Sends deck progress JSON after collection sync finishes.

| Key | Meaning |
| --- | --- |
| `enabled` | Master switch |
| `identifier` | Stable user id in the payload (e.g. email) |
| `include_subdecks` | When an endpoint has no deck filter, also emit nested deck rows |
| `endpoints` | List of targets (`url`, optional `decks`, `headers`, `method`, `timeout_seconds`) |
| `endpoint_url` | Legacy single URL (used only if `endpoints` is missing/empty) |
| `method` / `headers` / `timeout_seconds` | Defaults inherited by each endpoint |
| `notify_on_success` | Toast on successful delivery |
| `notify_on_error` | Toast / tooltip on failure |

**Deck filters are endpoint-scoped.** On an endpoint, omit `decks` or use `[]` = all decks; `decks: ["Kaishi 1.5k"]` = that deck and its children.

Example:

```json
{
  "identifier": "you@example.com",
  "endpoints": [
    {
      "url": "http://127.0.0.1:8787/anki",
      "decks": ["Kaishi 1.5k"]
    },
    {
      "url": "https://class.example/anki",
      "decks": ["UMD::CMSC417"],
      "headers": { "Authorization": "Bearer …" }
    }
  ]
}
```

Use **Tools → Anki Sync Webhook → Send progress now** to test without syncing.
