# smallsync

Draft, version 0. Anything here may still change.

A store is one person's records, kept on a server they pick. Apps keep their records in it,
each under its own types, the way AT Protocol apps share a repo. The server never reads
a record's value; it keeps the latest copy of each record and numbers every write. Clients
pull what changed since their last pull and push their own changes. Anyone can run a server,
write a client, or define new types.

## Records

Every record on the wire is one of three operations:

```json
{ "op": "create", "type": "lt.tsx.vantage.event#0", "id": "6f1c…", "seq": 431,
  "clock": "2026-11-12T09:21:03.250Z/0000/pixel", "value": { … } }
{ "op": "update", "type": "…", "id": "…", "seq": 433, "clock": "…", "value": { … } }
{ "op": "delete", "type": "…", "id": "…", "seq": 434, "clock": "…" }
```

- `type` is a reverse domain name and a version, like an Open Evnt component's type id:
  whoever owns the domain defines what goes in it. `id` is unique inside the type; the type
  says how ids are picked (UUIDs unless it says otherwise).
- `seq` is set by the server: the number of the write that produced this copy. One counter
  per store, so `seq` only goes up.
- `clock` is set by the client that made the change. See below.
- A `delete` has no `value`. The server keeps it as a tombstone.

## Clocks

A hybrid logical clock written as `<UTC time, ms, Z>/<counter, 4 digits>/<device>`, so two
clocks compare as plain strings. On each change a client takes the current time, or the
highest clock it has seen if that is later, adding 1 to the counter when the time part did
not move. A phone with a wrong clock then cannot win every conflict from then on.

The default rule for two copies of one record is that the higher clock wins. A type may
define a finer merge (per field, sets); clients that do not know the type use the default.

## Versions

A type ends in `#<version>`, as in Open Evnt (`directory.evnt.component.link#0`). Adding an
optional field keeps the version. A change that would break readers is a new version, and a
new version is a separate type: old clients keep reading `#0`, and the app that owns the type
moves its own records across. In a URL the `#` is written `%23`.

## Endpoints

Four, under the store's URL. Every request sends `Authorization: Bearer <token>`; nothing is
public. Errors are `{ "error": "<code>", "message": "…" }`: `401` for a missing or wrong
token, `410` for a cursor older than the tombstones the server kept.

### `GET /`

What this store speaks and what the token may do.

```json
{ "versions": [0], "subscribe": true, "read": ["*"], "write": ["lt.tsx.vantage.event#0"] }
```

`read` and `write` list the types the token may touch; `["*"]` is all of them, `[]` none.

### `GET /pull?since=<seq>&types=<a,b>&limit=<n>`

Records written after `since`, oldest first; `since=0` is everything. `types` is optional
and filters by type.

```json
{ "records": [ … ], "next": 431, "more": false }
```

Unlike Jetstream this is not a log of every write: each record appears once, as its latest
copy. A record created, edited and deleted between two pulls comes back as one `delete`. The
operation is relative to `since`:

- `create`: the record was created after `since`, so the reader has not seen it. Created means
  its first write, or its first write after a delete.
- `update`: it was created at or before `since`, so the reader may hold an older copy.
- `delete`: it is gone. A server may leave out deletes of records created after `since`.

Pull again from `next` while `more` is true. A server that has dropped tombstones older than
`since` answers `410`, and the client starts over from `0`.

### `POST /push`

```json
{ "records": [
  { "op": "create", "type": "…", "id": "…", "clock": "…", "value": { … } },
  { "op": "update", "type": "…", "id": "…", "base": 412, "clock": "…", "value": { … } },
  { "op": "delete", "type": "…", "id": "…", "base": 412, "clock": "…" } ] }
```

- `create` is written when the id has no record, or only a tombstone.
- `update` and `delete` carry `base`, the `seq` of the copy the client last saw, and are written
  only when the stored `seq` equals it.

Each record is written or refused on its own.

```json
{ "written": [ { "type": "…", "id": "…", "seq": 435 } ],
  "conflicts": [ { "op": "update", "type": "…", "id": "…", "seq": 420, "clock": "…", "value": { … } } ],
  "refused": [ { "type": "…", "id": "…", "error": "not-found" } ] }
```

- A conflict is the server's current copy, as an `update` or a `delete`. The client merges by
  the type's rule and pushes again with `base` set to that `seq`.
- `refused` covers an `update` or `delete` of an id the server never had (`not-found`) and
  writes outside the token's `write` list (`forbidden`).

### `GET /subscribe?since=<seq>&types=<a,b>`

Server-sent events, one record per event: first what `pull` would return for `since`, then
each write as it happens. Only when `GET /` says `"subscribe": true`; otherwise clients poll
`pull`.

## Tokens

How a token is made is the server's business. Two ways are named here:

- A static token, printed at setup or shown on a web page. Scripts and small servers use these.
- An OAuth access token from an OIDC provider. The server checks it against the issuer (`iss`,
  `aud`, `exp`, the issuer's signing keys), and `sub` says who is asking. Every `401` carries
  `WWW-Authenticate: Bearer resource_metadata="<url>"` (RFC 9728), a public document naming
  the issuer, so a client finds where to log in from the store's URL alone. Scopes are
  `read:<type>` and `write:<type>`, or `read:*` and `write:*`.

A token opens one store, and `GET /` says which types it may read and write. Revoking a device
is deleting its token, or its session at the provider.

## A server must

- keep, per record, the `seq` of its latest write, the `seq` of the write that created it, and
  the latest clock and value
- write a `create` only over nothing or a tombstone, and an `update` or `delete` only on a
  matching `base`; otherwise return the current copy
- keep tombstones, or answer `410` for a `since` older than the ones it kept

It never validates `value` and never compares clocks. A table of
`(type, id, seq, created_seq, clock, deleted, value)` and a counter is a whole server, small
enough for one Python script on the standard library.

## Example

A script adding a record:

```sh
curl -H "Authorization: Bearer $T" -d '{"records":[{"op":"create","type":"lt.tsx.vantage.event#0",
  "id":"'"$(uuidgen)"'","clock":"2026-11-12T09:21:00.000Z/0000/script",
  "value":{"source":{"type":"http","url":"https://example.org/e.evnt.json"},
  "format":"directory.evnt.event","addedAt":"2026-11-12T09:21:00Z"}}]}' \
  https://example.org/store/push
```

## Open

- Type schemas: prose per type, or a machine-readable schema like AT lexicons.
- Files (pictures, attachments): not covered.
- A reference server.
- Shared stores (two people, a club) work as is, since a token opens a store; a finer merge
  inside one record matters once two people edit the same one.
