"""封装 ByteTrack 帧间关联，属于 P3 的轨迹编号与生命周期模块。

输入为 Detector 返回的像素框和真实图像尺寸，输出带可选 track_id 的前端 Box。
只保存数值轨迹，不保存图像；每个视频会话单独创建 Tracker，由 Pipeline 串行调用。
当前分数与人数沿用本帧检测，丢失轨迹只在内部保留，不绘制不存在的目标。
"""

import os
import threading
from types import SimpleNamespace

import numpy as np

from .config import AppConfig, PROJECT_ROOT
from .schemas import Box, Detection


class Tracker:
    """为一个视频会话提供 update/reset/snapshot；轨迹编号不代表具体人物身份。

    输入配置里的 TRACK_MAX_AGE 决定丢失后保留多少个已处理帧，不是秒数。
    各类别分别关联，公开编号在本会话内递增，尺寸重置后也不复用旧编号。
    """

    def __init__(self, config: AppConfig) -> None:
        """加载已安装包内的 ByteTrack 配置，不加载 YOLO、不联网；后续由 Pipeline 创建。"""
        if config.tracker != "bytetrack.yaml":
            raise ValueError("当前只支持已安装包内的 bytetrack.yaml")
        os.environ.setdefault("YOLO_CONFIG_DIR", str(PROJECT_ROOT / "work" / "ultralytics"))
        os.environ.setdefault("MPLCONFIGDIR", str(PROJECT_ROOT / "work" / "matplotlib"))
        os.environ["YOLO_AUTOINSTALL"] = "false"
        # 延迟导入：只导入本项目 tracker 模块时不初始化第三方依赖，也不会打开设备。
        from ultralytics.engine.results import Boxes
        from ultralytics.trackers.byte_tracker import BYTETracker
        from ultralytics.utils import ROOT, YAML

        settings = YAML.load(ROOT / "cfg" / "trackers" / "bytetrack.yaml")
        settings["track_buffer"] = config.track_max_age
        self._settings = settings
        self._engine_type = BYTETracker
        self._boxes_type = Boxes
        self._lock = threading.RLock()
        self._engines = {}
        self._public_ids = {}
        self._next_id = 1
        self._size = None
        self._frame_count = 0

    def reset(self) -> None:
        """无输入，丢弃本会话旧轨迹；保留编号计数，防止旧选择误指向重置后的新目标。"""
        with self._lock:
            self._engines.clear()
            self._public_ids.clear()
            self._size = None
            self._frame_count = 0

    def update(self, detections: list[Detection], width: int, height: int) -> list[Box]:
        """接收当前像素检测和尺寸，输出同数量/同顺序的 Box，由 Pipeline 的处理线程调用。

        先校验并归一化，再按类别送给 ByteTrack；利用返回的当前检测索引绑定编号。
        未确认的新目标仍可显示白框，但 track_id 为 None；没有检测的目标不补画预测框。
        """
        if any(isinstance(size, bool) or not isinstance(size, int) or size <= 0 for size in (width, height)):
            raise ValueError("跟踪图像尺寸必须为正整数")
        if not isinstance(detections, list) or any(not isinstance(item, Detection) for item in detections):
            raise TypeError("Tracker.update 需要 Detection 列表")
        output = [Box.from_detection(item, width, height) for item in detections]
        with self._lock:
            if self._size != (width, height):
                self.reset()
                self._size = (width, height)
            self._frame_count += 1
            groups = {}
            for index, item in enumerate(detections):
                groups.setdefault(item.cls, []).append(index)
            for category in sorted(set(groups) | set(self._engines)):
                if category not in self._engines:
                    # 当前已安装版本直接以 track_buffer 作为保留帧数，不再接受 frame_rate 参数。
                    self._engines[category] = self._engine_type(SimpleNamespace(**self._settings))
                engine = self._engines[category]
                indices = groups.get(category, [])
                # 每行是 [左, 上, 右, 下, 分数, 类别]；空帧也更新，让丢失帧数正常递增。
                values = np.asarray([
                    [*detections[index].xyxy, detections[index].score, category] for index in indices
                ], dtype=np.float32).reshape(-1, 6)
                rows = engine.update(self._boxes_type(values, (height, width)))
                for row in rows:
                    local_index, internal_id = int(row[-1]), int(row[4])
                    if row[-1] != local_index or not 0 <= local_index < len(indices) or internal_id <= 0:
                        raise RuntimeError("ByteTrack 返回了无效的当前检测索引或轨迹编号")
                    key = (category, internal_id)
                    if key not in self._public_ids:
                        self._public_ids[key] = self._next_id
                        self._next_id += 1
                    # 只补编号，仍使用当前 Detection 的原始坐标和分数；显示平滑由前端负责。
                    output[indices[local_index]].track_id = self._public_ids[key]
            live_keys = {
                (category, track.track_id)
                for category, engine in self._engines.items()
                for track in [*engine.tracked_stracks, *engine.lost_stracks]
            }
            # 过期轨迹的映射也移除，避免长时间运行时历史编号表无限增长。
            self._public_ids = {key: value for key, value in self._public_ids.items() if key in live_keys}
        return output

    def snapshot(self) -> dict:
        """无输入，输出当前/暂时丢失的编号和处理帧数，供测试与后续锁定流程查询；不含图像。"""
        with self._lock:
            active, lost = [], []
            for category, engine in self._engines.items():
                for tracks, target in ((engine.tracked_stracks, active), (engine.lost_stracks, lost)):
                    for track in tracks:
                        public_id = self._public_ids.get((category, track.track_id))
                        if public_id is not None:
                            target.append(public_id)
            return {"active_ids": sorted(active), "lost_ids": sorted(lost), "frame_count": self._frame_count}
