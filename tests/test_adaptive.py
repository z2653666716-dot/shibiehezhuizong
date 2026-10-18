"""用可控时钟验证持续低帧率才降尺寸，避免短暂冷启动立即降低清晰度。"""
import asyncio
import itertools

import numpy as np

from app.config import AppConfig
from app.pipeline import Pipeline


def test_sustained_slow_frames_lower_capture_size(monkeypatch):
    """每次计时推进0.1秒，模拟慢检测；前30帧不降级，持续慢才建议480。"""
    import app.pipeline as module
    ticks = itertools.count()
    monkeypatch.setattr(module, "perf_counter", lambda: next(ticks) / 10)

    class EmptyDetector:
        def detect(self, frame):
            """返回空框，不需要图像识别、权重或设备。"""
            return []

    async def check():
        pipeline = Pipeline(EmptyDetector(), AppConfig())
        frame = np.zeros((32, 32, 3), np.uint8)
        for seq in range(30):
            result = await pipeline.process_frame(frame, seq)
            assert result.capture_max_side == 640
        for seq in range(30, 65):
            result = await pipeline.process_frame(frame, seq)
        assert result.capture_max_side == 480
    asyncio.run(check())
