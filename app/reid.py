"""将人物裁剪转换为外观向量，供视频会话与照片注册共用；不保存或上传图片。

MobileNetV3 读取本地校验过的预训练权重。颜色降级模式须由配置明确选择，不能静默替代。
"""
import cv2
import numpy as np


def normalize(vector):
    """输入有限非零向量，输出单位长度 float32 向量，供余弦匹配与 EMA 使用。"""
    vector = np.asarray(vector, dtype=np.float32).reshape(-1)
    length = float(np.linalg.norm(vector))
    if not np.isfinite(vector).all() or length <= 1e-8:
        raise ValueError("外观特征为空或包含无效数值")
    return vector / length


def cosine(first, second):
    """输入两个等维特征，输出 -1～1 相似度；不会把相似度称为身份概率。"""
    return float(np.clip(np.dot(normalize(first), normalize(second)), -1, 1))


def crop_target(frame, xyxy, padding=0.1):
    """输入 BGR 帧及归一化框，向外扩边后裁剪；只返回独立的内存数组。"""
    height, width = frame.shape[:2]
    left, top, right, bottom = xyxy
    dx, dy = (right - left) * padding, (bottom - top) * padding
    x1, y1 = max(0, int((left - dx) * width)), max(0, int((top - dy) * height))
    x2, y2 = min(width, int(np.ceil((right + dx) * width))), min(height, int(np.ceil((bottom + dy) * height)))
    if x2 - x1 < 8 or y2 - y1 < 16:
        return None
    return frame[y1:y2, x1:x2].copy()


class FeatureExtractor:
    """输入人物裁剪列表，输出每人一个特征；外观 576 维，HSV 颜色 128 维。"""

    def __init__(self, config):
        self.config = config
        self.model = None
        if config.reid_model == "osnet_x0_25":
            raise ValueError("可选 OSNet 后端未安装，请使用 mobilenet_v3_small 或显式选择 color_histogram")
        if config.reid_model == "mobilenet_v3_small":
            import torch
            from torchvision.models import mobilenet_v3_small
            if not config.reid_weights.is_file():
                raise FileNotFoundError("缺少本地外观权重，请运行 scripts/fetch_reid_weights.py")
            self.torch = torch
            self.device = torch.device("cpu" if config.det_device == "cpu" else f"cuda:{config.det_device}")
            model = mobilenet_v3_small(weights=None)
            model.load_state_dict(torch.load(config.reid_weights, map_location="cpu", weights_only=True))
            # 去掉分类器，只保留卷积和全局池化得到 576 维描述。
            self.model = torch.nn.Sequential(model.features, model.avgpool, torch.nn.Flatten()).eval().to(self.device)
            self.mean = torch.tensor([0.485, 0.456, 0.406], device=self.device)[None, :, None, None]
            self.std = torch.tensor([0.229, 0.224, 0.225], device=self.device)[None, :, None, None]

    def extract(self, crops, flip=False):
        """输入 BGR 裁剪列表和注册用翻转开关，批量输出 L2 特征；实时帧不做翻转。"""
        if not crops:
            return []
        colors = []
        for crop in crops:
            # HSV 三维 8×4×4=128 个格子；原方案 16×8×8 与 128 维不一致，采用明确可复现的分箱。
            hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
            histogram = cv2.calcHist([hsv], [0, 1, 2], None, [8, 4, 4], [0, 180, 0, 256, 0, 256])
            colors.append(normalize(histogram))
        if self.model is None:
            return colors
        torch = self.torch
        arrays = np.stack([cv2.cvtColor(cv2.resize(crop, (128, 256)), cv2.COLOR_BGR2RGB) for crop in crops])
        with torch.inference_mode():
            batch = torch.from_numpy(arrays).permute(0, 3, 1, 2).to(self.device).float() / 255
            batch = (batch - self.mean) / self.std
            embeddings = self.model(batch)
            if flip:
                embeddings = (embeddings + self.model(torch.flip(batch, dims=[3]))) / 2
            embeddings = embeddings.cpu().numpy()
        # 平方根权重使向量点积等于 w_appear*cos(外观)+w_color*cos(颜色)。
        return [np.concatenate([normalize(appear) * np.sqrt(self.config.reid_w_appear),
                                color * np.sqrt(self.config.reid_w_color)]).astype(np.float32)
                for appear, color in zip(embeddings, colors)]

    def smooth(self, old, new):
        """输入旧/新特征，输出指数平滑后的单位向量，抑制单帧姿态变化。"""
        if old is None:
            return new.copy()
        mixed = self.config.reid_ema * old + (1 - self.config.reid_ema) * new
        if len(mixed) == 704:
            return np.concatenate([normalize(mixed[:576]) * np.sqrt(self.config.reid_w_appear),
                                   normalize(mixed[576:]) * np.sqrt(self.config.reid_w_color)]).astype(np.float32)
        return normalize(mixed)
