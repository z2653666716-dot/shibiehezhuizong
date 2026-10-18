"""保存一路视频的目标、锁定身份与最新帧，仅在内存中工作。

Pipeline 创建和串行调用本模块；HTTP 操作通过随机会话凭据访问，避免多路视频串号。
"""

from dataclasses import dataclass
from secrets import token_urlsafe
from time import monotonic

from .schemas import IdentitySummary
from .tracker import Tracker


class SessionError(ValueError):
    """向接口提供可直接显示的错误码与中文说明。"""

    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass
class Observation:
    """一条轨迹的观测次数和身份；输入跟踪号，供锁定前检查目标是否稳定。"""

    hits: int = 0
    last_frame: int = 0
    identity_id: str | None = None


class VideoSession:
    """组合独立 Tracker 与锁定状态；token 只在当前视频连接存活时有效。"""

    def __init__(self, config):
        self.config = config
        self.tracker = Tracker(config)
        self.token = token_urlsafe(32)
        self.observations = {}
        self.identities = {}
        self.boxes = []
        self.seq = -1
        self.frame_count = 0
        self.updated_at = monotonic()
        self.next_identity = 1

    def update(self, detections, width, height):
        """接收当前像素框，更新帧间关联并统计连续观测，输出可显示的框。"""
        self.boxes = self.tracker.update(detections, width, height)
        self.frame_count += 1
        self.updated_at = monotonic()
        for box in self.boxes:
            if box.track_id is None:
                continue
            track = self.observations.setdefault(box.track_id, Observation())
            track.hits = track.hits + 1 if track.last_frame == self.frame_count - 1 else 1
            track.last_frame = self.frame_count
            if track.identity_id in self.identities:
                # model_copy 一次更新有关联的字段，避免赋值中间态违反 Box 的状态检查。
                self.boxes[self.boxes.index(box)] = box.model_copy(update={
                    "identity_id": track.identity_id, "state": "locked"})
        self.observations = {key: item for key, item in self.observations.items()
                             if self.frame_count - item.last_frame <= self.config.track_max_age}
        return self.boxes

    def lock(self, track_id, seq):
        """HTTP 锁定输入轨迹号/帧号，目标当前存在且稳定时返回身份编号。"""
        visible = any(box.track_id == track_id for box in self.boxes)
        if not visible or monotonic() - self.updated_at > 3 or seq > self.seq or self.seq - seq > 30:
            raise SessionError("TRACK_GONE", "目标已离开画面或画面已过期，请重新选择")
        track = self.observations[track_id]
        if track.hits < 5:
            raise SessionError("REID_NOT_WARM", "请让目标在画面中停留片刻后再按住")
        if track.identity_id not in self.identities:
            identity_id = f"ID-{self.next_identity:02d}"
            self.next_identity += 1
            self.identities[identity_id] = "长按锁定"
            track.identity_id = identity_id
        return {"ok": True, "identity_id": track.identity_id}

    def select(self, x, y, seq):
        """输入未镜像的归一化触点，只在命中的框中挑最小框，不锁定空白处的远处目标。"""
        hits = [box for box in self.boxes if box.track_id is not None
                and box.xyxy[0] <= x <= box.xyxy[2] and box.xyxy[1] <= y <= box.xyxy[3]]
        if not hits:
            raise SessionError("TRACK_GONE", "请按住目标框内")
        box = min(hits, key=lambda item: (item.xyxy[2] - item.xyxy[0]) * (item.xyxy[3] - item.xyxy[1]))
        return self.lock(box.track_id, seq)

    def summaries(self):
        """输出身份条；只将本帧可见且绑定的身份标为在线。"""
        online = {box.identity_id for box in self.boxes if box.identity_id}
        return [IdentitySummary(id=key, name=name, online=key in online)
                for key, name in self.identities.items()]

    def delete(self, identity_id):
        """删除指定身份并解除所有轨迹绑定，不删除或保存任何画面。"""
        if identity_id not in self.identities:
            raise SessionError("IDENTITY_NOT_FOUND", "身份不存在")
        del self.identities[identity_id]
        for track in self.observations.values():
            if track.identity_id == identity_id:
                track.identity_id = None

    def reset(self):
        """视频结束时丢弃跟踪与身份内存，新的连接必须重新注册。"""
        self.tracker.reset()
        self.observations.clear()
        self.identities.clear()
        self.boxes = []

    def snapshot(self):
        """兼容跟踪检查接口，只返回数值状态。"""
        return self.tracker.snapshot()
