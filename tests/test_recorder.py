"""验证默认禁止媒体保存，以及合成画面的MP4编码/回读；不使用摄像头素材。"""
import cv2
import numpy as np
import pytest

from app.config import AppConfig
from app.recorder import Recorder
from app.schemas import Box


def test_recording_denied_creates_no_files(tmp_path):
    """默认策略即使请求confirm也拒绝，且不会创建媒体目录。"""
    directory = tmp_path / "forbidden"
    recorder = Recorder(AppConfig(), directory)
    with pytest.raises(PermissionError): recorder.start(320, 240, confirm=True)
    assert not directory.exists()


def test_synthetic_mp4_is_readable_and_closes(tmp_path, monkeypatch):
    """只把人工生成的色块和框编码成视频，检查尺寸变化、事件与重复停止。"""
    import app.recorder as module
    clock = iter(range(100))
    monkeypatch.setattr(module, "monotonic", lambda: float(next(clock)))
    recorder = Recorder(AppConfig(allow_media_save=True), tmp_path / "synthetic")
    with pytest.raises(PermissionError): recorder.start(320, 240)
    assert recorder.start(320, 240, confirm=True)["active"]
    box = Box(cls=0, name="person", score=.9, track_id=1, xyxy=(.2, .1, .7, .9),
              state="locked", identity_id="ID-01")
    for seq in range(60):
        frame = np.full((240 if seq < 30 else 320, 320 if seq < 30 else 240, 3), (80, 40, 10), np.uint8)
        recorder.write(frame, [box], seq, [{"name": "synthetic_test", "identity_id": "ID-01"}] if seq == 0 else [])
    assert recorder.stop()["frames"] == 60
    assert recorder.stop()["active"] is False
    capture = cv2.VideoCapture(str(recorder.path))
    try:
        assert capture.isOpened()
        assert int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) == 60
        ok, frame = capture.read()
        assert ok and frame.shape == (240, 320, 3)
        # 标注绿框应产生明显高于红蓝通道的绿色像素。
        assert np.any(frame[:, :, 1].astype(int) - frame[:, :, 2].astype(int) > 50)
    finally:
        capture.release()
    text = recorder.path.with_suffix(".jsonl").read_text(encoding="utf-8")
    assert "synthetic_test" in text and '"recorded_frames": 60' in text
