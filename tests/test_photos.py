"""检查照片注册、缩略图清理与错误输入；仅使用公开样例/合成图片。"""
import base64

import cv2
from fastapi.testclient import TestClient
import numpy as np

from app.config import AppConfig
from app.schemas import Detection
from tests.test_ipcamera import TestDetector, service, sample_stream, wait_for


class PhotoDetector(TestDetector):
    """合成边界测试：黑图无人，其他图两个框；只用于接口，不声称真实检测结果。"""
    def detect(self, image):
        if float(image.mean()) < 1:
            return []
        height, width = image.shape[:2]
        return super().detect(image) + [Detection(cls=0, name="person", score=0.85,
            xyxy=(width * .7, height * .1, width * .8, height * .4))]


def test_photo_register_errors_and_memory_cleanup(service, monkeypatch, sample_stream):
    """multipart登记最大人物、无人/损坏/超大拒绝、缩略图仅当前会话可读、删除后消失。"""
    monkeypatch.setattr(service, "Detector", PhotoDetector)
    config = AppConfig(det_device="cpu", reid_model="color_histogram")
    image = cv2.imdecode(np.frombuffer(sample_stream["jpeg"], np.uint8), cv2.IMREAD_COLOR)
    frame = {"seq": 1, "ts": 0, "w": image.shape[1], "h": image.shape[0],
             "img": base64.b64encode(sample_stream["jpeg"]).decode()}
    with TestClient(service.create_app(config)) as client:
        with client.websocket_connect("/ws/stream") as ws:
            ws.send_json(frame)
            session = ws.receive_json()["session_id"]
            params = {"session_id": session}
            response = client.post("/api/identities/photo", params=params,
                files={"photo": ("public.jpg", sample_stream["jpeg"], "image/jpeg")})
            body = response.json()
            assert response.status_code == 200 and body["code"] == "MULTI_PERSON_PHOTO"
            assert body["quality"]["person_count"] == 2
            thumbnail = client.get(body["thumb"])
            assert thumbnail.content.startswith(b"\xff\xd8") and thumbnail.headers["cache-control"] == "no-store"
            assert client.get(body["thumb"].split("?")[0], params={"session_id": "wrong"}).json()["code"] == "SESSION_GONE"
            ws.send_json({**frame, "seq": 2})
            assert ws.receive_json()["identities"][0]["thumb"] == body["thumb"]
            # 删除必须同时清掉特征与内存缩略图。
            assert client.delete("/api/identities/ID-01", params=params).status_code == 200
            assert client.get(body["thumb"]).json()["code"] == "IDENTITY_NOT_FOUND"
            empty = cv2.imencode(".jpg", np.zeros((64, 64, 3), np.uint8))[1].tobytes()
            assert client.post("/api/identities/photo", params=params, content=empty,
                               headers={"Content-Type": "image/jpeg"}).json()["code"] == "NO_TARGET_IN_PHOTO"
            assert client.post("/api/identities/photo", params=params, content=b"invalid").json()["code"] == "BAD_PHOTO"
            assert client.post("/api/identities/photo", params=params,
                               content=b"x" * (6 * 1024 * 1024 + 1)).json()["code"] == "PHOTO_TOO_LARGE"
        wait_for(lambda: session not in client.app.state.pipeline.sessions)
        assert client.get(body["thumb"]).json()["code"] == "SESSION_GONE"
    assert sample_stream["requests"] == 0
