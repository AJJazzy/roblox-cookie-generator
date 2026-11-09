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

## Using the fixtures in a test

Load the JSON and use `sessions` as your test session store. For each entry in
`cases`, pass its `cookie` to your test authentication handler and compare the
result to `expected`. The document uses schema `version` 1.

| Outcome | Test input |
| --- | --- |
| `active` | A known cookie with an expiry after `reference_time` |
| `expired` | A known cookie that expires at or before `reference_time` |
| `revoked` | A known cookie marked revoked, regardless of expiry |
| `unknown` | A synthetic cookie absent from `sessions` |
| `missing` | A JSON `null` cookie |
| `malformed` | The `fixture_invalid` placeholder |

Each session record has a Unix timestamp in seconds (`expires_at`) and a
boolean `revoked` flag. Regular fixture cookies have a `fixture_` prefix
followed by 32 lowercase hexadecimal characters. `verify` evaluates each case
against the stored `reference_time`, so results are independent of the clock.

`verify` exits with 0 when all outcomes match, 1 when any outcome differs,
and 2 when the input or command is invalid. It accepts up to 4 MiB of UTF-8 JSON.

## Run the tests

```sh
python3 -m unittest discover -s tests -v
```
