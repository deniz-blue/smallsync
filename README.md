# smallsync

A protocol for syncing one user's typed JSON records through a server. Draft, version 0.

A store is an append-only log. Each entry creates, updates or deletes a record, which has a
type, an id and a JSON value. Apps share a store by using different types. The server appends
only entries that apply, and folds entries older than a month.

## Entries

```json
{ "seq": 431, "op": "create", "type": "org.example.note#0", "id": "6f1c2b9e-…",
  "at": 1794475263250, "value": { "text": "buy milk", "done": false } }

{ "seq": 432, "op": "update", "type": "org.example.note#0", "id": "6f1c2b9e-…",
  "at": 1794475800000, "value": [
    { "op": "test", "path": "/done", "value": false },
    { "op": "replace", "path": "/done", "value": true } ] }
```

- `seq`: the store's counter, set by the server.
- `op`: `create` with the whole value, `update` with a
  [JSON Patch](https://www.rfc-editor.org/rfc/rfc6902), or `delete` with no value.
- `type`: a reverse domain name and a version. A breaking change is a new version, so a new type.
- `id`: unique within the type.
- `at`: when the server appended the entry, in Unix milliseconds.

Clients leave records of types they don't know alone.

## Applying entries

The server refuses an entry that doesn't apply, with the `error` in brackets:

- `create` needs the record to be missing or deleted (`exists`).
- `update` needs the record to exist (`missing`) and every operation in the patch to succeed
  (`test-failed` for a `test`, `patch-failed` for any other).
- `delete` needs the record to exist (`missing`).

An update tests every path it replaces or removes, so it applies only to the version its author
saw. Array indexes shift when another entry inserts or removes, so data that two devices may edit
at once, like a set's members, belongs in separate records.

Clients apply pulled entries in `seq` order and keep their unpushed ones on top until the push
answers. When one is refused, the client pulls and redoes the change, or asks the user.

## History

The server keeps `history` days of entries. Once a day it folds each record's older entries into
one, with the `seq` and `at` of the newest: a `create` holding their combined value, or a
`delete` if the record was deleted by then. A `delete` older than a year is dropped.

Clients apply a pulled `create` as the record's whole value even when they have the record, and
skip a `delete` of one they don't have, so a device away for longer than `history` days still
pulls from its last `seq`. A new device pulls from `0`, and so does one whose last pull is more
than a year old, which rebuilds its records and keeps its unpushed entries.

## API

Paths are relative to the store's URL. Bodies are JSON, every request carries
`Authorization: Bearer <token>`, and `#` is `%23` in query strings. Web clients on another origin
need CORS to allow `Authorization`. Clients and servers ignore fields they don't know.

A request that fails gets `{ "error": "…", "message": "…" }`:

- `invalid` (`400`): the body or query doesn't match its schema
- `unauthorized` (`401`): the token is missing or bad
- `forbidden` (`403`): a type the token can't read or write
- `not-found` (`404`): `/subscribe` on a server without it
- `too-large` (`413`): the push is too big

### `GET /`

```json
{ "versions": [0], "history": 30, "subscribe": true,
  "read": ["*"], "write": ["org.example.note#0"] }
```

`read` and `write` are the types the token allows.

### `GET /pull?since=<seq>&types=<a,b>&limit=<n>`

```json
{ "entries": [ … ] }
```

Entries after `since` (default `0`) in `seq` order. Pull again from the last `seq` until a page
comes back empty.

### `POST /push`

```json
{ "entries": [
  { "key": "b1e0…", "op": "create", "type": "org.example.note#0", "id": "…",
    "value": { "text": "buy milk" } },
  { "key": "c47a…", "op": "delete", "type": "org.example.note#0", "id": "…" } ] }
```

Entries apply in order, and each gets its `seq` or the reason it was refused
([Applying entries](#applying-entries)):

```json
{ "results": [
  { "seq": 436 },
  { "error": "missing", "message": "record does not exist" } ] }
```

`key` is optional and unique to its entry, so a push can be retried: an entry whose `key` the
server already has gets that entry's `seq` back and isn't applied again. A type the token can't
write fails the whole push with `403`.

### `GET /subscribe?since=<seq>&types=<a,b>`

Server-sent events: what `/pull` returns, then each new entry. The event id is the `seq`, so
`Last-Event-ID` resumes.

```
id: 437
event: entry
data: {"seq":437,"op":"update","type":"org.example.note#0","id":"…","at":1794475900000,"value":[…]}
```

## Tokens

Static tokens or OIDC access tokens checked for signature, `iss`, `aud` and `exp`, as the server
chooses. A `401` carries `WWW-Authenticate: Bearer resource_metadata="…"`
([RFC 9728](https://www.rfc-editor.org/rfc/rfc9728)) so a client can find the issuer. Scopes are
`read:<type>`, `write:<type>`, `read:*` and `write:*`.

## Servers

```sql
CREATE TABLE log (
  seq   INTEGER PRIMARY KEY,
  op    TEXT    NOT NULL,
  type  TEXT    NOT NULL,
  id    TEXT    NOT NULL,
  at    INTEGER NOT NULL,
  value TEXT,
  key   TEXT    UNIQUE
);
CREATE INDEX log_record ON log (type, id, seq);
```

A push looks up the `key`, reads the record's entries, applies them, checks the new entry and
inserts it. A pull selects by `seq`. Folding deletes a record's older entries and turns the
newest into the `create`, or keeps it when it's a `delete`. It also removes `delete` entries
older than a year.

## Open questions

- Type schemas
- Files
- A reference server
