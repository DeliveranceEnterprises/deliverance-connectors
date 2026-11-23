# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT
"""Client for the WebSocket API served by the WDC robot's tablet app.

Stdlib only and ROS-free, so it can be unit tested without ROS. No WebSocket
package is available in the ROS1 image, and the protocol is small: RFC 6455
handshake, masked client frames, JSON text messages such as
{"cmd": "getPoses"} answered with {"data": ...}.

The server tags replies with no request id and can deliver a reply meant for
another client, so replies are checked against the shape expected for the
command, and mismatched ones are dropped.
"""

import base64
import json
import logging
import os
import socket
import struct
import threading
import time
from contextlib import contextmanager
from typing import Callable, Optional, Tuple

OP_CONTINUATION = 0x0
OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA

# Upper bound for one message; the map reply is the largest (a few MB).
MAX_MESSAGE_BYTES = 32 * 1024 * 1024

Frame = Tuple[bool, int, bytes]


class ProtocolError(ConnectionError):
    """The server sent something that is not valid WebSocket."""


class ConnectionClosed(ConnectionError):
    """The server closed the connection."""


class Preempted(Exception):
    """A priority request (STOP) needs the connection."""


def encode_frame(opcode: int, payload: bytes, mask: Optional[bytes] = None) -> bytes:
    """Encodes one final, masked client frame."""
    if mask is None:
        mask = os.urandom(4)
    length = len(payload)
    first = 0x80 | opcode
    if length <= 125:
        header = struct.pack("!BB", first, 0x80 | length)
    elif length <= 0xFFFF:
        header = struct.pack("!BBH", first, 0x80 | 126, length)
    else:
        header = struct.pack("!BBQ", first, 0x80 | 127, length)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return header + mask + masked


class FrameBuffer:
    """Accumulates received bytes and splits them into frames, keeping any
    bytes that belong to the next frame."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def __len__(self) -> int:
        return len(self._buf)

    def feed(self, data: bytes) -> None:
        self._buf.extend(data)

    def next_frame(self) -> Optional[Frame]:
        """Returns (fin, opcode, payload) for the next complete frame, or
        None when more bytes are needed."""
        buf = self._buf
        if len(buf) < 2:
            return None
        fin = bool(buf[0] & 0x80)
        opcode = buf[0] & 0x0F
        masked = bool(buf[1] & 0x80)
        length = buf[1] & 0x7F
        idx = 2
        if length == 126:
            if len(buf) < 4:
                return None
            length = struct.unpack("!H", bytes(buf[2:4]))[0]
            idx = 4
        elif length == 127:
            if len(buf) < 10:
                return None
            length = struct.unpack("!Q", bytes(buf[2:10]))[0]
            idx = 10
        if length > MAX_MESSAGE_BYTES:
            raise ProtocolError(f"frame of {length} bytes is too large")
        if opcode >= 0x8 and (length > 125 or not fin):
            raise ProtocolError("invalid control frame")
        needed = idx + (4 if masked else 0) + length
        if len(buf) < needed:
            return None
        if masked:
            mask = bytes(buf[idx:idx + 4])
            idx += 4
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(buf[idx:idx + length]))
        else:
            payload = bytes(buf[idx:idx + length])
        del buf[:needed]
        return fin, opcode, payload


class MessageAssembler:
    """Turns frames into complete data messages, handling fragmentation
    and control frames. `send_frame(opcode, payload)` is used for pong and
    close replies."""

    def __init__(self, send_frame: Callable[[int, bytes], None]) -> None:
        self._send_frame = send_frame
        self._fragments: Optional[bytearray] = None

    def reset(self) -> None:
        self._fragments = None

    def handle(self, frame: Frame) -> Optional[bytes]:
        """Returns the payload of a completed data message, else None."""
        fin, opcode, payload = frame
        if opcode == OP_PING:
            self._send_frame(OP_PONG, payload)
            return None
        if opcode == OP_PONG:
            return None
        if opcode == OP_CLOSE:
            try:
                self._send_frame(OP_CLOSE, payload[:2])
            finally:
                self._fragments = None
            raise ConnectionClosed("server closed the connection")
        if opcode in (OP_TEXT, OP_BINARY):
            if self._fragments is not None:
                raise ProtocolError("new message before the previous one ended")
            if fin:
                return payload
            self._fragments = bytearray(payload)
            return None
        if opcode == OP_CONTINUATION:
            if self._fragments is None:
                raise ProtocolError("continuation frame without a message")
            self._fragments.extend(payload)
            if len(self._fragments) > MAX_MESSAGE_BYTES:
                raise ProtocolError("message is too large")
            if fin:
                message = bytes(self._fragments)
                self._fragments = None
                return message
            return None
        raise ProtocolError(f"unknown opcode {opcode:#x}")


# Keys that identify the reply of each telemetry command. "info" replies
# carry many fields; any of these is enough to recognise one.
_REPLY_KEYS = {
    "getPoses": ("x", "y"),
    "scan": ("data", "angle_min"),
    "obtainingPower": ("percentage",),
    "map": ("data", "width", "height", "resolution"),
}
_INFO_KEYS = ("agvStop", "errorcode", "readycode")


def _looks_like(cmd: str, data) -> bool:
    if not isinstance(data, dict):
        return False
    if cmd == "info":
        return any(k in data for k in _INFO_KEYS)
    keys = _REPLY_KEYS.get(cmd)
    return keys is not None and all(k in data for k in keys)


def reply_matches(cmd: str, envelope) -> bool:
    """True when a decoded reply plausibly answers `cmd`.

    Telemetry commands must get their own shape. Other commands
    (navigation, stopAction, charging) must not get a telemetry reply. When
    the envelope names a command, it must be `cmd`."""
    if not isinstance(envelope, dict):
        return False
    named = envelope.get("cmd")
    if isinstance(named, str) and named and named != cmd:
        return False
    data = envelope.get("data")
    if cmd == "info" or cmd in _REPLY_KEYS:
        return _looks_like(cmd, data)
    return not any(_looks_like(other, data) for other in ("info", *_REPLY_KEYS))


class LocalApiClient:
    """One persistent connection, reopened after any failure, with one
    request in flight at a time.

    Requests made inside `priority()` (the STOP path) pause the others:
    a normal request waiting for its reply gives up the connection, and new
    normal requests are skipped until the priority block ends.
    """

    # How often a normal request waiting for its reply checks for a
    # priority request.
    _SLICE_SEC = 0.25
    # Mismatched replies dropped before a request gives up.
    _MAX_SKIPPED_REPLIES = 3

    def __init__(self, host: str, port: int, path: str, timeout: float = 4.0,
                 logger: Optional[logging.Logger] = None) -> None:
        self._host = host
        self._port = port
        self._path = path
        self._timeout = timeout
        self._log = logger or logging.getLogger(__name__)
        self._sock: Optional[socket.socket] = None
        self._frames = FrameBuffer()
        self._assembler = MessageAssembler(self._send_frame)
        self._lock = threading.Lock()
        self._priority_count = 0
        self._priority_guard = threading.Lock()
        self._local = threading.local()

    # -- priority -----------------------------------------------------------

    @contextmanager
    def priority(self):
        """Marks the requests of the current thread as priority."""
        with self._priority_guard:
            self._priority_count += 1
        self._local.priority = getattr(self._local, "priority", 0) + 1
        try:
            yield
        finally:
            self._local.priority -= 1
            with self._priority_guard:
                self._priority_count -= 1

    def _is_priority_thread(self) -> bool:
        return getattr(self._local, "priority", 0) > 0

    def _preempted(self) -> bool:
        return self._priority_count > 0 and not self._is_priority_thread()

    # -- transport ----------------------------------------------------------

    def _connect(self) -> None:
        sock = socket.create_connection((self._host, self._port), timeout=self._timeout)
        try:
            key = base64.b64encode(os.urandom(16)).decode()
            request = (
                f"GET {self._path} HTTP/1.1\r\n"
                f"Host: {self._host}:{self._port}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n"
            )
            sock.sendall(request.encode())
            response = b""
            while b"\r\n\r\n" not in response:
                chunk = sock.recv(4096)
                if not chunk:
                    raise ConnectionError("connection closed during the handshake")
                response += chunk
                if len(response) > 16384:
                    raise ProtocolError("handshake response is too long")
            head, _, rest = response.partition(b"\r\n\r\n")
            if b" 101" not in head.split(b"\r\n", 1)[0]:
                raise ConnectionError(f"WDC local API did not upgrade: {head[:200]!r}")
        except Exception:
            sock.close()
            raise
        self._sock = sock
        self._frames = FrameBuffer()
        self._frames.feed(rest)
        self._assembler.reset()

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        self._sock.sendall(encode_frame(opcode, payload))

    def _recv_message(self, deadline: float, preemptible: bool) -> bytes:
        while True:
            frame = self._frames.next_frame()
            while frame is not None:
                message = self._assembler.handle(frame)
                if message is not None:
                    return message
                frame = self._frames.next_frame()
            if preemptible and self._preempted():
                raise Preempted()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise socket.timeout("timed out waiting for a reply")
            self._sock.settimeout(min(remaining, self._SLICE_SEC) if preemptible else remaining)
            try:
                chunk = self._sock.recv(65536)
            except socket.timeout:
                continue
            if not chunk:
                raise ConnectionClosed("connection closed by the server")
            self._frames.feed(chunk)

    def close(self) -> None:
        try:
            if self._sock is not None:
                self._sock.close()
        except OSError:
            pass
        self._sock = None
        self._assembler.reset()

    # -- requests -----------------------------------------------------------

    def request(self, cmd: str, **extra):
        """Sends {"cmd": cmd, **extra} and returns the reply's "data" field,
        or None on any failure (or when skipped for a priority request).
        Never raises."""
        priority = self._is_priority_thread()
        if self._preempted():
            self._log.debug("WDC local API request(%s) skipped: priority request in progress", cmd)
            return None
        with self._lock:
            if self._preempted():
                self._log.debug("WDC local API request(%s) skipped: priority request in progress", cmd)
                return None
            try:
                if self._sock is None:
                    self._connect()
                payload = {"cmd": cmd}
                payload.update(extra)
                self._send_frame(OP_TEXT, json.dumps(payload).encode())
                deadline = time.monotonic() + self._timeout
                for _ in range(self._MAX_SKIPPED_REPLIES + 1):
                    raw = self._recv_message(deadline, preemptible=not priority)
                    try:
                        envelope = json.loads(raw.decode())
                    except ValueError:
                        envelope = None
                    if reply_matches(cmd, envelope):
                        return envelope.get("data")
                    self._log.warning("WDC local API: dropped a reply that does not match %r: %.120r", cmd, raw)
                raise ConnectionError("too many mismatched replies")
            except Preempted:
                # The reply may still arrive; the shape check drops it.
                self._log.info("WDC local API request(%s) gave way to a priority request", cmd)
                return None
            except Exception as exc:
                self._log.warning("WDC local API request(%s) failed: %s", cmd, exc)
            self.close()
            return None
