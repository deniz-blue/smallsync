# smallsync

A protocol for syncing one user's typed JSON records through a server. Draft, version 0.

- A store is an append-only log of entries that set, patch or delete records.
- A record has a type, an id and a JSON value.
- Apps share a store by using different types.

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

## API

- Paths are relative to the store's URL.
- Bodies are JSON. Unknown fields are ignored.
- Requests may carry `Authorization: Bearer <token>` ([Tokens](#tokens)).
- Servers allow `Authorization` in CORS for web clients on other origins.

Error responses:

```json
{ "error": "forbidden", "message": "can't write org.example.note#0" }
```

| `error` | Status | When |
|---|---|---|
| `invalid` | `400` | the body or query doesn't match its schema |
| `unauthorized` | `401` | the token is missing or bad |
| `forbidden` | `403` | the token can't read or write a type |
| `not-found` | `404` | `/subscribe` on a server without it |
| `too-large` | `413` | the push is too big |

### `GET /`

```json
{ "versions": [0], "history": 30, "subscribe": true,
  "read": ["*"], "write": ["org.example.note#0"] }
```

- `versions`: the protocol versions the server speaks.
- `history`: days of entries kept before folding.
- `subscribe`: whether `/subscribe` exists.
- `read`, `write`: the types the token allows.

### `GET /pull?since=<seq>&types=<a,b>&limit=<n>`

```json
{ "entries": [ … ] }
```

- Entries after `since` (default `0`), in `seq` order.
- Pull again from the last `seq` until a page comes back empty.
- Once a day, each record's entries older than `history` days fold into one, with the newest
  one's `seq` and `at`: a `set` of their combined value, or a `delete`.
- A `delete` older than a year is dropped.

Clients:

- apply pulled entries in `seq` order, with their unpushed entries on top
- skip a `delete` of a record they don't have
- leave records of types they don't know alone
- pull from their last `seq`, or from `0` when new or when their last pull is over a year old,
  keeping their unpushed entries

### `POST /push`

```json
{ "entries": [
  { "key": "b1e0…", "op": "set", "type": "org.example.note#0", "id": "…",
    "value": { "text": "buy milk" } },
  { "key": "c47a…", "op": "delete", "type": "org.example.note#0", "id": "…" } ] }
```

```json
{ "results": [
  { "seq": 436 },
  { "error": "missing", "message": "record does not exist" } ] }
```

- Entries apply in order. Each gets its `seq`, or an `error` when it doesn't apply:
  - `set` always applies.
  - `patch` needs the record to exist (`missing`) and every operation to succeed
    (`test-failed`, or `patch-failed` for any other operation).
  - `delete` needs the record to exist (`missing`).
- `key` is optional and unique per entry. An entry whose `key` the server already has gets that
  entry's `seq` and isn't applied again.
- A type the token can't write fails the whole push with `403`.

Clients:

- keep unpushed entries on top of pulled ones until the push answers
- on a refusal, pull and redo the change, or ask the user
- change an existing record with a patch that tests every path it replaces or removes
- put data that two devices may edit at once, like a list's items, in separate records

### `GET /subscribe?since=<seq>&types=<a,b>`

```
id: 437
event: entry
data: {"seq":437,"op":"patch","type":"org.example.note#0","id":"…","at":1794475900000,"value":[…]}
```

- Server-sent events: what `/pull` returns, then each new entry.
- The event id is the `seq`. `Last-Event-ID` resumes.

## Tokens

- Static tokens or OIDC access tokens checked for signature, `iss`, `aud` and `exp`, as the
  server chooses.
- A `401` carries `WWW-Authenticate: Bearer resource_metadata="…"`
  ([RFC 9728](https://www.rfc-editor.org/rfc/rfc9728)).
- Scopes: `read:<type>`, `write:<type>`, `read:*` and `write:*`.

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
- Fold: delete a record's older rows and rewrite the newest.

## Open questions

- Type schemas
- Files
- A reference server
