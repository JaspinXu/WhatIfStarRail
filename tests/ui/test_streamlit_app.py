from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_streamlit_quick_demo_loads_without_exceptions(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("ASTRAL_DATABASE", str(tmp_path / "ui.sqlite"))
    app_path = Path(__file__).resolve().parents[2] / "app" / "streamlit_app.py"

    app = AppTest.from_file(str(app_path), default_timeout=45)
    app.query_params["mode"] = "simulation"
    app.run()
    assert not app.exception
    assert len(app.button) == 2

    app.button[0].click().run(timeout=45)

    assert not app.exception
    assert len(app.tabs) == 5
    assert len(app.get("download_button")) == 1
    assert any("10" in success.value for success in app.success)


def test_streamlit_step_mode_handles_round_zero_and_advances(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("ASTRAL_DATABASE", str(tmp_path / "step-ui.sqlite"))
    app_path = Path(__file__).resolve().parents[2] / "app" / "streamlit_app.py"

    app = AppTest.from_file(str(app_path), default_timeout=45)
    app.query_params["mode"] = "simulation"
    app.run()
    app.button[1].click().run(timeout=45)

    assert not app.exception
    assert len(app.tabs) == 5
    assert not app.slider
    assert any("轮次 · 0" in caption.value for caption in app.caption)

    next(
        button for button in app.button if button.label == "推进一轮"
    ).click().run(timeout=45)

    assert not app.exception
    assert len(app.slider) == 1
