"""Chat window, message splitting, and conversation export."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Sequence

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from .bots import get_bot, is_known_bot
from .callsign import is_valid_destination, normalize_callsign
from .dialogs import alert, confirm, set_default_ok
from .storage import ChatMessage
from .ui_util import fmt_dt, fmt_time

if TYPE_CHECKING:
    from .app import AprsMessengerApp

TICK_SENT = ""  # no tick until ACK
TICK_DELIVERED = "✓"  # single tick when delivered (ACK received)
TICK_FAILED = "✗"


def split_aprs_message(text: str, limit: int = 67) -> list[str]:
    """Split long text into ordered APRS-sized chunks (max ~67 chars each)."""
    text = (text or "").replace("\r", " ").replace("\n", " ").strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    while text:
        if len(text) <= limit:
            parts.append(text)
            break
        chunk = text[:limit]
        # Prefer breaking on whitespace when possible
        sp = chunk.rfind(" ")
        if sp >= max(8, limit // 3):
            parts.append(text[:sp].rstrip())
            text = text[sp + 1 :].lstrip()
        else:
            parts.append(text[:limit])
            text = text[limit:]
    return [p for p in parts if p]


def format_chat_export(
    peer: str,
    msgs: Sequence[ChatMessage],
    operator: str,
    grid: str,
) -> str:
    """Build plain-text export of a conversation."""
    lines = [
        "APRS Messenger chat export",
        f"Peer: {peer}",
        f"Saved: {datetime.now().isoformat(timespec='seconds')}",
        f"Operator: {operator}  Grid: {grid}",
        "-" * 48,
    ]
    for m in msgs:
        who = operator if m.direction == "out" else peer
        lines.append(f"[{fmt_dt(m.ts)}] {who}: {m.body}")
    return "\n".join(lines) + "\n"


def save_chat_dialog(
    parent: Optional[Gtk.Window],
    peer: str,
    msgs: Sequence[ChatMessage],
    operator: str,
    grid: str,
) -> bool:
    """Prompt for a path and write the conversation export. Returns True if saved."""
    if not msgs:
        alert(parent, "Empty", "No messages to save.", error=False)
        return False
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dlg = Gtk.FileChooserDialog(
        title="Save chat",
        transient_for=parent,
        action=Gtk.FileChooserAction.SAVE,
    )
    dlg.add_buttons(
        Gtk.STOCK_CANCEL,
        Gtk.ResponseType.CANCEL,
        Gtk.STOCK_SAVE,
        Gtk.ResponseType.OK,
    )
    dlg.set_current_name(f"{peer}_{stamp}.txt")
    dlg.set_do_overwrite_confirmation(True)
    set_default_ok(dlg)
    resp = dlg.run()
    path = dlg.get_filename() if resp == Gtk.ResponseType.OK else None
    dlg.destroy()
    if not path:
        return False
    try:
        Path(path).write_text(
            format_chat_export(peer, msgs, operator, grid),
            encoding="utf-8",
        )
        alert(parent, "Saved", f"Chat saved to:\n{path}", error=False)
        return True
    except OSError as e:
        alert(parent, "Save failed", str(e))
        return False


class ChatWindow(Gtk.Window):
    def __init__(
        self,
        app: "AprsMessengerApp",
        peer: str,
        name: str = "",
        show_bot_example: bool = False,
    ):
        title = f"Chat with {peer}" + (f" — {name}" if name else "")
        super().__init__(title=title)
        self.app = app
        self.peer = peer
        self.show_bot_example = show_bot_example
        self.set_default_size(520, 600)
        self.set_transient_for(app.win)
        self.connect("destroy", self._on_destroy)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(vbox)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        header.get_style_context().add_class("panel")
        hlab = Gtk.Label(label=f"  {peer}  ")
        hlab.get_style_context().add_class("accent")
        header.pack_start(hlab, False, False, 8)
        if name:
            nlab = Gtk.Label(label=name)
            nlab.get_style_context().add_class("muted")
            header.pack_start(nlab, False, False, 4)
        tip = Gtk.Label(label="APRS · ~67 char limit")
        tip.get_style_context().add_class("muted")
        header.pack_end(tip, False, False, 12)
        vbox.pack_start(header, False, False, 0)

        bot = get_bot(peer)
        if show_bot_example and bot:
            help_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            help_box.get_style_context().add_class("panel")
            help_box.set_margin_start(8)
            help_box.set_margin_end(8)
            help_box.set_margin_top(8)
            t1 = Gtk.Label(label=f"Bot: {bot.name}")
            t1.get_style_context().add_class("accent2")
            t1.set_xalign(0)
            t2 = Gtk.Label(label=bot.description)
            t2.set_line_wrap(True)
            t2.set_xalign(0)
            t2.get_style_context().add_class("muted")
            t3 = Gtk.Label(label=f"Example message:\n{bot.example}")
            t3.set_line_wrap(True)
            t3.set_xalign(0)
            t3.set_selectable(True)
            t4 = Gtk.Label(label=bot.tips)
            t4.set_line_wrap(True)
            t4.set_xalign(0)
            t4.get_style_context().add_class("muted")
            for w in (t1, t2, t3, t4):
                w.set_margin_start(10)
                w.set_margin_end(10)
                help_box.pack_start(w, False, False, 2)
            use = Gtk.Button(label="Insert example into composer")
            use.connect("clicked", lambda *_: self.entry.set_text(bot.example[:67]))
            use.set_margin_start(10)
            use.set_margin_end(10)
            use.set_margin_bottom(8)
            help_box.pack_start(use, False, False, 4)
            vbox.pack_start(help_box, False, False, 0)

        tools = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        tools.set_margin_start(8)
        tools.set_margin_end(8)
        tools.set_margin_top(6)
        for label, cb, destructive in (
            ("Save chat…", self._save, False),
            ("Delete chat", self._delete, True),
        ):
            b = Gtk.Button(label=label)
            if destructive:
                b.get_style_context().add_class("destructive-action")
            b.connect("clicked", lambda _w, fn=cb: fn())
            tools.pack_start(b, False, False, 0)
        vbox.pack_start(tools, False, False, 0)

        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroll.set_vexpand(True)
        self.scroll.get_style_context().add_class("chat-scroll")
        self.msg_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.msg_box.set_margin_start(10)
        self.msg_box.set_margin_end(10)
        self.msg_box.set_margin_top(10)
        self.msg_box.set_margin_bottom(10)
        self.msg_box.set_valign(Gtk.Align.END)
        view = Gtk.Viewport()
        view.add(self.msg_box)
        self.scroll.add(view)
        vbox.pack_start(self.scroll, True, True, 0)

        bot_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bot_row.get_style_context().add_class("panel")
        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("Type an APRS message…")
        self.entry.connect("activate", lambda *_: self._send())
        bot_row.pack_start(self.entry, True, True, 8)
        send = Gtk.Button(label="Send")
        send.get_style_context().add_class("suggested-action")
        send.connect("clicked", lambda *_: self._send())
        bot_row.pack_end(send, False, False, 8)
        bot_row.set_margin_bottom(8)
        vbox.pack_end(bot_row, False, False, 8)

        self.reload()
        self.entry.grab_focus()
        self.connect("map-event", lambda *_: (self.scroll_to_bottom(), False)[1])
        GLib.idle_add(self.scroll_to_bottom)
        GLib.timeout_add(150, self.scroll_to_bottom)

    def _on_destroy(self, *_args) -> None:
        self.app._chat_windows.pop(self.peer, None)

    def _make_bubble(
        self, body: str, outgoing: bool, meta: str, tick: str = ""
    ) -> Gtk.Widget:
        """Build a left (incoming/blue) or right (outgoing/green) speech bubble."""
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        row.set_hexpand(True)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        card.set_size_request(120, -1)
        card.set_hexpand(False)
        card.get_style_context().add_class("bubble-out" if outgoing else "bubble-in")

        meta_l = Gtk.Label(label=meta)
        meta_l.get_style_context().add_class("bubble-meta")
        meta_l.set_xalign(0.0)
        meta_l.set_halign(Gtk.Align.START)
        card.pack_start(meta_l, False, False, 0)

        text_l = Gtk.Label(label=body)
        text_l.set_line_wrap(True)
        text_l.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        text_l.set_max_width_chars(36)
        text_l.set_xalign(0.0)
        text_l.set_justify(Gtk.Justification.LEFT)
        text_l.set_selectable(True)
        text_l.get_style_context().add_class("bubble-text")
        text_l.override_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(1, 1, 1, 1))
        card.pack_start(text_l, False, False, 0)

        if tick:
            tick_l = Gtk.Label(label=tick)
            tick_l.get_style_context().add_class("bubble-tick")
            tick_l.set_xalign(1.0)
            tick_l.override_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(1, 1, 1, 0.9))
            card.pack_start(tick_l, False, False, 0)

        if outgoing:
            row.pack_start(Gtk.Box(), True, True, 0)
            card.set_halign(Gtk.Align.END)
            row.pack_end(card, False, False, 0)
        else:
            card.set_halign(Gtk.Align.START)
            row.pack_start(card, False, False, 0)
            row.pack_end(Gtk.Box(), True, True, 0)

        return row

    def reload(self) -> None:
        for child in list(self.msg_box.get_children()):
            self.msg_box.remove(child)

        for m in self.app.store.list_messages(self.peer):
            if m.direction == "out":
                ticks = {
                    "sent": TICK_SENT,
                    "delivered": TICK_DELIVERED,
                    "failed": TICK_FAILED,
                    "pending": "",
                }.get(m.status, TICK_SENT)
                bubble = self._make_bubble(
                    m.body,
                    outgoing=True,
                    meta=f"{fmt_time(m.ts)}  You   {ticks}",
                )
            else:
                bubble = self._make_bubble(
                    m.body,
                    outgoing=False,
                    meta=f"{fmt_time(m.ts)}  {self.peer}",
                )
            self.msg_box.pack_start(bubble, False, False, 0)

        self.msg_box.show_all()
        self.scroll_to_bottom()

    def scroll_to_bottom(self) -> None:
        """Scroll transcript to the latest message."""

        def _do():
            adj = self.scroll.get_vadjustment()
            if adj:
                adj.set_value(adj.get_upper() - adj.get_page_size())
            return False

        GLib.idle_add(_do)
        return False

    def _send(self) -> None:
        body = self.entry.get_text().strip()
        if not body:
            return
        parts = split_aprs_message(body, 67)
        if len(parts) > 1:
            if not confirm(
                self,
                "Send as multiple messages?",
                f"Message is {len(body)} characters. APRS limit is 67.\n"
                f"It will be sent as {len(parts)} messages in order.",
            ):
                return
        self.entry.set_text("")
        self.app.send_chat(self.peer, body)
        self.scroll_to_bottom()

    def _save(self) -> None:
        msgs = self.app.store.list_messages(self.peer)
        save_chat_dialog(
            self,
            self.peer,
            msgs,
            self.app.callsign,
            self.app.grid,
        )

    def _delete(self) -> None:
        if confirm(
            self,
            "Delete chat?",
            f"Delete conversation with {self.peer} and close?",
        ):
            self.app.store.delete_conversation(self.peer)
            self.app._reload_conversations()
            self.destroy()


class ChatControllerMixin:
    """open_chat / send_chat and conversation list helpers for the main app."""

    def open_chat(self, peer: str, name: str = "", bot_help: bool = False) -> None:
        peer = normalize_callsign(peer)
        if is_known_bot(peer):
            bot_help = True
        if peer in self._chat_windows:  # type: ignore[attr-defined]
            w = self._chat_windows[peer]  # type: ignore[attr-defined]
            if w.get_realized():
                w.present()
                w.reload()
                w.scroll_to_bottom()
                self._reload_conversations()  # type: ignore[attr-defined]
                return
        win = ChatWindow(
            self,  # type: ignore[arg-type]
            peer,
            name,
            show_bot_example=bot_help or is_known_bot(peer),
        )
        self._chat_windows[peer] = win  # type: ignore[attr-defined]
        self._reload_conversations()  # type: ignore[attr-defined]
        win.show_all()
        GLib.idle_add(win.scroll_to_bottom)
        GLib.timeout_add(120, win.scroll_to_bottom)

    def send_chat(self, peer: str, text: str) -> None:
        peer = normalize_callsign(peer)
        text = text.strip()
        if not text:
            return
        client = getattr(self, "client", None)
        if not client or not client.connected:
            alert(
                self.win,  # type: ignore[attr-defined]
                "Not connected",
                "Not connected to APRS-IS.\n"
                "Wait until the status bar shows Connected, then try again.",
            )
            return
        parts = split_aprs_message(text, 67)
        if len(parts) > 1:
            self._set_status(f"Sending {len(parts)} parts to {peer}…")  # type: ignore[attr-defined]
        for part in parts:
            if not client or not client.connected:
                alert(
                    self.win,  # type: ignore[attr-defined]
                    "Connection lost",
                    "Disconnected from APRS-IS while sending.\n"
                    "Remaining parts were not sent.",
                )
                break
            try:
                mid = client.send_message(peer, part)
            except ConnectionError:
                alert(
                    self.win,  # type: ignore[attr-defined]
                    "Not connected",
                    "Not connected to APRS-IS.\nMessage was not sent.",
                )
                break
            self.store.add_message(peer, "out", part, msg_id=mid, status="sent")  # type: ignore[attr-defined]
        if peer in self._chat_windows:  # type: ignore[attr-defined]
            self._chat_windows[peer].reload()  # type: ignore[attr-defined]
            self._chat_windows[peer].scroll_to_bottom()  # type: ignore[attr-defined]
        self._reload_conversations()  # type: ignore[attr-defined]
