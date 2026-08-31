#!/usr/bin/env python3
"""Prueba rapida para correr DENTRO de Termux, en la propia tablet del robot.

Objetivo: comprobar que desde la propia tablet se puede hablar con su propio
servidor local (puerto 9015, / robot), usando 127.0.0.1 (localhost) en vez de
una IP de red -- si el bridge acaba corriendo aqui de verdad, esto es
exactamente la llamada que haria.

No necesita ninguna libreria externa, solo Python estandar.
"""

import base64
import json
import os
import socket
import struct

HOST = "127.0.0.1"
PORT = 9015
PATH = "/robot"


def ws_connect(host, port, path, timeout=6):
    s = socket.create_connection((host, port), timeout=timeout)
    key = base64.b64encode(os.urandom(16)).decode()
    req = (
        f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
        f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
    )
    s.sendall(req.encode())
    resp = s.recv(4096)
    if b"101" not in resp.split(b"\r\n")[0]:
        raise RuntimeError("No hizo upgrade: " + resp.decode(errors="replace")[:300])
    return s


def send_text(s, msg):
    payload = msg.encode()
    mask = os.urandom(4)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    length = len(payload)
    header = struct.pack("!BB", 0x81, 0x80 | length)
    s.sendall(header + mask + masked)


def recv_frame(s, timeout=6):
    s.settimeout(timeout)
    data = s.recv(65536)
    if len(data) < 2:
        return None
    b2 = data[1]
    masked = b2 & 0x80
    length = b2 & 0x7F
    idx = 2
    if length == 126:
        length = struct.unpack("!H", data[idx:idx + 2])[0]
        idx += 2
    if masked:
        mask = data[idx:idx + 4]
        idx += 4
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(data[idx:idx + length]))
    else:
        payload = data[idx:idx + length]
    return payload


print(f"Conectando a ws://{HOST}:{PORT}{PATH} ...")
sock = ws_connect(HOST, PORT, PATH)
print("Conexion abierta, pidiendo info...")
send_text(sock, '{"cmd":"info"}')
payload = recv_frame(sock)
print("RESPUESTA:")
print(json.dumps(json.loads(payload.decode()), indent=2, ensure_ascii=False))
sock.close()
