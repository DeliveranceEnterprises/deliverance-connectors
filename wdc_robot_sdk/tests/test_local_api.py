# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

import base64
import hashlib
import json
import socket
import struct
import threading
import time

import pytest

from wdc_local_api import (
    OP_BINARY,
    OP_CLOSE,
    OP_CONTINUATION,
    OP_PING,
    OP_PONG,
    OP_TEXT,
    ConnectionClosed,
    FrameBuffer,
    LocalApiClient,
    MessageAssembler,
    ProtocolError,
    encode_frame,
    reply_matches,
)


def server_frame(opcode, payload, fin=True):
    """Unmasked frame, as a server sends it."""
    first = (0x80 if fin else 0) | opcode
    n = len(payload)
    if n <= 125:
        header = struct.pack("!BB", first, n)
    elif n <= 0xFFFF:
        header = struct.pack("!BBH", first, 126, n)
    else:
        header = struct.pack("!BBQ", first, 127, n)
    return header + payload


def text(obj):
    return server_frame(OP_TEXT, json.dumps(obj).encode())


# -- frames -------------------------------------------------------------------


def test_masked_client_frame_round_trips():
    for size in (0, 5, 125, 126, 70000):
        payload = bytes(range(256)) * (size // 256) + bytes(size % 256)
        buf = FrameBuffer()
        buf.feed(encode_frame(OP_TEXT, payload))
        assert buf.next_frame() == (True, OP_TEXT, payload)
        assert len(buf) == 0


def test_several_frames_in_one_chunk_keep_the_leftover():
    buf = FrameBuffer()
    buf.feed(text({"data": 1}) + text({"data": 2}) + text({"data": 3})[:3])
    assert json.loads(buf.next_frame()[2]) == {"data": 1}
    assert json.loads(buf.next_frame()[2]) == {"data": 2}
    assert buf.next_frame() is None
    buf.feed(text({"data": 3})[3:])
    assert json.loads(buf.next_frame()[2]) == {"data": 3}


def test_frame_split_byte_by_byte():
    frame = server_frame(OP_TEXT, b"x" * 300)
    buf = FrameBuffer()
    for i, b in enumerate(frame):
        assert buf.next_frame() is None, i
        buf.feed(bytes([b]))
    assert buf.next_frame() == (True, OP_TEXT, b"x" * 300)


def test_invalid_control_frame_is_rejected():
    buf = FrameBuffer()
    buf.feed(server_frame(OP_PING, b"x", fin=False))
    with pytest.raises(ProtocolError):
        buf.next_frame()


def test_assembler_answers_ping_and_joins_fragments():
    sent = []
    asm = MessageAssembler(lambda op, p: sent.append((op, p)))
    assert asm.handle((False, OP_TEXT, b"hel")) is None
    assert asm.handle((True, OP_PING, b"hi")) is None
    assert sent == [(OP_PONG, b"hi")]
    assert asm.handle((True, OP_PONG, b"")) is None
    assert asm.handle((True, OP_CONTINUATION, b"lo")) == b"hello"
    assert asm.handle((True, OP_BINARY, b"raw")) == b"raw"


def test_assembler_close_and_protocol_errors():
    sent = []
    asm = MessageAssembler(lambda op, p: sent.append((op, p)))
    with pytest.raises(ConnectionClosed):
        asm.handle((True, OP_CLOSE, b"\x03\xe8bye"))
    assert sent == [(OP_CLOSE, b"\x03\xe8")]
    with pytest.raises(ProtocolError):
        asm.handle((True, OP_CONTINUATION, b"x"))
    asm.handle((False, OP_TEXT, b"a"))
    with pytest.raises(ProtocolError):
        asm.handle((True, OP_TEXT, b"b"))
    with pytest.raises(ProtocolError):
        MessageAssembler(lambda *_: None).handle((True, 0x3, b""))


# -- reply shapes -------------------------------------------------------------


@pytest.mark.parametrize(
    "cmd, envelope, expected",
    [
        ("getPoses", {"data": {"x": 1, "y": 2, "yaw": 0}}, True),
        ("getPoses", {"data": {"agvStop": True}}, False),
        ("info", {"data": {"agvStop": True, "errorcode": 0}}, True),
        ("info", {"data": {"x": 1, "y": 2, "pitch": 0}}, False),
        ("obtainingPower", {"data": {"percentage": 80}}, True),
        ("obtainingPower", {"data": "BUSY"}, False),
        ("scan", {"data": {"data": [1], "angle_min": 0}}, True),
        ("map", {"data": {"data": "", "width": 1, "height": 1, "resolution": 0.05}}, True),
        ("navigation", {"data": "accepted"}, True),
        ("navigation", {"data": {"agvStop": False, "errorcode": 0}}, False),
        ("stopAction", {"data": None}, True),
        ("stopAction", {"data": {"x": 0, "y": 0}}, False),
        ("info", {"cmd": "getPoses", "data": {"agvStop": True}}, False),
        ("info", "not a dict", False),
    ],
)
def test_reply_matches(cmd, envelope, expected):
    assert reply_matches(cmd, envelope) is expected


# -- client against a local server --------------------------------------------


class FakeTablet:
    """Accepts one WebSocket connection and answers each request with the
    frames the test queued for it."""

    def __init__(self, replies, handshake_extra=b""):
        self.replies = list(replies)
        self.received = []
        self.handshake_extra = handshake_extra
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(1)
        self.port = self.server.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        conn, _ = self.server.accept()
        with conn:
            data = b""
            while b"\r\n\r\n" not in data:
                data += conn.recv(4096)
            key = [line.split(b": ")[1] for line in data.split(b"\r\n") if line.lower().startswith(b"sec-websocket-key")][0]
            accept = base64.b64encode(hashlib.sha1(key + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest())
            conn.sendall(
                b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                b"Connection: Upgrade\r\nSec-WebSocket-Accept: " + accept + b"\r\n\r\n" + self.handshake_extra
            )
            buf = FrameBuffer()
            while True:
                frame = buf.next_frame()
                if frame is None:
                    chunk = conn.recv(65536)
                    if not chunk:
                        return
                    buf.feed(chunk)
                    continue
                self.received.append(frame)
                if frame[1] == OP_TEXT and self.replies:
                    reply = self.replies.pop(0)
                    if reply:
                        conn.sendall(reply)


def client(tablet, timeout=2.0):
    return LocalApiClient("127.0.0.1", tablet.port, "/robot", timeout=timeout)


def test_request_returns_data_and_keeps_extra_frames():
    tablet = FakeTablet([
        text({"data": {"x": 1, "y": 2}}) + text({"data": {"percentage": 50}}),
        b"",
    ])
    api = client(tablet)
    assert api.request("getPoses") == {"x": 1, "y": 2}
    # The second reply arrived in the same chunk and must not be lost.
    assert api.request("obtainingPower") == {"percentage": 50}
    assert json.loads(tablet.received[0][2]) == {"cmd": "getPoses"}


def test_request_answers_ping_before_the_reply():
    tablet = FakeTablet([server_frame(OP_PING, b"p") + text({"data": {"agvStop": True}})])
    api = client(tablet)
    assert api.request("info") == {"agvStop": True}
    deadline = time.time() + 2
    while time.time() < deadline and not any(f[1] == OP_PONG for f in tablet.received):
        time.sleep(0.01)
    assert (True, OP_PONG, b"p") in tablet.received


def test_request_drops_a_reply_meant_for_another_command():
    tablet = FakeTablet([text({"data": {"x": 1, "y": 2}}) + text({"data": {"agvStop": False, "errorcode": 0}})])
    api = client(tablet)
    assert api.request("info") == {"agvStop": False, "errorcode": 0}


def test_request_joins_fragmented_reply():
    body = json.dumps({"data": "accepted"}).encode()
    tablet = FakeTablet([
        server_frame(OP_TEXT, body[:4], fin=False) + server_frame(OP_CONTINUATION, body[4:]),
    ])
    assert client(tablet).request("navigation", name="A", x=0, y=0, yaw=0) == "accepted"


def test_bytes_after_the_handshake_are_kept():
    tablet = FakeTablet([b""], handshake_extra=server_frame(OP_PING, b"early"))
    tablet.replies = [text({"data": {"percentage": 10}})]
    assert client(tablet).request("obtainingPower") == {"percentage": 10}


def test_close_frame_returns_none():
    tablet = FakeTablet([server_frame(OP_CLOSE, b"\x03\xe8")])
    assert client(tablet).request("info") is None


def test_timeout_returns_none():
    tablet = FakeTablet([b""])
    assert client(tablet, timeout=0.3).request("info") is None


def test_priority_request_preempts_a_waiting_request():
    # The first request never gets a reply; a priority request from another
    # thread must not wait for its timeout.
    tablet = FakeTablet([b"", text({"data": "ok"})])
    api = client(tablet, timeout=10.0)
    results = {}

    def slow():
        results["slow"] = api.request("info")

    t = threading.Thread(target=slow)
    t.start()
    time.sleep(0.3)
    start = time.monotonic()
    with api.priority():
        results["stop"] = api.request("stopAction")
        # Normal requests from other threads are skipped meanwhile.
        other = {}
        o = threading.Thread(target=lambda: other.setdefault("r", api.request("info")))
        o.start()
        o.join()
    t.join()
    assert results["stop"] == "ok"
    assert results["slow"] is None
    assert other["r"] is None
    assert time.monotonic() - start < 3.0
