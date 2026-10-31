"""Tests for the static web UI files served by the API."""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import word_session.web

STATIC = Path(word_session.web.__file__).parent / "static"
IMPORT_RE = re.compile(r"""(?:import|export)\s+(?:[^'"()]*?\s+from\s+)?['"]([^'"]+)['"]""")
HTML_REF_RE = re.compile(r"""(?:src|href)="([^"#]+)\"""")


def _static_files() -> list[Path]:
    return sorted(p for p in STATIC.rglob("*") if p.is_file())


def _references() -> set[str]:
    """Collect URL paths referenced by index.html and by JS imports."""
    refs: set[str] = set()
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for ref in HTML_REF_RE.findall(html):
        refs.add("/" + ref.lstrip("/"))
    for js in STATIC.rglob("*.js"):
        for ref in IMPORT_RE.findall(js.read_text(encoding="utf-8")):
            target = (js.parent / ref).resolve().relative_to(STATIC.resolve())
            refs.add("/" + target.as_posix())
    return refs


def test_root_serves_html(anon_client: TestClient) -> None:
    response = anon_client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<title>Word Session</title>" in response.text


def test_security_headers_on_static(anon_client: TestClient) -> None:
    response = anon_client.get("/js/app.js")
    assert response.headers["content-security-policy"] == "default-src 'self'"


def test_references_are_found() -> None:
    refs = _references()
    for expected in ("/js/app.js", "/app.css", "/favicon.svg", "/js/views/detail.js", "/js/api.js"):
        assert expected in refs


def test_every_referenced_file_is_served(anon_client: TestClient) -> None:
    expected = {".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml"}
    for ref in sorted(_references()):
        response = anon_client.get(ref)
        assert response.status_code == 200, ref
        content_type = response.headers["content-type"].split(";")[0]
        assert content_type == expected[Path(ref).suffix], ref


def test_every_static_file_is_referenced() -> None:
    """Catch modules that were written but never imported."""
    refs = _references()
    for path in _static_files():
        assert "/" + path.relative_to(STATIC).as_posix() in refs or path.name == "index.html"


def _strip_comments(path: Path, text: str) -> str:
    """Drop comments so URLs mentioned in them are not flagged."""
    if path.suffix == ".js":
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        text = re.sub(r"(?m)^\s*//.*$", "", text)
    elif path.suffix == ".css":
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    elif path.suffix in (".html", ".svg"):
        text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    # The SVG namespace is an identifier, not a network request.
    return text.replace('xmlns="http://www.w3.org/2000/svg"', "")


@pytest.mark.parametrize("path", _static_files(), ids=lambda p: p.name)
def test_static_file_is_self_contained(path: Path) -> None:
    text = _strip_comments(path, path.read_text(encoding="utf-8"))
    assert not re.search(r"https?://", text), "external URL"
    assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write", text)
    assert not re.search(r"\beval\s*\(|new Function\s*\(", text)
    assert not re.search(r"""\bstyle\s*=\s*["']""", text), "inline style attribute"
    assert not re.search(r"\.style\.|\.cssText", text), "inline style"
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", text), "inline script"


def test_no_inline_event_handler_attributes_in_html() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"\son[a-z]+\s*=", html)
