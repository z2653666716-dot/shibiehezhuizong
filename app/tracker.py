"""封装ByteTrack与实验BoT-SORT帧间关联，负责轨迹编号和生命周期。

输入为 Detector 返回的像素框和真实图像尺寸，输出带可选 track_id 的前端 Box。
ByteTrack只保存数值；BoT-SORT的相机运动估计短暂保留上一帧灰度内存，不落盘。
每个视频会话单独创建Tracker，由Pipeline串行调用，reset时丢弃全部会话状态。
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
        if config.tracker not in {"bytetrack.yaml", "botsort.yaml"}:
            raise ValueError("只支持已安装包内的bytetrack.yaml或botsort.yaml")
        os.environ.setdefault("YOLO_CONFIG_DIR", str(PROJECT_ROOT / "work" / "ultralytics"))
        os.environ.setdefault("MPLCONFIGDIR", str(PROJECT_ROOT / "work" / "matplotlib"))
        os.environ["YOLO_AUTOINSTALL"] = "false"
        # 延迟导入：只导入本项目 tracker 模块时不初始化第三方依赖，也不会打开设备。
        from ultralytics.engine.results import Boxes
        from ultralytics.trackers.byte_tracker import BYTETracker
        from ultralytics.trackers.bot_sort import BOTSORT
        from ultralytics.utils import ROOT, YAML

        settings = YAML.load(ROOT / "cfg" / "trackers" / config.tracker)
        settings["track_buffer"] = config.track_max_age
        self._appearance = config.tracker == "botsort.yaml"
        if self._appearance:
            # 禁止第三方隐式下载ReID模型；只通过本项目已校验的本地编码器提供特征。
            settings.update(with_reid=False, model="auto", gmc_method="sparseOptFlow")
        self._settings = settings
        self._engine_type = BOTSORT if self._appearance else BYTETracker
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

    def update(self, detections: list[Detection], width: int, height: int, image=None, extractor=None) -> list[Box]:
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
                if self._appearance:
                    if image is None or extractor is None:
                        raise ValueError("BoT-SORT需要当前内存帧和已加载的本地行人编码器")
                    engine.args.with_reid = category == 0
                    engine.encoder = self.appearance_encoder(extractor) if category == 0 else None
                indices = groups.get(category, [])
                # 每行是 [左, 上, 右, 下, 分数, 类别]；空帧也更新，让丢失帧数正常递增。
                values = np.asarray([
                    [*detections[index].xyxy, detections[index].score, category] for index in indices
                ], dtype=np.float32).reshape(-1, 6)
                rows = engine.update(self._boxes_type(values, (height, width)), image) if self._appearance else engine.update(self._boxes_type(values, (height, width)))
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

    @staticmethod
    def appearance_encoder(extractor):
        """适配BoT-SORT的中心点/宽高框，返回OSNet外观特征，颜色不参与运动关联。"""
        def encode(image, boxes):
            from .reid import crop_target
            height, width = image.shape[:2]
            crops = []
            for row in boxes:
                center_x, center_y, box_width, box_height = row[:4]
                left, top = max(0, int(center_x - box_width / 2)), max(0, int(center_y - box_height / 2))
                right, bottom = min(width, int(center_x + box_width / 2)), min(height, int(center_y + box_height / 2))
                # 检测器本来只返回有效框；碰到越界空框时明确失败，不能给错误人物拼接随机特征。
                if right <= left or bottom <= top:
                    raise ValueError("BoT-SORT收到空人物裁剪")
                crop = crop_target(image, ((center_x - box_width / 2) / width,
                                          (center_y - box_height / 2) / height,
                                          (center_x + box_width / 2) / width,
                                          (center_y + box_height / 2) / height))
                # 极小目标不能构成身份模板，但仍允许运动层用其非空原框关联位置。
                crops.append(crop if crop is not None else image[top:bottom, left:right])
            fused = extractor.extract(crops)
            return [value[:-128] / max(float(np.linalg.norm(value[:-128])), 1e-8) for value in fused]
        return encode

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
