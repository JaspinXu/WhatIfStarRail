"""A process-owned capture worker: browser reruns only observe its status."""
from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from astral_agents.companion import StoryStore, SubtitleBuffer, capture_subtitles
from astral_agents.companion_models import CaptureProfile, IngestEvent


class CaptureService:
    def __init__(self, database: Path, read_frame=None):
        self.store = StoryStore(database)
        self._read_frame = read_frame
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._status = {"state": "stopped", "frames": 0, "saved": 0,
                        "last_text": "", "last_node": None, "last_seen": None,
                        "latency_ms": 0, "error": "", "timeline": ""}

    def status(self):
        with self._lock:
            return dict(self._status)

    def start(self, profile: CaptureProfile, *, new_timeline=False):
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise ValueError("采集器正在运行或停止中，请先停止后再启动")
            timeline = self.store.setting("capture_timeline")
            if new_timeline or not timeline:
                timeline = uuid4().hex
                self.store.save_setting("capture_timeline", timeline)
            self._stop.clear()
            self._status.update(state="starting", error="", timeline=timeline)
            self._thread = threading.Thread(target=self._run, args=(profile, timeline),
                                            name="whatif-capture", daemon=True)
            self._thread.start()

    def stop(self):
        with self._lock:
            self._stop.set()
            if self._thread and self._thread.is_alive():
                self._status["state"] = "stopping"

    def close(self):
        self.stop()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self, profile, timeline):
        buffer = SubtitleBuffer()
        # Do not duplicate the last visible subtitle after pausing/restarting.
        previous = self.store.setting("capture_last", {})
        if previous.get("timeline") == timeline:
            buffer.last = previous.get("text", "")
        try:
            if self._read_frame:
                read = self._read_frame
            else:
                from rapidocr_onnxruntime import RapidOCR
                reader = RapidOCR()
                def read():
                    return capture_subtitles(profile.region(), reader, profile.confidence)
            with self._lock:
                if not self._stop.is_set():
                    self._status["state"] = "running"
            while not self._stop.is_set():
                started = time.perf_counter()
                raw = read()
                with self._lock:
                    if self._stop.is_set():
                        break
                    self._status.update(frames=self._status["frames"] + 1,
                                        last_text=raw, last_seen=datetime.now(UTC).isoformat(),
                                        latency_ms=round((time.perf_counter() - started) * 1000))
                    text = buffer.push(raw)
                    if text:
                        event = IngestEvent(source="desktop-ocr", event_id=uuid4().hex,
                                            timeline=timeline, title=f"实况 · {text[:36]}",
                                            text=text, cast=profile.cast)
                        node_id, _ = self.store.ingest(event)
                        self.store.save_setting("capture_last", {"timeline": timeline, "text": text})
                        self._status.update(saved=self._status["saved"] + 1, last_node=node_id)
                self._stop.wait(profile.interval)
        except Exception as exc:
            with self._lock:
                self._status.update(state="error", error=f"{type(exc).__name__}：采集已停止，请检查依赖与字幕区域后重试")
        finally:
            with self._lock:
                if self._status["state"] != "error":
                    self._status["state"] = "stopped"
