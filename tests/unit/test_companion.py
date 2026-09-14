import json

import pytest

from astral_agents.companion import StoryStore, SubtitleBuffer, generate


def test_branch_isolation_and_persistence(tmp_path):
    path = tmp_path / "stories.sqlite"
    store = StoryStore(path)
    root = store.add("开始", "车门即将关闭", "三月七，丹恒")
    one = store.add("留下", "三月七留下", "三月七", "fork", root)
    two = store.add("离开", "丹恒离开", "丹恒", "fork", root)
    store.chat(one, "三月七", "担心吗", "我会等你")
    reopened = StoryStore(path)
    assert [n["id"] for n in reopened.lineage(two)] == [root, two]
    assert reopened.chats(two, "三月七") == []
    assert reopened.chats(one, "丹恒") == []
    exported = json.loads(reopened.export(two))
    assert len(exported["nodes"]) == 2
    assert exported["chats"] == []
    assert "我会等你" in reopened.export(one)


def test_subtitle_stability_and_repeated_dialogue():
    buffer = SubtitleBuffer()
    assert buffer.push("等等") is None
    assert buffer.push("等等，我们走吧") is None
    assert buffer.push("等等，我们走吧") == "等等，我们走吧"
    assert buffer.push("等等，我们走吧") is None
    assert buffer.push("") is None
    assert buffer.push("等等，我们走吧") is None
    assert buffer.push("等等，我们走吧") == "等等，我们走吧"


def test_invalid_and_missing_credentials(tmp_path, monkeypatch):
    store = StoryStore(tmp_path / "stories.sqlite")
    with pytest.raises(ValueError):
        store.add("空", " ", "丹恒")
    root = store.add("起点", "等待", "丹恒")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError):
        generate(store, root, "继续", live=True)
    assert len(store.nodes()) == 1
    assert "离线" in generate(store, root, "继续")


def test_model_receives_only_selected_branch_and_actor(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace

    calls = []

    class Client:
        def __init__(self, **kwargs):
            self.responses = self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def create(self, **kwargs):
            calls.append(json.loads(kwargs["input"]))
            return SimpleNamespace(output_text="我们先核实情况。")

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=Client))
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setenv("ASTRAL_OPENAI_MODEL", "test-model")
    store = StoryStore(tmp_path / "model.sqlite")
    root = store.add("起点", "共同前提", "丹恒，三月七")
    selected = store.add("选中", "眼前的事件", "丹恒", "fork", root)
    sibling = store.add("旁支", "不可见的旁支", "三月七", "fork", root)
    store.chat(sibling, "丹恒", "旁支问题", "旁支答案")
    store.chat(selected, "三月七", "其他人物问题", "其他人物答案")
    store.chat(selected, "丹恒", "此处问题", "此处答案")
    assert generate(store, selected, "心境？", actor="丹恒", live=True) == "我们先核实情况。"
    assert [n["content"] for n in calls[0]["branch"]] == ["共同前提", "眼前的事件"]
    assert [c["answer"] for c in calls[0]["history"]] == ["此处答案"]
