"""Address book page and contact CRUD dialogs."""

from __future__ import annotations

from typing import Optional

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from .callsign import is_valid_callsign, normalize_callsign
from .dialogs import alert, confirm, set_default_ok
from .storage import Contact, Storage
from .ui_util import style_tree


class AddressBookMixin:
    """Mixin: address book UI for AprsMessengerApp."""

    def _build_address_book(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(12)
        box.set_margin_end(12)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        back = Gtk.Button(label="← Back")
        back.connect("clicked", lambda *_: self._show("main"))  # type: ignore[attr-defined]
        top.pack_start(back, False, False, 0)
        title = Gtk.Label(label="Address Book")
        title.get_style_context().add_class("title")
        top.pack_start(title, False, False, 8)
        self._book_count = Gtk.Label(label="")
        self._book_count.get_style_context().add_class("muted")
        top.pack_end(self._book_count, False, False, 0)
        box.pack_start(top, False, False, 0)

        tools = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        add_b = Gtk.Button(label="Add contact")
        add_b.get_style_context().add_class("suggested-action")
        add_b.connect("clicked", lambda *_: self._add_contact())
        edit_b = Gtk.Button(label="Edit contact")
        edit_b.connect("clicked", lambda *_: self._edit_contact())
        del_b = Gtk.Button(label="Delete selected")
        del_b.get_style_context().add_class("destructive-action")
        del_b.connect("clicked", lambda *_: self._delete_contact())
        open_b = Gtk.Button(label="Open chat")
        open_b.connect("clicked", lambda *_: self._open_selected_contact())
        tools.pack_start(add_b, False, False, 0)
        tools.pack_start(edit_b, False, False, 0)
        tools.pack_start(del_b, False, False, 0)
        tools.pack_start(open_b, False, False, 0)
        hint = Gtk.Label(label="Double-click a contact to open chat")
        hint.get_style_context().add_class("muted")
        tools.pack_end(hint, False, False, 0)
        box.pack_start(tools, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)

        self._book_store = Gtk.ListStore(int, str, str, str)
        self._book_view = Gtk.TreeView(model=self._book_store)
        style_tree(self._book_view)
        for i, (title_h, w) in enumerate(
            (("Callsign", 120), ("Name", 180), ("Notes", 260))
        ):
            col = Gtk.TreeViewColumn(title_h, Gtk.CellRendererText(), text=i + 1)
            col.set_min_width(w)
            col.set_resizable(True)
            self._book_view.append_column(col)
        self._book_view.connect(
            "row-activated", lambda *_: self._open_selected_contact()
        )
        scroll.add(self._book_view)
        box.pack_start(scroll, True, True, 0)
        box.connect("map", lambda *_: self._reload_book())
        return box

    def _reload_book(self) -> None:
        self._book_store.clear()
        contacts = self.store.list_contacts()  # type: ignore[attr-defined]
        for ct in contacts:
            self._book_store.append([ct.id, ct.callsign, ct.name, ct.notes])
        self._book_count.set_text(
            f"{len(contacts)} / {Storage.MAX_CONTACTS} contacts"
        )

    def _selected_book_contact(self) -> Optional[Contact]:
        sel = self._book_view.get_selection()
        model, itr = sel.get_selected()
        if not itr:
            return None
        cid = model[itr][0]
        for ct in self.store.list_contacts():  # type: ignore[attr-defined]
            if ct.id == cid:
                return ct
        return None

    def _contact_dialog(
        self, title: str, call: str = "", name: str = "", notes: str = ""
    ) -> Optional[tuple[str, str, str]]:
        """Shared Add/Edit contact dialog. Returns (callsign, name, notes) or None."""
        dlg = Gtk.Dialog(title=title, transient_for=self.win, flags=0)  # type: ignore[attr-defined]
        dlg.add_buttons(
            Gtk.STOCK_CANCEL,
            Gtk.ResponseType.CANCEL,
            Gtk.STOCK_SAVE,
            Gtk.ResponseType.OK,
        )
        box = dlg.get_content_area()
        box.set_spacing(8)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        call_e = Gtk.Entry()
        call_e.set_placeholder_text("Callsign")
        call_e.set_text(call)
        name_e = Gtk.Entry()
        name_e.set_placeholder_text("Name")
        name_e.set_text(name)
        notes_e = Gtk.Entry()
        notes_e.set_placeholder_text("Notes (optional)")
        notes_e.set_text(notes)
        box.pack_start(Gtk.Label(label="Callsign", xalign=0), False, False, 0)
        box.pack_start(call_e, False, False, 0)
        box.pack_start(Gtk.Label(label="Name", xalign=0), False, False, 0)
        box.pack_start(name_e, False, False, 0)
        box.pack_start(Gtk.Label(label="Notes", xalign=0), False, False, 0)
        box.pack_start(notes_e, False, False, 0)
        dlg.show_all()
        set_default_ok(dlg, focus_button=False)
        call_e.grab_focus()
        resp = dlg.run()
        result = None
        if resp == Gtk.ResponseType.OK:
            c = normalize_callsign(call_e.get_text())
            n = name_e.get_text().strip() or c
            no = notes_e.get_text().strip()
            if not is_valid_callsign(c):
                dlg.destroy()
                alert(self.win, "Invalid callsign", "Please enter a valid callsign.")  # type: ignore[attr-defined]
                return None
            result = (c, n, no)
        dlg.destroy()
        return result

    def _add_contact(self) -> None:
        result = self._contact_dialog("Add contact")
        if not result:
            return
        call, name, notes = result
        try:
            self.store.add_contact(call, name, notes)  # type: ignore[attr-defined]
            self._reload_book()
        except ValueError as e:
            alert(self.win, "Cannot add", str(e))  # type: ignore[attr-defined]

    def _edit_contact(self) -> None:
        ct = self._selected_book_contact()
        if not ct:
            alert(self.win, "No selection", "Select a contact to edit.", error=False)  # type: ignore[attr-defined]
            return
        result = self._contact_dialog(
            "Edit contact",
            call=ct.callsign,
            name=ct.name,
            notes=ct.notes,
        )
        if not result:
            return
        call, name, notes = result
        try:
            self.store.update_contact(ct.id, call, name, notes)  # type: ignore[attr-defined]
            self._reload_book()
        except Exception as e:
            alert(self.win, "Cannot update", str(e))  # type: ignore[attr-defined]

    def _delete_contact(self) -> None:
        ct = self._selected_book_contact()
        if not ct:
            alert(
                self.win,  # type: ignore[attr-defined]
                "No selection",
                "Select a contact to delete.",
                error=False,
            )
            return
        if confirm(
            self.win,  # type: ignore[attr-defined]
            "Delete contact?",
            f"Delete {ct.callsign} ({ct.name})?",
        ):
            self.store.delete_contact(ct.id)  # type: ignore[attr-defined]
            self._reload_book()

    def _open_selected_contact(self) -> None:
        ct = self._selected_book_contact()
        if not ct:
            alert(self.win, "No selection", "Select a contact first.", error=False)  # type: ignore[attr-defined]
            return
        self.open_chat(ct.callsign, ct.name)  # type: ignore[attr-defined]
