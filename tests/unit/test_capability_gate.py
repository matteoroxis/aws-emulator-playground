"""Unit tests for the gate's classification rules (no emulator needed)."""

import pytest
from botocore.exceptions import ClientError

from tools.capability_gate import (
    DiffersFromAws,
    Expect,
    NotImplementedByEmulator,
    Outcome,
    Result,
    classify,
    judge,
    to_markdown,
)


def client_error(code, status):
    return ClientError({"Error": {"Code": code, "Message": "m"}, "ResponseMetadata": {"HTTPStatusCode": status}}, "Op")


@pytest.mark.parametrize(
    "exc, expected",
    [
        (client_error("NotImplemented", 501), Outcome.NOT_IMPLEMENTED),
        (client_error("Whatever", 501), Outcome.NOT_IMPLEMENTED),
        (NotImplementedByEmulator("501"), Outcome.NOT_IMPLEMENTED),
        (DiffersFromAws("rawPath"), Outcome.DIFFERS),
        (client_error("ValidationException", 400), Outcome.ERROR),
        (AssertionError("boom"), Outcome.ERROR),
    ],
)
def test_classify(exc, expected):
    assert classify(exc) is expected


@pytest.mark.parametrize(
    "expect, outcome, verdict",
    [
        (Expect.SUPPORTED, Outcome.OK, "pass"),
        (Expect.SUPPORTED, Outcome.NOT_IMPLEMENTED, "fail"),
        (Expect.SUPPORTED, Outcome.ERROR, "fail"),
        (Expect.SUPPORTED, Outcome.DIFFERS, "fail"),
        (Expect.KNOWN_GAP, Outcome.NOT_IMPLEMENTED, "pass"),
        (Expect.KNOWN_GAP, Outcome.DIFFERS, "pass"),
        (Expect.KNOWN_GAP, Outcome.OK, "gap-closed"),
        (Expect.KNOWN_GAP, Outcome.ERROR, "fail"),
    ],
)
def test_judge(expect, outcome, verdict):
    assert judge(expect, outcome) == verdict


def test_markdown_escapes_pipes():
    md = to_markdown([Result("s3", "c", Expect.SUPPORTED, Outcome.OK, "a|b", "pass")], "1.0.0")
    assert "a\\|b" in md
    assert md.startswith("### AWS Emulator capability gate (1.0.0)")
