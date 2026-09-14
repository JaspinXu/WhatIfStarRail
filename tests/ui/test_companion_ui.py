from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_companion_create_fork_continue_chat(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRAL_COMPANION_DATABASE", str(tmp_path / "companion.sqlite"))
    path = Path(__file__).resolve().parents[2] / "app" / "streamlit_app.py"
    app = AppTest.from_file(str(path), default_timeout=30).run()
    app.radio[0].set_value("星铁伴游").run()
    assert not app.exception
    app.text_input[0].set_value("列车启程")
    app.text_area[0].set_value("三月七和丹恒在车门前等待玩家。")
    next(b for b in app.button if b.label == "建立剧情节点").click().run()
    assert not app.exception
    next(b for b in app.button if b.label == "从这里创建分支").click().run()
    assert not app.exception
    assert len(app.selectbox[0].options) == 2
    next(b for b in app.button if b.label == "自然演进一轮").click().run()
    assert not app.exception
    assert len(app.selectbox[0].options) == 3
    app.chat_input[0].set_value("你现在担心什么？").run()
    assert not app.exception
    assert len(app.chat_message) == 2
