"""检查跟踪接入后的会话隔离与取消清理，不访问物理摄像头。

使用合成图像、固定检测器和本机官方样例 JPEG，实际经过 Pipeline/FastAPI。
测试重点是不同视频不能串号、取消等待不能跳过正在运行的工作线程。
"""

import asyncio
import base64
import threading

import cv2
from fastapi.testclient import TestClient
import numpy as np
import pytest

from app.config import AppConfig
from app.pipeline import Pipeline
from app.schemas import Detection
from tests.test_ipcamera import TestDetector, sample_stream, service


class SyntheticDetector:
    """只按合成像素选择左右位置，供测试轨迹隔离；不代表真实模型效果。"""

    def __init__(self):
        self.config = AppConfig()

    def detect(self, image):
        """输入全暗或全亮的合成图像，输出一个已知像素框。"""
        left = 20.0 if image[0, 0, 0] < 100 else 200.0
        return [Detection(cls=0, name="person", score=0.9, xyxy=(left, 20.0, left + 40, 140.0))]


def test_pipeline_uses_independent_contexts_and_resets_only_one():
    """同一个检测器可服务不同视频，但各自轨迹状态与清理必须独立。"""
    async def check():
        pipeline = Pipeline(SyntheticDetector())
        first, second = pipeline.create_tracker(), pipeline.create_tracker()
        dark = np.zeros((180, 400, 3), dtype=np.uint8)
        light = np.full_like(dark, 200)
        first_result = await pipeline.process_frame(dark, 1, tracker=first)
        second_result = await pipeline.process_frame(light, 1, tracker=second)
        assert first_result.boxes[0].track_id == second_result.boxes[0].track_id == 1
        await pipeline.reset_tracker(first)
        again = await pipeline.process_frame(light, 2, tracker=second)
        assert again.boxes[0].track_id == 1
        assert first.snapshot()["frame_count"] == 0 and second.snapshot()["frame_count"] == 2
        await pipeline.reset_tracker(second)
    asyncio.run(check())


def test_cancelled_inference_is_finished_before_tracker_reset():
    """取消 async 等待不会终止底层线程；清理必须等它离开处理锁，再清掉迟到轨迹。"""
    started, release = threading.Event(), threading.Event()

    class BlockingDetector(SyntheticDetector):
        def detect(self, image):
            started.set()
            release.wait(timeout=3)
            return super().detect(image)

    async def check():
        pipeline = Pipeline(BlockingDetector())
        tracker = pipeline.create_tracker()
        task = asyncio.create_task(pipeline.process_frame(np.zeros((180, 400, 3), np.uint8), 1, tracker))
        cleanup = None
        try:
            assert await asyncio.to_thread(started.wait, 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            cleanup = asyncio.create_task(pipeline.reset_tracker(tracker))
            await asyncio.sleep(0.02)
            assert not cleanup.done()
        finally:
            release.set()
            if cleanup is not None:
                await cleanup
        assert tracker.snapshot()["frame_count"] == 0
    asyncio.run(check())


def test_browser_connections_do_not_share_tracking_history(service, monkeypatch, sample_stream):
    """关闭一条真实 WS 连接不能影响另一条连接的轨迹；这里只发送本机公开样例。"""
    monkeypatch.setattr(service, "Detector", TestDetector)
    contexts = []
    original = Pipeline.create_tracker

    def capture_context(pipeline):
        tracker = original(pipeline)
        contexts.append(tracker)
        return tracker

    monkeypatch.setattr(Pipeline, "create_tracker", capture_context)
    image = cv2.imdecode(np.frombuffer(sample_stream["jpeg"], np.uint8), cv2.IMREAD_COLOR)
    message = {"type": "frame", "seq": 1, "ts": 0, "w": image.shape[1], "h": image.shape[0],
               "img": base64.b64encode(sample_stream["jpeg"]).decode("ascii")}
    with TestClient(service.create_app(AppConfig())) as client:
        assert client.get("/api/health").json()["tracking"]["scope"] == "per_video_session"
        with client.websocket_connect("/ws/stream") as second:
            second.send_json(message)
            second_id = second.receive_json()["boxes"][0]["track_id"]
            with client.websocket_connect("/ws/stream") as first:
                first.send_json(message)
                assert first.receive_json()["boxes"][0]["track_id"] == 1
            second.send_json({**message, "seq": 2})
            assert second.receive_json()["boxes"][0]["track_id"] == second_id == 1
    assert len(contexts) == 2
    assert all(context.snapshot()["frame_count"] == 0 for context in contexts)
    assert sample_stream["requests"] == 0
