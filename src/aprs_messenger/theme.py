"""Application CSS theme (GTK3)."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

CSS = b"""
window, dialog { background-color: #0d1117; color: #e6edf3; }
.panel { background-color: #161b22; }
.muted { color: #8b949e; }
.accent { color: #ffffff; font-weight: bold; }
.accent2 { color: #58a6ff; }
.title { font-size: 22px; font-weight: bold; }
button {
  background-image: none;
  background-color: #21262d;
  color: #e6edf3;
  border: 1px solid #30363d;
  border-radius: 6px;
  padding: 8px 14px;
}
button:hover { background-color: #30363d; }
button.suggested-action {
  background-image: none;
  background-color: #238636;
  color: #ffffff;
  border-color: #2ea043;
  font-weight: bold;
}
button.suggested-action:hover { background-color: #2ea043; }
button.destructive-action {
  background-image: none;
  background-color: #3d1214;
  color: #f85149;
  border-color: #f85149;
}
headerbar {
  background-image: none;
  background-color: #161b22;
  color: #e6edf3;
  border-bottom: 1px solid #30363d;
}
entry, textview, treeview {
  background-color: #0d1117;
  color: #e6edf3;
  border: 1px solid #30363d;
  border-radius: 4px;
  padding: 6px;
}
/* Strong visual highlight when a row is selected */
treeview:selected,
treeview.view:selected,
.view:selected {
  background-color: #1f6feb;
  color: #ffffff;
}
treeview:selected:focus,
treeview.view:selected:focus {
  background-color: #388bfd;
  color: #ffffff;
}
.flash-alert {
  background-color: #3d1214;
  color: #ffa198;
  font-weight: bold;
  padding: 6px 12px;
}
/* Chat speech bubbles */
.chat-scroll {
  background-color: #0d1117;
}
.bubble-meta {
  color: #ffffff;
  font-size: 11px;
}
.bubble-in {
  background-image: none;
  background-color: #1f6feb;
  color: #ffffff;
  border-radius: 14px;
  padding: 10px 10px;
  border: none;
}
.bubble-out {
  background-image: none;
  background-color: #238636;
  color: #ffffff;
  border-radius: 14px;
  padding: 10px 10px;
  border: none;
}
.bubble-text {
  color: #ffffff;
  font-size: 14px;
}
.bubble-tick {
  color: #ffffff;
  font-size: 11px;
}
"""


def apply_css() -> None:
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(),
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )
