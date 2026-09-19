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

import sys
import random
from dataclasses import dataclass, field
from typing import Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")

from gi.repository import Gtk, Adw, Gio, GLib  # noqa: E402

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
            raise DisplayConfigError(
                "No se pudo conectar a org.gnome.Mutter.DisplayConfig por "
                "DBus. ¿Estás corriendo GNOME Shell / Mutter en esta "
                f"sesión? Detalle: {e}"
            ) from e

        if self._proxy.get_name_owner() is None:
            raise DisplayConfigError(
                "El servicio org.gnome.Mutter.DisplayConfig no tiene owner "
                "en el bus de sesión. Esta app necesita correr dentro de "
                "una sesión de GNOME Shell (Mutter) activa."
            )

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
            raise DisplayConfigError(f"GetCurrentState falló: {e}") from e

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
        """Aplica una config de un solo monitor usando el layout actual
        para el resto (si hay más de uno) y solo cambia el scale del
        monitor elegido."""
        assert self._proxy is not None

        logical_monitors = GLib.Variant(
            "a(iiduba(ssa{sv}))",
            [(
                monitor.current_x,
                monitor.current_y,
                scale,
                monitor.current_transform,
                monitor.is_primary,
                [(monitor.connector, mode_id, {})],
            )],
        )
        properties = GLib.Variant("a{sv}", {})
        args = GLib.Variant(
            "(uua(iiduba(ssa{sv}))a{sv})",
            (serial, method, logical_monitors, properties),
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
            raise DisplayConfigError(f"ApplyMonitorsConfig falló: {e}") from e


def scale_candidates(mode: MonitorMode) -> list[float]:
    """A partir de los scales que reporta Mutter para el modo, arma una
    lista prolija de candidatos (pasos de 0.25, sin duplicados, con el
    100% siempre incluido)."""
    if not mode.supported_scales:
        return [1.0]
    lo = min(mode.supported_scales)
    hi = max(mode.supported_scales)
    candidates = set()
    step = 0.25
    v = round(lo / step) * step
    while v <= hi + 1e-6:
        candidates.add(round(v, 2))
        v += step
    candidates.add(1.0)
    candidates.add(round(mode.preferred_scale, 2))
    return sorted(c for c in candidates if lo - 1e-6 <= c <= hi + 1e-6)


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
            raise DisplayConfigError(
                f"El monitor {monitor.connector} no reporta ningún modo actual"
            )
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


# ---------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------

class ScaleDuelWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application):
        super().__init__(application=app, title="Escalado en duelo")
        self.set_default_size(560, 480)

        self.dc: Optional[MutterDisplayConfig] = None
        self.monitors: dict[str, Monitor] = {}
        self.serial: Optional[int] = None
        self.stage: Optional[ScaleStage] = None
        self.duel: Optional[DuelState] = None
        self._revert_timeout_id: Optional[int] = None

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
        retry = Gtk.Button(label="Reintentar")
        retry.add_css_class("suggested-action")
        retry.connect("clicked", lambda *_: self._load_monitors())
        box.append(retry)
        self.stack.add_named(box, "error")

    def _show_error(self, message: str) -> None:
        self.error_label.set_label(message)
        self.stack.set_visible_child_name("error")

    # -- página de selección de monitor y escalas -------------------------
    def _build_setup_page(self) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18,
                       margin_top=28, margin_bottom=28, margin_start=24, margin_end=24)

        title = Gtk.Label(label="Elegí el monitor y los niveles a comparar")
        title.add_css_class("title-2")
        title.set_halign(Gtk.Align.START)
        box.append(title)

        subtitle = Gtk.Label(
            label="Vamos a aplicar cada escalado de verdad en la pantalla "
                  "(modo prueba, se revierte solo si no confirmás) y vas "
                  "a elegir cuál se ve mejor, en duelos de a dos.",
            wrap=True, xalign=0.0,
        )
        subtitle.add_css_class("dim-label")
        box.append(subtitle)

        self.monitor_group = Adw.PreferencesGroup(title="Monitor")
        self.monitor_row = Adw.ComboRow(title="Pantalla")
        self.monitor_group.add(self.monitor_row)
        box.append(self.monitor_group)

        self.scales_group = Adw.PreferencesGroup(
            title="Niveles de escalado a comparar",
            description="Se arma un bracket de eliminación directa con todos "
                         "los que marques.",
        )
        box.append(self.scales_group)
        self.scale_checks: dict[float, Gtk.CheckButton] = {}

        self.mode_group = Adw.PreferencesGroup(title="Al terminar")
        self.mode_row = Adw.SwitchRow(
            title="Dejar aplicado el ganador",
            subtitle="Si lo apagás, solo te muestro el porcentaje y "
                     "restauro el escalado que tenías antes de abrir la app.",
        )
        self.mode_row.set_active(True)
        self.mode_group.add(self.mode_row)
        box.append(self.mode_group)

        start_btn = Gtk.Button(label="Empezar los duelos")
        start_btn.add_css_class("suggested-action")
        start_btn.add_css_class("pill")
        start_btn.set_halign(Gtk.Align.CENTER)
        start_btn.connect("clicked", self._on_start_clicked)
        box.append(start_btn)

        scroller = Gtk.ScrolledWindow(child=box, vexpand=True)
        self.stack.add_named(scroller, "setup")

    def _load_monitors(self) -> bool:
        self.dc = MutterDisplayConfig()
        try:
            self.dc.connect()
            self.serial, self.monitors = self.dc.get_current_state()
        except DisplayConfigError as e:
            self._show_error(str(e))
            return False

        if not self.monitors:
            self._show_error("Mutter no reportó ningún monitor conectado.")
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

        # limpiar checks anteriores
        for child_row in list(self.scale_checks.values()):
            self.scales_group.remove(child_row.get_parent().get_parent()
                                      if child_row.get_parent() else child_row)
        self.scale_checks.clear()
        # Adw.PreferencesGroup no tiene "clear" directo; reconstruimos el grupo
        parent = self.scales_group.get_parent()
        new_group = Adw.PreferencesGroup(
            title="Niveles de escalado a comparar",
            description="Se arma un bracket de eliminación directa con todos "
                         "los que marques.",
        )
        if parent is not None:
            idx_in_parent = 0
            box = parent
            box.remove(self.scales_group)
            box.insert_child_after(new_group, self.monitor_group)
        self.scales_group = new_group

        candidates = scale_candidates(mode)
        for c in candidates:
            check = Gtk.CheckButton(label=f"{round(c * 100)}%")
            check.set_active(abs(c - monitor.current_scale) < 1e-6 or abs(c - 1.0) < 1e-6)
            self.scales_group.add(check)
            self.scale_checks[c] = check

    def _on_start_clicked(self, _btn) -> None:
        idx = self.monitor_row.get_selected()
        connector = self._monitor_connectors[idx]
        monitor = self.monitors[connector]
        levels = [lvl for lvl, chk in self.scale_checks.items() if chk.get_active()]
        if len(levels) < 2:
            self._toast("Elegí al menos dos niveles de escalado para comparar")
            return

        try:
            self.stage = ScaleStage(self.dc, monitor)
        except DisplayConfigError as e:
            self._toast(str(e))
            return

        self.duel = DuelState(levels)
        self._keep_winner = self.mode_row.get_active()
        self._start_current_match()

    # -- página de duelo ----------------------------------------------------
    def _build_duel_page(self) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16,
                       margin_top=28, margin_bottom=28, margin_start=24, margin_end=24,
                       valign=Gtk.Align.CENTER)

        self.progress_label = Gtk.Label(xalign=0.0)
        self.progress_label.add_css_class("dim-label")
        box.append(self.progress_label)

        info = Gtk.Label(
            label="Mirá la pantalla: acabamos de aplicar el primer nivel. "
                  "Elegí el que se vea mejor.",
            wrap=True, xalign=0.0,
        )
        box.append(info)

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

        replay = Gtk.Button(label="Volver a mostrar ambos (alternar)")
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
            f"Ronda {self.duel.round_num} — enfrentamiento {this_match} de {total}"
        )
        self.btn_a.set_label(f"Elegir {round(match.a * 100)}%")
        self.btn_b.set_label(f"Elegir {round(match.b * 100)}%")
        self._current_match = match
        self._preview_showing_first = True
        self._apply_preview(match.a)
        self.stack.set_visible_child_name("duel")

    def _apply_preview(self, scale: float) -> None:
        try:
            self.stage.try_scale(scale)
        except DisplayConfigError as e:
            self._toast(f"No se pudo aplicar {round(scale*100)}%: {e}")

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
        self.result_pct_label.set_label(f"{round(winner * 100)}%")
        if self._keep_winner:
            try:
                self.stage.confirm(winner)
                self.result_note.set_label(
                    "Se aplicó y quedó guardado como escalado del monitor."
                )
            except DisplayConfigError as e:
                self.result_note.set_label(f"No se pudo dejarlo guardado: {e}")
        else:
            self.stage.restore_original()
            self.result_note.set_label(
                "No se guardó ningún cambio: se restauró el escalado anterior."
            )
        self.stack.set_visible_child_name("result")

    # -- página de resultado -------------------------------------------------
    def _build_result_page(self) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14,
                       valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER,
                       margin_top=40, margin_bottom=40, margin_start=24, margin_end=24)
        title = Gtk.Label(label="Ganador del bracket")
        title.add_css_class("title-2")
        box.append(title)
        self.result_pct_label = Gtk.Label(label="--")
        self.result_pct_label.add_css_class("title-1")
        box.append(self.result_pct_label)
        self.result_note = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        self.result_note.add_css_class("dim-label")
        box.append(self.result_note)
        again = Gtk.Button(label="Repetir con otros niveles")
        again.connect("clicked", lambda *_: self.stack.set_visible_child_name("setup"))
        box.append(again)
        self.stack.add_named(box, "result")

    # -- utilidades ------------------------------------------------------
    def _toast(self, message: str) -> None:
        self.toast_overlay.add_toast(Adw.Toast.new(message))

    def _on_close_request(self, *_args) -> bool:
        # si hay un TEST pendiente sin confirmar, Mutter lo revierte solo
        # (timeout interno). Si querés forzar la restauración explícita
        # antes de que la app se cierre, la dejamos igual: no bloqueamos
        # el cierre.
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
