# smallsync

A protocol for syncing one user's typed JSON records through a server. Draft, version 0.

A store is an append-only log of entries that set, patch or delete records. A record has a type,
an id and a JSON value. Apps share a store by using different types.

## Entries

```json
{ "seq": 431, "op": "set", "type": "org.example.note#0", "id": "6f1c2b9e-…",
  "at": 1794475263250, "value": { "text": "buy milk", "done": false } }

{ "seq": 432, "op": "patch", "type": "org.example.note#0", "id": "6f1c2b9e-…",
  "at": 1794475800000, "value": [
    { "op": "test", "path": "/done", "value": false },
    { "op": "replace", "path": "/done", "value": true } ] }
```

- `seq`: the store's counter, set by the server.
- `op`: `set` with the whole value, `patch` with a
  [JSON Patch](https://www.rfc-editor.org/rfc/rfc6902), or `delete` with no value.
- `type`: a reverse domain name and a version. A breaking change is a new version.
- `id`: unique within the type.
- `at`: when the server appended the entry, in Unix milliseconds.

Clients leave records of types they don't know alone.

## Applying entries

The server refuses an entry that doesn't apply, with the `error` in brackets:

- `set` always applies.
- `patch` needs the record to exist (`missing`) and every operation to succeed (`test-failed`,
  or `patch-failed` for any other operation).
- `delete` needs the record to exist (`missing`).

Change an existing record with a patch that tests every path it replaces or removes. Data that
two devices may edit at once, like a list's items, goes in separate records.

Clients apply pulled entries in `seq` order, with their unpushed ones on top until the push
answers. On a refusal, the client pulls and redoes the change, or asks the user.

## History

The server keeps `history` days of entries. Once a day it folds each record's older entries into
one with the newest one's `seq` and `at`: a `set` of their combined value, or a `delete`. A
`delete` older than a year is dropped.

Clients skip a pulled `delete` of a record they don't have. Devices pull from their last `seq`,
except a new device or one whose last pull is over a year old, which pulls from `0` and keeps its
unpushed entries.

## API

Paths are relative to the store's URL. Bodies are JSON, every request carries
`Authorization: Bearer <token>`, and `#` is `%23` in query strings. Web clients on another origin
need CORS to allow `Authorization`. Unknown fields are ignored.

A failed request gets `{ "error": "…", "message": "…" }`:

| `error` | Status | When |
|---|---|---|
| `invalid` | `400` | the body or query doesn't match its schema |
| `unauthorized` | `401` | the token is missing or bad |
| `forbidden` | `403` | a type the token can't read or write |
| `not-found` | `404` | `/subscribe` on a server without it |
| `too-large` | `413` | the push is too big |

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
  { "key": "b1e0…", "op": "set", "type": "org.example.note#0", "id": "…",
    "value": { "text": "buy milk" } },
  { "key": "c47a…", "op": "delete", "type": "org.example.note#0", "id": "…" } ] }
```

Entries apply in order. Each gets its `seq` or an error from
[Applying entries](#applying-entries):

```json
{ "results": [
  { "seq": 436 },
  { "error": "missing", "message": "record does not exist" } ] }
```

`key` is optional and unique per entry. An entry whose `key` the server already has gets that
entry's `seq` and isn't applied again. A type the token can't write fails the whole push with
`403`.

### `GET /subscribe?since=<seq>&types=<a,b>`

Server-sent events: what `/pull` returns, then each new entry. The event id is the `seq`;
`Last-Event-ID` resumes.

```
id: 437
event: entry
data: {"seq":437,"op":"patch","type":"org.example.note#0","id":"…","at":1794475900000,"value":[…]}
```

## Tokens

Static tokens or OIDC access tokens checked for signature, `iss`, `aud` and `exp`, as the server
chooses. A `401` carries `WWW-Authenticate: Bearer resource_metadata="…"`
([RFC 9728](https://www.rfc-editor.org/rfc/rfc9728)). Scopes are `read:<type>`, `write:<type>`,
`read:*` and `write:*`.

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

- Push: look up the `key`, read the record's entries, apply them, check the new entry, insert it.
- Pull: select by `seq`.
- Fold: delete a record's older entries, turn the newest into a `set` unless it's a `delete`, and
  drop `delete` entries older than a year.

## Open questions

- Type schemas
- Files
- A reference server
