# gnome-scale-duel

A GTK4 / libadwaita app to figure out which display scale actually
looks best on your GNOME/Wayland monitor, by dueling candidates
head-to-head in a blind single-elimination bracket -- instead of
guessing from a settings slider. Unlike a mockup that fakes scaling
with a CSS `transform: scale()`, this app applies the scale **for
real** on your screen through Mutter's actual DBus interface,
`org.gnome.Mutter.DisplayConfig`.

## Features

- **Three scaling mechanisms**, pick whichever your hardware supports:
  - **Recommended by physical size** -- detects the panel's real size
    via EDID (falls back to manual input), computes PPI, and suggests
    a scale range around it.
  - **Equivalence to known resolutions** -- lets you duel scales that
    make your screen behave like a known resolution (720p, 1080p,
    1440p, 4K...) of the same aspect ratio. Targets your monitor can't
    actually reach are shown disabled instead of silently hidden, so
    you can see *why* (Mutter rejects that scale for this panel).
  - **Text/UI density** -- when Mutter's real scaling is capped below
    100% by your hardware, this falls back to
    `org.gnome.desktop.interface text-scaling-factor`, a continuous
    value most GTK/Electron apps (VSCode, Firefox...) respect for
    their own UI density, even though it doesn't touch the real
    framebuffer resolution.
- **Blind duels**: each match shows "Choose A" / "Choose B", never the
  real percentage, so your pick isn't biased by the number. Every
  candidate keeps a stable letter for the whole tournament (assigned
  in shuffled order, so "A" isn't always the lowest scale).
- **Football-style bracket naming**: Quarterfinal, Semifinal, Final,
  based on how many matches are left.
- Real live changes via `ApplyMode.TEST` while you duel (Mutter
  reverts it on its own if you never confirm), and an explicit
  confirmation dialog before anything is saved (`ApplyMode.PERSISTENT`)
  or discarded.

## How it works

1. Reads connected monitors and their modes via `GetCurrentState`.
2. Builds a list of candidate scales depending on the mechanism you
   picked (a continuous range, or specific resolution-equivalence
   targets), always filtered to what Mutter actually supports for
   that mode/panel.
3. Builds a single-elimination bracket with the candidates you select.
4. Applies each duel's scale in `ApplyMode.TEST` (temporary --
   reverted automatically by Mutter if you never confirm).
5. When the bracket finishes, reveals the real winning percentage and
   asks you to confirm: apply and save (`ApplyMode.PERSISTENT`), or
   discard and restore what you had before opening the app.

## Requirements

```bash
sudo pacman -S python-gobject gtk4 libadwaita   # Arch
```

The app **must run inside your real GNOME graphical session** (it
needs `DBUS_SESSION_BUS_ADDRESS` pointing at the session bus where
Mutter lives). It won't work from a container, a headless VM, or a
session without GNOME Shell running.

## Usage

```bash
python3 scale_duel.py
```

## Language / Internationalization

The app is in **English by default**. If your system locale is any
Spanish variant (`es_AR`, `es_ES`, `es_MX`, ...), it switches to
**Spanish automatically** -- no setting to toggle, it just reads
`LANGUAGE`/`LC_ALL`/`LC_MESSAGES`/`LANG` like any other GNOME app.

All UI strings live in [`i18n.py`](i18n.py) as a plain dict, no
`gettext`/`.po` build step involved. **Contributions for more
languages are very welcome** -- to add one:

1. Copy the `"en"` dict in `i18n.py` into a new top-level key (e.g.
   `"fr"`) and translate every value, keeping the same `{placeholder}`
   names intact.
2. Add a locale-prefix check for it in `detect_lang()`.
3. Run `python3 test_i18n.py` -- it checks that every key present in
   `"en"` also exists in every other language dict, so nothing falls
   back silently.

You don't need to be a programmer to contribute a language: the
translatable strings are plain English sentences in one file. Open a
PR (or an issue if you'd rather just paste the translated text and
have someone wire it in).

## Tests

Bracket logic, candidate-scale math, EDID/PPI calculations, and the
i18n layer are all pure functions (no GTK, no DBus), so they run
anywhere:

```bash
python3 test_scale_duel.py
python3 test_i18n.py
# (or with pytest, if installed:)
python3 -m pytest test_scale_duel.py test_i18n.py -v
```

What's **not** covered by automated tests (needs a real GNOME
session): the DBus connection to Mutter, `GetCurrentState`,
`ApplyMonitorsConfig` in TEST/PERSISTENT mode, `text-scaling-factor`
via GSettings, and the full UI flow. All of that has been validated
live against a real Mutter/GNOME Shell 50 session while building this,
but if you hit an edge case on different hardware/GNOME version,
please open an issue with the traceback.

## Known limitations

- Only changes the scale of the monitor you pick; if you have more
  than one monitor, the others keep their current layout untouched.
- Doesn't manage `transform` (rotation) beyond preserving whatever is
  currently set.
- Which scales are actually available depends entirely on what Mutter
  reports as supported for your panel/mode -- some hardware flatly
  rejects any scale below 100% (confirmed via live `ApplyMonitorsConfig`
  calls, not just Mutter's advertised list), in which case only the
  text/UI density mechanism can go below 100%.

## License

MIT -- see [LICENSE](LICENSE). Free for anyone to use, modify, and
redistribute.
