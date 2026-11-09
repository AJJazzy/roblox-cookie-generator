# Session Cookie Fixture Lab

Generate repeatable session data for authentication tests. The CLI runs entirely
offline and uses synthetic values reserved for fixtures.

## Quick start

Use Python 3.10 or newer. The CLI uses the standard library.

```sh
python3 main.py generate --count 24 --seed 42 > fixtures.json
python3 main.py verify fixtures.json
```

`generate` writes JSON to standard output. It defaults to 12 cases and accepts
1 to 10,000. Use the same count and integer seed to reproduce a batch. Omit the
seed to generate a new batch.

You can also verify a batch without creating a file.

```sh
python3 main.py generate | python3 main.py verify
```

## Check one cookie

Pass a case's `cookie_header` to `check`. This example uses the first case
from the seed 42 batch above.

```sh
python3 main.py check fixtures.json \
  --cookie-header fixture_session=fixture_1c80317fa3b1799d0000000000000000
```

```json
{"outcome": "active", "account_id": "fixture_account_00001"}
```

`check` looks up the cookie in `sessions` at the batch's `reference_time`.
An active session resolves to its synthetic account ID. Other outcomes
return `null` for `account_id`. Omit `--cookie-header` to check a missing
cookie. The command exits with 0 when it evaluates the cookie and 2 when
the fixture store or header is invalid.

## Using the fixtures in a test

Load the JSON and use `sessions` as your test session store. For each entry in
`cases`, use `cookie` as the raw value or `cookie_header` as the value of an
HTTP `Cookie` request header. Compare the result to `expected` and
`expected_account_id`. A missing cookie has `null` in both cookie fields.

| Outcome | Test input |
| --- | --- |
| `active` | A known cookie with an expiry after `reference_time` |
| `expired` | A known cookie that expires at or before `reference_time` |
| `revoked` | A known cookie marked revoked, regardless of expiry |
| `unknown` | A synthetic cookie absent from `sessions` |
| `missing` | A JSON `null` cookie |
| `malformed` | The `fixture_invalid` placeholder in a syntactically valid HTTP cookie |

Each session record has a Unix timestamp in seconds (`expires_at`) and a
boolean `revoked` flag. Schema version 2 also records a synthetic `account_id`
for each session. Regular fixture values have a `fixture_` prefix followed by
32 lowercase hexadecimal characters and use the `fixture_session` cookie
name. `check` and `verify` also accept version 1 fixtures. For those files,
`check` returns `null` for the account ID.

`verify` checks the header and account expectations for version 2 cases. It
evaluates each case against the stored `reference_time`, so results are
independent of the clock.

`verify` exits with 0 when all outcomes match, 1 when any outcome differs,
and 2 when the input or command is invalid. It accepts up to 4 MiB of UTF-8 JSON.

## Run the tests

```sh
python3 -m unittest discover -s tests -v
```
