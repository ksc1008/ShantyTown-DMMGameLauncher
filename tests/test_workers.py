"""Tests for gui.workers — signal emissions on the launch flow."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from shantytown.core.api import AuthInvalidError, DmmApiClient
from shantytown.gui.workers import LaunchWorker


def _make_worker(api: DmmApiClient) -> LaunchWorker:
    return LaunchWorker(
        api=api,
        token="tok",
        product_id="tskx",
        game_type="GTYPE",
        install_dir=Path("."),
        exe_path=Path("game.exe"),
    )


def test_auth_invalid_emits_dedicated_signal_before_finished(qtbot):
    api = MagicMock(spec=DmmApiClient)
    api.launch_game.side_effect = AuthInvalidError("expired", detail="")
    worker = _make_worker(api)

    order: list[str] = []
    worker.auth_invalid.connect(lambda: order.append("auth_invalid"))
    worker.finished.connect(lambda *_: order.append("finished"))

    worker.run()

    # auth_invalid must precede finished so the dialog can wire its
    # logout button before finish() rebuilds the button row.
    assert order == ["auth_invalid", "finished"]


def test_non_auth_error_does_not_emit_auth_invalid(qtbot):
    from shantytown.core.api import GameNotLinkedError

    api = MagicMock(spec=DmmApiClient)
    api.launch_game.side_effect = GameNotLinkedError("nope", detail="")
    worker = _make_worker(api)

    emitted: list[str] = []
    worker.auth_invalid.connect(lambda: emitted.append("auth_invalid"))
    finished: list[bool] = []
    worker.finished.connect(lambda success, *_: finished.append(success))

    worker.run()

    assert emitted == []
    assert finished == [False]
