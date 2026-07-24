"""APRS-IS TCP client: login, send messages, receive messages & ACKs."""

from __future__ import annotations

import logging
import queue
import re
import socket
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from .callsign import aprs_addressee, normalize_callsign

log = logging.getLogger(__name__)

DEFAULT_SERVER = "rotate.aprs2.net"
DEFAULT_PORT = 14580

# Incoming APRS message: :ADDRESSEE:text{id   or  :ADDRESSEE:ack123
_MSG_RE = re.compile(
    r"^:([\w\-]{1,9})\s*:(.*)$"
)


@dataclass
class IncomingMessage:
    from_call: str
    to_call: str
    body: str
    msg_id: str
    is_ack: bool
    is_rej: bool
    raw: str


class AprsIsClient:
    """Background APRS-IS connection."""

    def __init__(
        self,
        callsign: str,
        passcode: str,
        server: str = DEFAULT_SERVER,
        port: int = DEFAULT_PORT,
        app_name: str = "APRSMessenger",
        app_version: str = "1.0",
        on_message: Optional[Callable[[IncomingMessage], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
    ):
        self.callsign = normalize_callsign(callsign)
        self.passcode = str(passcode).strip()
        self.server = server
        self.port = port
        self.app_name = app_name
        self.app_version = app_version
        self.on_message = on_message
        self.on_status = on_status

        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._send_q: queue.Queue[str] = queue.Queue()
        self._msg_seq = int(time.time()) % 90 + 10  # 10–99 two-digit ids
        self._connected = False
        self._lock = threading.Lock()

    @property
    def connected(self) -> bool:
        return self._connected

    def _status(self, text: str) -> None:
        log.info(text)
        if self.on_status:
            try:
                self.on_status(text)
            except Exception:
                log.exception("status callback failed")

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="aprs-is", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            if self._sock:
                self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            if self._sock:
                self._sock.close()
        except OSError:
            pass
        self._sock = None
        self._connected = False
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None

    def next_msg_id(self) -> str:
        with self._lock:
            self._msg_seq = (self._msg_seq % 99) + 1
            # APRS message IDs: up to 5 alphanumeric; we use 2-digit for compact ACKs
            return f"{self._msg_seq:02d}"

    def send_message(self, to_call: str, text: str, msg_id: Optional[str] = None) -> str:
        """
        Queue an APRS text message. Returns message id used for ACK tracking.
        Format: CALL>APRS,TCPIP*::ADDRESSEE:message{id

        Raises ConnectionError if not currently connected to APRS-IS so callers
        do not record a false "sent" state while offline.
        """
        if not self._connected:
            raise ConnectionError("Not connected to APRS-IS")
        to_call = normalize_callsign(to_call)
        text = (text or "").replace("\r", " ").replace("\n", " ").strip()
        if len(text) > 67:
            text = text[:67]
        mid = msg_id or self.next_msg_id()
        addressee = aprs_addressee(to_call)
        # Third-party / direct station format for APRS-IS clients
        line = f"{self.callsign}>APRS,TCPIP*::{addressee}:{text}{{{mid}"
        self._send_q.put(line)
        return mid

    def send_position(
        self,
        lat: float,
        lon: float,
        comment: str = "",
        symbol_table: str = "/",
        symbol_code: str = "[",
    ) -> str:
        """
        Queue an APRS position beacon (uncompressed) for APRS-IS / aprs.fi.

        Format: CALL>APRS,TCPIP*:=DDMM.mmN/DDDMM.mmE[comment
        '=' = messaging-capable position report without timestamp.
        Default symbol '[' = human / runner (portable operator).
        Returns the TNC2 line queued.
        """
        from .weather import latlon_to_aprs

        pos = latlon_to_aprs(lat, lon)
        # Insert symbol table/code into latlon string: DDMM.mmN/DDDMM.mmE  →  DDMM.mmN c DDDMM.mmE s
        # latlon_to_aprs returns DDMM.mmN/DDDMM.mmE — replace middle '/' with symbol_table
        # and append symbol_code after lon.
        if "/" in pos:
            lat_part, lon_part = pos.split("/", 1)
            body = f"={lat_part}{symbol_table}{lon_part}{symbol_code}"
        else:
            body = f"={pos}{symbol_code}"
        comment = (comment or "").replace("\r", " ").replace("\n", " ").strip()
        # APRS comment after symbol is typically limited (~43 chars practical)
        if len(comment) > 43:
            comment = comment[:43]
        line = f"{self.callsign}>APRS,TCPIP*:{body}{comment}"
        self._send_q.put(line)
        log.info("TX position: %s", line)
        return line

    def send_ack(self, to_call: str, msg_id: str) -> None:
        """Acknowledge receipt of a message (WhatsApp-style delivery for the sender)."""
        to_call = normalize_callsign(to_call)
        addressee = aprs_addressee(to_call)
        line = f"{self.callsign}>APRS,TCPIP*::{addressee}:ack{msg_id}"
        self._send_q.put(line)

    def send_rej(self, to_call: str, msg_id: str) -> None:
        to_call = normalize_callsign(to_call)
        addressee = aprs_addressee(to_call)
        line = f"{self.callsign}>APRS,TCPIP*::{addressee}:rej{msg_id}"
        self._send_q.put(line)

    def _run(self) -> None:
        backoff = 2
        while not self._stop.is_set():
            try:
                self._connect_and_loop()
                backoff = 2
            except Exception as e:
                self._connected = False
                self._status(f"Disconnected: {e}. Reconnecting…")
                self._close_sock()
                # wait with stop awareness
                for _ in range(int(backoff * 10)):
                    if self._stop.is_set():
                        return
                    time.sleep(0.1)
                backoff = min(backoff * 2, 60)

    def _close_sock(self) -> None:
        try:
            if self._sock:
                self._sock.close()
        except OSError:
            pass
        self._sock = None

    def _connect_and_loop(self) -> None:
        self._status(f"Connecting to {self.server}:{self.port}…")
        sock = socket.create_connection((self.server, self.port), timeout=30)
        sock.settimeout(1.0)
        self._sock = sock

        # Read server banner
        try:
            banner = sock.recv(512).decode("utf-8", errors="replace")
            log.debug("banner: %s", banner.strip())
        except socket.timeout:
            pass

        # Login — filter for messages to us
        # g/MYCALL receives messages addressed to us; m/ asks for messages
        filt = f"g/{self.callsign} b/{self.callsign}"
        login = (
            f"user {self.callsign} pass {self.passcode} "
            f"vers {self.app_name} {self.app_version} filter {filt}\r\n"
        )
        sock.sendall(login.encode("utf-8"))

        # Expect # logresp
        deadline = time.time() + 15
        buf = ""
        logged_in = False
        while time.time() < deadline and not self._stop.is_set():
            try:
                chunk = sock.recv(4096).decode("utf-8", errors="replace")
                if not chunk:
                    raise ConnectionError("Server closed connection during login")
                buf += chunk
                for line in buf.split("\n"):
                    line = line.strip()
                    if line.startswith("# logresp"):
                        if "unverified" in line.lower():
                            raise ConnectionError(
                                "Login unverified — check callsign and aprs.fi passcode"
                            )
                        if "verified" in line.lower() or "OK" in line:
                            logged_in = True
                        else:
                            # some servers: # logresp CALL verified, server XXX
                            logged_in = "logresp" in line
                if logged_in:
                    break
                # keep only last partial line
                if "\n" in buf:
                    buf = buf.split("\n")[-1]
            except socket.timeout:
                continue

        if not logged_in:
            # proceed carefully — some servers are quiet; check for verified in buffer
            if "unverified" in buf.lower():
                raise ConnectionError("Login unverified — check callsign and passcode")
            if "logresp" not in buf.lower():
                # still try — many servers accept and only stream data
                log.warning("No explicit logresp; continuing: %r", buf[:200])
            else:
                logged_in = True

        self._connected = True
        self._status(f"Connected as {self.callsign} (APRS-IS)")

        rx_buf = buf if not logged_in or "#" in buf else ""
        # strip consumed lines already processed — start clean after login traffic
        if "\n" in rx_buf:
            parts = rx_buf.split("\n")
            for line in parts[:-1]:
                self._handle_line(line.strip())
            rx_buf = parts[-1]

        while not self._stop.is_set():
            # outbound
            try:
                while True:
                    line = self._send_q.get_nowait()
                    payload = (line.rstrip("\r\n") + "\r\n").encode("utf-8")
                    sock.sendall(payload)
                    log.info("TX: %s", line)
            except queue.Empty:
                pass

            try:
                data = sock.recv(4096)
                if not data:
                    raise ConnectionError("Connection closed by server")
                rx_buf += data.decode("utf-8", errors="replace")
                while "\n" in rx_buf:
                    line, rx_buf = rx_buf.split("\n", 1)
                    self._handle_line(line.strip("\r"))
            except socket.timeout:
                continue

    def _addressed_to_us(self, parsed: IncomingMessage) -> bool:
        """True if the APRS message addressee is our callsign (SSID-tolerant)."""
        our = normalize_callsign(self.callsign)
        to = normalize_callsign(parsed.to_call)
        if not our or not to:
            return False
        our_base = our.split("-", 1)[0]
        to_base = to.split("-", 1)[0]
        return to_base == our_base or to == our

    def _handle_line(self, line: str) -> None:
        if not line or line.startswith("#"):
            if line.startswith("#"):
                log.debug("server: %s", line)
            return
        parsed = parse_aprs_message_line(line)
        if not parsed:
            return
        # Messages, ACKs, and REJs must all be addressed to us (no passthrough for foreign ACKs)
        if not self._addressed_to_us(parsed):
            return

        if self.on_message:
            try:
                self.on_message(parsed)
            except Exception:
                log.exception("on_message failed")


def parse_aprs_message_line(line: str) -> Optional[IncomingMessage]:
    """
    Parse a TNC2 monitor-format APRS frame for message payloads.
    Example: FROM>TO,PATH::ADDRESSEE:hello{01
    """
    if ":" not in line or ">" not in line:
        return None
    try:
        header, rest = line.split(":", 1)
    except ValueError:
        return None
    # rest may start with another colon for messages ::ADDRESSEE:
    # header is FROM>TO,PATH
    from_call = header.split(">", 1)[0].strip().upper()

    # Message payload starts with :ADDRESSEE:
    # In TNC2, after first colon we get :ADDRESSEE:body  OR path already split
    # Full: FROM>TO,PATH::ADDRESSEE:body
    # After split on first ':', rest is :ADDRESSEE:body
    if not rest.startswith(":"):
        # could be weather etc.
        return None
    payload = rest[1:]  # ADDRESSEE:body
    if ":" not in payload:
        return None
    addressee, body = payload.split(":", 1)
    to_call = addressee.strip().upper()
    body = body.rstrip("\r")

    is_ack = False
    is_rej = False
    msg_id = ""
    text = body

    ack_m = re.match(r"^(ack)([A-Za-z0-9]{1,5})\s*$", body, re.I)
    rej_m = re.match(r"^(rej)([A-Za-z0-9]{1,5})\s*$", body, re.I)
    if ack_m:
        is_ack = True
        msg_id = ack_m.group(2)
        text = ""
    elif rej_m:
        is_rej = True
        msg_id = rej_m.group(2)
        text = ""
    else:
        # Optional trailing message id: ...{abc12  (1–5 alnum only, must be at end).
        # Do not treat '{' inside the text (e.g. "code {foo} bar") as a msg id.
        id_m = re.search(r"\{([A-Za-z0-9]{1,5})\s*$", body)
        if id_m:
            msg_id = id_m.group(1)
            text = body[: id_m.start()].rstrip()
        else:
            text = body
            msg_id = ""

    return IncomingMessage(
        from_call=from_call,
        to_call=to_call,
        body=text,
        msg_id=msg_id,
        is_ack=is_ack,
        is_rej=is_rej,
        raw=line,
    )
