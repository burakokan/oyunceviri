import asyncio
import json
import socket
import threading
import time

from websockets.asyncio.server import broadcast, serve

BEACON_PORT = 8766


class SubtitleServer:
    """WebSocket server the TV app connects to. Runs its own event loop on a thread.

    A UDP beacon every second lets the TV app find this PC without an IP. It goes out on every network
    adapter (a VPN adapter would otherwise take the plain broadcast away from the home network) and
    straight to the TV's address once it is known (beacon_to).
    TV -> PC messages: "hello" (version + current style), "style" (changed on the TV),
    "ack" (a line is on screen; used to measure the PC -> TV delay).
    """

    def __init__(self, port, on_clients=None, on_ack=None, on_style=None):
        self.port = port
        self.on_clients = on_clients or (lambda clients: None)
        self.on_ack = on_ack or (lambda line_id, rtt_ms: None)
        self.on_style = on_style or (lambda style: None)
        self.beacon_to = set()      # TV addresses the beacon is also sent to directly
        self.clients = {}  # connection -> {"ip", "version", "style"}
        self.error = None
        self._sent_at = {}
        self._last_line = None
        self._last_boxes = {}       # "screen" / "regions" -> the last message: a TV that (re)connects gets it too
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        threading.Thread(target=self._loop.run_until_complete, args=(self._main(),), daemon=True).start()
        threading.Thread(target=self._beacon, daemon=True).start()
        self._ready.wait(3)

    @property
    def tv_ips(self):
        return sorted({info["ip"] for info in list(self.clients.values())})

    def _beacon(self):
        payload = f"GAMETRANSLATE {self.port}".encode()
        socks, refreshed = [], 0.0
        direct = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)    # unbound: the route to the TV decides
        while True:
            if time.monotonic() - refreshed > 30:       # adapters come and go (VPN on/off)
                for s, _ in socks:
                    s.close()
                socks, refreshed = self._beacon_sockets(), time.monotonic()
            for sock, targets in socks:
                for target in targets:
                    try:
                        sock.sendto(payload, (target, BEACON_PORT))
                    except OSError:
                        pass
            for ip in list(self.beacon_to):
                try:
                    direct.sendto(payload, (ip, BEACON_PORT))
                except OSError:
                    pass
            time.sleep(1)

    @staticmethod
    def _beacon_sockets():
        """One broadcast socket per IPv4 address of this PC: (socket, [limited + subnet broadcast])."""
        out = []
        try:
            import psutil
            addrs = [(a.address, a.netmask) for nics in psutil.net_if_addrs().values() for a in nics
                     if a.family == socket.AF_INET and not a.address.startswith(("127.", "169.254."))]
        except Exception:  # noqa: BLE001
            addrs = []
        for ip, mask in addrs:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.bind((ip, 0))
            except OSError:
                continue
            targets = ["255.255.255.255"]
            try:
                ipn = int.from_bytes(socket.inet_aton(ip), "big")
                maskn = int.from_bytes(socket.inet_aton(mask or "255.255.255.0"), "big")
                targets.append(socket.inet_ntoa(((ipn & maskn) | (~maskn & 0xFFFFFFFF)).to_bytes(4, "big")))
            except OSError:
                pass
            out.append((sock, targets))
        if not out:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            out.append((sock, ["255.255.255.255"]))
        return out

    async def _main(self):
        try:
            async with serve(self._handler, "0.0.0.0", self.port, compression=None, ping_interval=5) as server:
                self._ready.set()
                await server.serve_forever()
        except OSError as e:
            self.error = f"Port {self.port} kullanılamıyor: {e}"
            self._ready.set()

    async def _handler(self, ws):
        self.clients[ws] = {"ip": ws.remote_address[0], "version": "?", "style": None}
        self._notify_clients()
        try:
            if self._last_line:
                await ws.send(self._last_line)
            for data in list(self._last_boxes.values()):
                await ws.send(data)
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                kind = msg.get("type")
                if kind == "ack":
                    sent = self._sent_at.pop(msg.get("id"), None)
                    if sent is not None:
                        self.on_ack(msg.get("id"), (time.perf_counter() - sent) * 1000)
                elif kind == "hello":
                    self.clients[ws].update(version=msg.get("version", "?"), style=msg.get("style"))
                    self._notify_clients()
                    if msg.get("style"):
                        self.on_style(msg["style"])
                elif kind == "style" and msg.get("style"):
                    self.clients[ws]["style"] = msg["style"]
                    self.on_style(msg["style"])
        finally:
            self.clients.pop(ws, None)
            self._notify_clients()

    def snapshot(self):
        """The connected TV apps right now: [{"ip", "version", "style"}]."""
        return [dict(info) for info in list(self.clients.values())]

    def _notify_clients(self):
        self.on_clients(self.snapshot())

    def send(self, message):
        data = json.dumps(message, ensure_ascii=False)
        if message.get("type") == "line":
            if len(self._sent_at) > 50:
                self._sent_at.clear()
            self._sent_at[message["id"]] = time.perf_counter()
            self._last_line = data
        elif message.get("type") == "clear":
            self._last_line = None
        elif message.get("type") in ("screen", "regions"):
            self._last_boxes[message["type"]] = data
        self._loop.call_soon_threadsafe(broadcast, list(self.clients), data)
