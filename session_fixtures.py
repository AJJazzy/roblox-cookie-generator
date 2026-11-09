"""Generate and evaluate a synthetic session store and its test cases."""

import random
import re
from typing import TypedDict


SCHEMA_VERSION = 1
REFERENCE_TIME = 1_700_000_000
MAX_CASES = 10_000
OUTCOMES = ("active", "expired", "revoked", "unknown", "missing", "malformed")
COOKIE_FORMAT = re.compile(r"fixture_[0-9a-f]{32}")
MALFORMED_COOKIE = "fixture_invalid"


class Session(TypedDict):
    expires_at: int
    revoked: bool


class Case(TypedDict):
    cookie: str | None
    expected: str


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
        cookie = f"fixture_{batch_id}{index:016x}"

        if expected == "missing":
            cases.append({"cookie": None, "expected": expected})
            continue
        if expected == "malformed":
            cases.append({"cookie": MALFORMED_COOKIE, "expected": expected})
            continue
        if expected != "unknown":
            sessions[cookie] = {
                "expires_at": REFERENCE_TIME if expected == "expired" else REFERENCE_TIME + 3600,
                "revoked": expected == "revoked",
            }
        cases.append({"cookie": cookie, "expected": expected})

    return {
        "version": SCHEMA_VERSION,
        "reference_time": REFERENCE_TIME,
        "sessions": sessions,
        "cases": cases,
    }


def _is_fixture_cookie(value: object) -> bool:
    return isinstance(value, str) and COOKIE_FORMAT.fullmatch(value) is not None


def _is_timestamp(value: object) -> bool:
    return type(value) is int and value >= 0


def _outcome(cookie: str | None, sessions: dict[str, Session], now: int) -> str:
    if cookie is None:
        return "missing"
    if cookie == MALFORMED_COOKIE:
        return "malformed"
    session = sessions.get(cookie)
    if session is None:
        return "unknown"
    if session["revoked"]:
        return "revoked"
    if session["expires_at"] <= now:
        return "expired"
    return "active"


def verify_fixtures(data: object) -> tuple[int, list[str]]:
    if (
        not isinstance(data, dict)
        or type(data.get("version")) is not int
        or data["version"] != SCHEMA_VERSION
    ):
        raise ValueError(f"Expected a fixture object with version {SCHEMA_VERSION}.")

    now = data.get("reference_time")
    if not _is_timestamp(now):
        raise ValueError("Reference time must be a nonnegative integer.")

    sessions = data.get("sessions")
    if not isinstance(sessions, dict) or len(sessions) > MAX_CASES:
        raise ValueError(f"Expected a session object with at most {MAX_CASES:,} entries.")
    for cookie, session in sessions.items():
        if not _is_fixture_cookie(cookie):
            raise ValueError("Session keys must use the synthetic cookie format.")
        if (
            not isinstance(session, dict)
            or not _is_timestamp(session.get("expires_at"))
            or not isinstance(session.get("revoked"), bool)
        ):
            raise ValueError("Session records require an integer expires_at and boolean revoked.")

    cases = data.get("cases")
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
        actual = _outcome(cookie, sessions, now)
        if actual != expected:
            mismatches.append(f"Case {index} expected {expected} and got {actual}.")

    return len(cases), mismatches
