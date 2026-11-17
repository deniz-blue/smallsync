# smallsync-server

The reference server: Starlette, one store in one SQLite file. Pushes are checked against the
spec's [`schemas/`](../schemas), so it runs from this repo.

```sh
cp access.example.json access.json
SMALLSYNC_ACCESS=access.json uv run uvicorn smallsync_server.app:app --port 8080
```

- `SMALLSYNC_ACCESS`: a JSON file with the scopes a request gets without a token, and each
  token's scopes.
  ```json
  { "anonymous": [], "tokens": { "change-me": ["read:*", "write:*"] } }
  ```
- `SMALLSYNC_DB`: the SQLite file, `smallsync.db` by default.
- `SMALLSYNC_HISTORY`: days of entries kept before folding, `30` by default. Folding runs at
  start and then once a day.
- `SMALLSYNC_MAX_BODY`: the largest push in bytes, 1 MiB by default.
- `/pull` pages hold up to 1000 entries.
- `/subscribe` sends a `: ping` comment after 15 quiet seconds.
- Static tokens only. A `401` carries `WWW-Authenticate: Bearer`.
