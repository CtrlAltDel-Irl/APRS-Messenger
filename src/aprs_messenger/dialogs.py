"""Shared GTK dialog helpers."""

from __future__ import annotations

from typing import Optional

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402


def set_default_ok(dlg: Gtk.Dialog, *, focus_button: bool = True) -> None:
    """
    Make OK the default response (Enter activates OK).

    When focus_button is True (typical for OK/Cancel prompts), also move
    keyboard focus to the OK button so it is the selected control.
    Use focus_button=False for dialogs with text entries so typing still works;
    Enter in those entries will still activate OK via the default response.
    """
    dlg.set_default_response(Gtk.ResponseType.OK)
    if focus_button:
        btn = dlg.get_widget_for_response(Gtk.ResponseType.OK)
        if btn is not None:
            btn.set_can_default(True)
            btn.grab_default()
            btn.grab_focus()


def confirm(parent: Optional[Gtk.Window], title: str, text: str) -> bool:
    dlg = Gtk.MessageDialog(
        transient_for=parent,
        flags=0,
        message_type=Gtk.MessageType.QUESTION,
        buttons=Gtk.ButtonsType.OK_CANCEL,
        text=title,
    )
    dlg.format_secondary_text(text)
    set_default_ok(dlg)
    resp = dlg.run()
    dlg.destroy()
    return resp == Gtk.ResponseType.OK


def alert(
    parent: Optional[Gtk.Window],
    title: str,
    text: str,
    error: bool = True,
) -> None:
    dlg = Gtk.MessageDialog(
        transient_for=parent,
        flags=0,
        message_type=Gtk.MessageType.ERROR if error else Gtk.MessageType.INFO,
        buttons=Gtk.ButtonsType.OK,
        text=title,
    )
    dlg.format_secondary_text(text)
    set_default_ok(dlg)
    dlg.run()
    dlg.destroy()
