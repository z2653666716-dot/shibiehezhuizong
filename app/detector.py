"""封装 YOLO11n 单帧检测，属于 ViTrack 的检测模块。

输入是 AppConfig 和 OpenCV 的 BGR 图像数组，输出是 schemas.Detection 列表。
pipeline.py 负责调用本模块、转换前端坐标和计时；跟踪由后续独立 tracker.py 负责。
"""

import logging
import os
from pathlib import Path

import numpy as np

from .config import AppConfig, PROJECT_ROOT
from .schemas import Detection


logger = logging.getLogger(__name__)


class Detector:
    """持有一个可复用的 YOLO 模型，由后续应用启动流程创建一次。

    初始化输入为 AppConfig；detect 接收图像并返回像素坐标的 Detection 列表。
    同一个实例由后续流水线按顺序调用，避免每处理一帧都重新读取权重。
    """

    def __init__(self, config: AppConfig) -> None:
        """检查权重和运行设备，再加载本地 YOLO 模型。

        输入：经过配置模块检查的 AppConfig；输出：可执行 detect 的检测器实例。
        调用者是未来的应用启动流程；本方法调用 PyTorch 设备检查和 Ultralytics 加载。
        """
        # 先检查本地权重，避免库在文件名拼错时自动联网下载，掩盖路径问题。
        if not config.det_model.is_file():
            raise FileNotFoundError(
                f"找不到检测权重：{config.det_model}，请先运行 scripts/fetch_weights.ps1"
            )
        if config.det_model.suffix.lower() != ".pt":
            raise ValueError("DET_MODEL 应指向本阶段使用的 YOLO .pt 权重文件")

        self.config = config
        # 在导入第三方模型库前准备其配置与缓存目录；尊重用户已显式设置的位置。
        for variable, folder in {
            "YOLO_CONFIG_DIR": "ultralytics",
            "MPLCONFIGDIR": "matplotlib",
            "TORCH_HOME": "torch",
        }.items():
            cache_path = os.environ.setdefault(variable, str(PROJECT_ROOT / "work" / folder))
            Path(cache_path).mkdir(parents=True, exist_ok=True)

        # 延迟导入：只导入 detector 模块时不会加载 PyTorch 或初始化模型。
        # 依赖由环境脚本统一安装，处理帧期间禁止第三方库隐式运行 pip。
        os.environ["YOLO_AUTOINSTALL"] = "false"
        import torch
        from ultralytics import YOLO

        self.cuda_available = torch.cuda.is_available()
        logger.info("CUDA 可用：%s；所选设备：%s", self.cuda_available, config.det_device)
        if config.det_device != "cpu":
            if not self.cuda_available:
                raise RuntimeError("当前 PyTorch 无法使用 GPU，请检查环境或将 DET_DEVICE 改为 cpu")
            device_count = torch.cuda.device_count()
            if config.det_device >= device_count:
                raise RuntimeError(
                    f"GPU 编号 {config.det_device} 不存在，当前只有 {device_count} 张可用 GPU"
                )
            self.device_name = torch.cuda.get_device_name(config.det_device)
        else:
            self.device_name = "cpu"

        # 权重只在这里读取一次；task 明确指定本模块处理目标检测。
        self.model = YOLO(str(config.det_model), task="detect")
        logger.info("检测模型已加载：%s；设备名称：%s", config.det_model.name, self.device_name)

    def detect(self, frame_bgr: np.ndarray) -> list[Detection]:
        """对一张 BGR 图像执行检测，由流水线逐帧调用。

        输入：形状为 (高度, 宽度, 3)、像素类型为 uint8 的 NumPy 数组。
        输出：像素坐标的 Detection 列表；没有目标时返回空列表。
        处理顺序：检查输入 → 模型预测 → 转换 GPU 数据 → 构造标准结果。
        """
        if not isinstance(frame_bgr, np.ndarray):
            raise TypeError("检测输入必须是 OpenCV/NumPy 图像数组")
        if frame_bgr.dtype != np.uint8:
            raise ValueError("图像像素类型必须为 uint8，也就是每个通道取值 0～255")
        if (frame_bgr.ndim != 3 or frame_bgr.shape[2] != 3
                or frame_bgr.shape[0] == 0 or frame_bgr.shape[1] == 0):
            raise ValueError("图像必须是非空的三通道 BGR 彩色图，形状为 (高度, 宽度, 3)")

        # 翻转或切片产生的数组可能不是连续存储；需要时才复制，使模型接收稳定的布局。
        frame_bgr = np.ascontiguousarray(frame_bgr)
        config = self.config
        classes = None if config.target_classes is None else list(config.target_classes)
        prediction = self.model.predict(
            source=frame_bgr,
            imgsz=config.det_imgsz,
            conf=config.det_conf,
            iou=config.det_iou,
            classes=classes,
            device=config.det_device,
            save=False,
            stream=False,
            verbose=False,
        )[0]
        boxes = prediction.boxes
        if boxes is None or len(boxes) == 0:
            return []

        # GPU 张量不能直接交给普通 JSON；先搬到 CPU，再转成 Python 列表。
        all_coordinates = boxes.xyxy.detach().cpu().tolist()
        scores = boxes.conf.detach().cpu().tolist()
        class_ids = boxes.cls.detach().cpu().tolist()
        detections = []
        # 三组数据按同一索引对应；strict=True 在长度异常时立刻报错，避免字段错配。
        for box_coordinates, score, class_id in zip(all_coordinates, scores, class_ids, strict=True):
            left, top, right, bottom = box_coordinates
            # 边缘裁剪可能使框退化为一条线，此类框没有可裁剪面积，不向后续模块传递。
            if right <= left or bottom <= top:
                continue
            category = int(class_id)
            detections.append(Detection(
                cls=category,
                name=prediction.names[category],
                score=score,
                xyxy=(left, top, right, bottom),
            ))
        return detections
