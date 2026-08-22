# Zero-Setup LAN Discovery — Design Document

> **Status:** Proposed (not yet implemented)
>
> Goal: the app should work on the same network with **no setup required from
> the user** — no typing IPs, no configuration. The client automatically finds
> any running Clipboard Sync server on the local network and connects.

---

## 1. Problem

Today the client requires a manually entered server IP
(`clipboard_sync/ui/panels.py`, client panel). This works but means every user
must know the server machine's IP address and type it in.

## 2. Solution overview

A lightweight UDP beacon protocol alongside the existing TCP clipboard channel:

- The **server** periodically *broadcasts* a discovery beacon over UDP.
- The **client** *listens* for beacons; the first valid one it sees is
  auto-filled into the UI and auto-connected via the existing connect path.

No infrastructure, no mDNS library dependency, no firewall port-forwarding —
just one extra UDP socket per instance.

```
Server (192.168.1.10)                     Client
       |                                     |
       |--UDP broadcast :5557 every 3s------>|  "CLIPSYNC_V1|DESKTOP-AB12|5556|<uuid>"
       |                                     |
       |<============ TCP :5556 =============|  existing clipboard protocol (unchanged)
```

---

## 3. Protocol specification

### Beacon packet

Sent as UTF-8 datagram to `255.255.255.255:5557` (`SO_BROADCAST`):

```
CLIPSYNC_V1|<hostname>|<tcp_port>|<instance_uuid>
```

| Field           | Purpose                                                        |
|-----------------|----------------------------------------------------------------|
| `CLIPSYNC_V1`   | Magic prefix — listener discards unrelated UDP noise instantly |
| `<hostname>`    | Display name of the server machine (`socket.gethostname()`)    |
| `<tcp_port>`    | TCP port of the clipboard service (currently `5556`)           |
| `<instance_uuid>`| Stable per-machine ID — used to dedupe and ignore own beacons |

### Constants (to be added to `clipboard_sync/core/config.py`)

```python
DISCOVERY_PORT   = 5557
BEACON_INTERVAL  = 3      # seconds between broadcasts
BEACON_MAGIC     = "CLIPSYNC_V1"
INSTANCE_FILE    = os.path.join(MODE_DIR, "instance.json")
```

---

## 4. New module: `clipboard_sync/network/discovery.py`

Two independent daemon-thread classes; no tkinter imports (same rule as
`client.py` / `server.py`).

### `DiscoveryBroadcaster`

Used by the server.

- Creates a UDP socket with `SO_BROADCAST`.
- Loop: send beacon → sleep `BEACON_INTERVAL` → repeat.
- `start()` / `stop()` lifecycle mirroring `ServerHost`; stopped together with
  the accept loop.

### `DiscoveryListener`

Used by the client.

- Binds `0.0.0.0:5557`.
- On each datagram:
  1. Reject if it doesn't start with the magic prefix.
  2. Parse fields; reject malformed packets.
  3. Ignore beacons whose `instance_uuid` matches this machine's own ID
     (prevents self-discovery).
  4. Dedupe by `(uuid, ip)` so repeat beacons don't retrigger callbacks.
  5. Fire `on_server_found(hostname, ip, tcp_port)` exactly once per server.
- `start()` / `stop()` lifecycle; the stop event interrupts the receive wait
  (short socket timeout pattern, same as the TCP loops).

### Instance UUID

Generated once per machine and persisted to
`~/.clipboard-sync/instance.json`. Prevents an instance from discovering
itself and makes dedupe stable across app restarts.

---

## 5. Integration changes

### 5.1 Server — `clipboard_sync/network/server.py`

- `start()`: also start a `DiscoveryBroadcaster` after the accept loop starts.
- `stop()`: stop the broadcaster.
- No change to the TCP clipboard protocol.

### 5.2 Client — `clipboard_sync/app.py`

Launch-time decision order in `_start_services()`:

1. `last_connected_ip` exists → connect immediately (current behavior;
   discovery stays off).
2. Else, if `auto_discover` enabled → start the listener:
   - status/log shows *"Searching for servers on LAN…"*
   - on first discovery → prefill IP field → `_start_client()`
   - if nothing found after ~15 s → log a warning hinting that Windows
     Firewall may be blocking (see §7)
3. Else → current *"No saved server IP"* warning.

Manual entry always wins: typing an IP and clicking Connect works exactly as
today, regardless of discovery state.

### 5.3 Settings — `settings.py`

New client-only row next to the reconnect delay:

> ☑ Auto-discover servers on LAN

Config key `auto_discover`, default `true`
(`clipboard_sync/core/config.py`, client defaults).

### 5.4 Config default

```python
"auto_discover": True,
```

Existing config files get the key filled in automatically by `load_config`.

---

## 6. Behavior matrix

| Situation                                   | Result                                        |
|---------------------------------------------|-----------------------------------------------|
| Client launches, server running on same LAN | Auto-finds & connects within ~3 s             |
| Saved / last-connected IP exists            | Connects to it immediately (discovery skipped)|
| User types an IP manually                   | Works as today                                |
| Multiple servers on the LAN                 | First discovered wins; others logged          |
| No server found                             | Keeps searching silently, retries forever     |
| Server closes                               | Existing auto-reconnect loop takes over       |
| Different subnet / VLAN / guest network     | Discovery does not work (broadcast limitation)|

---

## 7. Caveats & notes

- **Windows Firewall:** the first launch of the exe triggers the Windows
  allow/deny prompt for network access. Both sides must click **Allow**
  (the server needs inbound UDP 5557 + TCP 5556). If denied, discovery fails
  silently — hence the ~15 s "nothing found" warning in the log.
- **Subnets:** directed broadcasts don't cross routers. Apartments/small
  offices with a single router are fine; VLANs and guest Wi-Fi isolation are
  not.
- **Security:** beacons reveal hostname + IP to anyone on the LAN. This is
  equivalent to what mDNS/SSDP expose on every home network; the clipboard
  data itself remains on the existing unencrypted TCP channel (unchanged risk).
- **Port conflict:** another app using UDP 5557 would break discovery only —
  the clipboard channel keeps working. A bind failure is logged as a warning.
- **Future option (out of scope):** if a stale saved IP stops responding, the
  reconnect loop could fall back to discovery instead of retrying forever.
