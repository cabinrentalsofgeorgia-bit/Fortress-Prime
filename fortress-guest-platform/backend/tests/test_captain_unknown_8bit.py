"""Issue #259 — Captain unknown-8bit codec shim.

RFC 1428 / RFC 1652 'unknown-8bit' is a legitimate MIME encoding declaration
meaning '8-bit content of unknown character set'. Python's stdlib codecs
registry has no entry for it, so a raw .decode('unknown-8bit') raises
LookupError before errors='replace' takes effect. Captain's IMAP fetch path
was silently dropping ~10 messages per patrol on gary-crog before this fix.
"""
from __future__ import annotations

import codecs

from email import message_from_bytes


def test_unknown_8bit_codec_resolves_to_latin1() -> None:
    """After Captain module import, codecs.lookup('unknown-8bit') succeeds."""
    import backend.services.captain_multi_mailbox  # noqa: F401

    info = codecs.lookup("unknown-8bit")
    assert info.name == "iso8859-1"  # latin-1's canonical Python codec name


def test_unknown_8bit_decodes_arbitrary_bytes() -> None:
    """Every byte 0x00-0xff round-trips through the unknown-8bit codec."""
    import backend.services.captain_multi_mailbox  # noqa: F401

    raw = bytes(range(256))
    decoded = raw.decode("unknown-8bit")
    assert len(decoded) == 256
    assert decoded.encode("unknown-8bit") == raw


def test_unknown_8bit_case_and_underscore_variants() -> None:
    """Codec name lookup is case-insensitive and tolerates underscore variant."""
    import backend.services.captain_multi_mailbox  # noqa: F401

    canonical = codecs.lookup("unknown-8bit").name
    assert codecs.lookup("UNKNOWN-8BIT").name == canonical
    assert codecs.lookup("Unknown-8bit").name == canonical
    assert codecs.lookup("unknown_8bit").name == canonical


def test_email_parse_with_unknown_8bit_charset() -> None:
    """Real-world: parse a message claiming charset='unknown-8bit'."""
    import backend.services.captain_multi_mailbox  # noqa: F401

    raw_msg = (
        b"From: test@example.com\r\n"
        b"Subject: Test\r\n"
        b"Content-Type: text/plain; charset=\"unknown-8bit\"\r\n"
        b"Content-Transfer-Encoding: 8bit\r\n"
        b"\r\n"
        b"Hello \xe9\xe8\xe0 world\r\n"  # bytes that fail strict utf-8
    )
    msg = message_from_bytes(raw_msg)
    payload_bytes = msg.get_payload(decode=True)
    assert isinstance(payload_bytes, (bytes, bytearray))
    charset = msg.get_content_charset()
    assert charset == "unknown-8bit"
    payload = bytes(payload_bytes).decode(charset)
    assert "Hello" in payload
    assert "world" in payload
