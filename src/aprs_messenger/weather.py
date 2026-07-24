"""Maidenhead grid → lat/lon and landscape weather widget with scene effects."""

from __future__ import annotations

import json
import logging
import math
import random
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GLib", "2.0")
from gi.repository import GLib, Gtk  # noqa: E402

log = logging.getLogger(__name__)

_WMO = {
    0: ("Clear", "sun"),
    1: ("Mainly clear", "sun_cloud"),
    2: ("Partly cloudy", "sun_cloud"),
    3: ("Overcast", "cloud"),
    45: ("Fog", "fog"),
    48: ("Rime fog", "fog"),
    51: ("Light drizzle", "drizzle"),
    53: ("Drizzle", "drizzle"),
    55: ("Dense drizzle", "rain"),
    61: ("Light rain", "rain"),
    63: ("Rain", "rain"),
    65: ("Heavy rain", "rain_heavy"),
    71: ("Light snow", "snow"),
    73: ("Snow", "snow"),
    75: ("Heavy snow", "snow"),
    80: ("Rain showers", "rain"),
    81: ("Showers", "rain"),
    82: ("Violent showers", "rain_heavy"),
    95: ("Thunderstorm", "storm"),
    96: ("Storm + hail", "storm"),
    99: ("Severe storm", "storm"),
}


def grid_to_latlon(grid: str) -> tuple[float, float]:
    """Center of a 4- or 6-character Maidenhead field/square/subsquare."""
    g = (grid or "").strip().upper()
    if len(g) < 4:
        raise ValueError("Grid too short")
    lon = (ord(g[0]) - ord("A")) * 20 - 180
    lat = (ord(g[1]) - ord("A")) * 10 - 90
    lon += int(g[2]) * 2
    lat += int(g[3]) * 1
    if len(g) >= 6:
        lon += (ord(g[4]) - ord("A")) * (2.0 / 24.0)
        lat += (ord(g[5]) - ord("A")) * (1.0 / 24.0)
        lon += 2.0 / 48.0
        lat += 1.0 / 48.0
    else:
        lon += 1.0
        lat += 0.5
    return lat, lon


def latlon_to_aprs(lat: float, lon: float) -> str:
    """Convert decimal degrees to APRS lat/lon: DDMM.mmN/DDDMM.mmE."""
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    alat = abs(lat)
    alon = abs(lon)
    lat_deg = int(alat)
    lat_min = (alat - lat_deg) * 60.0
    lon_deg = int(alon)
    lon_min = (alon - lon_deg) * 60.0
    return f"{lat_deg:02d}{lat_min:05.2f}{ns}/{lon_deg:03d}{lon_min:05.2f}{ew}"


def wmo_meta(code: int) -> tuple[str, str]:
    """Return (label, scene_kind)."""
    if code in _WMO:
        return _WMO[code]
    for k in sorted(_WMO.keys(), reverse=True):
        if code >= k:
            return _WMO[k]
    return ("Weather", "cloud")


def wmo_label(code: int) -> tuple[str, str]:
    """Compatibility: (emoji_placeholder, label)."""
    label, kind = wmo_meta(code)
    icons = {
        "sun": "☀️",
        "sun_cloud": "⛅",
        "cloud": "☁️",
        "fog": "🌫️",
        "drizzle": "🌦️",
        "rain": "🌧️",
        "rain_heavy": "🌧️",
        "snow": "🌨️",
        "storm": "⛈️",
    }
    return icons.get(kind, "🌡️"), label


@dataclass
class DayForecast:
    date: str
    t_max: float
    t_min: float
    precip: float
    weathercode: int
    wind_max: float = 0.0

    @property
    def weekday(self) -> str:
        try:
            d = datetime.strptime(self.date, "%Y-%m-%d")
            return d.strftime("%a")
        except ValueError:
            return self.date

    @property
    def day_num(self) -> str:
        try:
            d = datetime.strptime(self.date, "%Y-%m-%d")
            return d.strftime("%-d %b")
        except ValueError:
            return self.date

    @property
    def icon_label(self) -> tuple[str, str]:
        return wmo_label(int(self.weathercode))

    @property
    def scene(self) -> str:
        return wmo_meta(int(self.weathercode))[1]


def fetch_3day_forecast(lat: float, lon: float, timeout: float = 12.0) -> list[DayForecast]:
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat:.4f}&longitude={lon:.4f}"
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,"
        "weathercode,windspeed_10m_max"
        "&timezone=auto&forecast_days=3"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "APRS-Messenger/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    daily = data.get("daily") or {}
    dates = daily.get("time") or []
    out: list[DayForecast] = []
    for i, date in enumerate(dates[:3]):
        out.append(
            DayForecast(
                date=date,
                t_max=float((daily.get("temperature_2m_max") or [0])[i]),
                t_min=float((daily.get("temperature_2m_min") or [0])[i]),
                precip=float((daily.get("precipitation_sum") or [0])[i] or 0),
                weathercode=int((daily.get("weathercode") or [0])[i] or 0),
                wind_max=float((daily.get("windspeed_10m_max") or [0])[i] or 0),
            )
        )
    return out


class WeatherChart(Gtk.Box):
    """Landscape weather widget with animated sun / cloud / rain scenes."""

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.set_halign(Gtk.Align.CENTER)
        self.set_hexpand(True)
        self.set_margin_start(12)
        self.set_margin_end(12)
        self.set_margin_top(4)
        self.set_margin_bottom(12)

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._title = Gtk.Label(label="⛅  Local Weather")
        self._title.get_style_context().add_class("title")
        self._title.set_xalign(0)
        head.pack_start(self._title, True, True, 0)
        self._status = Gtk.Label(label="")
        self._status.get_style_context().add_class("muted")
        head.pack_end(self._status, False, False, 0)
        self.pack_start(head, False, False, 0)

        frame = Gtk.Frame()
        frame.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
        self._screen = Gtk.DrawingArea()
        # Landscape phone / tablet aspect
        self._screen.set_size_request(720, 280)
        self._screen.set_hexpand(True)
        self._screen.connect("draw", self._on_draw)
        frame.add(self._screen)
        self.pack_start(frame, True, True, 0)

        self._days: list[DayForecast] = []
        self._grid = ""
        self._latlon: Optional[tuple[float, float]] = None
        self._error = ""
        self._loading = False
        self._t0 = time.time()
        self._rain: list[tuple[float, float, float, float]] = []
        self._snow: list[tuple[float, float, float, float]] = []
        self._cloud_seed = random.Random(42)
        self._anim_id = GLib.timeout_add(40, self._tick_anim)  # ~25 fps

    def destroy(self):
        if self._anim_id:
            GLib.source_remove(self._anim_id)
            self._anim_id = 0
        super().destroy()

    def _tick_anim(self) -> bool:
        if self.get_mapped() and (self._days or self._loading):
            self._screen.queue_draw()
        return True

    def set_grid(self, grid: str) -> None:
        grid = (grid or "").strip().upper()
        if grid == self._grid and (self._days or self._error):
            return
        self._grid = grid
        if not grid:
            self._days = []
            self._error = "Set your Maidenhead grid on login"
            self._status.set_text("")
            self._screen.queue_draw()
            return
        try:
            self._latlon = grid_to_latlon(grid)
        except ValueError:
            self._days = []
            self._error = f"Invalid grid: {grid}"
            self._screen.queue_draw()
            return
        self._loading = True
        self._error = ""
        self._status.set_text(f"Updating {grid}…")
        self._screen.queue_draw()
        lat, lon = self._latlon
        threading.Thread(
            target=self._fetch_thread,
            args=(grid, lat, lon),
            name="wx-fetch",
            daemon=True,
        ).start()

    def refresh(self) -> None:
        g = self._grid
        self._grid = ""
        self.set_grid(g)

    def _fetch_thread(self, grid: str, lat: float, lon: float) -> None:
        try:
            days = fetch_3day_forecast(lat, lon)
            err = ""
        except (
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
            KeyError,
            IndexError,
            ValueError,
        ) as e:
            days = []
            err = "Offline / unavailable"
            log.warning("weather fetch failed: %s", e)

        def apply():
            if self._grid != grid:
                return False
            self._days = days
            self._error = err
            self._loading = False
            if days:
                self._status.set_text(f"Grid {grid}  ·  {lat:.2f}°, {lon:.2f}°")
                self._seed_particles(days[0].scene)
            else:
                self._status.set_text(err or "No data")
            self._screen.queue_draw()
            return False

        GLib.idle_add(apply)

    def _seed_particles(self, scene: str) -> None:
        rng = random.Random(hash(self._grid) & 0xFFFF)
        self._rain = []
        self._snow = []
        n = 0
        if scene in ("drizzle",):
            n = 40
        elif scene in ("rain",):
            n = 70
        elif scene in ("rain_heavy", "storm"):
            n = 110
        for _ in range(n):
            self._rain.append(
                (rng.random(), rng.random(), 0.4 + rng.random() * 0.8, 0.6 + rng.random())
            )
        if scene == "snow":
            for _ in range(55):
                self._snow.append(
                    (rng.random(), rng.random(), 0.3 + rng.random() * 0.5, 0.5 + rng.random())
                )

    # ── drawing helpers ───────────────────────────────────
    @staticmethod
    def _round_rect(cr, x, y, w, h, r):
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()

    @staticmethod
    def _text(cr, x, y, text, size, rgba, center=False, right=False):
        if len(rgba) == 3:
            cr.set_source_rgb(*rgba)
        else:
            cr.set_source_rgba(*rgba)
        cr.select_font_face("Sans", 0, 1)
        cr.set_font_size(size)
        ext = cr.text_extents(str(text))
        tx = x
        if center:
            tx = x - ext.width / 2 - ext.x_bearing
        elif right:
            tx = x - ext.width - ext.x_bearing
        cr.move_to(tx, y)
        cr.show_text(str(text))

    def _draw_sun(self, cr, cx, cy, r, t, bright=True):
        import cairo

        # Rays
        cr.save()
        cr.translate(cx, cy)
        cr.rotate(t * 0.35)
        n_rays = 12
        for i in range(n_rays):
            a = (2 * math.pi * i) / n_rays
            cr.save()
            cr.rotate(a)
            cr.set_source_rgba(1.0, 0.85, 0.25, 0.35 if bright else 0.2)
            cr.move_to(r * 0.55, -3)
            cr.line_to(r * 1.15, 0)
            cr.line_to(r * 0.55, 3)
            cr.close_path()
            cr.fill()
            cr.restore()
        cr.restore()

        # Core glow
        rg = cairo.RadialGradient(cx, cy, r * 0.2, cx, cy, r * 1.1)
        rg.add_color_stop_rgba(0, 1.0, 0.98, 0.7, 1.0)
        rg.add_color_stop_rgba(0.45, 1.0, 0.8, 0.2, 0.95)
        rg.add_color_stop_rgba(1, 1.0, 0.6, 0.1, 0.0)
        cr.set_source(rg)
        cr.arc(cx, cy, r * 1.1, 0, 2 * math.pi)
        cr.fill()

        # Disk
        cr.set_source_rgb(1.0, 0.9, 0.35)
        cr.arc(cx, cy, r * 0.48, 0, 2 * math.pi)
        cr.fill()
        cr.set_source_rgba(1, 1, 1, 0.35)
        cr.arc(cx - r * 0.12, cy - r * 0.12, r * 0.18, 0, 2 * math.pi)
        cr.fill()

    def _draw_cloud(self, cr, cx, cy, scale, alpha=0.92, gray=0.95):
        cr.set_source_rgba(gray, gray, gray + 0.02, alpha)
        # puffs
        for dx, dy, s in (
            (-28, 4, 1.0),
            (-8, -10, 1.25),
            (14, -6, 1.15),
            (32, 6, 0.95),
            (0, 8, 1.1),
        ):
            cr.arc(cx + dx * scale, cy + dy * scale, 18 * s * scale, 0, 2 * math.pi)
            cr.fill()
        # soft shadow under cloud
        cr.set_source_rgba(0.2, 0.25, 0.35, 0.12 * alpha)
        cr.save()
        cr.translate(cx, cy + 22 * scale)
        cr.scale(1.0, 0.35)
        cr.arc(0, 0, 40 * scale, 0, 2 * math.pi)
        cr.fill()
        cr.restore()

    def _draw_rain(self, cr, x0, y0, w, h, t, heavy=False):
        cr.set_line_width(1.6 if heavy else 1.2)
        for px, py, spd, length in self._rain:
            # fall + slight wind
            y = (py + t * spd * 0.55) % 1.0
            x = (px + t * 0.08 * spd) % 1.0
            sx = x0 + x * w
            sy = y0 + y * h
            ln = (10 if heavy else 7) * length
            cr.set_source_rgba(0.7, 0.85, 1.0, 0.35 + 0.35 * spd)
            cr.move_to(sx, sy)
            cr.line_to(sx - 2, sy + ln)
            cr.stroke()

    def _draw_snow(self, cr, x0, y0, w, h, t):
        for px, py, spd, size in self._snow:
            y = (py + t * spd * 0.18) % 1.0
            x = (px + math.sin(t * 1.2 + px * 10) * 0.03 + t * 0.02) % 1.0
            sx = x0 + x * w
            sy = y0 + y * h
            r = 1.5 + size * 2.0
            cr.set_source_rgba(1, 1, 1, 0.75)
            cr.arc(sx, sy, r, 0, 2 * math.pi)
            cr.fill()

    def _draw_lightning(self, cr, cx, cy, t):
        # flash every ~3s
        phase = (t * 1.7) % 3.0
        if phase > 0.12:
            return
        alpha = 0.55 * (1.0 - phase / 0.12)
        cr.set_source_rgba(1, 1, 0.85, alpha)
        cr.set_line_width(2.5)
        cr.move_to(cx, cy - 30)
        cr.line_to(cx - 8, cy)
        cr.line_to(cx + 4, cy)
        cr.line_to(cx - 10, cy + 40)
        cr.stroke()
        # sky flash
        cr.set_source_rgba(1, 1, 1, alpha * 0.12)
        cr.paint()

    def _draw_fog(self, cr, x0, y0, w, h, t):
        for i in range(5):
            y = y0 + h * (0.25 + i * 0.12)
            offset = math.sin(t * 0.4 + i) * 20
            cr.set_source_rgba(0.85, 0.9, 0.95, 0.12 + i * 0.03)
            self._round_rect(cr, x0 + 10 + offset, y, w - 40, 14, 7)
            cr.fill()

    def _scene_colors(self, scene: str) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        if scene == "sun":
            return (0.25, 0.55, 0.95), (0.55, 0.8, 1.0)
        if scene == "sun_cloud":
            return (0.3, 0.5, 0.8), (0.55, 0.7, 0.9)
        if scene == "cloud":
            return (0.35, 0.42, 0.52), (0.55, 0.6, 0.68)
        if scene in ("drizzle", "rain"):
            return (0.22, 0.3, 0.42), (0.4, 0.48, 0.58)
        if scene in ("rain_heavy", "storm"):
            return (0.12, 0.14, 0.22), (0.28, 0.3, 0.4)
        if scene == "snow":
            return (0.45, 0.55, 0.7), (0.75, 0.82, 0.92)
        if scene == "fog":
            return (0.5, 0.55, 0.6), (0.7, 0.72, 0.75)
        return (0.2, 0.35, 0.6), (0.4, 0.55, 0.8)

    def _on_draw(self, widget: Gtk.DrawingArea, cr) -> bool:
        import cairo

        alloc = widget.get_allocation()
        w, h = float(alloc.width), float(alloc.height)
        t = time.time() - self._t0

        # Outer landscape phone body
        cr.set_source_rgb(0.07, 0.08, 0.1)
        self._round_rect(cr, 0, 0, w, h, 22)
        cr.fill()

        m = 8.0
        sx, sy = m, m
        sw, sh = w - 2 * m, h - 2 * m

        scene = self._days[0].scene if self._days else "cloud"
        top, bot = self._scene_colors(scene)

        lg = cairo.LinearGradient(0, sy, 0, sy + sh)
        lg.add_color_stop_rgb(0, *top)
        lg.add_color_stop_rgb(1, *bot)
        cr.set_source(lg)
        self._round_rect(cr, sx, sy, sw, sh, 16)
        cr.fill()

        # Clip scene to screen
        cr.save()
        self._round_rect(cr, sx, sy, sw, sh, 16)
        cr.clip()

        # Landscape layout: left 55% scene art, right 45% forecast panel
        split = sx + sw * 0.55
        scene_w = split - sx
        scene_h = sh

        if self._loading and not self._days:
            self._text(cr, w / 2, h / 2, "Updating forecast…", 16, (1, 1, 1), center=True)
            cr.restore()
            return False
        if self._error and not self._days:
            self._text(cr, w / 2, h / 2 - 8, self._error, 14, (1, 0.85, 0.8), center=True)
            self._text(cr, w / 2, h / 2 + 16, "Check network connection", 12, (0.9, 0.95, 1), center=True)
            cr.restore()
            return False
        if not self._days:
            self._text(cr, w / 2, h / 2, "Log in with your grid for weather", 14, (1, 1, 1), center=True)
            cr.restore()
            return False

        today = self._days[0]
        label, _ = wmo_meta(today.weathercode)

        # ── animated scene (left) ──
        if scene in ("sun", "sun_cloud"):
            self._draw_sun(cr, sx + scene_w * 0.35, sy + scene_h * 0.38, 52, t, bright=True)
        if scene in ("sun_cloud", "cloud", "drizzle", "rain", "rain_heavy", "storm", "fog", "snow"):
            # drifting clouds
            drift = t * 12
            for i, (bx, by, sc, gray) in enumerate(
                (
                    (0.15, 0.28, 1.1, 0.97),
                    (0.48, 0.22, 0.95, 0.9),
                    (0.72, 0.35, 1.2, 0.88),
                    (0.35, 0.48, 0.85, 0.92),
                )
            ):
                if scene == "sun" and i > 0:
                    continue
                if scene == "sun_cloud" and i > 2:
                    continue
                cx = sx + ((bx * scene_w + drift * (0.4 + i * 0.15)) % (scene_w + 80)) - 40
                cy = sy + by * scene_h
                g = gray if scene not in ("storm", "rain_heavy") else 0.55
                a = 0.9 if scene != "fog" else 0.5
                self._draw_cloud(cr, cx, cy, sc * 0.9, alpha=a, gray=g)

        if scene in ("drizzle", "rain", "rain_heavy", "storm"):
            self._draw_rain(
                cr,
                sx,
                sy + 40,
                scene_w,
                scene_h - 50,
                t,
                heavy=scene in ("rain_heavy", "storm"),
            )
        if scene == "snow":
            self._draw_snow(cr, sx, sy + 30, scene_w, scene_h - 40, t)
        if scene == "fog":
            self._draw_fog(cr, sx, sy, scene_w, scene_h, t)
        if scene == "storm":
            self._draw_lightning(cr, sx + scene_w * 0.55, sy + 70, t)

        # Ground hill silhouette
        cr.set_source_rgba(0.05, 0.12, 0.1, 0.35)
        cr.move_to(sx, sy + sh)
        cr.curve_to(
            sx + scene_w * 0.25,
            sy + sh - 40,
            sx + scene_w * 0.5,
            sy + sh - 18,
            sx + scene_w,
            sy + sh - 50,
        )
        cr.line_to(sx + scene_w, sy + sh)
        cr.close_path()
        cr.fill()

        # Today summary overlay on scene
        self._text(cr, sx + 20, sy + 28, self._grid or "—", 13, (1, 1, 1, 0.85))
        self._text(cr, sx + 20, sy + 70, f"{today.t_max:.0f}°", 42, (1, 1, 1))
        self._text(cr, sx + 20, sy + 94, label, 14, (1, 1, 1, 0.9))
        self._text(
            cr,
            sx + 20,
            sy + 116,
            f"H {today.t_max:.0f}°  ·  L {today.t_min:.0f}°  ·  💧 {today.precip:.1f} mm",
            12,
            (1, 1, 1, 0.75),
        )

        # ── right forecast panel (landscape) ──
        panel_x = split + 6
        panel_w = sx + sw - panel_x - 10
        panel_y = sy + 12
        panel_h = sh - 24
        cr.set_source_rgba(0.05, 0.08, 0.14, 0.45)
        self._round_rect(cr, panel_x, panel_y, panel_w, panel_h, 14)
        cr.fill()
        cr.set_source_rgba(1, 1, 1, 0.1)
        cr.set_line_width(1)
        self._round_rect(cr, panel_x, panel_y, panel_w, panel_h, 14)
        cr.stroke()

        self._text(cr, panel_x + 14, panel_y + 22, "3-DAY FORECAST", 11, (1, 1, 1, 0.6))

        n = len(self._days)
        col_w = panel_w / max(n, 1)
        for i, d in enumerate(self._days):
            x = panel_x + col_w * (i + 0.5)
            if i == 0:
                cr.set_source_rgba(1, 1, 1, 0.08)
                self._round_rect(
                    cr, panel_x + col_w * i + 6, panel_y + 32, col_w - 12, panel_h - 48, 10
                )
                cr.fill()

            # mini scene icon per day
            mini_scene = d.scene
            icon_y = panel_y + 78
            if mini_scene in ("sun", "sun_cloud"):
                self._draw_sun(cr, x, icon_y, 16, t + i, bright=True)
            if mini_scene in ("sun_cloud", "cloud", "fog", "drizzle", "rain", "rain_heavy", "storm", "snow"):
                g = 0.6 if mini_scene in ("storm", "rain_heavy") else 0.95
                self._draw_cloud(cr, x + 6, icon_y + 4, 0.45, alpha=0.9, gray=g)
            if mini_scene in ("rain", "rain_heavy", "drizzle", "storm"):
                cr.set_source_rgba(0.7, 0.85, 1.0, 0.7)
                cr.set_line_width(1.2)
                for k in range(3):
                    cr.move_to(x - 6 + k * 6, icon_y + 14)
                    cr.line_to(x - 8 + k * 6, icon_y + 24)
                    cr.stroke()

            self._text(cr, x, panel_y + 52, d.weekday.upper(), 12, (1, 1, 1, 0.8), center=True)
            self._text(cr, x, panel_y + 120, f"{d.t_max:.0f}°", 18, (1, 1, 1), center=True)
            self._text(cr, x, panel_y + 140, f"{d.t_min:.0f}°", 13, (1, 1, 1, 0.65), center=True)
            self._text(cr, x, panel_y + 162, f"💧{d.precip:.0f}mm", 11, (0.75, 0.9, 1.0), center=True)
            self._text(
                cr,
                x,
                panel_y + 182,
                wmo_meta(d.weathercode)[0][:12],
                10,
                (1, 1, 1, 0.55),
                center=True,
            )

        cr.restore()

        # Landscape home bar (side-ish bottom center)
        cr.set_source_rgba(1, 1, 1, 0.3)
        self._round_rect(cr, w / 2 - 36, h - m - 6, 72, 3.5, 2)
        cr.fill()
        return False
