"""GTK3 application shell — login, main hub, connection, navigation."""

from __future__ import annotations

import logging
import queue
from typing import Optional

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from . import __app_name__, __version__
from .address_book import AddressBookMixin
from .aprs_is import AprsIsClient, IncomingMessage
from .bots import get_bot
from .bots_ui import BotsPageMixin
from .callsign import (
    is_valid_callsign,
    is_valid_grid,
    normalize_callsign,
    normalize_grid,
)
from .chat import ChatControllerMixin, ChatWindow
from .conversations import ConversationsMixin
from .dialogs import alert, confirm
from .notify import play_message_bell
from .storage import Storage
from .theme import apply_css
from .weather import WeatherChart, grid_to_latlon

log = logging.getLogger(__name__)


class AprsMessengerApp(
    AddressBookMixin,
    ConversationsMixin,
    BotsPageMixin,
    ChatControllerMixin,
    Gtk.Application,
):
    def __init__(self):
        super().__init__(application_id="radio.aprs.Messenger")
        self.store = Storage()
        self.client: Optional[AprsIsClient] = None
        self._ui_q: queue.Queue = queue.Queue()
        self._chat_windows: dict[str, ChatWindow] = {}
        self.win: Optional[Gtk.ApplicationWindow] = None
        self._stack: Optional[Gtk.Stack] = None
        self._status_label: Optional[Gtk.Label] = None
        self._call_label: Optional[Gtk.Label] = None
        self._flash_label: Optional[Gtk.Label] = None
        self._weather: Optional[WeatherChart] = None
        self.callsign = ""
        self.grid = ""

    def do_activate(self):
        apply_css()
        if self.win:
            self.win.present()
            return

        self.win = Gtk.ApplicationWindow(
            application=self, title=f"{__app_name__} v{__version__}"
        )
        self.win.set_default_size(1000, 680)
        self.win.connect("destroy", self._on_quit)

        hb = Gtk.HeaderBar()
        hb.set_show_close_button(True)
        hb.props.title = __app_name__
        self.win.set_titlebar(hb)

        self._call_label = Gtk.Label(label="")
        self._call_label.get_style_context().add_class("accent")
        hb.pack_start(self._call_label)

        logout_btn = Gtk.Button(label="Log out")
        logout_btn.connect("clicked", lambda *_: self.logout())
        hb.pack_end(logout_btn)

        about_btn = Gtk.Button(label="About")
        about_btn.connect("clicked", lambda *_: self._show_about())
        hb.pack_end(about_btn)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.win.add(vbox)

        self._flash_label = Gtk.Label(label="")
        self._flash_label.get_style_context().add_class("flash-alert")
        self._flash_label.set_no_show_all(True)
        self._flash_label.hide()
        vbox.pack_start(self._flash_label, False, False, 0)

        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        vbox.pack_start(self._stack, True, True, 0)

        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        status_box.get_style_context().add_class("panel")
        status_box.set_margin_start(8)
        status_box.set_margin_end(8)
        status_box.set_margin_bottom(4)
        self._status_label = Gtk.Label(label="Not connected", xalign=0)
        self._status_label.get_style_context().add_class("muted")
        status_box.pack_start(self._status_label, True, True, 8)
        vbox.pack_end(status_box, False, False, 4)

        self._stack.add_named(self._build_login(), "login")
        self._stack.add_named(self._build_main(), "main")
        self._stack.add_named(self._build_address_book(), "book")
        self._stack.add_named(self._build_conversations(), "chats")
        self._stack.add_named(self._build_bots(), "bots")

        self.win.show_all()
        GLib.timeout_add(100, self._poll_ui_queue)

        if self.store.is_configured():
            call, passcode = self.store.get_credentials()
            grid = self.store.get_grid()
            detail = f"Continue signed in as {call}"
            if grid:
                detail += f" ({grid})"
            detail += (
                "?\n\nOK — reconnect and open Main Menu\n"
                "Cancel — log out and sign in as another user"
            )
            if confirm(self.win, "Active login found", detail):
                self.callsign = call
                self.grid = grid
                label = call + (f"  ·  {grid}" if grid else "")
                if self._call_label:
                    self._call_label.set_text(label)
                self._stack.set_visible_child_name("main")
                self._connect(call, passcode)
                if self._weather and self.grid:
                    self._weather.set_grid(self.grid)
            else:
                if self.client:
                    self.client.stop()
                    self.client = None
                self.store.clear_credentials()
                self.callsign = ""
                self.grid = ""
                if self._call_label:
                    self._call_label.set_text("")
                if hasattr(self, "_login_call"):
                    self._login_call.set_text("")
                if hasattr(self, "_login_pass"):
                    self._login_pass.set_text("")
                if hasattr(self, "_login_grid"):
                    self._login_grid.set_text("")
                self._stack.set_visible_child_name("login")
        else:
            self._stack.set_visible_child_name("login")

    # ── pages ─────────────────────────────────────────────
    def _build_login(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_halign(Gtk.Align.CENTER)
        box.set_valign(Gtk.Align.CENTER)
        box.set_margin_top(40)
        box.set_margin_bottom(40)
        box.set_margin_start(40)
        box.set_margin_end(40)

        title = Gtk.Label(label="📡 APRS MESSENGER")
        title.get_style_context().add_class("title")
        box.pack_start(title, False, False, 0)

        sub = Gtk.Label(
            label="For licensed amateur radio operators · APRS-IS messaging"
        )
        sub.get_style_context().add_class("muted")
        box.pack_start(sub, False, False, 0)

        grid = Gtk.Grid(column_spacing=8, row_spacing=6)
        grid.set_margin_top(16)
        box.pack_start(grid, False, False, 0)

        grid.attach(Gtk.Label(label="Your callsign", xalign=0), 0, 0, 1, 1)
        self._login_call = Gtk.Entry()
        self._login_call.set_placeholder_text("e.g. W1AW")
        self._login_call.set_width_chars(28)
        grid.attach(self._login_call, 0, 1, 1, 1)

        grid.attach(
            Gtk.Label(label="aprs.fi / APRS-IS passcode", xalign=0), 0, 2, 1, 1
        )
        self._login_pass = Gtk.Entry()
        self._login_pass.set_visibility(False)
        self._login_pass.set_placeholder_text("Numeric passcode")
        self._login_pass.set_width_chars(28)
        grid.attach(self._login_pass, 0, 3, 1, 1)

        grid.attach(
            Gtk.Label(label="Maidenhead Grid Locator (4–6 characters)", xalign=0),
            0,
            4,
            1,
            1,
        )
        self._login_grid = Gtk.Entry()
        self._login_grid.set_placeholder_text("e.g. FN31 or IO91wm")
        self._login_grid.set_width_chars(28)
        self._login_grid.set_max_length(6)
        grid.attach(self._login_grid, 0, 5, 1, 1)

        hint = Gtk.Label(
            label="Passcode: apps.magicbug.co.uk/passcode/  ·  Use only your licensed callsign\n"
            "Grid: 4 or 6 character Maidenhead locator (AA00 or AA00aa)"
        )
        hint.get_style_context().add_class("muted")
        hint.set_line_wrap(True)
        hint.set_justify(Gtk.Justification.CENTER)
        box.pack_start(hint, False, False, 4)

        go = Gtk.Button(label="Connect")
        go.get_style_context().add_class("suggested-action")
        go.connect("clicked", self._on_login)
        self._login_grid.connect("activate", self._on_login)
        self._login_pass.connect(
            "activate", lambda *_: self._login_grid.grab_focus()
        )
        box.pack_start(go, False, False, 8)

        saved, _ = self.store.get_credentials()
        if saved:
            self._login_call.set_text(saved)
        g = self.store.get_grid()
        if g:
            self._login_grid.set_text(g)
        return box

    def _build_main(self) -> Gtk.Widget:
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        outer.set_halign(Gtk.Align.CENTER)
        outer.set_valign(Gtk.Align.START)
        outer.set_margin_top(20)
        outer.set_margin_bottom(20)
        outer.set_margin_start(12)
        outer.set_margin_end(12)

        t = Gtk.Label(label="Main Menu")
        t.get_style_context().add_class("title")
        outer.pack_start(t, False, False, 0)

        grid = Gtk.Grid()
        grid.set_column_spacing(8)
        grid.set_row_spacing(8)
        grid.set_halign(Gtk.Align.CENTER)
        outer.pack_start(grid, False, False, 8)

        grid.attach(
            self._menu_card(
                "📇  Address Book",
                f"Up to {Storage.MAX_CONTACTS} Callsigns & Names.\n"
                "Double-Click Contact to chat.",
                lambda: self._show("book"),
            ),
            0,
            0,
            1,
            1,
        )
        grid.attach(
            self._menu_card(
                "💬  Chat Messages",
                "Send APRS messages to other HAM Operators Worldwide.",
                lambda: self._show("chats"),
            ),
            1,
            0,
            1,
            1,
        )
        grid.attach(
            self._menu_card(
                "🤖  APRS Bots",
                "SMS, EMAIL-2, APTDAP, WTSAPP",
                lambda: self._show("bots"),
            ),
            0,
            1,
            1,
            1,
        )
        grid.attach(
            self._menu_card(
                "📡  Beacon Position",
                "Send your location to aprs.fi",
                self._beacon_position,
            ),
            1,
            1,
            1,
            1,
        )

        self._weather = WeatherChart()
        outer.pack_start(self._weather, False, False, 8)
        if self.grid:
            self._weather.set_grid(self.grid)

        scroll.add(outer)
        return scroll

    def _menu_card(self, title: str, desc: str, cb) -> Gtk.EventBox:
        eb, _ = self._menu_card_with_badge(title, desc, cb, show_badge=False)
        return eb

    def _menu_card_with_badge(
        self, title: str, desc: str, cb, show_badge: bool = True
    ) -> tuple[Gtk.EventBox, Optional[Gtk.Label]]:
        eb = Gtk.EventBox()
        frame = Gtk.Frame()
        frame.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        inner.set_size_request(220, 160)
        inner.set_halign(Gtk.Align.CENTER)
        inner.set_margin_top(20)
        inner.set_margin_bottom(20)
        inner.set_margin_start(14)
        inner.set_margin_end(14)

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        head.set_halign(Gtk.Align.CENTER)
        head.set_hexpand(True)
        tl = Gtk.Label(label=title)
        tl.get_style_context().add_class("title")
        tl.set_justify(Gtk.Justification.CENTER)
        tl.set_halign(Gtk.Align.CENTER)
        tl.set_xalign(0.5)
        head.pack_start(tl, False, False, 0)
        badge = None
        if show_badge:
            badge = Gtk.Label(label="")
            badge.get_style_context().add_class("badge")
            badge.set_no_show_all(True)
            badge.hide()
            head.pack_start(badge, False, False, 0)
        inner.pack_start(head, False, False, 0)

        dl = Gtk.Label(label=desc)
        dl.set_line_wrap(True)
        dl.set_justify(Gtk.Justification.CENTER)
        dl.set_halign(Gtk.Align.CENTER)
        dl.set_xalign(0.5)
        dl.set_max_width_chars(28)
        dl.get_style_context().add_class("muted")
        inner.pack_start(dl, False, False, 0)
        frame.add(inner)
        eb.add(frame)
        eb.set_above_child(True)

        def on_press(_w, event):
            if event.type in (
                Gdk.EventType.BUTTON_PRESS,
                Gdk.EventType._2BUTTON_PRESS,
            ):
                cb()
                return True
            return False

        eb.connect("button-press-event", on_press)
        return eb, badge

    def _show(self, name: str) -> None:
        assert self._stack
        self._stack.set_visible_child_name(name)
        if name == "book":
            self._reload_book()
        elif name == "chats":
            self._reload_conversations()
        elif name == "main":
            if self._weather and self.grid:
                self._weather.set_grid(self.grid)

    # ── position beacon ───────────────────────────────────
    def _beacon_position(self) -> None:
        if not self.client or not self.client.connected:
            alert(
                self.win,
                "Not connected",
                "Connect to APRS-IS before sending a beacon.",
            )
            return
        grid = (self.grid or self.store.get_grid() or "").strip().upper()
        if not grid:
            alert(
                self.win,
                "No grid set",
                "Log in with a Maidenhead Grid Locator (4–6 characters)\n"
                "before sending a position beacon.",
            )
            return
        try:
            lat, lon = grid_to_latlon(grid)
        except ValueError:
            alert(
                self.win,
                "Invalid grid",
                f"Cannot convert grid {grid} to coordinates.",
            )
            return

        status = f"{self.callsign} Via APRS-Messenger"
        if not confirm(
            self.win,
            "Send position beacon?",
            f"Grid: {grid}\n"
            f"Approx: {lat:.4f}°, {lon:.4f}°\n"
            f"Status: {status}\n\n"
            "This publishes your position to APRS-IS (visible on aprs.fi).",
        ):
            return
        try:
            line = self.client.send_position(lat, lon, comment=status)
            self._set_status(f"Position beacon sent ({grid})")
            alert(
                self.win,
                "Beacon sent",
                f"Queued for APRS-IS:\n{line}\n\n"
                f"Check aprs.fi/?call={self.callsign} in a few moments.",
                error=False,
            )
        except Exception as e:
            alert(self.win, "Beacon failed", str(e))

    # ── login / connection ────────────────────────────────
    def _on_login(self, *_args) -> None:
        call = normalize_callsign(self._login_call.get_text())
        passcode = self._login_pass.get_text().strip()
        grid = normalize_grid(self._login_grid.get_text())
        if not is_valid_callsign(call):
            alert(
                self.win,
                "Invalid callsign",
                "Enter a valid amateur callsign (e.g. W1AW, G0ABC).",
            )
            return
        if not passcode or not passcode.lstrip("-").isdigit():
            alert(
                self.win,
                "Invalid passcode",
                "Enter your numeric APRS-IS / aprs.fi passcode.",
            )
            return
        if not is_valid_grid(grid):
            alert(
                self.win,
                "Invalid grid",
                "Enter a Maidenhead locator of 4 or 6 characters\n"
                "(e.g. FN31 or IO91wm).",
            )
            return
        if not confirm(
            self.win,
            f"Connect as {call}?",
            f"Grid: {grid}\n\n"
            "Only use a callsign you are licensed to operate.\n"
            "APRS messaging is part of the amateur radio service.",
        ):
            return
        self.store.set_credentials(call, passcode, grid)
        self.callsign = call
        self.grid = grid
        if self._call_label:
            self._call_label.set_text(f"{call}  ·  {grid}")
        self._connect(call, passcode)
        self._show("main")
        if self._weather:
            self._weather.set_grid(grid)

    def _connect(self, callsign: str, passcode: str) -> None:
        if self.client:
            self.client.stop()
        self.client = AprsIsClient(
            callsign=callsign,
            passcode=passcode,
            on_message=lambda m: self._ui_q.put(("aprs", m)),
            on_status=lambda s: self._ui_q.put(("status", s)),
        )
        self.client.start()
        self._set_status("Connecting…")

    def _set_status(self, text: str) -> None:
        if self._status_label:
            self._status_label.set_text(text)

    def _poll_ui_queue(self):
        try:
            while True:
                kind, payload = self._ui_q.get_nowait()
                if kind == "status":
                    self._set_status(payload)
                elif kind == "aprs":
                    self._handle_incoming(payload)
        except queue.Empty:
            pass
        return True

    def _addressed_to_us(self, msg: IncomingMessage) -> bool:
        """SSID-tolerant check that the message addressee is this station."""
        our = normalize_callsign(self.callsign)
        to = normalize_callsign(msg.to_call)
        if not our or not to:
            return False
        our_base = our.split("-", 1)[0]
        to_base = to.split("-", 1)[0]
        return to_base == our_base or to == our

    def _handle_incoming(self, msg: IncomingMessage) -> None:
        if not self._addressed_to_us(msg):
            return

        if msg.is_ack or msg.is_rej:
            if not (msg.msg_id or "").strip():
                return
            peer = normalize_callsign(msg.from_call)
            status = "delivered" if msg.is_ack else "failed"
            self.store.update_message_status(msg.msg_id, status, peer=peer)
            if peer in self._chat_windows:
                self._chat_windows[peer].reload()
            return

        peer = normalize_callsign(msg.from_call)
        body = msg.body.strip()
        if not body:
            return

        self.store.add_message(
            peer, "in", body, msg_id=msg.msg_id, status="received"
        )
        if msg.msg_id and self.client:
            try:
                self.client.send_ack(peer, msg.msg_id)
            except Exception:
                log.exception("failed to queue ACK")

        chat_open = (
            peer in self._chat_windows and self._chat_windows[peer].get_realized()
        )
        if not chat_open:
            ct = self.store.get_contact_by_callsign(peer)
            bot = get_bot(peer)
            name = ct.name if ct else (bot.name if bot else "")
            self.open_chat(peer, name, bot_help=bot is not None)
            self._set_status(f"New message from {peer}")
            self._flash_new_message(peer, body)
            play_message_bell()
            try:
                display = Gdk.Display.get_default()
                if display:
                    display.beep()
            except Exception:
                pass
        else:
            self._chat_windows[peer].reload()
            self._chat_windows[peer].present()

        self._reload_conversations()

    def _flash_new_message(self, peer: str, body: str) -> None:
        if not self._flash_label:
            return
        preview = (body[:50] + "…") if len(body) > 50 else body
        self._flash_label.set_text(f"  🔔  New message from {peer}: {preview}  ")
        self._flash_label.show()

        def hide():
            if self._flash_label:
                self._flash_label.hide()
            return False

        GLib.timeout_add(6000, hide)

    def _show_about(self) -> None:
        dlg = Gtk.MessageDialog(
            transient_for=self.win,
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.NONE,
            text=f"{__app_name__} {__version__} by Eamon Morgan - MI7DJT",
        )
        dlg.set_title("About")
        dlg.set_modal(True)
        dlg.show_all()

        def close_about():
            try:
                dlg.destroy()
            except Exception:
                pass
            return False

        GLib.timeout_add(5000, close_about)

    def logout(self) -> None:
        if not confirm(
            self.win,
            "Log out?",
            "Clear saved callsign, passcode, and grid?",
        ):
            return
        if self.client:
            self.client.stop()
            self.client = None
        self.store.clear_credentials()
        self.callsign = ""
        self.grid = ""
        if self._call_label:
            self._call_label.set_text("")
        self._login_pass.set_text("")
        self._show("login")

    def _on_quit(self, *_args) -> None:
        if self.client:
            self.client.stop()
        self.store.close()

    def run_app(self) -> int:
        return self.run([])


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    app = AprsMessengerApp()
    app.run_app()
