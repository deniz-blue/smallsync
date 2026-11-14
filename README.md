# smallsync

A protocol for syncing typed JSON records through a server. Draft, version 0.

A store belongs to one user and is an append-only log. Each entry creates, updates or deletes
one record, which has a type, an id and a JSON value. Several apps can share a store, each under
its own types. The server checks each entry against its record before appending it, so the log
holds only changes that applied, and it folds entries older than a month.

## Entries

```json
{ "seq": 431, "op": "create", "type": "org.example.note#0", "id": "6f1c2b9e-…",
  "at": 1794475263250, "value": { "text": "buy milk", "done": false } }

{ "seq": 432, "op": "update", "type": "org.example.note#0", "id": "6f1c2b9e-…",
  "at": 1794475800000, "value": [
    { "op": "test", "path": "/done", "value": false },
    { "op": "replace", "path": "/done", "value": true } ] }
```

- `seq`: set by the server, one counter per store.
- `op`: `create`, `update` or `delete`.
- `value`: the whole value for a `create`, a [JSON Patch](https://www.rfc-editor.org/rfc/rfc6902)
  for an `update`, absent for a `delete`.
- `type`: a reverse domain name and a version. Its owner defines the value and the ids.
- `id`: unique within the type.
- `at`: set by the server when it appends the entry, in Unix milliseconds.

A breaking change to a type gets a new version, which is a separate type. Clients leave
records of types they don't know untouched.

## Applying entries

The server applies each pushed entry to its record and appends only the ones that apply:

- A `create` applies only if the record doesn't exist or is deleted.
- An `update` applies only if the record exists and every operation in its patch succeeds.
- A `delete` applies only if the record exists.

An update tests the current value of every path it replaces or removes, so it applies only to
the version its author saw.

Clients apply pulled entries in `seq` order as they come. A client keeps its own unpushed
entries applied on top of what it has pulled until the push answers. One that was refused was
written against a version that has since changed: the client pulls, then redoes the change on
the current record or asks the user.

Array indexes shift when an earlier entry inserts or removes, so data that two devices may edit
at once, like the members of a set, belongs in separate records.

## History

The server keeps entries for at least `history` days, given by `GET /`. Once a day it folds each
record's older entries into one `create` holding the value they add up to, with the `seq` and
`at` of the newest of them. A record that was deleted by then loses its older entries
altogether.

A new device pulls from `0`: one `create` per record, then the recent changes. A device whose
last pull is older than `history` days does the same and rebuilds its records, keeping its
unpushed entries. A device that pulled more recently never sees a folded entry, since
everything folded was already behind its last pull.

## API

Paths are relative to the store's URL. JSON in and out, `Authorization: Bearer <token>` on
every request, and `#` written as `%23` in query strings. Web clients on another origin need the
server to allow the `Authorization` header through CORS.

Errors are `{ "error": "…", "message": "…" }` with `400`, `401`, `403` or `413`.

### `GET /`

```json
{ "versions": [0], "history": 30, "subscribe": true,
  "read": ["*"], "write": ["org.example.note#0"] }
```

Protocol versions, the days of history kept, whether `/subscribe` exists, and the types the
token may read and write.

### `GET /pull?since=<seq>&types=<a,b>&limit=<n>`

```json
{ "entries": [ … ] }
```

Entries after `since` (default `0`) in `seq` order. Pull again from the last `seq` received
until a page comes back empty.

### `POST /push`

```json
{ "entries": [
  { "op": "create", "type": "org.example.note#0", "id": "…", "value": { "text": "buy milk" } },
  { "op": "delete", "type": "org.example.note#0", "id": "…" } ] }
```

The server applies the entries in order and answers for each, in the same order, with the `seq`
it was appended at or the reason it was refused:

```json
{ "results": [
  { "seq": 436 },
  { "error": "conflict", "message": "record does not exist" } ] }
```

A type the token may not write fails the whole push with `403`.

### `GET /subscribe?since=<seq>&types=<a,b>`

Server-sent events: what `/pull` would return, then each entry as it is appended. The event id
is the `seq`, so `Last-Event-ID` resumes.

```
id: 437
event: entry
data: {"seq":437,"op":"update","type":"org.example.note#0","id":"…","at":1794475900000,"value":[…]}
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
  at    INTEGER NOT NULL,
  value TEXT
);
CREATE INDEX log_record ON log (type, id, seq);
```

A push reads the record's entries by `type` and `id`, applies them, checks the new entry and
`INSERT`s it. A pull is a `SELECT` by `seq`. Folding a record is a `DELETE` of its older
entries and an `UPDATE` of the newest into the `create`.

## Open questions

- Type schemas
- Files
- A reference server
