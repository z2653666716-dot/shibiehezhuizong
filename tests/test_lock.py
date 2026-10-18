"""用合成检测和本机公开图片检查锁定接口，不访问设备或保存媒体。"""
import base64

from fastapi.testclient import TestClient

from app.config import AppConfig
from tests.test_ipcamera import TestDetector, service, sample_stream, wait_for


def test_lock_lifecycle(service, monkeypatch, sample_stream):
    """验证目标未稳定/过期、两会话隔离、锁定变绿、身份删除和断开失效。"""
    monkeypatch.setattr(service, "Detector", TestDetector)
    import cv2
    import numpy as np
    image = cv2.imdecode(np.frombuffer(sample_stream["jpeg"], np.uint8), cv2.IMREAD_COLOR)
    frame = {"type": "frame", "seq": 1, "ts": 0, "w": image.shape[1], "h": image.shape[0],
             "img": base64.b64encode(sample_stream["jpeg"]).decode()}
    with TestClient(service.create_app(AppConfig())) as client:
        with client.websocket_connect("/ws/stream") as ws:
            ws.send_json(frame)
            first = ws.receive_json()
            action = {"session_id": first["session_id"], "track_id": 1, "seq": 1}
            assert client.post("/api/lock", json=action).json()["code"] == "REID_NOT_WARM"
            for seq in range(2, 6):
                ws.send_json({**frame, "seq": seq}); ws.receive_json()
            action["seq"] = 5
            assert client.post("/api/lock", json={**action, "track_id": 999}).json()["code"] == "TRACK_GONE"
            assert client.post("/api/lock", json=action).json()["identity_id"] == "ID-01"
            ws.send_json({**frame, "seq": 6})
            result = ws.receive_json()
            assert result["boxes"][0]["state"] == "locked"
            assert result["identities"][0]["online"]
            denied = client.post("/api/record/start", json={"session_id": action["session_id"], "confirm": True})
            assert denied.json()["code"] == "MEDIA_SAVE_FORBIDDEN"
            assert client.post("/api/select", json={"session_id": action["session_id"], "seq": 6,
                                                    "x": 0.99, "y": 0.99}).json()["code"] == "TRACK_GONE"
            with client.websocket_connect("/ws/stream") as other:
                other.send_json(frame)
                second = other.receive_json()
                assert second["boxes"][0]["state"] == "none"
                assert second["session_id"] != action["session_id"]
            assert client.delete("/api/identities/ID-01", params={"session_id": action["session_id"]}).status_code == 200
        # WS 断开后服务端需要异步等待在途线程收尾；等清理真正完成再断言凭据失效。
        wait_for(lambda: action["session_id"] not in client.app.state.pipeline.sessions)
        assert client.get("/api/identities", params={"session_id": action["session_id"]}).json()["code"] == "SESSION_GONE"
    assert sample_stream["requests"] == 0
