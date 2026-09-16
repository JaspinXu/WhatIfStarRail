from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_companion_create_fork_continue_chat(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRAL_COMPANION_DATABASE", str(tmp_path / "companion.sqlite"))
    path = Path(__file__).resolve().parents[2] / "app" / "streamlit_app.py"
    app = AppTest.from_file(str(path), default_timeout=30).run()
    app.radio[0].set_value("星铁伴游").run()
    assert not app.exception
    app.text_input(key="new_title").set_value("列车启程")
    app.text_area(key="new_content").set_value("三月七和丹恒在车门前等待玩家。")
    next(b for b in app.button if b.label == "建立剧情节点").click().run()
    assert not app.exception
    next(b for b in app.button if b.label == "从这里创建分支").click().run()
    assert not app.exception
    assert len(app.selectbox(key="story_selected").options) == 2
    next(b for b in app.button if b.label == "自然演进一轮").click().run()
    assert not app.exception
    assert len(app.selectbox(key="story_selected").options) == 3
    app.chat_input[0].set_value("你现在担心什么？").run()
    assert not app.exception
    assert len(app.chat_message) == 2


def test_default_workbench_and_public_character_cards(tmp_path, monkeypatch):
    from astral_agents.companion import StoryStore

    database = tmp_path / "cards.sqlite"
    monkeypatch.setenv("ASTRAL_COMPANION_DATABASE", str(database))
    path = Path(__file__).resolve().parents[2] / "app" / "streamlit_app.py"
    app = AppTest.from_file(str(path), default_timeout=30).run()
    assert not app.exception
    assert app.radio[0].value == "星铁伴游"
    assert len(app.tabs) == 5
    assert len(StoryStore(database).cards()) == 4
    assert "CANARY" not in str(StoryStore(database).cards())
    next(b for b in app.button if b.key == "starter_信号另一端的你").click().run()
    assert not app.exception
    assert len(StoryStore(database).nodes()) == 1
    app.text_input(key="library_query").set_value("不存在的剧情").run()
    assert any("找到 0 个节点" in c.value for c in app.caption)


def test_prompt_chip_navigation_and_leaf_delete(tmp_path, monkeypatch):
    from astral_agents.companion import StoryStore

    database = tmp_path / "nav.sqlite"
    monkeypatch.setenv("ASTRAL_COMPANION_DATABASE", str(database))
    store = StoryStore(database)
    root = store.add("起点", "三月七在车门前等待。", "三月七")
    leaf = store.add("如果", "三月七决定留下。", "三月七", "fork", root)
    path = Path(__file__).resolve().parents[2] / "app" / "streamlit_app.py"
    app = AppTest.from_file(str(path), default_timeout=30).run()
    assert app.selectbox(key="story_selected").value == leaf
    next(b for b in app.button if b.key == "prompt_你现在最担心什么？").click().run()
    assert not app.exception
    assert store.chats(leaf, "三月七")[0]["question"] == "你现在最担心什么？"
    next(b for b in app.button if b.key == "nav_parent").click().run()
    assert app.selectbox(key="story_selected").value == root
    assert any(b.key == "child_" + leaf for b in app.button)
    next(b for b in app.button if b.key == "child_" + leaf).click().run()
    app.checkbox(key="confirm_delete_" + leaf).check().run()
    next(b for b in app.button if b.key == "delete_" + leaf).click().run()
    assert not app.exception
    assert [n["id"] for n in store.nodes()] == [root]
    assert store.chats(leaf, "三月七") == []
    assert app.selectbox(key="story_selected").value == root
