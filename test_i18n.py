"""Tests for i18n.py -- language detection and translation completeness.

Run with: python3 test_i18n.py (see bottom of file) or via the same
ad-hoc runner used for test_scale_duel.py, since pytest isn't
available in every dev environment this project targets.
"""
import importlib

from i18n import STRINGS, detect_lang, t


def test_detect_lang_defaults_to_english_with_no_locale():
    assert detect_lang(env={}) == "en"


def test_detect_lang_spanish_variants():
    for value in ["es_AR.UTF-8", "es_ES.UTF-8", "es_MX", "es_CO.UTF-8", "es"]:
        assert detect_lang(env={"LANG": value}) == "es", value


def test_detect_lang_non_spanish_defaults_to_english():
    for value in ["en_US.UTF-8", "fr_FR.UTF-8", "pt_BR.UTF-8", "de_DE.UTF-8"]:
        assert detect_lang(env={"LANG": value}) == "en", value


def test_detect_lang_prefers_language_over_lang():
    # LANGUAGE tiene prioridad sobre LANG en la mayoría de los entornos
    # GNOME/glibc; probamos que nuestra heurística respeta ese orden.
    assert detect_lang(env={"LANGUAGE": "es_AR:en", "LANG": "en_US.UTF-8"}) == "es"


def test_detect_lang_ignores_c_and_posix():
    assert detect_lang(env={"LANG": "C"}) == "en"
    assert detect_lang(env={"LANG": "POSIX"}) == "en"


def test_every_spanish_key_exists_in_english_and_vice_versa():
    en_keys = set(STRINGS["en"].keys())
    es_keys = set(STRINGS["es"].keys())
    missing_in_es = en_keys - es_keys
    missing_in_en = es_keys - en_keys
    assert not missing_in_es, f"Faltan en es: {missing_in_es}"
    assert not missing_in_en, f"Sobran en es (no están en en): {missing_in_en}"


def test_t_falls_back_to_english_for_unknown_language():
    import i18n
    original_lang = i18n.LANG
    try:
        i18n.LANG = "fr"  # idioma no soportado todavía
        assert t("window_title") == STRINGS["en"]["window_title"]
    finally:
        i18n.LANG = original_lang


def test_t_formats_placeholders():
    import i18n
    original_lang = i18n.LANG
    try:
        i18n.LANG = "en"
        assert t("choose_button", letter="C") == "Choose C"
        i18n.LANG = "es"
        assert t("choose_button", letter="C") == "Elegir C"
    finally:
        i18n.LANG = original_lang


def test_t_unknown_key_returns_key_itself():
    assert t("this_key_does_not_exist") == "this_key_does_not_exist"


if __name__ == "__main__":
    mod = importlib.import_module(__name__)
    fns = [n for n in dir(mod) if n.startswith("test_")]
    ok = 0
    for name in fns:
        try:
            getattr(mod, name)()
            ok += 1
        except Exception as e:  # noqa: BLE001
            print("FAIL", name, repr(e))
    print(f"{ok}/{len(fns)} passed")
