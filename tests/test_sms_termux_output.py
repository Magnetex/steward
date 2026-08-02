"""Handling whatever termux-sms-list actually hands back.

Termux:API is not guaranteed to emit clean JSON — a denied permission or a
version mismatch between the app and the `termux-api` package produces plain
text instead, and some builds print warnings ahead of the array.
"""
import pytest

from app.services.sms_import import SMSUnavailable, parse_termux_output


GOOD = '[{"sender":"VM-HDFCBK","body":"hello","received":"2026-08-01 10:00:00"}]'


def test_parses_normal_output():
    rows = parse_termux_output(GOOD)
    assert len(rows) == 1
    assert rows[0]["sender"] == "VM-HDFCBK"


def test_empty_output_is_an_empty_inbox_not_an_error():
    assert parse_termux_output("") == []
    assert parse_termux_output("   \n") == []


def test_skips_noise_printed_before_the_json():
    """Some builds emit a warning line first."""
    rows = parse_termux_output("Warning: something\n" + GOOD)
    assert len(rows) == 1


def test_tolerates_a_byte_order_mark():
    assert len(parse_termux_output("﻿" + GOOD)) == 1


def test_accepts_a_single_object():
    rows = parse_termux_output('{"sender":"X","body":"y","received":"2026-08-01 10:00:00"}')
    assert len(rows) == 1


def test_plain_text_error_is_reported_with_what_was_said():
    """The old message threw the reason away; it must survive."""
    with pytest.raises(SMSUnavailable) as exc:
        parse_termux_output("Permission denied for READ_SMS")
    assert "Permission denied for READ_SMS" in str(exc.value)


def test_empty_stdout_with_stderr_surfaces_the_stderr():
    with pytest.raises(SMSUnavailable) as exc:
        parse_termux_output("", "termux-api: command not found")
    assert "command not found" in str(exc.value)


def test_non_dict_entries_are_dropped():
    assert parse_termux_output('[{"sender":"a"}, "junk", null]') == [{"sender": "a"}]
