#!/usr/bin/env python3
"""
gnome-scale-duel
=================

App GTK4 / libadwaita para GNOME en Wayland que te deja comparar dos
niveles de escalado ("scale") de un monitor, uno contra el otro, en
vivo -- igual que el bracket de eliminación del artefacto original,
pero aplicando el escalado de verdad en tu pantalla en lugar de un
zoom CSS.

Cómo escala de verdad
----------------------
GNOME/Mutter en Wayland no expone el "scale" fraccional por xrandr:
lo maneja el compositor a través de la interfaz DBus
``org.gnome.Mutter.DisplayConfig`` (servicio ``org.gnome.Mutter``,
objeto ``/org/gnome/Mutter/DisplayConfig``). Esta app:

1. Llama a ``GetCurrentState`` para leer los monitores conectados,
   sus modos disponibles y qué "scale" soporta cada modo.
2. Arma una lista de "candidatos" de escalado dentro del rango que
   Mutter permite para el monitor elegido (normalmente pasos de
   0.25 entre 1.0 y el máximo que declare el modo).
3. Para cada duelo, llama a ``ApplyMonitorsConfig`` en modo
   ``ApplyMode.TEST`` (valor 2) con un timeout corto: la pantalla
   cambia de escala al toque, y si en unos segundos no confirmás con
   ``ConfirmDisplayConfigChange`` (o volvés a aplicar sobre ella),
   Mutter la revierte solo. Así nunca podés quedarte con una pantalla
   rota o sin poder ver el botón para deshacer.
4. El ganador final se aplica en modo ``ApplyMode.PERSISTENT``
   (valor 1) recién cuando vos lo confirmás explícitamente desde la
   pantalla de resultado; si preferís, podés "solo ver el número" y
   dejar la pantalla como estaba antes de abrir la app.

Requisitos (Arch / paquetes típicos de GNOME):
    sudo pacman -S python-gobject gtk4 libadwaita

Uso:
    python3 scale_duel.py

La app tiene que correr *dentro* de tu sesión gráfica real (no en un
contenedor ni en una VM sin acceso al bus de sesión), porque necesita
DBUS_SESSION_BUS_ADDRESS apuntando a tu sesión de GNOME.
"""
from __future__ import annotations

import glob
import math
import os
import random
import re
import sys
from dataclasses import dataclass, field
from typing import Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")

from gi.repository import Gtk, Adw, Gio, GLib  # noqa: E402

from i18n import t  # noqa: E402

APP_ID = "org.eibu.GnomeScaleDuel"
DISPLAY_CONFIG_BUS_NAME = "org.gnome.Mutter.DisplayConfig"
DISPLAY_CONFIG_OBJECT_PATH = "/org/gnome/Mutter/DisplayConfig"
DISPLAY_CONFIG_IFACE = "org.gnome.Mutter.DisplayConfig"

# ApplyMode de Mutter (org.gnome.Mutter.DisplayConfig.ApplyMonitorsConfig)
APPLY_MODE_VERIFY = 0      # solo valida, no cambia nada
APPLY_MODE_TEST = 2        # aplica temporal, revierte solo si no se confirma
APPLY_MODE_PERSISTENT = 1  # aplica y guarda

# Cuánto le decimos a Mutter que espere antes de revertir un TEST si no
# llega la confirmación (Mutter tiene su propio timeout interno de ~20s
# para ApplyMode.TEST; nosotros confirmamos o revertimos bastante antes).
TEST_REVERT_SECONDS = 20


class DisplayConfigError(RuntimeError):
    pass


@dataclass
class MonitorMode:
    mode_id: str
    width: int
    height: int
    refresh: float
    preferred_scale: float
    supported_scales: list[float]
    is_current: bool
    is_preferred: bool


@dataclass
class Monitor:
    connector: str
    vendor: str
    product: str
    serial: str
    modes: list[MonitorMode] = field(default_factory=list)
    current_x: int = 0
    current_y: int = 0
    current_scale: float = 1.0
    current_transform: int = 0
    is_primary: bool = False

    @property
    def label(self) -> str:
        vp = f"{self.vendor} {self.product}".strip()
        return f"{self.connector} — {vp}" if vp and vp != " " else self.connector

    @property
    def current_mode(self) -> Optional[MonitorMode]:
        for m in self.modes:
            if m.is_current:
                return m
        # si ninguno está marcado current (raro), usamos el preferido
        for m in self.modes:
            if m.is_preferred:
                return m
        return self.modes[0] if self.modes else None


class MutterDisplayConfig:
    """Envoltorio fino sobre org.gnome.Mutter.DisplayConfig por GDBus."""

    def __init__(self):
        self._proxy: Optional[Gio.DBusProxy] = None

    def connect(self) -> None:
        try:
            self._proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION,
                Gio.DBusProxyFlags.NONE,
                None,
                DISPLAY_CONFIG_BUS_NAME,
                DISPLAY_CONFIG_OBJECT_PATH,
                DISPLAY_CONFIG_IFACE,
                None,
            )
        except GLib.Error as e:
            raise DisplayConfigError(t("err_dbus_connect", detail=e)) from e

        if self._proxy.get_name_owner() is None:
            raise DisplayConfigError(t("err_no_owner"))

    def get_current_state(self):
        """Devuelve (serial, monitores) leyendo GetCurrentState."""
        assert self._proxy is not None
        try:
            result = self._proxy.call_sync(
                "GetCurrentState",
                None,
                Gio.DBusCallFlags.NONE,
                -1,
                None,
            )
        except GLib.Error as e:
            raise DisplayConfigError(t("err_get_state", detail=e)) from e

        serial, monitors_v, logical_v, _properties = result.unpack()
        monitors: dict[str, Monitor] = {}

        for mon in monitors_v:
            mon_spec, modes_v, _mon_props = mon
            connector, vendor, product, serial_str = mon_spec
            monitor = Monitor(
                connector=connector, vendor=vendor, product=product,
                serial=serial_str,
            )
            for mode in modes_v:
                (mode_id, width, height, refresh, pref_scale,
                 supported_scales, mode_props) = mode
                is_current = bool(mode_props.get("is-current", False))
                is_preferred = bool(mode_props.get("is-preferred", False))
                monitor.modes.append(MonitorMode(
                    mode_id=mode_id, width=width, height=height,
                    refresh=refresh, preferred_scale=pref_scale,
                    supported_scales=list(supported_scales),
                    is_current=is_current, is_preferred=is_preferred,
                ))
            monitors[connector] = monitor

        for logical in logical_v:
            (x, y, scale, transform, is_primary,
             logical_monitors, _logical_props) = logical
            for lm_connector, lm_vendor, lm_product, lm_serial in logical_monitors:
                mon = monitors.get(lm_connector)
                if mon is not None:
                    mon.current_x = x
                    mon.current_y = y
                    mon.current_scale = scale
                    mon.current_transform = transform
                    mon.is_primary = is_primary

        return serial, monitors

    def apply_monitors_config(
        self,
        serial: int,
        method: int,
        monitor: Monitor,
        mode_id: str,
        scale: float,
    ) -> None:
        """Envía sólo el monitor elegido; no preserva el layout completo.

        Mutter 50.4 y 50.5 clasifican los monitores conectados omitidos como
        deshabilitados. La preservación multi-monitor no está implementada.
        """
        assert self._proxy is not None

        logical_monitors = [(
            monitor.current_x,
            monitor.current_y,
            scale,
            monitor.current_transform,
            monitor.is_primary,
            [(monitor.connector, mode_id, {})],
        )]
        args = GLib.Variant(
            "(uua(iiduba(ssa{sv}))a{sv})",
            (serial, method, logical_monitors, {}),
        )
        try:
            self._proxy.call_sync(
                "ApplyMonitorsConfig",
                args,
                Gio.DBusCallFlags.NONE,
                -1,
                None,
            )
        except GLib.Error as e:
            raise DisplayConfigError(t("err_apply_config", detail=e)) from e


def scale_candidates(mode: MonitorMode) -> list[float]:
    """Candidatos exactos anunciados por Mutter, ordenados y sin duplicados.

    No interpola, redondea ni agrega escalas por defecto: una lista de
    supported_scales vacía no permite ofrecer ningún candidato.
    """
    return sorted(set(mode.supported_scales))


def filter_candidates_by_range(candidates: list[float], lo: float, hi: float) -> list[float]:
    """Recorta la lista de candidatos a los que caen dentro de [lo, hi]
    (el rango que el usuario definió como piso y techo del duelo)."""
    if lo > hi:
        lo, hi = hi, lo
    return [c for c in candidates if lo - 1e-6 <= c <= hi + 1e-6]


def diagonal_inches(width_cm: float, height_cm: float) -> float:
    """Diagonal en pulgadas a partir del tamaño físico (en cm) que
    reporta el EDID del panel."""
    return math.hypot(width_cm, height_cm) / 2.54


def parse_edid_physical_size_cm(edid_bytes: bytes) -> Optional[tuple[int, int]]:
    """Tamaño físico (ancho_cm, alto_cm) declarado en el EDID (offsets
    21/22), o None si el EDID es muy corto o no lo declara (0x0, típico
    de proyectores o EDIDs sintéticos)."""
    if len(edid_bytes) < 23:
        return None
    width_cm, height_cm = edid_bytes[21], edid_bytes[22]
    if width_cm == 0 or height_cm == 0:
        return None
    return width_cm, height_cm


def find_edid_sysfs_path(connector: str) -> Optional[str]:
    """Busca el archivo EDID en /sys/class/drm para el connector que
    reporta Mutter (p.ej. 'eDP-1'), que en sysfs aparece con un
    prefijo 'cardN-' que hay que descartar."""
    for path in glob.glob("/sys/class/drm/*/edid"):
        dirname = os.path.basename(os.path.dirname(path))
        suffix = re.sub(r"^card\d+-", "", dirname)
        if suffix == connector:
            return path
    return None


def detect_diagonal_inches(connector: str) -> Optional[float]:
    """Intenta leer el tamaño físico real del panel vía EDID (sysfs).
    Devuelve None si no se pudo (sin permisos, EDID vacío/sin tamaño,
    monitor externo sin esa info, etc.) y en ese caso el usuario tiene
    que ingresar la diagonal a mano."""
    path = find_edid_sysfs_path(connector)
    if path is None:
        return None
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    size = parse_edid_physical_size_cm(data)
    if size is None:
        return None
    return round(diagonal_inches(*size), 2)


def compute_ppi(width_px: int, height_px: int, diagonal_in: float) -> float:
    """Pixeles por pulgada a partir de la resolución y la diagonal
    física del panel."""
    if diagonal_in <= 0:
        return 0.0
    return math.hypot(width_px, height_px) / diagonal_in


def recommend_scale(ppi: float) -> float:
    """Escala 'natural' recomendada al estilo GNOME: ppi/96 redondeado
    a pasos de 0.25, nunca por debajo de 100%."""
    if ppi <= 0:
        return 1.0
    raw = ppi / 96.0
    step = 0.25
    val = round(raw / step) * step
    return max(1.0, round(val, 2))


def recommend_range(recommended: float, supported_scales: list[float]) -> tuple[float, float]:
    """Rango sugerido de escalado a comparar: +/-0.5 alrededor de la
    escala recomendada, recortado a lo que el monitor soporta de
    verdad según Mutter."""
    if not supported_scales:
        return (recommended, recommended)
    lo_bound = min(supported_scales)
    hi_bound = max(supported_scales)
    lo = max(lo_bound, round(recommended - 0.5, 2))
    hi = min(hi_bound, round(recommended + 0.5, 2))
    if lo > hi:
        lo = hi = max(lo_bound, min(recommended, hi_bound))
    return (lo, hi)


# Resoluciones "de catálogo" conocidas, para el modo de equivalencia. No
# hace falta que estén ordenadas; se filtran por aspect ratio y se
# ordenan por escala resultante al calcularlas.
COMMON_RESOLUTIONS: list[tuple[int, int, str]] = [
    (1280, 720, "720p"),
    (1366, 768, "768p"),
    (1600, 900, "900p"),
    (1920, 1080, "1080p"),
    (2560, 1440, "1440p"),
    (3200, 1800, "1800p"),
    (3840, 2160, "2160p (4K)"),
    (1024, 768, "768p (4:3)"),
    (1280, 1024, "SXGA (5:4)"),
    (1680, 1050, "WSXGA+ (16:10)"),
    (1920, 1200, "WUXGA (16:10)"),
    (2560, 1600, "WQXGA (16:10)"),
]


TEXT_SCALING_FACTOR_BOUNDS = (0.5, 3.0)  # límites reales del esquema GSettings


def text_scale_candidates(lo: float, hi: float, step: float = 0.05) -> list[float]:
    """Candidatos de densidad de texto/UI (org.gnome.desktop.interface
    text-scaling-factor) entre lo y hi, en pasos de `step`, recortados
    al rango que acepta el esquema GSettings (a diferencia del scale de
    Mutter, acá cualquier valor del rango es válido -- no hay una lista
    de "soportados" que consultar)."""
    if lo > hi:
        lo, hi = hi, lo
    bound_lo, bound_hi = TEXT_SCALING_FACTOR_BOUNDS
    lo = max(bound_lo, lo)
    hi = min(bound_hi, hi)
    if lo > hi:
        return []
    candidates = set()
    v = round(lo / step) * step
    while v <= hi + 1e-9:
        candidates.add(round(v, 2))
        v += step
    candidates.add(round(lo, 2))
    candidates.add(round(hi, 2))
    if lo - 1e-9 <= 1.0 <= hi + 1e-9:
        candidates.add(1.0)
    return sorted(c for c in candidates if lo - 1e-6 <= c <= hi + 1e-6)


@dataclass
class ResolutionEquivalent:
    scale: float
    target_width: int
    target_height: int
    label: str


def resolution_equivalents(
    mode: MonitorMode,
    aspect_tol: float = 0.02,
    scale_tol_rel: float = 0.03,
) -> list[ResolutionEquivalent]:
    """De la lista de resoluciones conocidas, devuelve solo las que
    tienen el mismo aspect ratio que el modo actual Y cuya escala
    "ideal" (para lograr esa resolución lógica) cae cerca de un scale
    que Mutter realmente soporta para este modo -- nunca se propone un
    valor que Mutter vaya a rechazar."""
    if not mode.supported_scales or mode.height == 0:
        return []
    native_aspect = mode.width / mode.height
    seen_scales: set[float] = set()
    out: list[ResolutionEquivalent] = []
    for width, height, label in COMMON_RESOLUTIONS:
        if height == 0:
            continue
        aspect = width / height
        if abs(aspect - native_aspect) > aspect_tol * native_aspect:
            continue
        ideal_scale = mode.width / width
        nearest = min(mode.supported_scales, key=lambda s: abs(s - ideal_scale))
        if abs(nearest - ideal_scale) > scale_tol_rel * ideal_scale:
            continue
        key = round(nearest, 3)
        if key in seen_scales:
            continue
        seen_scales.add(key)
        out.append(ResolutionEquivalent(
            scale=nearest, target_width=width, target_height=height, label=label,
        ))
    out.sort(key=lambda r: r.scale)
    return out


@dataclass
class ResolutionTarget:
    label: str
    target_width: int
    target_height: int
    ideal_scale: float
    achievable_scale: Optional[float]

    @property
    def achievable(self) -> bool:
        return self.achievable_scale is not None


def resolution_targets(
    mode: MonitorMode,
    aspect_tol: float = 0.02,
    scale_tol_rel: float = 0.03,
) -> list[ResolutionTarget]:
    """Como resolution_equivalents(), pero devuelve TODAS las
    resoluciones de catálogo con el mismo aspect ratio -- incluidas las
    que este monitor no puede lograr -- para que la UI pueda mostrarle
    al usuario el espectro completo y por qué algunas están bloqueadas
    (Mutter las rechaza para este modo/panel)."""
    if mode.height == 0:
        return []
    native_aspect = mode.width / mode.height
    out: list[ResolutionTarget] = []
    for width, height, label in COMMON_RESOLUTIONS:
        if height == 0:
            continue
        aspect = width / height
        if abs(aspect - native_aspect) > aspect_tol * native_aspect:
            continue
        ideal_scale = mode.width / width
        achievable_scale = None
        if mode.supported_scales:
            nearest = min(mode.supported_scales, key=lambda s: abs(s - ideal_scale))
            if abs(nearest - ideal_scale) <= scale_tol_rel * ideal_scale:
                achievable_scale = nearest
        out.append(ResolutionTarget(
            label=label, target_width=width, target_height=height,
            ideal_scale=ideal_scale, achievable_scale=achievable_scale,
        ))
    out.sort(key=lambda r: r.ideal_scale)
    return out


def letter_for_index(index: int) -> str:
    """A, B, C, ..., Z, AA, AB, ... (para no quedarse sin letras si
    algún día hay más de 26 candidatos)."""
    n = index + 1
    letters = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


ROUND_NAME_KEYS = {
    1: "round_final",
    2: "round_semifinal",
    4: "round_quarterfinal",
    8: "round_roundof16",
}


def round_name(matches_in_round: int) -> str:
    """Nombre de ronda al estilo de un cuadro de eliminación directa de
    fútbol, según cuántos enfrentamientos tiene la ronda actual."""
    key = ROUND_NAME_KEYS.get(matches_in_round)
    if key:
        return t(key)
    return t("round_generic", n=matches_in_round * 2)


@dataclass
class Match:
    a: float
    b: float


class DuelState:
    """Lógica del bracket de eliminación directa, separada de la UI para
    poder testearla sin GTK."""

    def __init__(self, levels: list[float], rng: Optional[random.Random] = None):
        if len(levels) < 2:
            raise ValueError("Hacen falta al menos 2 niveles de escalado")
        self._rng = rng or random.Random()
        # las letras se asignan sobre un orden barajado (no el orden en
        # que vienen los niveles, que suele estar ordenado de menor a
        # mayor escala) para que "A" no sea siempre el más bajo y "H" el
        # más alto -- eso delataría el valor real sin mostrarlo. Cada
        # candidato mantiene su letra a lo largo de todo el torneo.
        shuffled_for_labels = self._shuffle(levels)
        self.labels: dict[float, str] = {
            level: letter_for_index(i) for i, level in enumerate(shuffled_for_labels)
        }
        self.round_list: list[float] = self._shuffle(levels)
        self.round_num = 1
        self.match_index = 0
        self.next_round: list[float] = []
        self.finished = False
        self.winner: Optional[float] = None
        self._advance_byes()

    def _shuffle(self, levels: list[float]) -> list[float]:
        out = list(levels)
        self._rng.shuffle(out)
        return out

    def _advance_byes(self) -> None:
        while len(self.round_list) - self.match_index == 1 and len(self.round_list) > 1:
            self.next_round.append(self.round_list[self.match_index])
            self.match_index += 1
        if self.match_index >= len(self.round_list):
            if len(self.next_round) <= 1:
                self.finished = True
                self.winner = self.next_round[0] if self.next_round else self.round_list[0]
                return
            self.round_list = self.next_round
            self.next_round = []
            self.match_index = 0
            self.round_num += 1
            self._advance_byes()

    def current_match(self) -> Optional[Match]:
        if self.finished:
            return None
        a = self.round_list[self.match_index]
        b = self.round_list[self.match_index + 1]
        return Match(a=a, b=b)

    def progress(self) -> tuple[int, int]:
        """(número de enfrentamiento actual, total de enfrentamientos en la ronda)"""
        total = len(self.round_list) // 2
        this_match = self.match_index // 2 + 1
        return this_match, total

    def pick(self, level: float) -> None:
        if self.finished:
            return
        match = self.current_match()
        assert match is not None
        if level not in (match.a, match.b):
            raise ValueError("Ese nivel no es parte del enfrentamiento actual")
        self.next_round.append(level)
        self.match_index += 2
        self._advance_byes()


class ScaleStage:
    """Maneja el ciclo aplicar-en-TEST / confirmar / revertir contra
    Mutter para un monitor dado."""

    def __init__(self, dc: MutterDisplayConfig, monitor: Monitor):
        self.dc = dc
        self.monitor = monitor
        self._original_scale = monitor.current_scale
        self._mode = monitor.current_mode
        if self._mode is None:
            raise DisplayConfigError(t("err_no_current_mode", connector=monitor.connector))
        self._pending = False

    def try_scale(self, scale: float) -> None:
        """Aplica `scale` en modo TEST. Si ya había un TEST pendiente sin
        confirmar, Mutter lo reemplaza por este (no hace falta revertir
        antes)."""
        serial, _monitors = self.dc.get_current_state()
        self.dc.apply_monitors_config(
            serial, APPLY_MODE_TEST, self.monitor, self._mode.mode_id, scale,
        )
        self._pending = True

    def confirm(self, scale: float) -> None:
        """Aplica `scale` en modo PERSISTENT (la queda guardada)."""
        serial, _monitors = self.dc.get_current_state()
        self.dc.apply_monitors_config(
            serial, APPLY_MODE_PERSISTENT, self.monitor, self._mode.mode_id, scale,
        )
        self._pending = False

    def restore_original(self) -> None:
        """Vuelve al scale que estaba antes de abrir la app."""
        try:
            serial, _monitors = self.dc.get_current_state()
            self.dc.apply_monitors_config(
                serial, APPLY_MODE_PERSISTENT, self.monitor, self._mode.mode_id,
                self._original_scale,
            )
        except DisplayConfigError:
            pass
        self._pending = False


TEXT_SCALING_SCHEMA = "org.gnome.desktop.interface"
TEXT_SCALING_KEY = "text-scaling-factor"

# Cuánto esperar sin confirmación antes de revertir un preview de texto
# solo (Mutter tiene su propio timeout para el TEST real; acá lo
# imitamos a mano porque GSettings no revierte nada por su cuenta).
TEXT_REVERT_SECONDS = 20


class TextScaleStage:
    """Mismo ciclo try/confirm/restore que ScaleStage, pero para
    org.gnome.desktop.interface text-scaling-factor -- no cambia la
    resolución real, solo la densidad de texto/UI (Xft DPI), y por eso
    acepta cualquier valor continuo del rango sin que el compositor lo
    rechace. Muchas apps (GTK, Electron como VSCode, Firefox) escalan
    su UI en proporción a esto, aunque el framebuffer no cambie."""

    def __init__(self):
        self._settings = Gio.Settings.new(TEXT_SCALING_SCHEMA)
        self._original_value = self._settings.get_double(TEXT_SCALING_KEY)
        self._pending = False

    def try_scale(self, scale: float) -> None:
        self._settings.set_double(TEXT_SCALING_KEY, scale)
        self._pending = True

    def confirm(self, scale: float) -> None:
        self._settings.set_double(TEXT_SCALING_KEY, scale)
        self._pending = False

    def restore_original(self) -> None:
        self._settings.set_double(TEXT_SCALING_KEY, self._original_value)
        self._pending = False


# ---------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------

class ScaleDuelWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application):
        super().__init__(application=app, title=t("window_title"))
        self.set_default_size(560, 480)

        self.dc: Optional[MutterDisplayConfig] = None
        self.monitors: dict[str, Monitor] = {}
        self.serial: Optional[int] = None
        self.stage: Optional[ScaleStage] = None
        self.duel: Optional[DuelState] = None
        self._revert_timeout_id: Optional[int] = None
        self._current_candidates: list[float] = []
        self._diagonal_source_detected = False
        self._winner_scale: Optional[float] = None

        self.toolbar_view = Adw.ToolbarView()
        self.set_content(self.toolbar_view)
        self.header = Adw.HeaderBar()
        self.toolbar_view.add_top_bar(self.header)

        self.toast_overlay = Adw.ToastOverlay()
        self.toolbar_view.set_content(self.toast_overlay)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.toast_overlay.set_child(self.stack)

        self._build_setup_page()
        self._build_duel_page()
        self._build_result_page()
        self._build_error_page()

        self.connect("close-request", self._on_close_request)
        GLib.idle_add(self._load_monitors)

    # -- página de errores ------------------------------------------------
    def _build_error_page(self) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                       valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER,
                       margin_top=40, margin_bottom=40, margin_start=24, margin_end=24)
        icon = Gtk.Image.new_from_icon_name("dialog-error-symbolic")
        icon.set_pixel_size(48)
        box.append(icon)
        self.error_label = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        self.error_label.add_css_class("title-3")
        box.append(self.error_label)
        retry = Gtk.Button(label=t("retry_button"))
        retry.add_css_class("suggested-action")
        retry.connect("clicked", lambda *_: self._load_monitors())
        box.append(retry)
        self.stack.add_named(box, "error")

    def _show_error(self, message: str) -> None:
        self.error_label.set_label(message)
        self.stack.set_visible_child_name("error")

    # -- página de selección de monitor y rango de escalado ----------------
    def _build_setup_page(self) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18,
                       margin_top=28, margin_bottom=28, margin_start=24, margin_end=24)

        title = Gtk.Label(label=t("setup_title"))
        title.add_css_class("title-2")
        title.set_halign(Gtk.Align.START)
        box.append(title)

        subtitle = Gtk.Label(label=t("setup_subtitle"), wrap=True, xalign=0.0)
        subtitle.add_css_class("dim-label")
        box.append(subtitle)

        self.monitor_group = Adw.PreferencesGroup(title=t("group_monitor"))
        self.monitor_row = Adw.ComboRow(title=t("combo_screen"))
        self.monitor_group.add(self.monitor_row)
        box.append(self.monitor_group)

        self.mechanism_group = Adw.PreferencesGroup(
            title=t("group_mechanism"),
            description=t("mechanism_description"),
        )
        box.append(self.mechanism_group)
        self.mech_radio_display = Gtk.CheckButton(label=t("mech_display_label"))
        self.mech_radio_display.set_active(True)
        self.mech_radio_display.connect("toggled", self._on_mechanism_changed)
        self.mechanism_group.add(self.mech_radio_display)
        self.mech_radio_text = Gtk.CheckButton(label=t("mech_text_label"))
        self.mech_radio_text.set_group(self.mech_radio_display)
        self.mechanism_group.add(self.mech_radio_text)

        self.mode_choice_group = Adw.PreferencesGroup(title=t("group_compare_mode"))
        box.append(self.mode_choice_group)
        self.mode_radio_size = Gtk.CheckButton(label=t("mode_size_label"))
        self.mode_radio_size.set_active(True)
        self.mode_radio_size.connect("toggled", self._on_compare_mode_changed)
        self.mode_choice_group.add(self.mode_radio_size)
        self.mode_radio_equiv = Gtk.CheckButton(label=t("mode_equiv_label"))
        self.mode_radio_equiv.set_group(self.mode_radio_size)
        self.mode_choice_group.add(self.mode_radio_equiv)

        self.detect_group = Adw.PreferencesGroup(
            title=t("group_detect"),
            description=t("detect_description"),
        )
        box.append(self.detect_group)
        self.diagonal_row = Adw.SpinRow.new_with_range(5.0, 100.0, 0.1)
        self.diagonal_row.set_title(t("diagonal_title"))
        self.diagonal_row.set_digits(1)
        self.diagonal_row.connect("notify::value", lambda *_: self._on_diagonal_changed())
        self.detect_group.add(self.diagonal_row)
        self.detect_label = Gtk.Label(wrap=True, xalign=0.0)
        self.detect_label.add_css_class("dim-label")
        self.detect_group.add(self.detect_label)

        self.range_group = Adw.PreferencesGroup(
            title=t("group_range"),
            description=t("range_description"),
        )
        box.append(self.range_group)
        self.min_row = Adw.SpinRow.new_with_range(50, 400, 5)
        self.min_row.set_title(t("min_pct"))
        self.range_group.add(self.min_row)
        self.max_row = Adw.SpinRow.new_with_range(50, 400, 5)
        self.max_row.set_title(t("max_pct"))
        self.range_group.add(self.max_row)

        self.equiv_group = Adw.PreferencesGroup(
            title=t("group_equiv"),
            description=t("equiv_description"),
        )
        self.equiv_group.set_visible(False)
        box.append(self.equiv_group)
        self.equiv_checks: dict[float, Gtk.CheckButton] = {}
        self._equiv_rows: list[Gtk.CheckButton] = []
        self.equiv_empty_label = Gtk.Label(label=t("equiv_empty"), wrap=True, xalign=0.0)
        self.equiv_empty_label.add_css_class("dim-label")
        self.equiv_empty_label.set_visible(False)
        self.equiv_group.add(self.equiv_empty_label)

        self.text_range_group = Adw.PreferencesGroup(
            title=t("group_text_range"),
            description=t("text_range_description"),
        )
        self.text_range_group.set_visible(False)
        box.append(self.text_range_group)
        self.text_min_row = Adw.SpinRow.new_with_range(50, 300, 5)
        self.text_min_row.set_title(t("min_pct"))
        self.text_min_row.set_value(75)
        self.text_range_group.add(self.text_min_row)
        self.text_max_row = Adw.SpinRow.new_with_range(50, 300, 5)
        self.text_max_row.set_title(t("max_pct"))
        self.text_max_row.set_value(100)
        self.text_range_group.add(self.text_max_row)

        start_btn = Gtk.Button(label=t("start_button"))
        start_btn.add_css_class("suggested-action")
        start_btn.add_css_class("pill")
        start_btn.set_halign(Gtk.Align.CENTER)
        start_btn.connect("clicked", self._on_start_clicked)
        box.append(start_btn)

        scroller = Gtk.ScrolledWindow(child=box, vexpand=True)
        self.stack.add_named(scroller, "setup")

    def _on_mechanism_changed(self, _btn) -> None:
        display_mode = self.mech_radio_display.get_active()
        self.mode_choice_group.set_visible(display_mode)
        self.text_range_group.set_visible(not display_mode)
        if display_mode:
            self._on_compare_mode_changed(None)
        else:
            self.detect_group.set_visible(False)
            self.range_group.set_visible(False)
            self.equiv_group.set_visible(False)

    def _load_monitors(self) -> bool:
        self.dc = MutterDisplayConfig()
        try:
            self.dc.connect()
            self.serial, self.monitors = self.dc.get_current_state()
        except DisplayConfigError as e:
            self._show_error(str(e))
            return False

        if not self.monitors:
            self._show_error(t("err_no_monitors"))
            return False

        model = Gtk.StringList()
        connectors = []
        for connector, mon in self.monitors.items():
            model.append(mon.label)
            connectors.append(connector)
        self._monitor_connectors = connectors
        self.monitor_row.set_model(model)
        self.monitor_row.set_selected(0)
        self.monitor_row.connect("notify::selected", self._on_monitor_changed)
        self._on_monitor_changed(self.monitor_row, None)

        self.stack.set_visible_child_name("setup")
        return False

    def _on_monitor_changed(self, row: Adw.ComboRow, _param) -> None:
        idx = row.get_selected()
        if idx < 0 or idx >= len(self._monitor_connectors):
            return
        connector = self._monitor_connectors[idx]
        monitor = self.monitors[connector]
        mode = monitor.current_mode
        if mode is None:
            return

        self._current_candidates = scale_candidates(mode)
        detected = detect_diagonal_inches(connector)
        self._diagonal_source_detected = detected is not None
        self.diagonal_row.set_value(detected if detected is not None else 15.6)
        self._recompute_recommendation()
        self._rebuild_equiv_group(mode)

    def _on_compare_mode_changed(self, _btn) -> None:
        size_mode = self.mode_radio_size.get_active()
        self.detect_group.set_visible(size_mode)
        self.range_group.set_visible(size_mode)
        self.equiv_group.set_visible(not size_mode)

    def _rebuild_equiv_group(self, mode: MonitorMode) -> None:
        for check in list(self._equiv_rows):
            self.equiv_group.remove(check)
        self._equiv_rows = []
        self.equiv_checks.clear()

        targets = resolution_targets(mode)
        self.equiv_empty_label.set_visible(not targets)
        for target in targets:
            if target.achievable:
                check = Gtk.CheckButton(label=t(
                    "equiv_check_label", label=target.label,
                    w=target.target_width, h=target.target_height,
                    pct=round(target.achievable_scale * 100),
                ))
                check.set_active(abs(target.achievable_scale - 1.0) < 1e-6)
                self.equiv_checks[target.achievable_scale] = check
            else:
                check = Gtk.CheckButton(label=t(
                    "equiv_check_unavailable", label=target.label,
                    w=target.target_width, h=target.target_height,
                    pct=round(target.ideal_scale * 100),
                ))
                check.set_sensitive(False)
            self.equiv_group.add(check)
            self._equiv_rows.append(check)

    def _on_diagonal_changed(self) -> None:
        self._diagonal_source_detected = False
        self._recompute_recommendation()

    def _recompute_recommendation(self) -> None:
        idx = self.monitor_row.get_selected()
        if idx < 0 or idx >= len(getattr(self, "_monitor_connectors", [])):
            return
        connector = self._monitor_connectors[idx]
        monitor = self.monitors[connector]
        mode = monitor.current_mode
        if mode is None:
            return

        diagonal = self.diagonal_row.get_value()
        ppi = compute_ppi(mode.width, mode.height, diagonal)
        rec = recommend_scale(ppi)
        lo, hi = recommend_range(rec, self._current_candidates or mode.supported_scales)

        origin = t("origin_edid") if self._diagonal_source_detected else t("origin_manual")
        self.detect_label.set_label(t(
            "detect_label_text", w=mode.width, h=mode.height, origin=origin,
            diagonal=diagonal, ppi=ppi, rec_pct=round(rec * 100),
            lo_pct=round(lo * 100), hi_pct=round(hi * 100),
        ))
        self.min_row.set_value(round(lo * 100))
        self.max_row.set_value(round(hi * 100))

    def _on_start_clicked(self, _btn) -> None:
        if self.mech_radio_text.get_active():
            lo = self.text_min_row.get_value() / 100.0
            hi = self.text_max_row.get_value() / 100.0
            levels = text_scale_candidates(lo, hi)
            if len(levels) < 2:
                self._toast(t("toast_text_range_narrow"))
                return
            self.stage = TextScaleStage()
            self.duel = DuelState(levels)
            self._start_current_match()
            return

        idx = self.monitor_row.get_selected()
        connector = self._monitor_connectors[idx]
        monitor = self.monitors[connector]

        if self.mode_radio_size.get_active():
            lo = self.min_row.get_value() / 100.0
            hi = self.max_row.get_value() / 100.0
            levels = filter_candidates_by_range(self._current_candidates, lo, hi)
            if len(levels) < 2:
                self._toast(t("toast_range_narrow"))
                return
        else:
            levels = [lvl for lvl, chk in self.equiv_checks.items() if chk.get_active()]
            if len(levels) < 2:
                self._toast(t("toast_need_two_equiv"))
                return

        try:
            self.stage = ScaleStage(self.dc, monitor)
        except DisplayConfigError as e:
            self._toast(str(e))
            return

        self.duel = DuelState(levels)
        self._start_current_match()

    # -- página de duelo ----------------------------------------------------
    def _build_duel_page(self) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16,
                       margin_top=28, margin_bottom=28, margin_start=24, margin_end=24,
                       valign=Gtk.Align.CENTER)

        self.progress_label = Gtk.Label(xalign=0.0)
        self.progress_label.add_css_class("dim-label")
        box.append(self.progress_label)

        self.showing_label = Gtk.Label(wrap=True, xalign=0.0)
        box.append(self.showing_label)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12,
                           homogeneous=True)
        self.btn_a = Gtk.Button()
        self.btn_a.add_css_class("pill")
        self.btn_a.connect("clicked", lambda *_: self._on_pick(0))
        buttons.append(self.btn_a)

        self.btn_b = Gtk.Button()
        self.btn_b.add_css_class("pill")
        self.btn_b.connect("clicked", lambda *_: self._on_pick(1))
        buttons.append(self.btn_b)
        box.append(buttons)

        replay = Gtk.Button(label=t("replay_button"))
        replay.connect("clicked", lambda *_: self._toggle_preview())
        box.append(replay)

        self.stack.add_named(box, "duel")
        self._preview_showing_first = True

    def _start_current_match(self) -> None:
        assert self.duel is not None
        match = self.duel.current_match()
        if match is None:
            self._finish_duel()
            return
        this_match, total = self.duel.progress()
        self.progress_label.set_label(
            t("match_progress", round=round_name(total), this=this_match, total=total)
        )
        self._current_match = match
        self._preview_showing_first = True
        self.btn_a.set_label(t("choose_button", letter=self.duel.labels[match.a]))
        self.btn_b.set_label(t("choose_button", letter=self.duel.labels[match.b]))
        self._apply_preview(match.a)
        self.stack.set_visible_child_name("duel")

    def _apply_preview(self, scale: float) -> None:
        letter = self.duel.labels.get(scale, "?")
        try:
            self.stage.try_scale(scale)
            self.showing_label.set_label(t("showing_now", letter=letter))
        except DisplayConfigError as e:
            self._toast(t("toast_apply_failed", letter=letter, detail=e))

    def _toggle_preview(self) -> None:
        match = self._current_match
        self._preview_showing_first = not self._preview_showing_first
        self._apply_preview(match.a if self._preview_showing_first else match.b)

    def _on_pick(self, which: int) -> None:
        match = self._current_match
        level = match.a if which == 0 else match.b
        # dejamos aplicado el elegido mientras seguimos, así el próximo
        # duelo compara "contra el actual campeón" visualmente
        self._apply_preview(level)
        self.duel.pick(level)
        self._start_current_match()

    def _finish_duel(self) -> None:
        assert self.duel is not None and self.duel.winner is not None
        winner = self.duel.winner
        self._winner_scale = winner
        # el ganador queda aplicado en modo TEST (ya lo estaba, del último
        # duelo) mientras el usuario decide si lo confirma o lo descarta
        self.result_pct_label.set_label(f"{round(winner * 100)}%")
        self.result_note.set_label(t("result_note_initial"))
        self.stack.set_visible_child_name("result")

    def _lock_decision_buttons(self) -> None:
        for btn in self._decision_buttons:
            btn.set_sensitive(False)
        self.again_btn.set_sensitive(False)

    def _unlock_decision_buttons(self) -> None:
        for btn in self._decision_buttons:
            btn.set_sensitive(True)
        self.again_btn.set_sensitive(True)

    def _confirm_dialog(self, heading: str, body: str, accept_label: str, on_accept) -> None:
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("cancel", t("dialog_cancel"))
        dialog.add_response("accept", accept_label)
        dialog.set_response_appearance("accept", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("accept")
        dialog.set_close_response("cancel")

        def _on_response(_dlg, response_id):
            self._unlock_decision_buttons()
            if response_id == "accept":
                on_accept()

        dialog.connect("response", _on_response)
        self._lock_decision_buttons()
        dialog.present(self)

    def _on_apply_winner(self, _btn) -> None:
        what = (t("what_text") if isinstance(self.stage, TextScaleStage)
                else t("what_display"))

        def do_apply():
            try:
                self.stage.confirm(self._winner_scale)
                self.result_note.set_label(t("result_note_applied", what=what))
            except DisplayConfigError as e:
                self.result_note.set_label(t("result_note_apply_failed", detail=e))
                return
            self.close()

        self._confirm_dialog(
            heading=t("apply_dialog_heading"),
            body=t("apply_dialog_body", pct=round(self._winner_scale * 100), what=what),
            accept_label=t("apply_dialog_accept"),
            on_accept=do_apply,
        )

    def _on_discard_winner(self, _btn) -> None:
        def do_discard():
            self.stage.restore_original()
            self.result_note.set_label(t("result_note_discarded"))
            self.close()

        self._confirm_dialog(
            heading=t("discard_dialog_heading"),
            body=t("discard_dialog_body"),
            accept_label=t("discard_dialog_accept"),
            on_accept=do_discard,
        )

    # -- página de resultado -------------------------------------------------
    def _build_result_page(self) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14,
                       valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER,
                       margin_top=40, margin_bottom=40, margin_start=24, margin_end=24)
        title = Gtk.Label(label=t("result_title"))
        title.add_css_class("title-2")
        box.append(title)
        self.result_pct_label = Gtk.Label(label="--")
        self.result_pct_label.add_css_class("title-1")
        box.append(self.result_pct_label)
        self.result_note = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        self.result_note.add_css_class("dim-label")
        box.append(self.result_note)

        decision = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12,
                            homogeneous=True, halign=Gtk.Align.CENTER)
        apply_btn = Gtk.Button(label=t("apply_button"))
        apply_btn.add_css_class("suggested-action")
        apply_btn.add_css_class("pill")
        apply_btn.connect("clicked", self._on_apply_winner)
        decision.append(apply_btn)
        discard_btn = Gtk.Button(label=t("discard_button"))
        discard_btn.add_css_class("pill")
        discard_btn.connect("clicked", self._on_discard_winner)
        decision.append(discard_btn)
        box.append(decision)
        self._decision_buttons = [apply_btn, discard_btn]

        self.again_btn = Gtk.Button(label=t("again_button"))
        self.again_btn.connect(
            "clicked", lambda *_: self.stack.set_visible_child_name("setup")
        )
        box.append(self.again_btn)
        self.stack.add_named(box, "result")

    # -- utilidades ------------------------------------------------------
    def _toast(self, message: str) -> None:
        self.toast_overlay.add_toast(Adw.Toast.new(message))

    def _on_close_request(self, *_args) -> bool:
        # si hay un TEST de Mutter pendiente sin confirmar, el propio
        # compositor lo revierte solo (timeout interno). GSettings no
        # tiene ese mecanismo, así que si cerramos con un preview de
        # texto/UI sin confirmar, lo revertimos nosotros a mano.
        if isinstance(self.stage, TextScaleStage) and self.stage._pending:
            self.stage.restore_original()
        return False


class ScaleDuelApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_activate(self) -> None:
        win = self.props.active_window
        if not win:
            win = ScaleDuelWindow(self)
        win.present()


def main() -> int:
    app = ScaleDuelApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
