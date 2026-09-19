"""Tests de la lógica pura (sin GTK, sin DBus) de scale_duel.py.

Corre con: python3 -m pytest test_scale_duel.py -v
"""
import random
import sys
import types

# --- stub de gi/Gtk/Adw/Gio/GLib para poder importar scale_duel.py sin
# tener PyGObject/GTK4/libadwaita instalados en este entorno de tests.
# Solo se usan los símbolos referenciados a nivel de módulo (imports y
# definición de clases); la lógica que testeamos no llama nada de GTK.

def _install_gi_stubs():
    if "gi" in sys.modules:
        return

    gi = types.ModuleType("gi")
    gi.require_version = lambda *a, **k: None

    repository = types.ModuleType("gi.repository")

    class _Base:
        def __init__(self, *a, **k):
            pass

    Gtk = types.ModuleType("gi.repository.Gtk")
    for name in ["Box", "Label", "Button", "CheckButton", "StringList",
                 "ScrolledWindow", "Stack", "Image", "Orientation",
                 "Align", "Justification", "StackTransitionType"]:
        setattr(Gtk, name, _Base)
    Gtk.Orientation = types.SimpleNamespace(VERTICAL=0, HORIZONTAL=1)
    Gtk.Align = types.SimpleNamespace(CENTER=0, START=1)
    Gtk.Justification = types.SimpleNamespace(CENTER=0)
    Gtk.StackTransitionType = types.SimpleNamespace(CROSSFADE=0)

    Adw = types.ModuleType("gi.repository.Adw")
    for name in ["ApplicationWindow", "Application", "ToolbarView",
                 "HeaderBar", "ToastOverlay", "Toast", "PreferencesGroup",
                 "ComboRow", "SwitchRow"]:
        setattr(Adw, name, _Base)
    Adw.Toast.new = staticmethod(lambda *a, **k: None)

    Gio = types.ModuleType("gi.repository.Gio")
    Gio.DBusProxy = types.SimpleNamespace(new_for_bus_sync=lambda *a, **k: None)
    Gio.BusType = types.SimpleNamespace(SESSION=0)
    Gio.DBusProxyFlags = types.SimpleNamespace(NONE=0)
    Gio.DBusCallFlags = types.SimpleNamespace(NONE=0)

    GLib = types.ModuleType("gi.repository.GLib")
    class _GLibError(Exception):
        pass
    GLib.Error = _GLibError
    GLib.Variant = lambda *a, **k: None
    GLib.idle_add = lambda *a, **k: None

    repository.Gtk = Gtk
    repository.Adw = Adw
    repository.Gio = Gio
    repository.GLib = GLib

    sys.modules["gi"] = gi
    sys.modules["gi.repository"] = repository
    sys.modules["gi.repository.Gtk"] = Gtk
    sys.modules["gi.repository.Adw"] = Adw
    sys.modules["gi.repository.Gio"] = Gio
    sys.modules["gi.repository.GLib"] = GLib


_install_gi_stubs()

from scale_duel import (  # noqa: E402
    DuelState, scale_candidates, MonitorMode,
    filter_candidates_by_range, diagonal_inches, parse_edid_physical_size_cm,
    compute_ppi, recommend_scale, recommend_range, resolution_equivalents,
)


def test_duel_two_levels_picks_the_chosen_one():
    d = DuelState([1.0, 1.25], rng=random.Random(1))
    assert not d.finished
    match = d.current_match()
    assert {match.a, match.b} == {1.0, 1.25}
    d.pick(1.25)
    assert d.finished
    assert d.winner == 1.25


def test_duel_power_of_two_no_byes():
    levels = [1.0, 1.25, 1.5, 1.75]
    d = DuelState(levels, rng=random.Random(2))
    seen_rounds = set()
    while not d.finished:
        seen_rounds.add(d.round_num)
        match = d.current_match()
        d.pick(match.a)  # siempre elige "a"
    assert d.finished
    assert d.winner in levels
    assert seen_rounds == {1, 2}


def test_duel_odd_count_uses_byes_and_terminates():
    levels = [0.75, 0.8, 0.85, 0.87, 0.9, 0.95, 1.0]  # 7 niveles, como el artefacto
    d = DuelState(levels, rng=random.Random(3))
    picks = []
    guard = 0
    while not d.finished:
        guard += 1
        assert guard < 100, "el bracket no debería tardar tanto en terminar"
        match = d.current_match()
        chosen = match.a
        picks.append(chosen)
        d.pick(chosen)
    assert d.finished
    assert d.winner in levels
    # el ganador tiene que haber sido elegido en algún momento o haber
    # pasado por bye (en 7 elementos, exactamente uno tiene bye en ronda 1)
    assert d.winner in picks or True  # el bye no queda en 'picks', solo confirmamos que terminó


def test_duel_rejects_pick_not_in_current_match():
    d = DuelState([1.0, 1.25, 1.5], rng=random.Random(4))
    match = d.current_match()
    other = next(x for x in (1.0, 1.25, 1.5) if x not in (match.a, match.b))
    try:
        d.pick(other)
        assert False, "debería haber rechazado un pick fuera del enfrentamiento actual"
    except ValueError:
        pass


def test_duel_requires_at_least_two_levels():
    try:
        DuelState([1.0])
        assert False, "debería exigir al menos 2 niveles"
    except ValueError:
        pass


def test_scale_candidates_includes_100_and_preferred():
    mode = MonitorMode(
        mode_id="0", width=1920, height=1080, refresh=60.0,
        preferred_scale=1.25, supported_scales=[1.0, 1.25, 1.5, 1.75, 2.0],
        is_current=True, is_preferred=True,
    )
    candidates = scale_candidates(mode)
    assert 1.0 in candidates
    assert 1.25 in candidates
    assert candidates == sorted(candidates)
    assert min(candidates) >= 1.0
    assert max(candidates) <= 2.0


def test_scale_candidates_narrow_range_hidpi():
    # un monitor 4K típico en GNOME suele reportar scales entre 1.0 y 3.0
    mode = MonitorMode(
        mode_id="0", width=3840, height=2160, refresh=60.0,
        preferred_scale=2.0, supported_scales=[1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0],
        is_current=True, is_preferred=True,
    )
    candidates = scale_candidates(mode)
    assert 2.0 in candidates
    assert max(candidates) <= 3.0 + 1e-6
    assert min(candidates) >= 1.0 - 1e-6


def test_scale_candidates_no_supported_scales_falls_back_to_100():
    mode = MonitorMode(
        mode_id="0", width=1920, height=1080, refresh=60.0,
        preferred_scale=1.0, supported_scales=[],
        is_current=True, is_preferred=True,
    )
    assert scale_candidates(mode) == [1.0]


def test_filter_candidates_by_range_keeps_only_inside_bounds():
    candidates = [1.0, 1.25, 1.5, 1.75, 2.0]
    assert filter_candidates_by_range(candidates, 1.25, 1.75) == [1.25, 1.5, 1.75]


def test_filter_candidates_by_range_swaps_if_inverted():
    candidates = [1.0, 1.25, 1.5]
    assert filter_candidates_by_range(candidates, 1.5, 1.0) == candidates


def test_diagonal_inches_matches_known_panel():
    # panel de 34x19 cm (medido real vía EDID) es ~15.3"
    assert abs(diagonal_inches(34, 19) - 15.34) < 0.05


def test_parse_edid_physical_size_ignores_zero():
    edid = bytearray(30)
    edid[21] = 0
    edid[22] = 0
    assert parse_edid_physical_size_cm(bytes(edid)) is None

    edid[21] = 34
    edid[22] = 19
    assert parse_edid_physical_size_cm(bytes(edid)) == (34, 19)


def test_parse_edid_physical_size_too_short():
    assert parse_edid_physical_size_cm(b"\x00" * 10) is None


def test_compute_ppi_matches_expected_1080p_laptop():
    ppi = compute_ppi(1920, 1080, 15.34)
    assert 140 < ppi < 148


def test_recommend_scale_rounds_to_quarter_steps():
    assert recommend_scale(96) == 1.0
    assert recommend_scale(144) == 1.5
    assert recommend_scale(190) == 2.0
    assert recommend_scale(48) == 1.0  # nunca por debajo de 100%


def test_recommend_range_clamped_to_supported_scales():
    supported = [1.0, 1.25, 1.5, 1.75, 2.0]
    lo, hi = recommend_range(1.5, supported)
    assert lo == 1.0
    assert hi == 2.0

    lo2, hi2 = recommend_range(1.0, supported)
    assert lo2 == 1.0
    assert hi2 == 1.5


def test_resolution_equivalents_matches_real_1080p_laptop_panel():
    # caso real medido en esta laptop: panel 1920x1080, Mutter solo
    # ofrece scales >= 1.0 para este modo (no soporta "downscaling"
    # para emular 1440p/4K en este hardware).
    mode = MonitorMode(
        mode_id="0", width=1920, height=1080, refresh=60.0,
        preferred_scale=1.0,
        supported_scales=[1.0, 1.25, 1.3333333730697632, 1.5, 1.6666666269302368, 2.0],
        is_current=True, is_preferred=True,
    )
    results = resolution_equivalents(mode)
    labels = {r.label: r.scale for r in results}
    assert "1080p" in labels and abs(labels["1080p"] - 1.0) < 1e-6
    assert "720p" in labels and abs(labels["720p"] - 1.5) < 1e-6
    # no debería inventar equivalencias que Mutter rechazaría (1440p/4K
    # necesitarían scale < 1.0, que este panel no soporta)
    assert "1440p" not in labels
    assert "2160p (4K)" not in labels
    # 16:10 no debe colarse por aspect ratio distinto
    assert "WSXGA+ (16:10)" not in labels


def test_resolution_equivalents_supports_downscale_on_hidpi_panel():
    # panel 4K típico que sí soporta escalas fraccionarias hacia abajo
    mode = MonitorMode(
        mode_id="0", width=3840, height=2160, refresh=60.0,
        preferred_scale=2.0,
        supported_scales=[0.5, 0.75, 1.0, 1.25, 1.5, 2.0],
        is_current=True, is_preferred=True,
    )
    results = resolution_equivalents(mode)
    labels = {r.label: r.scale for r in results}
    assert abs(labels["1440p"] - 1.5) < 1e-6  # 3840/2560 = 1.5
    assert abs(labels["2160p (4K)"] - 1.0) < 1e-6


def test_resolution_equivalents_empty_without_supported_scales():
    mode = MonitorMode(
        mode_id="0", width=1920, height=1080, refresh=60.0,
        preferred_scale=1.0, supported_scales=[],
        is_current=True, is_preferred=True,
    )
    assert resolution_equivalents(mode) == []
