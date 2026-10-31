"""Tests for the static web UI files served by the API."""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import word_session.web

STATIC = Path(word_session.web.__file__).parent / "static"
IMPORT_RE = re.compile(r"""(?:import|export)\s+(?:[^'"()]*?\s+from\s+)?['"]([^'"]+)['"]""")
HTML_REF_RE = re.compile(r"""(?:src|href)="([^"#]+)\"""")
HELP_REF_RE = re.compile(r"""help\.html#([\w-]+)""")
ID_RE = re.compile(r"""\sid="([^"]+)\"""")
PAGES = ("index.html", "help.html")


def _static_files() -> list[Path]:
    return sorted(p for p in STATIC.rglob("*") if p.is_file())


def _references() -> set[str]:
    """Collect URL paths referenced by the HTML pages and by JS imports."""
    refs: set[str] = set()
    for page in PAGES:
        html = (STATIC / page).read_text(encoding="utf-8")
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
    for expected in (
        "/js/app.js",
        "/app.css",
        "/favicon.svg",
        "/js/views/detail.js",
        "/js/api.js",
        "/help.html",
        "/help.css",
    ):
        assert expected in refs


def test_every_referenced_file_is_served(anon_client: TestClient) -> None:
    expected = {
        ".js": "text/javascript",
        ".css": "text/css",
        ".svg": "image/svg+xml",
        ".html": "text/html",
    }
    for ref in sorted(_references() - {"/"}):  # "/" is the help page's link back
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


@pytest.mark.parametrize("page", PAGES)
def test_no_inline_event_handler_attributes_in_html(page: str) -> None:
    html = (STATIC / page).read_text(encoding="utf-8")
    assert not re.search(r"\son[a-z]+\s*=", html)


# ---- help page ------------------------------------------------------------------


def _help_ids() -> list[str]:
    return ID_RE.findall((STATIC / "help.html").read_text(encoding="utf-8"))


def test_help_page_is_served_without_login(anon_client: TestClient) -> None:
    response = anon_client.get("/help.html")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["content-security-policy"] == "default-src 'self'"
    assert "<title>Word Session help</title>" in response.text


def test_help_ids_are_unique() -> None:
    ids = _help_ids()
    assert len(ids) == len(set(ids))


def test_help_page_internal_links_resolve() -> None:
    html = (STATIC / "help.html").read_text(encoding="utf-8")
    targets = set(re.findall(r"""href="#([^"]+)\"""", html))
    assert targets, "the table of contents links nowhere"
    assert targets <= set(_help_ids()), sorted(targets - set(_help_ids()))


def _manager_help_anchors() -> set[str]:
    """Collect the help sections the manager links to."""
    anchors = set(HELP_REF_RE.findall((STATIC / "index.html").read_text(encoding="utf-8")))
    for js in STATIC.rglob("*.js"):
        text = js.read_text(encoding="utf-8")
        anchors |= set(HELP_REF_RE.findall(text))
        # helpLink(anchor, ...), withHelp(el, anchor, ...), addFieldHelp(field, anchor, ...),
        # helpHeading(tag, text, anchor) and the settings legend(text, anchor).
        anchors |= set(re.findall(r"""helpLink\("([\w-]+)\"""", text))
        anchors |= set(re.findall(r"""(?:withHelp|addFieldHelp)\(.*?,\s*"([\w-]+)\"""", text))
        anchors |= set(re.findall(r"""helpHeading\("h\d",\s*"[^"]+",\s*"([\w-]+)\"""", text))
        anchors |= set(re.findall(r"""legend\("[^"]+",\s*"([\w-]+)""", text))
        # withHelp(text, ...columnHelp[text]) in the sessions table.
        anchors |= set(re.findall(r"""\[\s*"([\w-]+)",\s*"[^"]+"\s*\]""", text))
    return anchors


def test_manager_help_links_point_at_existing_sections() -> None:
    anchors = _manager_help_anchors()
    assert len(anchors) > 20
    missing = anchors - set(_help_ids())
    assert not missing, sorted(missing)


def test_links_in_index_html_have_tooltips() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for tag in re.findall(r"<(?:button|a)\b[^>]*>", html):
        if "skip-link" in tag:
            continue
        assert "title=" in tag, tag
