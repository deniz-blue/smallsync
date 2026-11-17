# smallsync-server

The reference server: Starlette, any number of stores, one SQLite file each. Pushes are checked
against the spec's [`schemas/`](../schemas), so it runs from this repo.

```sh
cp access.example.json access.json
SMALLSYNC_ACCESS=access.json uv run uvicorn smallsync_server.app:app --port 8080
```

Or with Docker, from the repo root:

```sh
docker build -f server/Dockerfile -t smallsync .
docker run -p 127.0.0.1:8080:8080 -v ./data:/data -v ./server/access.json:/config/access.json:ro smallsync
```

- A store's URL is `/<store>/`.
- `SMALLSYNC_ACCESS`: a JSON file with the stores. Each has the scopes a request gets without a
  token, and each token's scopes. A token opens only its own store. Restart to apply changes.
  ```json
  { "stores": { "deniz": { "anonymous": [], "tokens": { "change-me": ["read:*", "write:*"] } } } }
  ```
- `SMALLSYNC_DATA`: the folder for the SQLite files, `data` by default.
- `SMALLSYNC_HISTORY`: days of entries kept before a record's older entries are compacted into
  one, `30` by default. Compacting runs at start and then once a day.
- `SMALLSYNC_MAX_BODY`: the largest push in bytes, 1 MiB by default.
- `/pull` pages hold up to 1000 entries.
- `/subscribe` sends a `: ping` comment after 15 quiet seconds.
- Static tokens only. A `401` carries `WWW-Authenticate: Bearer`.
