"""Run the command line against real (private, invisible) Word processes."""

from pathlib import Path
from typing import Any

import pytest

from word_session.word.worker import ComWorker

from .conftest import WordHarness, last_json, local_state

pytestmark = pytest.mark.word

Capsys = pytest.CaptureFixture[str]


def _open_three(h: WordHarness, docs: dict[str, Path], capsys: Capsys) -> None:
    """Open alpha, gamma and beta so that beta is active."""
    h.open_docs(docs["alpha"], docs["gamma"], docs["beta"])
    capsys.readouterr()


def _statuses(report: dict[str, Any]) -> dict[str, str]:
    """Map file names to restore statuses."""
    return {Path(r["path"]).name: r["status"] for r in report["results"]}


def test_unsaved_document_warned_and_skipped(
    harness: WordHarness, docs: dict[str, Path], capsys: Capsys
) -> None:
    harness.open_docs(docs["alpha"])
    harness.add_unsaved()
    capsys.readouterr()

    assert harness.run("save") == 0
    assert "never saved" in capsys.readouterr().err  # defect 6

    assert harness.run("--json", "show", "latest") == 0
    session = last_json(capsys)
    assert sorted(d["location"] for d in session["documents"]) == ["local", "unsaved"]

    harness.close_all()
    assert harness.run("--json", "restore") == 0
    statuses = [r["status"] for r in last_json(capsys)["results"]]
    assert sorted(statuses) == ["opened", "skipped"]
    assert len(harness.open_paths()) == 1


def test_save_keeps_active_and_show_lists_positions(
    harness: WordHarness, docs: dict[str, Path], capsys: Capsys
) -> None:
    _open_three(harness, docs, capsys)
    harness.select(docs["alpha"], 100, 120)
    harness.activate(docs["beta"])

    assert harness.run("save", "--name", "three") == 0
    assert harness.active_path().casefold() == str(docs["beta"]).casefold()  # defect 2
    capsys.readouterr()

    assert harness.run("--json", "show", "latest") == 0
    session = last_json(capsys)
    assert len(session["documents"]) == 3
    by_name = {Path(d["path"]).name: d for d in session["documents"]}
    assert by_name["alpha.docx"]["position"]["start"] == 100
    assert all(d["position"]["page"] for d in session["documents"])
    assert by_name["beta.docx"]["active"] is True


def test_restore_reopens_positions_and_active(
    harness: WordHarness, docs: dict[str, Path], capsys: Capsys
) -> None:
    _open_three(harness, docs, capsys)
    harness.select(docs["alpha"], 100, 120)
    harness.select(docs["gamma"], 2000, 2000)
    harness.activate(docs["beta"])
    assert harness.run("save") == 0
    harness.close_all()
    assert harness.open_paths() == []
    capsys.readouterr()

    assert harness.run("--json", "restore") == 0
    assert set(_statuses(last_json(capsys)).values()) == {"opened"}
    assert len(harness.open_paths()) == 3
    assert harness.active_path().casefold() == str(docs["beta"]).casefold()

    assert harness.run("--json", "current") == 0
    current = {Path(d["path"]).name: d for d in last_json(capsys)}
    assert current["alpha.docx"]["position"]["start"] == 100
    assert current["gamma.docx"]["position"]["start"] == 2000


def test_renamed_file_is_missing_exit_4(
    harness: WordHarness, docs: dict[str, Path], capsys: Capsys
) -> None:
    _open_three(harness, docs, capsys)
    assert harness.run("save") == 0
    harness.close_all()
    docs["gamma"].rename(docs["gamma"].with_name("gamma-renamed.docx"))
    capsys.readouterr()

    assert harness.run("--json", "restore") == 4
    statuses = _statuses(last_json(capsys))
    assert statuses == {"alpha.docx": "opened", "beta.docx": "opened", "gamma.docx": "missing"}
    assert len(harness.open_paths()) == 2


def test_locked_file_reported_without_dialog(
    harness: WordHarness, docs: dict[str, Path], second_word: ComWorker, capsys: Capsys
) -> None:
    _open_three(harness, docs, capsys)
    assert harness.run("save") == 0
    harness.close_all()
    second_word.call(lambda b: b.open_document(local_state(docs["alpha"])))
    capsys.readouterr()

    # The 60 s worker timeout bounds this call; a dialog would exceed it.
    assert harness.run("--json", "restore") == 4
    statuses = _statuses(last_json(capsys))
    assert statuses["alpha.docx"] == "locked"
    assert statuses["beta.docx"] == statuses["gamma.docx"] == "opened"
    assert len(harness.open_paths()) == 2


def test_non_ascii_and_space_path_round_trips(
    harness: WordHarness, docs: dict[str, Path], capsys: Capsys
) -> None:
    harness.open_docs(docs["space"])
    harness.select(docs["space"], 50, 60)
    assert harness.run("save") == 0
    harness.close_all()
    capsys.readouterr()

    assert harness.run("--json", "restore") == 0
    assert _statuses(last_json(capsys)) == {"with space é.docx": "opened"}
    assert harness.run("--json", "current") == 0
    (doc,) = last_json(capsys)
    assert doc["position"]["start"] == 50


def test_dry_run_makes_no_word_calls(
    harness: WordHarness, docs: dict[str, Path], capsys: Capsys
) -> None:
    _open_three(harness, docs, capsys)
    assert harness.run("save") == 0
    harness.close_all()
    capsys.readouterr()

    assert harness.run("--json", "restore", "--dry-run") == 0
    assert {r["status"] for r in last_json(capsys)["results"]} == {"skipped"}
    assert harness.open_paths() == []


def test_current_matches_word(harness: WordHarness, docs: dict[str, Path], capsys: Capsys) -> None:
    _open_three(harness, docs, capsys)
    assert harness.run("--json", "current") == 0
    listed = sorted(d["path"].casefold() for d in last_json(capsys))
    assert listed == sorted(p.casefold() for p in harness.open_paths())
