# smallsync

A protocol for syncing typed JSON records through a server. Draft, version 0.

A store holds records, each with a type, an id and a JSON value. Several apps can share a
store, each under its own types. The server never reads values. It numbers every write, so a
client asks for everything after the last number it saw.

## Records

```json
{ "op": "create", "type": "org.example.note#0", "id": "6f1c2b9e-…", "seq": 431,
  "ts": 1794475263250, "value": { "text": "buy milk" } }
```

- `op`: `create`, `update` or `delete`. A delete has no `value`; the server keeps a tombstone.
- `type`: a reverse domain name and a version. Its owner defines the value, the ids and how
  two copies merge.
- `id`: unique within the type.
- `seq`: set by the server, one counter per store.
- `ts`: when the change was made, by the device's clock, in Unix milliseconds.

A breaking change to a type gets a new version, which is a separate type. Clients leave
records of types they don't know untouched.

## Conflicts

A push conflicts only when another device wrote the record after the copy it was based on. The
device that pushed settles it: unless the type defines its own merge, the later `ts` wins, and
a tie keeps the server's copy.

## API

Paths are relative to the store's URL. JSON in and out, `Authorization: Bearer <token>` on
every request. Errors are `{ "error": "…", "message": "…" }` with `400`, `401`, `410` or `413`.

### `GET /`

```json
{ "versions": [0], "subscribe": true, "read": ["*"], "write": ["org.example.note#0"] }
```

Protocol versions, whether `/subscribe` exists, and the types the token may read and write.

### `GET /pull?since=<seq>&types=<a,b>&limit=<n>`

```json
{ "records": [ … ], "next": 431, "more": false }
```

Records written after `since` (default `0`) in `seq` order, each once as its latest copy. Call
again with `since=next` while `more` is true. `op` is relative to `since`:

- `create`: created after `since`.
- `update`: existed at `since`.
- `delete`: gone. May be left out if it was also created after `since`.

`410` means `since` is older than the oldest tombstone kept; pull from `0`.

### `POST /push`

```json
{ "records": [
  { "op": "create", "type": "…", "id": "…", "ts": …, "value": { … } },
  { "op": "update", "type": "…", "id": "…", "base": 412, "ts": …, "value": { … } },
  { "op": "delete", "type": "…", "id": "…", "base": 412, "ts": … } ] }
```

A `create` succeeds over nothing or a tombstone. An `update` or `delete` succeeds only if `base`
is still the record's latest `seq`.

```json
{ "written": [ { "type": "…", "id": "…", "seq": 435 } ],
  "conflicts": [ { "op": "update", "type": "…", "id": "…", "seq": 420, "ts": …, "value": { … } } ],
  "refused": [ { "type": "…", "id": "…", "error": "not-found" } ] }
```

For a conflict, the client merges with the returned copy and pushes again with its `seq` as
`base`. `refused` errors are `not-found` and `forbidden`.

### `GET /subscribe?since=<seq>&types=<a,b>`

Server-sent events: what `/pull` would return, then each write as it happens. The event id is
the `seq`, so `Last-Event-ID` resumes.

```
id: 435
event: record
data: {"op":"update","type":"org.example.note#0","id":"…","seq":435,"ts":…,"value":{…}}
```

## Tokens

The server decides how tokens are issued: static tokens, or OIDC access tokens checked for
signature, `iss`, `aud` and `exp`. A `401` carries
`WWW-Authenticate: Bearer resource_metadata="…"` ([RFC 9728](https://www.rfc-editor.org/rfc/rfc9728))
so a client can find the issuer. Scopes are `read:<type>`, `write:<type>`, `read:*` and
`write:*`.

## Servers

```sql
CREATE TABLE records (
  type        TEXT    NOT NULL,
  id          TEXT    NOT NULL,
  seq         INTEGER NOT NULL UNIQUE,
  created_seq INTEGER NOT NULL,
  ts          INTEGER NOT NULL,
  deleted     INTEGER NOT NULL,
  value       TEXT,
  PRIMARY KEY (type, id)
);
```

## Open questions

- Type schemas
- Files
- A reference server
