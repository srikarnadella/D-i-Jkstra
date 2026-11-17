"""Guard: any f-string rendered with unsafe_allow_html=True may only interpolate values that
are escaped with _safe(...) or formatted numbers ({x:.1f}). Library/user text must never be raw."""
import ast
import glob
import os

ROOT = os.path.join(os.path.dirname(__file__), "..")
APP_FILES = [os.path.join(ROOT, "3dapp.py"), *glob.glob(os.path.join(ROOT, "ui", "*.py"))]


def _unsafe_fstring_values(path):
    tree = ast.parse(open(path).read())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not any(k.arg == "unsafe_allow_html" and getattr(k.value, "value", False) is True for k in node.keywords):
            continue
        for arg in node.args:
            for part in ast.walk(arg):
                if isinstance(part, ast.FormattedValue):
                    yield node.lineno, part


def test_unsafe_html_only_interpolates_escaped_or_numeric_values():
    bad = []
    for path in APP_FILES:
        for lineno, fv in _unsafe_fstring_values(path):
            escaped = isinstance(fv.value, ast.Call) and getattr(fv.value.func, "id", "") == "_safe"
            numeric = fv.format_spec is not None or (isinstance(fv.value, ast.Call)
                                                     and getattr(fv.value.func, "id", "") == "len")
            if not (escaped or numeric):
                bad.append(f"{os.path.basename(path)}:{lineno} {ast.unparse(fv.value)}")
    assert not bad, "unescaped value in unsafe_allow_html: " + ", ".join(bad)


def test_xml_billion_laughs_rejected():
    import pytest
    from defusedxml import EntitiesForbidden
    import db
    bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;">]><DJ_PLAYLISTS>&b;</DJ_PLAYLISTS>'
    with pytest.raises(EntitiesForbidden):
        db.parse_rekordbox_xml(bomb)
