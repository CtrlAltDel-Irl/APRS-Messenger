"""APRS bots browser page."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from .bots import POPULAR_BOTS, get_bot
from .dialogs import alert
from .ui_util import style_tree


class BotsPageMixin:
    """Mixin: bots list UI for AprsMessengerApp."""

    def _build_bots(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(12)
        box.set_margin_end(12)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        back = Gtk.Button(label="← Back")
        back.connect("clicked", lambda *_: self._show("main"))  # type: ignore[attr-defined]
        top.pack_start(back, False, False, 0)
        title = Gtk.Label(label="APRS Bots")
        title.get_style_context().add_class("title")
        top.pack_start(title, False, False, 8)
        hint = Gtk.Label(label="Double-click a bot to open chat with usage example")
        hint.get_style_context().add_class("muted")
        top.pack_end(hint, False, False, 0)
        box.pack_start(top, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        self._bots_store = Gtk.ListStore(str, str, str, str)
        self._bots_view = Gtk.TreeView(model=self._bots_store)
        style_tree(self._bots_view)
        for i, (h, w) in enumerate((("Bot", 100), ("Name", 140), ("Purpose", 420))):
            col = Gtk.TreeViewColumn(h, Gtk.CellRendererText(), text=i + 1)
            col.set_min_width(w)
            col.set_resizable(True)
            self._bots_view.append_column(col)
        for b in POPULAR_BOTS:
            self._bots_store.append(
                [b.callsign, b.display_call, b.name, b.description]
            )
        self._bots_view.connect(
            "row-activated", lambda *_: self._open_selected_bot()
        )
        scroll.add(self._bots_view)
        box.pack_start(scroll, True, True, 0)

        open_b = Gtk.Button(label="Open selected bot chat")
        open_b.get_style_context().add_class("suggested-action")
        open_b.connect("clicked", lambda *_: self._open_selected_bot())
        box.pack_start(open_b, False, False, 4)
        return box

    def _open_selected_bot(self) -> None:
        sel = self._bots_view.get_selection()
        model, itr = sel.get_selected()
        if not itr:
            alert(self.win, "No selection", "Select a bot first.", error=False)  # type: ignore[attr-defined]
            return
        call = model[itr][0]
        bot = get_bot(call)
        self.open_chat(call, bot.name if bot else "", bot_help=True)  # type: ignore[attr-defined]
