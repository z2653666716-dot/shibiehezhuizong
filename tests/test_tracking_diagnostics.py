"""验证手势与身份拒绝诊断可关联且不泄露媒体/向量；输入仅合成颜色和已知数值。"""
import json
import logging
from time import monotonic

import pytest
from fastapi.testclient import TestClient

from app.config import AppConfig
from tests.test_ipcamera import service
from tests.test_single_target import colored_session, advance
from scripts.analyze_tracking import read_events, summarize


@pytest.fixture
def records():
    """临时收集app.session的受控文字，不读取用户画面或正式日志文件。"""
    output = []

    class Collector(logging.Handler):
        def emit(self, record):
            if record.getMessage().startswith("TRACK_DIAG "):
                output.append(json.loads(record.getMessage().split("TRACK_DIAG ", 1)[1]))

    target = logging.getLogger("app.session")
    handler, previous_level = Collector(), target.level
    target.addHandler(handler)
    target.setLevel(logging.INFO)
    try:
        yield output
    finally:
        target.removeHandler(handler)
        target.setLevel(previous_level)


def test_logs_distinguish_success_from_next_frame_rejection(records, tmp_path):
    """先真实锁定合成目标，再保持同一轨迹换外观；必须记下成功和后续拒绝，不能当作取消。"""
    session, frame = colored_session()
    track_id = session.boxes[0].track_id
    session.lock(track_id, session.seq, "lock")
    advance(session, frame)
    changed = frame.copy()
    changed[:, :160] = (240, 0, 0)
    advance(session, changed)
    success = next(item for item in records if item["event"] == "lock_result")
    rejected = next(item for item in records if item["event"] == "identity_unbound")
    assert success["action"] == "locked" and rejected["seq"] > success["seq"]
    assert rejected["session"] == success["session"] == session.trace_id
    assert rejected["track_id"] == success["track_id"] == track_id
    assert rejected["check"]["reason"] == "FUSED_SCORE_LOW"
    assert rejected["check"]["score"] < rejected["check"]["high"]
    text = json.dumps(records)
    assert session.token not in text
    assert "templates" not in text and "thumbnail" not in text and "base64" not in text
    # 同一拒绝原因持续12帧，不应每帧刷一条相同拒绝消息。
    before = sum(item["event"] == "candidate_rejected" for item in records)
    for _ in range(12):
        advance(session, changed)
    assert sum(item["event"] == "candidate_rejected" for item in records) == before
    # 用实际产生的匿名记录验证分析工具能找出“请求成功后被核验拒绝”的完整链路。
    path = tmp_path / "synthetic_diagnostics.log"
    path.write_text("\n".join("TRACK_DIAG " + json.dumps(item) for item in records), encoding="utf-8")
    report = summarize(read_events([path]))
    assert report["locked_then_rejected"][0]["reason"] == "FUSED_SCORE_LOW"
    assert report["locked_then_rejected"][0]["locked_seq"] < report["locked_then_rejected"][0]["rejected_seq"]


def test_diagnostic_endpoint_restricts_content_and_session(service, records):
    """接口只接受会话内的有限枚举/数字，拒绝媒体字段、任意文字和过量事件。"""
    with TestClient(service.create_app(AppConfig(det_device="cpu", reid_model="color_histogram"))) as client:
        tracker = client.app.state.pipeline.create_tracker()
        event = {"session_id": tracker.token, "seq": 0, "track_id": 1,
                 "event": "press_start", "pointer": "touch"}
        assert client.post("/api/interaction-events", json={**event, "img": "never log this"}).status_code == 422
        assert client.post("/api/interaction-events", json={**event, "reason": "arbitrary text"}).status_code == 422
        assert client.post("/api/interaction-events", json={**event, "session_id": "x" * 32}).status_code == 409
        assert client.post("/api/interaction-events", json=event).json()["recorded"] is True
        assert any(item["event"] == "client_gesture" for item in records)
        tracker._interaction_times.clear()
        tracker._interaction_times.extend([monotonic()] * 10)
        assert client.post("/api/interaction-events", json=event).json()["recorded"] is False
        assert tracker.token not in json.dumps(records)
        assert client.get("/api/health").json()["diagnostics"]["identity_rejection_reasons"] is True
