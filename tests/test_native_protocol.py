"""
native_host/host.py 프로토콜 테스트.
length-prefix JSON 인코딩/디코딩 및 _reply 헬퍼를 검증한다.
"""
from __future__ import annotations

import io
import json
import struct
import sys


def _encode(data: dict) -> bytes:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    return struct.pack("<I", len(body)) + body


def _decode(raw: bytes) -> dict:
    length = struct.unpack("<I", raw[:4])[0]
    return json.loads(raw[4 : 4 + length])


class _FakeStdin:
    def __init__(self, data: bytes) -> None:
        self.buffer = io.BytesIO(data)


class _FakeStdout:
    def __init__(self) -> None:
        self.buffer = io.BytesIO()

    def getvalue(self) -> bytes:
        return self.buffer.getvalue()


def test_read_message_roundtrip():
    """read_message가 length-prefixed JSON을 올바르게 파싱한다."""
    from native_host.host import read_message

    msg = {"action": "ping", "request_id": "r1", "payload": {}}
    old, sys.stdin = sys.stdin, _FakeStdin(_encode(msg))
    try:
        result = read_message()
    finally:
        sys.stdin = old
    assert result == msg


def test_send_message_format():
    """send_message가 올바른 4-byte little-endian 길이 prefix를 붙인다."""
    from native_host.host import send_message

    fake = _FakeStdout()
    old, sys.stdout = sys.stdout, fake
    try:
        send_message({"success": True, "request_id": "r1", "data": {"status": "ok"}})
    finally:
        sys.stdout = old

    raw = fake.getvalue()
    assert len(raw) >= 4
    length = struct.unpack("<I", raw[:4])[0]
    assert length == len(raw) - 4
    decoded = json.loads(raw[4:])
    assert decoded["success"] is True
    assert decoded["request_id"] == "r1"


def test_read_message_empty_stdin_returns_none():
    """stdin이 비어 있으면 None을 반환한다."""
    from native_host.host import read_message

    old, sys.stdin = sys.stdin, _FakeStdin(b"")
    try:
        result = read_message()
    finally:
        sys.stdin = old
    assert result is None


def test_reply_success():
    from native_host.host import _reply

    r = _reply("abc", True, {"status": "ok"})
    assert r == {"success": True, "request_id": "abc", "data": {"status": "ok"}}


def test_reply_error():
    from native_host.host import _reply

    r = _reply("xyz", False, error="unknown_action: foo")
    assert r["success"] is False
    assert r["error"] == "unknown_action: foo"
    assert r["request_id"] == "xyz"
    assert "data" not in r


def test_reply_success_no_data():
    """data=None이면 data 키가 응답에 포함되지 않는다."""
    from native_host.host import _reply

    r = _reply("r", True, data=None)
    assert "data" not in r


def test_send_then_read_roundtrip():
    """send_message로 쓴 바이트를 read_message로 다시 읽을 수 있다."""
    from native_host.host import read_message, send_message

    original = {"action": "get_job_status", "request_id": "42", "payload": {"job_id": "abc"}}

    fake_out = _FakeStdout()
    old_out, sys.stdout = sys.stdout, fake_out
    try:
        send_message(original)
    finally:
        sys.stdout = old_out

    fake_in = _FakeStdin(fake_out.getvalue())
    old_in, sys.stdin = sys.stdin, fake_in
    try:
        result = read_message()
    finally:
        sys.stdin = old_in

    assert result == original
