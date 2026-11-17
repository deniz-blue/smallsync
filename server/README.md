# smallsync-server

The reference server: Python 3.11+, standard library only, one store in one SQLite file.

```sh
cp access.example.json access.json
python -m smallsync_server --access access.json --db smallsync.db --port 8080
```

- `--access`: a JSON file with the scopes a request gets without a token, and each token's scopes.
  ```json
  { "anonymous": [], "tokens": { "change-me": ["read:*", "write:*"] } }
  ```
- `--history`: days of entries kept before folding, `30` by default. Folding runs at start and
  then once a day.
- `--max-body`: the largest push in bytes, 1 MiB by default.
- `/pull` pages hold up to 1000 entries.
- `/subscribe` sends a `: ping` comment after 15 quiet seconds.
- Static tokens only. A `401` carries `WWW-Authenticate: Bearer`.
