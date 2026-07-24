"""Conversation list page (chat history browser)."""

from __future__ import annotations

from typing import Optional

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Pango  # noqa: E402

from .bots import get_bot
from .callsign import is_valid_destination, normalize_callsign
from .chat import save_chat_dialog
from .dialogs import alert, confirm, set_default_ok
from .ui_util import fmt_dt, style_tree


class ConversationsMixin:
    """Mixin: conversation list UI for AprsMessengerApp."""

    def _build_conversations(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(12)
        box.set_margin_end(12)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        back = Gtk.Button(label="← Back")
        back.connect("clicked", lambda *_: self._show("main"))  # type: ignore[attr-defined]
        top.pack_start(back, False, False, 0)
        title = Gtk.Label(label="Chat Messages")
        title.get_style_context().add_class("title")
        top.pack_start(title, False, False, 8)
        new_b = Gtk.Button(label="New chat…")
        new_b.get_style_context().add_class("suggested-action")
        new_b.connect("clicked", lambda *_: self._new_chat())
        top.pack_end(new_b, False, False, 0)
        box.pack_start(top, False, False, 0)

        tools = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        open_b = Gtk.Button(label="Open")
        open_b.connect("clicked", lambda *_: self._open_selected_conversation())
        del_b = Gtk.Button(label="Delete chat")
        del_b.get_style_context().add_class("destructive-action")
        del_b.connect("clicked", lambda *_: self._delete_selected_chat())
        save_b = Gtk.Button(label="Save chat…")
        save_b.connect("clicked", lambda *_: self._save_selected_chat())
        tools.pack_start(open_b, False, False, 0)
        tools.pack_start(del_b, False, False, 0)
        tools.pack_start(save_b, False, False, 0)
        box.pack_start(tools, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        self._chat_store = Gtk.ListStore(str, str, str, str)
        self._chat_view = Gtk.TreeView(model=self._chat_store)
        style_tree(self._chat_view)
        for i, (title_h, mw) in enumerate(
            (("Callsign", 100), ("Name", 120), ("Last message", 220), ("Time", 120))
        ):
            rend = Gtk.CellRendererText()
            if i == 2:
                rend.set_property("ellipsize", Pango.EllipsizeMode.END)
            col = Gtk.TreeViewColumn(title_h, rend, text=i)
            col.set_resizable(True)
            col.set_min_width(mw)
            if i == 2:
                col.set_expand(True)
            self._chat_view.append_column(col)
        self._chat_view.connect(
            "row-activated", lambda *_: self._open_selected_conversation()
        )
        scroll.add(self._chat_view)
        box.pack_start(scroll, True, True, 0)

        legend = Gtk.Label(label="✓ = delivered (ACK received)")
        legend.get_style_context().add_class("muted")
        box.pack_start(legend, False, False, 4)

        box.connect("map", lambda *_: self._reload_conversations())
        return box

    def _reload_conversations(self) -> None:
        if not hasattr(self, "_chat_store"):
            return
        self._chat_store.clear()
        for row in self.store.list_conversations():  # type: ignore[attr-defined]
            body = (row["last_body"] or "")[:80]
            self._chat_store.append(
                [
                    row["peer"],
                    row["name"] or "",
                    body,
                    fmt_dt(row["last_ts"]),
                ]
            )

    def _selected_chat_peer(self) -> Optional[tuple[str, str]]:
        sel = self._chat_view.get_selection()
        model, itr = sel.get_selected()
        if not itr:
            return None
        return model[itr][0], model[itr][1]

    def _open_selected_conversation(self) -> None:
        sel = self._selected_chat_peer()
        if not sel:
            return
        peer, name = sel
        self.open_chat(peer, name)  # type: ignore[attr-defined]

    def _delete_selected_chat(self) -> None:
        sel = self._selected_chat_peer()
        if not sel:
            alert(
                self.win,  # type: ignore[attr-defined]
                "No selection",
                "Select a chat to delete.",
                error=False,
            )
            return
        peer, _ = sel
        if confirm(
            self.win,  # type: ignore[attr-defined]
            "Delete chat?",
            f"Permanently delete all messages with {peer}?",
        ):
            self.store.delete_conversation(peer)  # type: ignore[attr-defined]
            if peer in self._chat_windows:  # type: ignore[attr-defined]
                self._chat_windows[peer].destroy()  # type: ignore[attr-defined]
            self._reload_conversations()

    def _save_selected_chat(self) -> None:
        sel = self._selected_chat_peer()
        if not sel:
            alert(
                self.win,  # type: ignore[attr-defined]
                "No selection",
                "Select a chat to save.",
                error=False,
            )
            return
        peer, _ = sel
        msgs = self.store.list_messages(peer)  # type: ignore[attr-defined]
        save_chat_dialog(
            self.win,  # type: ignore[attr-defined]
            peer,
            msgs,
            self.callsign,  # type: ignore[attr-defined]
            self.grid,  # type: ignore[attr-defined]
        )

    def _new_chat(self) -> None:
        dlg = Gtk.Dialog(title="New chat", transient_for=self.win, flags=0)  # type: ignore[attr-defined]
        dlg.add_buttons(
            Gtk.STOCK_CANCEL,
            Gtk.ResponseType.CANCEL,
            "Open",
            Gtk.ResponseType.OK,
        )
        box = dlg.get_content_area()
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        e = Gtk.Entry()
        e.set_placeholder_text("Station callsign")
        box.pack_start(Gtk.Label(label="Callsign", xalign=0), False, False, 0)
        box.pack_start(e, False, False, 4)
        dlg.show_all()
        set_default_ok(dlg, focus_button=False)
        # Keep focus in the callsign entry so typing works; Enter still activates OK
        e.grab_focus()
        resp = dlg.run()
        call = normalize_callsign(e.get_text())
        dlg.destroy()
        if resp != Gtk.ResponseType.OK:
            return
        if not is_valid_destination(call):
            alert(
                self.win,  # type: ignore[attr-defined]
                "Invalid callsign",
                "Enter a valid callsign or bot address.",
            )
            return
        ct = self.store.get_contact_by_callsign(call)  # type: ignore[attr-defined]
        bot = get_bot(call)
        name = ct.name if ct else (bot.name if bot else "")
        self.open_chat(call, name, bot_help=bot is not None)  # type: ignore[attr-defined]
