"""
Minimal i18n for gnome-scale-duel.

English is the default language. Spanish is used automatically when the
system locale is any Spanish variant (es_AR, es_ES, es_MX, ...). No GTK
dependency here on purpose, so this module can be imported and unit
tested without a display server.

To add another language:
1. Copy the "en" dict below into a new top-level key (e.g. "fr") and
   translate every value. Keep the same keys and the same `{placeholder}`
   names -- they get filled in with `.format(...)`.
2. Add a short prefix check in `detect_lang()` (e.g. locale starting
   with "fr" -> "fr").
3. Run `python3 test_scale_duel.py`-style checks (see test_i18n.py) to
   confirm every key that "en" has is also present in your language.

Pull requests for new languages are very welcome -- you don't need to
translate everything at once, missing keys silently fall back to
English (see `t()` below).
"""
from __future__ import annotations

import os
from typing import Optional

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        # -- errors (DisplayConfig / DBus) --
        "err_dbus_connect": (
            "Could not connect to org.gnome.Mutter.DisplayConfig over "
            "DBus. Are you running GNOME Shell / Mutter in this session? "
            "Detail: {detail}"
        ),
        "err_no_owner": (
            "The org.gnome.Mutter.DisplayConfig service has no owner on "
            "the session bus. This app needs to run inside an active "
            "GNOME Shell (Mutter) session."
        ),
        "err_get_state": "GetCurrentState failed: {detail}",
        "err_apply_config": "ApplyMonitorsConfig failed: {detail}",
        "err_no_current_mode": "Monitor {connector} doesn't report any current mode",
        "err_no_monitors": "Mutter didn't report any connected monitor.",

        # -- window / general --
        "window_title": "Scale Duel",
        "retry_button": "Retry",

        # -- setup page --
        "setup_title": "Choose the monitor and the range to compare",
        "setup_subtitle": (
            "Define the floor and ceiling of the scale to test. We'll "
            "build a blind bracket between those values -- you won't see "
            "the real percentage until the end, only which one looks "
            "better. Then you decide whether to apply it or discard it."
        ),
        "group_monitor": "Monitor",
        "combo_screen": "Screen",
        "group_mechanism": "Mechanism",
        "mechanism_description": (
            "Mutter's real scaling can be blocked by the monitor for "
            "certain ranges (some panels won't accept going below 100%). "
            "Text/UI density has no such limit, but it only affects apps "
            "that respect the system's font density (GTK, Electron like "
            "VSCode, Firefox), not the real resolution."
        ),
        "mech_display_label": "Real monitor scaling (Mutter)",
        "mech_text_label": "Text/UI size (works with VSCode, GTK, Electron)",
        "group_compare_mode": "Comparison mode",
        "mode_size_label": "Recommended by physical size (continuous range)",
        "mode_equiv_label": "Equivalence to known resolutions (720p, 1080p, 1440p, 4K...)",
        "group_detect": "Physical size and density",
        "detect_description": "Only used to calculate a range recommendation.",
        "diagonal_title": "Panel diagonal (inches)",
        "group_range": "Scaling range to duel",
        "range_description": (
            "Floor and ceiling of the single-elimination bracket. All "
            "scales the monitor supports within that range are used."
        ),
        "min_pct": "Minimum (%)",
        "max_pct": "Maximum (%)",
        "group_equiv": "Equivalent resolutions",
        "equiv_description": (
            "Only the ones this monitor really supports are offered "
            "(same aspect ratio, exact scale Mutter accepts). Check at "
            "least two to duel."
        ),
        "equiv_empty": (
            "This monitor doesn't offer any known resolution "
            "equivalences within what Mutter allows."
        ),
        "equiv_check_label": "{label} ({w}x{h}, {pct}%)",
        "equiv_check_unavailable": (
            "{label} ({w}x{h}, would need {pct}% -- this monitor doesn't "
            "support it)"
        ),
        "group_text_range": "Text/UI density range to duel",
        "text_range_description": (
            "Percentage of the system font size (text-scaling-factor). "
            "Accepts any value between 50% and 300%, no monitor "
            "restrictions."
        ),
        "start_button": "Start the blind duels",
        "detect_label_text": (
            "Resolution {w}x{h}, diagonal {origin} of {diagonal:.1f}\" -> "
            "~{ppi:.0f} PPI. Recommendation: ~{rec_pct}%, suggested range "
            "{lo_pct}%-{hi_pct}%."
        ),
        "origin_edid": "detected via EDID",
        "origin_manual": "entered manually",
        "toast_text_range_narrow": (
            "That text/UI range is too narrow -- widen the minimum/maximum"
        ),
        "toast_range_narrow": (
            "That range only has one scale supported by the monitor -- "
            "widen the minimum/maximum"
        ),
        "toast_need_two_equiv": "Check at least two equivalent resolutions to duel",

        # -- duel page --
        "replay_button": "Show both again (toggle)",
        "choose_button": "Choose {letter}",
        "showing_now": "Showing now: option {letter}.",
        "toast_apply_failed": "Could not apply option {letter}: {detail}",
        "match_progress": "{round} — match {this} of {total}",
        "round_final": "Final",
        "round_semifinal": "Semifinal",
        "round_quarterfinal": "Quarterfinal",
        "round_roundof16": "Round of 16",
        "round_generic": "Round of {n}",

        # -- result page --
        "result_title": "Bracket winner",
        "result_note_initial": (
            "This is how the screen looks right now with the bracket "
            "winner. Should we keep it applied, or go back to what you "
            "had before?"
        ),
        "apply_button": "Apply and save",
        "discard_button": "Discard and restore",
        "again_button": "Try another range",
        "apply_dialog_heading": "Apply and save this scale?",
        "apply_dialog_body": (
            "{pct}% will be saved as {what} and the window will close."
        ),
        "apply_dialog_accept": "Apply and close",
        "discard_dialog_heading": "Discard and restore?",
        "discard_dialog_body": (
            "This will go back to the scale you had before opening the "
            "app and the window will close."
        ),
        "discard_dialog_accept": "Discard and close",
        "dialog_cancel": "Cancel",
        "what_display": "this monitor's scale",
        "what_text": "the text/UI size",
        "result_note_applied": "Applied and saved as {what}.",
        "result_note_apply_failed": "Could not save it: {detail}",
        "result_note_discarded": (
            "No changes were saved: the previous scale was restored."
        ),
    },
    "es": {
        "err_dbus_connect": (
            "No se pudo conectar a org.gnome.Mutter.DisplayConfig por "
            "DBus. ¿Estás corriendo GNOME Shell / Mutter en esta sesión? "
            "Detalle: {detail}"
        ),
        "err_no_owner": (
            "El servicio org.gnome.Mutter.DisplayConfig no tiene owner "
            "en el bus de sesión. Esta app necesita correr dentro de una "
            "sesión de GNOME Shell (Mutter) activa."
        ),
        "err_get_state": "GetCurrentState falló: {detail}",
        "err_apply_config": "ApplyMonitorsConfig falló: {detail}",
        "err_no_current_mode": "El monitor {connector} no reporta ningún modo actual",
        "err_no_monitors": "Mutter no reportó ningún monitor conectado.",

        "window_title": "Escalado en duelo",
        "retry_button": "Reintentar",

        "setup_title": "Elegí el monitor y el rango a comparar",
        "setup_subtitle": (
            "Definí el piso y el techo del escalado a probar. Vamos a "
            "armar un bracket a ciegas entre esos valores -- no vas a "
            "ver el porcentaje real hasta el final, solo cuál se ve "
            "mejor. Ahí decidís si lo aplicás o lo descartás."
        ),
        "group_monitor": "Monitor",
        "combo_screen": "Pantalla",
        "group_mechanism": "Mecanismo",
        "mechanism_description": (
            "El escalado real de Mutter puede estar bloqueado por el "
            "monitor para ciertos rangos (algunos paneles no aceptan "
            "bajar de 100%). La densidad de texto/UI no tiene ese "
            "límite, pero solo afecta a apps que respetan la densidad de "
            "fuente del sistema (GTK, Electron como VSCode, Firefox), no "
            "la resolución real."
        ),
        "mech_display_label": "Escalado real del monitor (Mutter)",
        "mech_text_label": "Tamaño de texto/UI (funciona con VSCode, GTK, Electron)",
        "group_compare_mode": "Modo de comparación",
        "mode_size_label": "Recomendado por tamaño físico (rango continuo)",
        "mode_equiv_label": "Equivalencia a resoluciones conocidas (720p, 1080p, 1440p, 4K...)",
        "group_detect": "Tamaño físico y densidad",
        "detect_description": "Usado solo para calcular una recomendación de rango.",
        "diagonal_title": "Diagonal del panel (pulgadas)",
        "group_range": "Rango de escalado a duelar",
        "range_description": (
            "Piso y techo del bracket de eliminación directa. Se toman "
            "todos los escalados que soporta el monitor dentro de ese "
            "rango."
        ),
        "min_pct": "Mínimo (%)",
        "max_pct": "Máximo (%)",
        "group_equiv": "Resoluciones equivalentes",
        "equiv_description": (
            "Solo se ofrecen las que este monitor soporta de verdad "
            "(mismo aspect ratio, escala exacta que acepta Mutter). "
            "Marcá al menos dos para duelar."
        ),
        "equiv_empty": (
            "Este monitor no ofrece equivalencias de resolución "
            "conocidas dentro de lo que Mutter permite."
        ),
        "equiv_check_label": "{label} ({w}x{h}, {pct}%)",
        "equiv_check_unavailable": (
            "{label} ({w}x{h}, necesitaría {pct}% -- este monitor no lo "
            "soporta)"
        ),
        "group_text_range": "Rango de densidad de texto/UI a duelar",
        "text_range_description": (
            "Porcentaje del tamaño de fuente del sistema "
            "(text-scaling-factor). Acepta cualquier valor entre 50% y "
            "300%, sin restricciones del monitor."
        ),
        "start_button": "Empezar los duelos a ciegas",
        "detect_label_text": (
            "Resolución {w}x{h}, diagonal {origin} de {diagonal:.1f}\" -> "
            "~{ppi:.0f} PPI. Recomendación: ~{rec_pct}%, rango sugerido "
            "{lo_pct}%–{hi_pct}%."
        ),
        "origin_edid": "detectada por EDID",
        "origin_manual": "ingresada a mano",
        "toast_text_range_narrow": (
            "Ese rango de texto/UI es muy angosto -- ampliá el mínimo/máximo"
        ),
        "toast_range_narrow": (
            "Ese rango solo tiene un escalado soportado por el monitor "
            "-- ampliá el mínimo/máximo"
        ),
        "toast_need_two_equiv": "Marcá al menos dos resoluciones equivalentes para duelar",

        "replay_button": "Volver a mostrar ambas (alternar)",
        "choose_button": "Elegir {letter}",
        "showing_now": "Mostrando ahora: opción {letter}.",
        "toast_apply_failed": "No se pudo aplicar la opción {letter}: {detail}",
        "match_progress": "{round} — enfrentamiento {this} de {total}",
        "round_final": "Final",
        "round_semifinal": "Semifinal",
        "round_quarterfinal": "Cuartos de final",
        "round_roundof16": "Octavos de final",
        "round_generic": "Ronda de {n}",

        "result_title": "Ganador del bracket",
        "result_note_initial": (
            "Así quedó la pantalla ahora mismo con el ganador del "
            "bracket. ¿Lo dejamos aplicado o volvemos al escalado que "
            "tenías antes?"
        ),
        "apply_button": "Aplicar y guardar",
        "discard_button": "Descartar y restaurar",
        "again_button": "Repetir con otro rango",
        "apply_dialog_heading": "¿Aplicar y guardar este escalado?",
        "apply_dialog_body": (
            "Se va a guardar {pct}% como {what} y la ventana se va a "
            "cerrar."
        ),
        "apply_dialog_accept": "Aplicar y cerrar",
        "discard_dialog_heading": "¿Descartar y restaurar?",
        "discard_dialog_body": (
            "Se va a volver al escalado que tenías antes de abrir la "
            "app y la ventana se va a cerrar."
        ),
        "discard_dialog_accept": "Descartar y cerrar",
        "dialog_cancel": "Cancelar",
        "what_display": "escalado de este monitor",
        "what_text": "tamaño de texto/UI",
        "result_note_applied": "Se aplicó y quedó guardado como {what}.",
        "result_note_apply_failed": "No se pudo dejarlo guardado: {detail}",
        "result_note_discarded": (
            "No se guardó ningún cambio: se restauró el escalado "
            "anterior."
        ),
    },
}


def detect_lang(env: Optional[dict] = None) -> str:
    """Devuelve "es" si alguna variable de locale del sistema empieza
    con "es" (cualquier variante: es_AR, es_ES, es_MX.UTF-8, es...),
    si no "en". LANGUAGE puede traer una lista separada por ':'."""
    env = env if env is not None else os.environ
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = env.get(var, "")
        if not value:
            continue
        for chunk in value.split(":"):
            code = chunk.strip().lower()
            if code.startswith("es"):
                return "es"
            if code and code != "c" and code != "posix":
                # ya encontramos un idioma no vacío no-español en la
                # variable de mayor prioridad -> nos quedamos con inglés
                return "en"
    return "en"


LANG = detect_lang()


def t(key: str, **kwargs) -> str:
    """Traduce `key` al idioma detectado, con fallback a inglés si la
    clave falta en el idioma actual o el idioma no existe."""
    lang_strings = STRINGS.get(LANG, STRINGS["en"])
    template = lang_strings.get(key, STRINGS["en"].get(key, key))
    if kwargs:
        return template.format(**kwargs)
    return template
