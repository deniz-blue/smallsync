# smallsync

A protocol for syncing typed JSON records through a server. Draft, version 0.

A store is an append-only log. Each entry creates, updates or deletes one record, which has a
type, an id and a JSON value. Several apps can share a store, each under its own types. The
server never reads values and settles nothing: it numbers entries, and clients replay them.

## Entries

```json
{ "seq": 431, "op": "create", "type": "org.example.note#0", "id": "6f1c2b9e-…",
  "ts": 1794475263250, "value": { "text": "buy milk" } }
```

- `seq`: set by the server, one counter per store.
- `op`: `create`, `update` or `delete`. A delete has no `value`.
- `type`: a reverse domain name and a version. Its owner defines the value and the ids.
- `id`: unique within the type.
- `ts`: when the change was made, by the device's clock, in Unix milliseconds.

A breaking change to a type gets a new version, which is a separate type. Clients leave
records of types they don't know untouched.

## Conflicts

Every client reads the same log in the same order and applies each entry by the same rule, so
they all end up with the same records:

- An entry applies only if its `ts` is not earlier than the record's current `ts`.
- An `update` or `delete` of a record that doesn't exist or is deleted doesn't apply. A
  `create` brings a deleted record back.

A client applies its own unpushed entries on top of what it has pulled, again after every
pull, until they come back in one.

Records are replaced whole, so data that two devices may edit at once, like the members of a
set, belongs in separate records.

## API

Paths are relative to the store's URL. JSON in and out, `Authorization: Bearer <token>` on
every request, and `#` written as `%23` in query strings. Web clients on another origin need the
server to allow the `Authorization` header through CORS.

Errors are `{ "error": "…", "message": "…" }` with `400`, `401`, `403` or `413`.

### `GET /`

```json
{ "versions": [0], "subscribe": true, "read": ["*"], "write": ["org.example.note#0"] }
```

Protocol versions, whether `/subscribe` exists, and the types the token may read and write.

### `GET /pull?since=<seq>&types=<a,b>&limit=<n>`

```json
{ "entries": [ … ] }
```

Entries after `since` (default `0`) in `seq` order, as they were pushed. Pull again from the
last `seq` received until a page comes back empty.

### `POST /push`

```json
{ "entries": [
  { "op": "create", "type": "org.example.note#0", "id": "…", "ts": 1794475263250, "value": { "text": "buy milk" } },
  { "op": "delete", "type": "org.example.note#0", "id": "…", "ts": 1794475800000 } ] }
```

The server appends the entries in order and answers `204`. A type the token may not write
fails the whole push with `403`.

### `GET /subscribe?since=<seq>&types=<a,b>`

Server-sent events: what `/pull` would return, then each entry as it is appended. The event id
is the `seq`, so `Last-Event-ID` resumes.

```
id: 435
event: entry
data: {"seq":435,"op":"update","type":"org.example.note#0","id":"…","ts":1794475900000,"value":{…}}
```

## Tokens

The server decides how tokens are issued: static tokens, or OIDC access tokens checked for
signature, `iss`, `aud` and `exp`. A `401` carries
`WWW-Authenticate: Bearer resource_metadata="…"` ([RFC 9728](https://www.rfc-editor.org/rfc/rfc9728))
so a client can find the issuer. Scopes are `read:<type>`, `write:<type>`, `read:*` and
`write:*`.

## Servers

```sql
CREATE TABLE log (
  seq   INTEGER PRIMARY KEY,
  op    TEXT    NOT NULL,
  type  TEXT    NOT NULL,
  id    TEXT    NOT NULL,
  ts    INTEGER NOT NULL,
  value TEXT
);
```

A push is an `INSERT`, a pull a `SELECT` by `seq`.

## Open questions

- Type schemas
- Files
- A reference server
- Snapshots, so a new device doesn't replay the whole log
