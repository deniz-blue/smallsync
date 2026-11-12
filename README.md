# smallsync

A protocol for keeping one person's app data in sync across their devices, on a server they
choose.

Draft, version 0. Anything here may still change.

A store holds records. Each record has a type, an id and a JSON value. Apps share a store the
way AT Protocol apps share a repo: each one keeps its records under its own types and ignores
the rest. The server doesn't look inside values. It keeps the latest copy of every record and
numbers every write, so a client can ask for everything written since the last number it saw.

The whole server is one table and a counter.

## Records

A record travels as one of three operations:

```json
{ "op": "create", "type": "org.example.note#0", "id": "6f1c2b9e-…", "seq": 431,
  "clock": "2026-11-12T09:21:03.250Z/0000/phone", "value": { "text": "buy milk" } }

{ "op": "update", "type": "org.example.note#0", "id": "6f1c2b9e-…", "seq": 433,
  "clock": "2026-11-12T09:25:41.002Z/0000/laptop", "value": { "text": "buy oat milk" } }

{ "op": "delete", "type": "org.example.note#0", "id": "6f1c2b9e-…", "seq": 434,
  "clock": "2026-11-12T09:30:00.000Z/0000/phone" }
```

| Field | Set by | Meaning |
|---|---|---|
| `type` | client | What the record is, as a reverse domain name and a version. |
| `id` | client | Unique within the type. UUIDs unless the type says otherwise. |
| `seq` | server | The number of the write that produced this copy. One counter per store. |
| `clock` | client | When the change was made, for settling conflicts. See [Clocks](#clocks). |
| `value` | client | Any JSON. A `delete` has none. |

A deleted record stays on the server as a tombstone, so clients that were offline still hear
about the delete.

## Types

A type is a reverse domain name followed by `#` and a version: `org.example.note#0`. Whoever
owns the domain decides what the value holds, how ids are picked and how two copies merge.
The `#` versioning is the same as Open Evnt components (`directory.evnt.component.link#0`).

Adding an optional field keeps the version. A change that breaks existing readers gets a new
version, and a new version is a separate type: old clients keep reading `#0` while the owning
app moves its records to `#1`. Clients keep records of types they don't know and never change
them.

In a URL, `#` must be written `%23`.

## Clocks

A clock is a hybrid logical clock written as three parts joined by `/`:

```
2026-11-12T09:21:03.250Z/0000/phone
```

1. UTC time with milliseconds, always in this exact format.
2. A counter, four digits.
3. The device that made the change: letters, digits, `.`, `_` and `-`.

Every part has a fixed width or comes last, so two clocks compare as plain strings.

A client keeps the highest clock it has seen. To stamp a change, it takes the current time; if
that is not later than the highest clock, it reuses the highest clock's time and adds 1 to its
counter. A device whose clock runs fast can't keep winning conflicts this way: once the others
have seen its clock, their next changes stamp higher.

Unless a type defines its own merge, the copy with the higher clock wins. A type may merge more
finely, field by field or as a set. Clients that don't know the type use the default.

## API

All endpoints are relative to the store's URL, for example `https://example.org/store`.
Requests and responses are JSON. Every request needs `Authorization: Bearer <token>`.

| Endpoint | |
|---|---|
| `GET /` | What the store supports and what the token may do |
| `GET /pull` | Records written since a given `seq` |
| `POST /push` | Write records |
| `GET /subscribe` | Records as they are written (server-sent events) |

Errors look like `{ "error": "not-found", "message": "…" }`.

| Status | When |
|---|---|
| `400` | The request is malformed. |
| `401` | The token is missing, wrong or expired. |
| `410` | `since` is older than the oldest tombstone the server still keeps. |
| `413` | The push is larger than the server accepts. |

### `GET /`

```json
{ "versions": [0], "subscribe": true, "read": ["*"], "write": ["org.example.note#0"] }
```

- `versions`: protocol versions the server speaks.
- `subscribe`: whether `/subscribe` exists.
- `read`, `write`: the types this token may read and write. `["*"]` means all, `[]` none.

### `GET /pull?since=<seq>&types=<a,b>&limit=<n>`

Returns the records written after `since`, ordered by `seq`. Every parameter is optional:
`since` defaults to `0` (everything), `types` filters by type, and the server picks a default
and a maximum for `limit`. Types the token may not read are left out.

```json
{ "records": [ … ], "next": 431, "more": false }
```

Call again with `since=next` while `more` is true. When the server answers `410`, start over
from `0`.

Each record appears once, as its latest copy. This is not a log of every write: a record
created, edited and deleted between two pulls arrives as a single `delete`. The `op` is
relative to `since`:

- `create`: the record's first write came after `since`. A record written again after being
  deleted counts as new from that write.
- `update`: the record already existed at `since`, so the reader may hold an older copy.
- `delete`: the record is gone. The server may skip a delete when the record was also created
  after `since`, because the reader never saw it.

A client applies `create` and `update` the same way. The difference matters to readers that
keep no state, like a bot announcing new records.

### `POST /push`

```json
{ "records": [
  { "op": "create", "type": "org.example.note#0", "id": "…", "clock": "…", "value": { … } },
  { "op": "update", "type": "org.example.note#0", "id": "…", "base": 412, "clock": "…", "value": { … } },
  { "op": "delete", "type": "org.example.note#0", "id": "…", "base": 412, "clock": "…" } ] }
```

- `create` succeeds when the id is unused or only has a tombstone.
- `update` and `delete` carry `base`: the `seq` of the copy the client last saw. They succeed
  only when that is still the server's latest copy.

Each record succeeds or fails on its own.

```json
{ "written": [ { "type": "…", "id": "…", "seq": 435 } ],
  "conflicts": [ { "op": "update", "type": "…", "id": "…", "seq": 420, "clock": "…", "value": { … } } ],
  "refused": [ { "type": "…", "id": "…", "error": "not-found" } ] }
```

- `written`: the new `seq` of each stored record.
- `conflicts`: the server's latest copy of each record that changed since the client's `base`,
  or that already existed for a `create`. The client merges by the type's rule and pushes again
  with the new `base`.
- `refused`: an `update` or `delete` of an id the server never had (`not-found`), or a type the
  token may not write (`forbidden`).

### `GET /subscribe?since=<seq>&types=<a,b>`

Only when `GET /` says `"subscribe": true`. A [server-sent events](https://html.spec.whatwg.org/multipage/server-sent-events.html)
stream: first everything `/pull` would return for `since`, then every write as it happens.

```
id: 435
event: record
data: {"op":"update","type":"org.example.note#0","id":"…","seq":435,"clock":"…","value":{…}}
```

The `id` is the record's `seq`, so a reconnecting client resumes with `Last-Event-ID` instead of
`since`. The server closes the stream when the token expires, and the client reconnects with a
fresh one. Without `/subscribe`, clients poll `/pull`.

Browsers' `EventSource` can't send an `Authorization` header, so web clients read the stream
with `fetch` instead.

## Syncing

What a client keeps for each store: the `next` of its last pull, and the `seq` of the copy it
last saw for each record.

1. Pull until `more` is false.
2. For each record, keep the server's copy if nothing changed locally since that record's last
   `seq`; otherwise merge the two by the type's rule.
3. Push what changed locally, each `update` and `delete` with the `seq` it was based on.
4. Store the new `seq` of every written record; merge and push again for every conflict.

A client sees its own writes again on the next pull. It can skip any whose `seq` it already has.

## Tokens

The server decides how tokens are issued. A token opens one store, and `GET /` says what it may
read and write. Two kinds are named here.

**Static tokens**, printed at setup or shown on a web page. Good for scripts and small servers.
Revoking one is deleting it.

**OIDC access tokens.** The server checks the issuer's signature and the `iss`, `aud` and `exp`
claims; `sub` says who is asking. Every `401` carries a header pointing to a public metadata
document ([RFC 9728](https://www.rfc-editor.org/rfc/rfc9728)) that names the issuer, so a
client can find where to log in from the store's URL alone:

```
WWW-Authenticate: Bearer resource_metadata="https://example.org/.well-known/oauth-protected-resource/store"
```

Scopes are `read:<type>` and `write:<type>`, or `read:*` and `write:*`.

## Servers

A server must:

- keep, for every record, the `seq` of its latest write, the `seq` of the write that created
  it, its latest clock and value, and whether it is deleted;
- accept a `create` only over nothing or a tombstone, and an `update` or `delete` only when
  `base` matches; otherwise return the latest copy as a conflict;
- keep tombstones, or answer `410` to a `since` older than the ones it kept.

It never validates values and never compares clocks. This is the whole storage:

```sql
CREATE TABLE records (
  type        TEXT    NOT NULL,
  id          TEXT    NOT NULL,
  seq         INTEGER NOT NULL UNIQUE,
  created_seq INTEGER NOT NULL,
  clock       TEXT    NOT NULL,
  deleted     INTEGER NOT NULL,
  value       TEXT,
  PRIMARY KEY (type, id)
);
```

That fits in one Python script on the standard library.

## Example

Add a note from a shell:

```sh
curl https://example.org/store/push \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"records":[{"op":"create","type":"org.example.note#0","id":"'"$(uuidgen)"'",
       "clock":"2026-11-12T09:21:00.000Z/0000/shell","value":{"text":"buy milk"}}]}'
```

Read everything:

```sh
curl https://example.org/store/pull -H "Authorization: Bearer $TOKEN"
```

## Open questions

- Type schemas: prose for each type, or something machine-readable like AT lexicons.
- Files such as pictures and attachments.
- A reference server.
- Merging inside one record when two people edit it, once stores are shared.
