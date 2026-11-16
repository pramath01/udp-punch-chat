"""UDP hole-punch chat that finds its peer through an HTTP signaling server.

Usage: python chat_bore.py <signal_host:port> <room> [name] [local_port]
  e.g. python chat_bore.py bore.pub:12345 my-long-random-room laptop
"""
import json
import os
import socket                                              import struct
import sys
import threading
import time
import urllib.request

if len(sys.argv) < 3:
    sys.exit("usage: python chat_bore.py <host:port> <room> [name] [local_port]")                                     
signal_url = "http://" + sys.argv[1]
room = sys.argv[2]
name = sys.argv[3] if len(sys.argv) > 3 else "peer"
local_port = int(sys.argv[4]) if len(sys.argv) > 4 else 0

MAGIC = 0x2112A442
STUN = (socket.gethostbyname("stun.l.google.com"), 19302)


def binding_request():
    return struct.pack("!HHI", 0x0001, 0, MAGIC) + os.urandom(12)


def parse_mapped(data):
    pos = 20
    while pos + 4 <= len(data):
        atype, alen = struct.unpack("!HH", data[pos:pos + 4])
        val = data[pos + 4:pos + 4 + alen]
        if atype == 0x0020:
            port = struct.unpack("!H", val[2:4])[0] ^ (MAGIC >> 16)
            ip = struct.unpack("!I", val[4:8])[0] ^ MAGIC
            return socket.inet_ntoa(struct.pack("!I", ip)), port
        pos += 4 + alen + (-alen % 4)
    return None


def post_join(addr):
    body = json.dumps({"room": room, "addr": addr}).encode()
    req = urllib.request.Request(
        signal_url + "/join", data=body,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)["peer"]


# --- 1. bind a UDP socket and learn our public address via STUN ---
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("0.0.0.0", local_port))
sock.settimeout(3.0)
sock.sendto(binding_request(), STUN)
data, _ = sock.recvfrom(2048)
mine = parse_mapped(data)
print(f"[chat] your public address: {mine[0]}:{mine[1]}")
sock.settimeout(None)

peer = None
connected = threading.Event()


def keepalive():
    while True:
        time.sleep(10)
        sock.sendto(binding_request(), STUN)  # keeps our NAT mapping alive
        if peer:
            sock.sendto(b"KA", peer)


threading.Thread(target=keepalive, daemon=True).start()

# --- 2. exchange addresses through the signaling server ---
print(f"[chat] joining room '{room}', waiting for the other peer...")
my_addr = f"{mine[0]}:{mine[1]}"
while peer is None:
    try:
        found = post_join(my_addr)
    except Exception as e:
        print(f"[chat] signaling error: {e}")
        found = None
    if found:
        ip, port = found.rsplit(":", 1)
        peer = (ip, int(port))
    else:
        time.sleep(1)
print(f"[chat] found peer {peer[0]}:{peer[1]}")


# --- 3. punch, then chat ---
def receiver():
    global peer
    while True:
        data, addr = sock.recvfrom(2048)
        if addr == STUN:
            continue
        if addr != peer:
            if addr[0] == peer[0]:
                print(f"\r[chat] peer port changed {peer} -> {addr}, switching")
                peer = addr
            else:
                print(f"\r[chat] ignored packet from unexpected source {addr}")
                continue
        if not connected.is_set():
            connected.set()
        if data == b"PUNCH":
            sock.sendto(b"ACK", peer)
        elif data.startswith(b"MSG "):
            print(f"\r{data[4:].decode(errors='replace')}\n> ", end="", flush=True)


threading.Thread(target=receiver, daemon=True).start()

print("[chat] punching...")
tries = 0
while not connected.is_set():
    sock.sendto(b"PUNCH", peer)
    time.sleep(0.5)
    tries += 1
    if tries % 10 == 0:
        print(f"[chat] still trying ({tries // 2}s)...")
    if tries >= 120:
        sys.exit("[chat] gave up after 60s")

for _ in range(3):
    sock.sendto(b"PUNCH", peer)
    time.sleep(0.2)

print("[chat] connected! type a message and press Enter (/quit to exit)")
try:
    while True:
        msg = input("> ")
        if msg.strip() == "/quit":
            break
        if msg:
            sock.sendto(f"MSG {name}: {msg}".encode(), peer)
except (KeyboardInterrupt, EOFError):
    pass