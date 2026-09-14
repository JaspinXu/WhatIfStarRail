import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from astral_agents.capture_service import CaptureService
from astral_agents.companion import StoryStore
from astral_agents.companion_models import CaptureProfile, CharacterCard, IngestEvent


def event(**overrides):
    return IngestEvent(**({"source": "test", "timeline": "one", "event_id": "001",
                          "title": "开局", "text": "三月七：出发吧。", "cast": "三月七"} | overrides))


def test_ingest_idempotency_conflict_and_timeline_isolation(tmp_path):
    store = StoryStore(tmp_path / "story.sqlite")
    one, created = store.ingest(event())
    assert created
    assert store.ingest(event()) == (one, False)
    with pytest.raises(ValueError):
        store.ingest(event(text="冲突内容"))
    two, _ = store.ingest(event(event_id="002", text="下一句"))
    separate, _ = store.ingest(event(event_id="003", timeline="two"))
    assert [n["id"] for n in store.lineage(two)] == [one, two]
    assert len(store.lineage(separate)) == 1
    assert len(store.nodes()) == 3


def test_concurrent_delivery_creates_one_node(tmp_path):
    store = StoryStore(tmp_path / "concurrent.sqlite")
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: store.ingest(event()), range(8)))
    assert sum(created for _, created in results) == 1
    assert len({node_id for node_id, _ in results}) == 1


def test_archive_import_remaps_ids_and_preserves_chat(tmp_path):
    store = StoryStore(tmp_path / "archive.sqlite")
    root = store.add("开局", "选择", "三月七")
    leaf = store.add("分支", "留下", "三月七", "fork", root)
    store.chat(leaf, "三月七", "为什么", "因为你还在这里")
    imported = store.import_archive(store.export(leaf))
    assert imported != leaf
    assert len(store.nodes()) == 4
    assert store.lineage(imported)[0]["id"] != root
    assert store.chats(imported, "三月七")[0]["answer"] == "因为你还在这里"


@pytest.mark.parametrize("corrupt", ["duplicate", "cycle", "dangling", "chat", "version"])
def test_import_rejects_invalid_graph_without_partial_writes(tmp_path, corrupt):
    store = StoryStore(tmp_path / "invalid.sqlite")
    root = store.add("开局", "选择", "三月七")
    data = json.loads(store.export(root))
    if corrupt == "duplicate":
        data["nodes"].append(data["nodes"][0])
    elif corrupt in {"cycle", "dangling"}:
        data["nodes"][0]["parent"] = root if corrupt == "cycle" else "missing"
    elif corrupt == "chat":
        data["chats"] = [{"node": "missing", "actor": "三月七", "question": "?", "answer": "!"}]
    else:
        data["version"] = 99
    with pytest.raises(ValueError):
        store.import_archive(json.dumps(data))
    assert len(store.nodes()) == 1


def test_settings_and_cards_persist(tmp_path):
    path = tmp_path / "settings.sqlite"
    store = StoryStore(path)
    profile = CaptureProfile(left=-1500, cast="三月七, 丹恒")
    store.save_setting("capture_profile", profile.model_dump())
    store.save_card(CharacterCard(name="丹恒", voice="简短、克制"))
    reopened = StoryStore(path)
    assert reopened.setting("capture_profile")["left"] == -1500
    assert reopened.cards()[0]["voice"] == "简短、克制"


def test_worker_stop_during_ocr_does_not_commit(tmp_path):
    entered = threading.Event()
    release = threading.Event()
    calls = 0

    def read():
        nonlocal calls
        calls += 1
        if calls == 2:
            entered.set()
            assert release.wait(4)
        return "三月七：等等。"

    service = CaptureService(tmp_path / "worker.sqlite", read)
    try:
        service.start(CaptureProfile(interval=.5))
        assert entered.wait(4)
        service.stop()
        release.set()
        service.close()
        assert service.status()["state"] == "stopped"
        assert service.store.nodes() == []
    finally:
        release.set()
        service.close()


def test_worker_errors_are_observable(tmp_path):
    failed = threading.Event()

    def read():
        failed.set()
        raise RuntimeError("unavailable")

    service = CaptureService(tmp_path / "failure.sqlite", read)
    service.start(CaptureProfile())
    assert failed.wait(3)
    service._thread.join(3)
    assert service.status()["state"] == "error"
    assert "RuntimeError" in service.status()["error"]
    assert service.store.nodes() == []


def test_worker_saves_without_ui_and_deduplicates_frames(tmp_path):
    sampled = threading.Event()
    release = threading.Event()
    count = 0

    def read():
        nonlocal count
        count += 1
        if count == 3:
            sampled.set()
            assert release.wait(4)
        return "三月七：出发吧。"

    service = CaptureService(tmp_path / "background.sqlite", read)
    try:
        service.start(CaptureProfile(interval=.5))
        assert sampled.wait(4)
        assert service.status()["saved"] == 1
        assert len(service.store.nodes()) == 1
        with pytest.raises(ValueError):
            service.start(CaptureProfile())
    finally:
        service.stop()
        release.set()
        service.close()
