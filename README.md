# UDP Hole-Punch Chat (with HTTP signaling)

A tiny peer-to-peer terminal chat written in pure Python (standard library only). Two peers find each other's public address through a small HTTP signaling server, punch a hole through their NATs with UDP, and then chat **directly**, with no server relaying messages.

```
 Peer A ──┐                         ┌── Peer B
          │  1. POST /join          │
          ├────────────►  Signaling server  ◄────────────┤
          │  2. "your peer is X"    │
          │                                               │
          └──────────── 3. direct UDP chat ───────────────┘
```

- `signal_server.py`: HTTP signaling server (rendezvous only; never sees chat traffic)
- `chat_bore.py`: the chat client (STUN lookup, signaling, UDP punch, chat)

---

## Table of contents

1. [How it works](#how-it-works)
2. [Requirements](#requirements)
3. [Quick start](#quick-start)
4. [Setup: Android phone (Termux)](#setup-android-phone-termux)
5. [Setup: Laptop / desktop](#setup-laptop--desktop)
6. [Ways to expose the signaling server](#ways-to-expose-the-signaling-server)
7. [Setup combinations (who runs what)](#setup-combinations-who-runs-what)
8. [Command reference](#command-reference)
9. [Testing the server by hand](#testing-the-server-by-hand)
10. [Chat commands](#chat-commands)
11. [Troubleshooting](#troubleshooting)
12. [NAT compatibility and limitations](#nat-compatibility-and-limitations)
13. [Security notes](#security-notes)

---

## How it works

1. **STUN.** Each peer binds a UDP socket and asks `stun.l.google.com:19302` what public `ip:port` its NAT assigned to that socket.
2. **Signaling.** Each peer POSTs `{"room": "...", "addr": "ip:port"}` to the signaling server's `/join`. The server remembers who is in each room and replies with the other peer's address (or `null` if nobody else is there yet). Peers poll once per second until they get an answer.
3. **Hole punching.** Both peers now send `PUNCH` UDP packets to each other's public address from the *same socket* they used for STUN. Each outgoing packet creates a NAT mapping that lets the other side's packets in. When a `PUNCH`/`ACK` arrives, the connection is established.
4. **Chat.** Messages are sent as `MSG name: text` over UDP. A keepalive every 10 seconds holds the NAT mapping open.

The signaling server only exchanges addresses. Chat traffic is direct peer to peer.

Server behaviour: rooms expire peers after **60 seconds** of silence, up to **1000 rooms**, request bodies are capped at **1 KB**, and the server only handles `POST /join` (a plain `GET` returns `501`, which is normal).

---

## Requirements

| Component | Needed on | Requirement |
|---|---|---|
| Python | every machine | Python **3.8+** (tested on 3.12). **No pip packages**; stdlib only. |
| Internet | every peer | Outbound UDP to `stun.l.google.com:19302` and outbound HTTP(S) to the signaling server. |
| Signaling server | exactly one machine | Python plus a way to be reachable by both peers (tunnel, public IP, or same network). |
| Tunnel tool | server machine, if it is behind NAT | One of: `bore`, `cloudflared`, `ssh` (localhost.run), `ngrok`. See [exposing the server](#ways-to-expose-the-signaling-server). |
| Compatible NATs | both peers | At least one peer, ideally both, on a *cone-type* NAT. See [NAT compatibility](#nat-compatibility-and-limitations). |

Files to put on each machine:

- Server machine: `signal_server.py`
- Every peer machine: `chat_bore.py`
- A machine that is both server and peer needs both files.

---

## Quick start

On the machine that will host the signaling server (terminal 1):

```bash
python signal_server.py            # listens on 127.0.0.1:8080
```

Terminal 2 on the same machine, expose it (example using bore):

```bash
bore local 8080 --to bore.pub      # prints: listening at bore.pub:PORT
```

On **each** peer (the server machine can be one of them), using the same room name:

```bash
python chat_bore.py bore.pub:PORT my-long-random-room alice
python chat_bore.py bore.pub:PORT my-long-random-room bob
```

You should see `found peer`, then `punching...`, then `connected!`. Type a message and press Enter.

> The bore `PORT` changes every time you restart bore. Always use the one it just printed.

---

## Setup: Android phone (Termux)

### 1. Install Termux

Install Termux from **F-Droid** (https://f-droid.org/packages/com.termux/). The Play Store version is outdated and its package repos are broken.

### 2. Update packages and install Python

```bash
pkg update && pkg upgrade -y
pkg install -y python git curl
python3 --version
```

### 3. Get the files

Either clone your repo:

```bash
git clone https://github.com/<you>/<repo>.git
cd <repo>
```

or copy `signal_server.py` and `chat_bore.py` into `~/downloads` (or anywhere) by hand.

### 4. Keep Termux alive

Android kills background apps aggressively. Run this in each session so the process is not suspended:

```bash
termux-wake-lock
```

Also disable battery optimization for Termux (Settings → Apps → Termux → Battery → Unrestricted). Keep the Termux notification visible.

### 5a. Phone as a **peer only**

```bash
python chat_bore.py <signal_host:port> <room> <your-name>
# e.g.
python chat_bore.py bore.pub:41234 my-long-random-room phoneB
```

### 5b. Phone as the **signaling server** (plus tunnel)

You need three things running at once, so use three Termux sessions (swipe in from the left edge, then **New session**) or use `tmux`:

```bash
pkg install -y tmux
tmux new -s sig
```

Session 1, the server:

```bash
python signal_server.py
```

Session 2, the tunnel. Install bore first (see below), then:

```bash
bore local 8080 --to bore.pub
```

Session 3, the phone's own peer (optional):

```bash
python chat_bore.py bore.pub:<PORT> my-long-random-room phoneA
```

#### Installing bore on Termux

Option A, build with Rust (slow, but simple):

```bash
pkg install -y rust
cargo install bore-cli
export PATH="$HOME/.cargo/bin:$PATH"
```

Option B, prebuilt binary (fast). Download the `aarch64-unknown-linux-musl` tarball from https://github.com/ekzhang/bore/releases, then:

```bash
tar xzf bore-*-aarch64-unknown-linux-musl.tar.gz
mv bore $PREFIX/bin/
chmod +x $PREFIX/bin/bore
bore --version
```

If bore is unavailable or flaky, use `cloudflared` or `ssh` instead; see [below](#ways-to-expose-the-signaling-server).

### Phone-specific tips

- Mobile data (Jio, Airtel, Vi and others) often uses carrier-grade NAT and is frequently **symmetric**, which breaks hole punching. If it fails, try Wi-Fi.
- Two phones on the **same Wi-Fi** may fail too, because the script punches to each other's *public* IP and many routers don't support hairpinning (NAT loopback). A good test is one phone on Wi-Fi and the other on mobile data.
- Run `termux-wake-lock` in every session that must stay alive.

---

## Setup: Laptop / desktop

### Linux

```bash
sudo apt update && sudo apt install -y python3 git curl     # Debian/Ubuntu
# sudo dnf install -y python3 git curl                       # Fedora
# sudo pacman -S python git curl                             # Arch
python3 --version
```

### macOS

```bash
brew install python git          # or use the python.org installer
python3 --version
```

### Windows

Install Python from https://www.python.org/downloads/ (tick **Add python.exe to PATH**) or:

```powershell
winget install Python.Python.3.12
python --version
```

On Windows use `python` and `py` instead of `python3`.

### Laptop as a **peer only**

```bash
python3 chat_bore.py <signal_host:port> <room> <your-name>
# e.g.
python3 chat_bore.py bore.pub:41234 my-long-random-room laptop
```

If Windows Defender Firewall asks about Python, allow it on the network type you're using. Outbound UDP is normally fine, but a strict firewall can block the inbound punch.

### Laptop as the **signaling server**

Terminal 1:

```bash
python3 signal_server.py 8080
```

Terminal 2, tunnel (pick one of the [options below](#ways-to-expose-the-signaling-server)). With bore:

```bash
# Linux / macOS
brew install bore-cli          # macOS (Homebrew)
cargo install bore-cli         # any OS with Rust installed
# or download a binary from https://github.com/ekzhang/bore/releases

bore local 8080 --to bore.pub
```

Terminal 3 (optional), the laptop's own peer:

```bash
python3 chat_bore.py bore.pub:<PORT> my-long-random-room laptop
```

---

## Ways to expose the signaling server

The server binds to `127.0.0.1` by default, so it is only reachable from its own machine. Both peers must be able to reach it, so you need one of these.

### Option 1: bore (default in this project)

Free public relay, no account.

```bash
bore local 8080 --to bore.pub
# → listening at bore.pub:PORT
```

Peers use `bore.pub:PORT`. Works with the client as written.

### Option 2: cloudflared quick tunnel (HTTPS, no account)

```bash
# Termux:  pkg install cloudflared
# macOS:   brew install cloudflared
# Linux/Windows: https://github.com/cloudflare/cloudflared/releases
cloudflared tunnel --url http://localhost:8080
# → https://something-random.trycloudflare.com
```

The client currently prepends `http://` to its first argument. To accept full URLs, change this line in `chat_bore.py`:

```python
# before
signal_url = "http://" + sys.argv[1]

# after
signal_url = sys.argv[1] if sys.argv[1].startswith(("http://", "https://")) else "http://" + sys.argv[1]
```

Then run:

```bash
python chat_bore.py https://something-random.trycloudflare.com my-room alice
```

### Option 3: localhost.run (SSH, no install)

```bash
ssh -R 80:localhost:8080 nokey@localhost.run
# → prints an https://....lhr.life URL
```

Use the client patch from Option 2.

### Option 4: ngrok (account required)

```bash
ngrok http 8080
# → https://xxxx.ngrok-free.app
```

Use the client patch from Option 2.

### Option 5: same LAN / Wi-Fi (no tunnel)

Bind the server to all interfaces. Edit the last lines of `signal_server.py`, changing `127.0.0.1` to `0.0.0.0` in both the print and `ThreadingHTTPServer`, then find the server's LAN IP:

```bash
ip addr | grep inet          # Linux / Termux (or: ifconfig)
```

Peers use `<LAN-IP>:8080`:

```bash
python chat_bore.py 192.168.1.20:8080 my-room alice
```

Note that this only helps with signaling. Two peers on the same LAN still punch via their public address, so hairpin NAT support is needed.

### Option 6: VPS or any host with a public IP

Run the server on the VPS bound to `0.0.0.0`, open the port, and use it directly:

```bash
python3 signal_server.py 8080                     # after editing bind to 0.0.0.0
sudo ufw allow 8080/tcp                           # if using ufw
python chat_bore.py <vps-ip>:8080 my-room alice
```

Keep it running with `tmux`, `screen`, or a `systemd` unit. This is the most reliable option, because the server doesn't depend on a free relay.

### Option 7: router port-forward

Forward TCP 8080 on your router to the server machine (bind `0.0.0.0`), and give peers your public IP (or a DDNS name) with port 8080.

---

## Setup combinations (who runs what)

The signaling server and the peers are independent. Mix and match:

| # | Server runs on | Tunnel | Peer 1 | Peer 2 | Notes |
|---|---|---|---|---|---|
| 1 | Phone A (Termux) | bore on Phone A | Phone A | Phone B (Termux) | Everything on phones. Use `termux-wake-lock`. |
| 2 | Phone A (Termux) | bore on Phone A | Phone B | Laptop | Server phone need not run a peer. |
| 3 | Laptop | bore on laptop | Laptop | Phone (Termux) | Most stable server host. |
| 4 | Laptop | bore on laptop | Laptop 1 | Laptop 2 | Two laptops, different networks. |
| 5 | Laptop | none (LAN) | Laptop | Phone on same Wi-Fi | Bind `0.0.0.0`; punch needs hairpin NAT. |
| 6 | VPS | none (public IP) | Any | Any | Best reliability; no tunnel needed. |
| 7 | Any | cloudflared / ngrok / localhost.run | Any | Any | Needs the HTTPS client patch. |

What each role needs, in short:

- **Server role:** `signal_server.py` plus Python, and reachability (a tunnel, public IP or LAN).
- **Peer role:** `chat_bore.py` plus Python, outbound UDP to STUN, and outbound HTTP(S) to the server.
- **Both roles on one device:** run them in separate terminals or sessions.

---

## Command reference

### `signal_server.py`

```bash
python signal_server.py [port]       # default port 8080
```

| Setting | Where | Default |
|---|---|---|
| Port | first CLI argument | `8080` |
| Bind address | last line of the file | `127.0.0.1` |
| Peer expiry (`TTL`) | top of file | `60` seconds |
| Max rooms (`MAX_ROOMS`) | top of file | `1000` |

### `chat_bore.py`

```bash
python chat_bore.py <signal_host:port> <room> [name] [local_port]
```

| Argument | Required | Meaning |
|---|---|---|
| `signal_host:port` | yes | Address of the signaling server, e.g. `bore.pub:41234`. |
| `room` | yes | Shared room name. Both peers must use exactly the same one. |
| `name` | no | Display name shown on your messages (default `peer`). |
| `local_port` | no | Fixed local UDP port (default `0` = random). Useful if you port-forward UDP on a router. |

### bore

```bash
bore local 8080 --to bore.pub        # expose local port 8080
```

---

## Testing the server by hand

The server only accepts `POST /join`. Open a second terminal:

```bash
# Two peers joining the same room back-to-back
curl -s -X POST http://127.0.0.1:8080/join -d '{"room":"t","addr":"1.2.3.4:1111"}'; echo
curl -s -X POST http://127.0.0.1:8080/join -d '{"room":"t","addr":"5.6.7.8:2222"}'; echo
```

Expected output on a clean room:

```
{"peer": null}
{"peer": "1.2.3.4:1111"}
```

Test through the tunnel from the *other* phone or laptop to confirm it is reachable:

```bash
curl -s -X POST http://bore.pub:PORT/join -d '{"room":"x","addr":"1.2.3.4:1"}'
# → {"peer": null}
```

Notes:

- `curl http://127.0.0.1:8080` (a `GET`) returning **501** is normal, since only `POST /join` is implemented.
- Entries expire after 60 seconds. If you wait between test calls, you may get `{"peer": null}` again.
- Leftover test entries can show up as peers, so use a fresh room name for each test.

---

## Chat commands

Once you see `connected!`:

- Type a message and press **Enter** to send it.
- `/quit` exits.
- `Ctrl+C` or `Ctrl+D` also exits.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `signaling error: Connection refused` | Nothing listening at that host:port. The tunnel is down, or the bore port is stale or mistyped. | Restart `bore local 8080 --to bore.pub`, use the **new** port. Check the server is still running. Test with the `curl` POST above. |
| `signaling error: timed out` | Server unreachable or the relay is slow or blocked. | Check the network, retry, or switch tunnel option. |
| `signaling error: HTTP Error 400` | Malformed request. | Make sure the files are unmodified and the room and address are valid. |
| `HTTP Error 503: busy` | Server has 1000 active rooms. | Wait or raise `MAX_ROOMS`. |
| Stuck on `waiting for the other peer...` | The other peer hasn't started or uses a different room name. | Start the other peer with the exact same room, host and port. |
| `found peer` then `gave up after 60s` | NAT hole punch failed (symmetric NAT or hairpin issue). | See [NAT compatibility](#nat-compatibility-and-limitations). Try different networks. |
| `peer port changed ... switching` | The peer's NAT remapped its port (normal on some NATs). | Nothing needed; the client follows it. |
| `ignored packet from unexpected source` | Packet from an IP other than your peer. | Usually harmless noise. |
| `your public address` not shown / STUN timeout | Outbound UDP blocked, or no DNS for `stun.l.google.com`. | Check the connection; try another network; some networks block UDP 19302. |
| `SyntaxError` near the end of `chat_bore.py` | File got truncated or mangled when copying. | The line must read `except (KeyboardInterrupt, EOFError):`. |
| Termux session dies in the background | Android battery management. | Run `termux-wake-lock`, set Termux battery to Unrestricted, keep the notification. |
| `bore: command not found` | Not installed or not on `PATH`. | Install it (see above) and `export PATH="$HOME/.cargo/bin:$PATH"` if built with cargo. |
| `Address already in use` on the server | Port 8080 is taken. | Use another port: `python signal_server.py 8081`, then `bore local 8081 ...`. |

---

## NAT compatibility and limitations

UDP hole punching works when the NATs reuse the same public port for a socket regardless of destination (cone-type NATs). It fails when a NAT assigns a different port per destination (**symmetric NAT**).

| Peer A \ Peer B | Full / restricted cone | Port-restricted cone | Symmetric |
|---|---|---|---|
| **Full / restricted cone** | works | works | usually works |
| **Port-restricted cone** | works | works | fails |
| **Symmetric** | usually works | fails | fails |

Practical guidance:

- Home Wi-Fi routers are usually cone-type, so punching typically works.
- Mobile carrier networks often use CGNAT, and many are symmetric. Try Wi-Fi if mobile data fails.
- **Same-NAT peers** (two phones on the same Wi-Fi, or both behind the same carrier) need the NAT to support hairpinning. Many don't, so test with peers on different networks.
- There is **no relay fallback**. If punching fails, the chat cannot connect. A TURN server or a TCP relay would be needed.
- The client is IPv4 only.
- There is no message acknowledgement, retransmission, or ordering. It is plain UDP.
- Only two peers per room are matched at a time (the server hands out the most recently seen other peer).

### Address and port changes (bore port, phone IP, restarts)

The address exchange happens **once, at startup**. Nothing re-discovers addresses afterwards, so anything that changes an address mid-session needs a manual restart.

| What changes | What happens | What to do |
|---|---|---|
| **bore port changes** (you restart `bore`, or bore.pub drops the tunnel and you reconnect) | The old `bore.pub:PORT` stops working and the new port is random. Peers that are **already connected keep chatting**, because the chat is direct UDP and no longer uses the server. **New** peers, or peers restarting, get `Connection refused` until you give them the new port. | Restart bore, copy the new port, and restart the clients with it: `python chat_bore.py bore.pub:NEWPORT room name`. Bore ports can't be reserved on bore.pub. For a stable address use a VPS or a named Cloudflare tunnel. |
| **Signaling server restarts or its phone/laptop sleeps** | All rooms are lost (they live in memory only). Existing chats are unaffected. | Restart the server, then the tunnel (new port), then the peers. |
| **A phone's public IP changes** (Wi-Fi ↔ mobile data, airplane mode, router reconnect, carrier re-assigns CGNAT address) | The NAT mapping is gone. Your public `ip:port` was read from STUN **only at startup**, so the client doesn't notice. The other peer sees packets from an unfamiliar IP and **ignores them** (`ignored packet from unexpected source`). The chat goes silent and does **not** recover by itself. | Press `Ctrl+C` / `/quit` on **both** peers and start them again, ideally with a fresh room name. |
| **Only the public port changes** (same IP, new port, e.g. NAT rebinding after idle) | The receiving side prints `peer port changed ... switching` and follows the new port. | Nothing, as long as the **IP stays the same**. If both sides' ports changed at once, it may not recover; restart. |
| **One peer restarts** | It gets a new socket and a new public port. It asks the server for a peer, but the other side stopped polling after connecting, so its entry expires after 60 seconds. The restarted peer may get a stale address or `null`, and the old peer doesn't know the new address. | Restart **both** peers together with the same room name (or a new one). |
| **Phone sleeps or Termux is killed** | Keepalives stop (every 10 s). The NAT drops the mapping, often within 30-120 s on mobile networks. Messages stop arriving. | Use `termux-wake-loc# udp-punch-chat
Peer-to-peer terminal chat over UDP hole punching, with a tiny HTTP signaling server. Pure Python, works on Termux.
