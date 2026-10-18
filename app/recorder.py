"""可选的标注视频录制；默认禁止保存，只有服务配置和启动请求双重允许才写媒体。

VideoSession 调用 write，结束时 release；测试只用合成画面，实际用户画面禁止落盘。
"""
from datetime import datetime
import json
from pathlib import Path
from time import monotonic
from uuid import uuid4

import cv2

from .config import PROJECT_ROOT


class Recorder:
    """输入帧/框，输出本机mp4与数值jsonl；不访问摄像头，也不主动开始录制。"""

    def __init__(self, config, directory=None):
        self.config = config
        self.directory = Path(directory) if directory else PROJECT_ROOT / "outputs/recordings"
        self.writer = None
        self.path = None
        self.event_stream = None
        self.size = None
        self.frames = 0
        self.last_write = float("-inf")

    def start(self, width, height, confirm=False):
        """显式双重允许后创建输出，输入初始尺寸，返回录制状态；默认拒绝落盘。"""
        if not self.config.allow_media_save or confirm is not True:
            raise PermissionError("当前禁止保存画面，录制不可用")
        if self.writer is not None:
            return self.status()
        if width < 1 or height < 1:
            raise ValueError("请先开始检测，收到画面后再录制")
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / ("annotated_" + datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid4().hex[:12] + ".mp4")
        # 常见mp4编码要求偶数尺寸；后续逐帧按这一尺寸等比缩放并填边。
        self.size = (max(2, width // 2 * 2), max(2, height // 2 * 2))
        writer = cv2.VideoWriter(str(self.path), cv2.VideoWriter_fourcc(*"mp4v"), self.config.record_fps, self.size)
        if not writer.isOpened():
            writer.release()
            raise RuntimeError("当前环境无法创建 MP4，请检查 OpenCV 编码支持")
        self.writer = writer
        self.event_stream = self.path.with_suffix(".jsonl").open("w", encoding="utf-8")
        self.frames = 0
        self.last_write = float("-inf")
        return self.status()

    def write(self, frame, boxes, seq, events=()):
        """输入当前BGR与归一化框，限速写标注帧；数值事件全部保留，不保存原始帧。"""
        if self.writer is None:
            return
        for event in events:
            self.event_stream.write(json.dumps({"seq": seq, **event}, ensure_ascii=False) + "\n")
        now = monotonic()
        if now - self.last_write < 1 / self.config.record_fps:
            return
        canvas = frame.copy()
        height, width = canvas.shape[:2]
        for box in boxes:
            color = (90, 220, 60) if box.state == "locked" else (255, 255, 255)
            x1, y1, x2, y2 = (int(value * (width if index % 2 == 0 else height)) for index, value in enumerate(box.xyxy))
            cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)
            label = box.identity_id or f"{box.name} #{box.track_id} {box.score:.2f}"
            cv2.putText(canvas, label, (x1, max(16, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, .5, color, 1, cv2.LINE_AA)
        target_width, target_height = self.size
        ratio = min(target_width / width, target_height / height)
        resized = cv2.resize(canvas, (max(1, round(width * ratio)), max(1, round(height * ratio))))
        import numpy as np
        output = np.zeros((target_height, target_width, 3), dtype=np.uint8)
        left, top = (target_width - resized.shape[1]) // 2, (target_height - resized.shape[0]) // 2
        output[top:top + resized.shape[0], left:left + resized.shape[1]] = resized
        self.writer.write(output)
        self.frames += 1
        self.last_write = now
        if self.frames % 30 == 0:
            self.event_stream.write(json.dumps({"seq": seq, "recorded_frames": self.frames,
                "bindings": [{"track_id": box.track_id, "identity_id": box.identity_id} for box in boxes]}) + "\n")
            self.event_stream.flush()

    def stop(self):
        """无输入，关闭写入器/事件文件并返回结果；多次停止安全。"""
        if self.writer is not None:
            self.writer.release()
            self.writer = None
        if self.event_stream is not None:
            self.event_stream.close()
            self.event_stream = None
        return self.status()

    def status(self):
        """返回是否允许、是否录制、文件名与已写帧数，不暴露磁盘绝对路径。"""
        return {"allowed": self.config.allow_media_save, "active": self.writer is not None,
                "filename": self.path.name if self.path else None, "frames": self.frames}
