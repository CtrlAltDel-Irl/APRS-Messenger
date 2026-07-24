"""Small UI formatting and TreeView helpers."""

from __future__ import annotations

from datetime import datetime

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402


def fmt_time(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M")


def fmt_dt(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def style_tree(view: Gtk.TreeView) -> None:
    """Make single-click selection visually obvious."""
    view.set_activate_on_single_click(False)
    view.set_enable_search(True)
    view.set_grid_lines(Gtk.TreeViewGridLines.HORIZONTAL)
    sel = view.get_selection()
    sel.set_mode(Gtk.SelectionMode.SINGLE)
