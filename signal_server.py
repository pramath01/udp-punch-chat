"""Tiny HTTP signaling server. Peers POST their STUN-discovered public
ip:port with a room name and get back the other peer's address.

Run:   python signal_server.py [port]        (default 8080)Expose with bore:   bore local 8080 --to bore.pub
"""
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
TTL = 60          # seconds before a silent peer is forgotten
MAX_ROOMS = 1000
rooms = {}        # room -> {addr: last_seen}


def clean():
    now = time.time()
    for r in list(rooms):
        rooms[r] = {a: t for a, t in rooms[r].items() if now - t < TTL}
        if not rooms[r]:
            del rooms[r]


class Handler(BaseHTTPRequestHandler):
    def reply(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/join":
            return self.reply(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            if n > 1024:
                return self.reply(413, {"error": "too large"})
            body = json.loads(self.rfile.read(n))
            room = str(body["room"])[:64]
            addr = str(body["addr"])[:64]
            ip, port = addr.rsplit(":", 1)
            int(port)
        except Exception:
            return self.reply(400, {"error": "bad request"})

        clean()
        if room not in rooms and len(rooms) >= MAX_ROOMS:
            return self.reply(503, {"error": "busy"})

        members = rooms.setdefault(room, {})
        members[addr] = time.time()
        others = [a for a in members if a != addr]
        peer = max(others, key=members.get) if others else None
        self.reply(200, {"peer": peer})

    def log_message(self, fmt, *args):
        pass  # keep addresses out of the console


print(f"[signal] listening on 127.0.0.1:{PORT}")
ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()