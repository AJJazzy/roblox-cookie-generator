"""Command-line interface for offline session fixtures."""

import argparse
import json
import sys
from pathlib import Path

from session_fixtures import MAX_CASES, check_cookie, generate_fixtures, verify_fixtures


MAX_INPUT_BYTES = 4 * 1024 * 1024


def read_fixtures(filename: str) -> object:
    if filename == "-":
        content = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    else:
        with Path(filename).open("rb") as stream:
            content = stream.read(MAX_INPUT_BYTES + 1)

    if len(content) > MAX_INPUT_BYTES:
        raise ValueError("Fixture JSON must be at most 4 MiB.")
    return json.loads(content.decode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate and verify synthetic session fixtures offline."
    )
    commands = parser.add_subparsers(dest="command")

    generate = commands.add_parser("generate", help="Write fixture JSON to stdout")
    generate.add_argument(
        "--count", type=int, default=12, help=f"case count from 1 to {MAX_CASES:,} (default 12)"
    )
    generate.add_argument("--seed", type=int, help="integer seed for repeatable fixtures")

    verify = commands.add_parser("verify", help="Check the expected outcomes in fixture JSON")
    verify.add_argument(
        "file", nargs="?", default="-", help="path to fixture JSON (default stdin)"
    )

    check = commands.add_parser("check", help="Resolve one synthetic cookie in the fixture store")
    check.add_argument("file", help="path to fixture JSON (use - for stdin)")
    check.add_argument("--cookie-header", help="fixture Cookie header value (omit for missing)")

    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0

    try:
        if args.command == "generate":
            fixtures = generate_fixtures(args.count, args.seed)
            print(json.dumps(fixtures, indent=2))
            return 0

        fixtures = read_fixtures(args.file)
        if args.command == "check":
            outcome, account_id = check_cookie(fixtures, args.cookie_header)
            print(json.dumps({"outcome": outcome, "account_id": account_id}))
            return 0

        total, mismatches = verify_fixtures(fixtures)
    except (OSError, ValueError, RecursionError) as error:
        print(error, file=sys.stderr)
        return 2

    if mismatches:
        for mismatch in mismatches[:10]:
            print(mismatch, file=sys.stderr)
        print(f"{len(mismatches)} of {total} fixture cases failed.", file=sys.stderr)
        return 1

    print(f"Verified {total} fixture cases.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
