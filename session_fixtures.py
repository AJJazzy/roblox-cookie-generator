"""Generate and evaluate a synthetic session store and its test cases."""

import random
import re
from typing import TypedDict


SCHEMA_VERSION = 2
REFERENCE_TIME = 1_700_000_000
MAX_CASES = 10_000
OUTCOMES = ("active", "expired", "revoked", "unknown", "missing", "malformed")
COOKIE_NAME = "fixture_session"
COOKIE_FORMAT = re.compile(r"fixture_[0-9a-f]{32}")
MALFORMED_COOKIE = "fixture_invalid"
ACCOUNT_FORMAT = re.compile(r"fixture_account_[0-9]{5}")


class Session(TypedDict):
    expires_at: int
    revoked: bool
    account_id: str | None


class Case(TypedDict):
    cookie: str | None
    cookie_header: str | None
    expected: str
    expected_account_id: str | None


class FixtureSet(TypedDict):
    version: int
    reference_time: int
    sessions: dict[str, Session]
    cases: list[Case]


def generate_fixtures(count: int, seed: int | None = None) -> FixtureSet:
    if type(count) is not int or not 1 <= count <= MAX_CASES:
        raise ValueError(f"Count must be between 1 and {MAX_CASES:,}.")

    batch_id = f"{random.Random(seed).getrandbits(64):016x}"
    sessions: dict[str, Session] = {}
    cases: list[Case] = []

    for index in range(count):
        expected = OUTCOMES[index % len(OUTCOMES)]
        cookie: str | None = f"fixture_{batch_id}{index:016x}"
        account_id = None

        if expected == "missing":
            cookie = None
        elif expected == "malformed":
            cookie = MALFORMED_COOKIE
        elif expected != "unknown":
            account_id = f"fixture_account_{index // len(OUTCOMES) + 1:05d}"
            sessions[cookie] = {
                "expires_at": REFERENCE_TIME if expected == "expired" else REFERENCE_TIME + 3600,
                "revoked": expected == "revoked",
                "account_id": account_id,
            }

        cases.append(
            {
                "cookie": cookie,
                "cookie_header": _cookie_header(cookie),
                "expected": expected,
                "expected_account_id": account_id if expected == "active" else None,
            }
        )

    return {
        "version": SCHEMA_VERSION,
        "reference_time": REFERENCE_TIME,
        "sessions": sessions,
        "cases": cases,
    }


def _is_fixture_cookie(value: object) -> bool:
    return isinstance(value, str) and COOKIE_FORMAT.fullmatch(value) is not None


def _is_fixture_account(value: object) -> bool:
    return isinstance(value, str) and ACCOUNT_FORMAT.fullmatch(value) is not None


def _is_timestamp(value: object) -> bool:
    return type(value) is int and value >= 0


def _cookie_header(cookie: str | None) -> str | None:
    return f"{COOKIE_NAME}={cookie}" if cookie is not None else None


def _evaluate(
    cookie: str | None, sessions: dict[str, Session], now: int
) -> tuple[str, str | None]:
    if cookie is None:
        return "missing", None
    if cookie == MALFORMED_COOKIE:
        return "malformed", None
    session = sessions.get(cookie)
    if session is None:
        return "unknown", None
    if session["revoked"]:
        return "revoked", None
    if session["expires_at"] <= now:
        return "expired", None
    return "active", session["account_id"]


def _read_store(data: object) -> tuple[int, int, dict[str, Session], object]:
    if not isinstance(data, dict):
        raise ValueError("Expected a fixture object.")
    version = data.get("version")
    if type(version) is not int or version not in (1, SCHEMA_VERSION):
        raise ValueError(f"Expected fixture schema version 1 or {SCHEMA_VERSION}.")

    now = data.get("reference_time")
    if not _is_timestamp(now):
        raise ValueError("Reference time must be a nonnegative integer.")

    records = data.get("sessions")
    if not isinstance(records, dict) or len(records) > MAX_CASES:
        raise ValueError(f"Expected a session object with at most {MAX_CASES:,} entries.")
    sessions: dict[str, Session] = {}
    for cookie, session in records.items():
        if not _is_fixture_cookie(cookie):
            raise ValueError("Session keys must use the synthetic cookie format.")
        if (
            not isinstance(session, dict)
            or not _is_timestamp(session.get("expires_at"))
            or not isinstance(session.get("revoked"), bool)
        ):
            raise ValueError("Session records require an integer expires_at and boolean revoked.")
        account_id = session.get("account_id") if version == SCHEMA_VERSION else None
        if version == SCHEMA_VERSION and not _is_fixture_account(account_id):
            raise ValueError("Version 2 session records require a synthetic account_id.")
        sessions[cookie] = {
            "expires_at": session["expires_at"],
            "revoked": session["revoked"],
            "account_id": account_id,
        }
    return version, now, sessions, data.get("cases")


def check_cookie(data: object, cookie_header: str | None) -> tuple[str, str | None]:
    """Resolve a single fixture Cookie header value against the session store."""
    cookie = None
    if cookie_header is not None:
        name, separator, value = cookie_header.partition("=")
        if name != COOKIE_NAME or not separator or (
            value != MALFORMED_COOKIE and not _is_fixture_cookie(value)
        ):
            raise ValueError(f"Cookie header must be one {COOKIE_NAME} pair with a synthetic value.")
        cookie = value

    _, now, sessions, _ = _read_store(data)
    return _evaluate(cookie, sessions, now)


def verify_fixtures(data: object) -> tuple[int, list[str]]:
    version, now, sessions, cases = _read_store(data)
    if not isinstance(cases, list) or not 1 <= len(cases) <= MAX_CASES:
        raise ValueError(f"Expected a list of 1 to {MAX_CASES:,} fixture cases.")

    mismatches = []
    for index, case in enumerate(cases, start=1):
        if not isinstance(case, dict) or "cookie" not in case:
            raise ValueError(f"Case {index} requires a cookie field.")
        cookie = case["cookie"]
        if cookie is not None and cookie != MALFORMED_COOKIE and not _is_fixture_cookie(cookie):
            raise ValueError(f"Case {index} requires a synthetic cookie or null.")

        expected = case.get("expected")
        if expected not in OUTCOMES:
            raise ValueError(f"Case {index} has an invalid expected outcome.")
        expected_account_id = None
        if version == SCHEMA_VERSION:
            if "cookie_header" not in case or case["cookie_header"] != _cookie_header(cookie):
                raise ValueError(f"Case {index} requires a cookie_header matching its cookie.")
            if "expected_account_id" not in case:
                raise ValueError(f"Case {index} requires an expected_account_id field.")
            expected_account_id = case["expected_account_id"]
            if expected_account_id is not None and not _is_fixture_account(expected_account_id):
                raise ValueError(f"Case {index} requires a synthetic expected_account_id or null.")

        actual, account_id = _evaluate(cookie, sessions, now)
        if actual != expected:
            mismatches.append(f"Case {index} expected {expected} and got {actual}.")
        elif account_id != expected_account_id:
            mismatches.append(
                f"Case {index} expected account {expected_account_id!r} and got {account_id!r}."
            )

    return len(cases), mismatches
