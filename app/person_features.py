"""使用已校验的OSNet ONNX提取行人身份特征，供ReID和BoT-SORT共用。

输入人物BGR裁剪列表，输出512维单位向量；在本机ONNX Runtime执行，不联网、不保存裁剪。
模型发布者标注MSMT17，训练来源限制见third_party.md，不把模型文件名当作实测成绩。
"""
import hashlib

import cv2
import numpy as np

from .reid import normalize

MODEL_SHA256 = "e78604f4ccda49b8f41cd0f8f7303800ce75d2361895ebb0729513c1bf53d277"


class PersonEncoder:
    """由FeatureExtractor创建；一次加载本地模型，重复将人物裁剪转换为特征。"""

    def __init__(self, path, device="cpu"):
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != MODEL_SHA256:
            raise ValueError("OSNet模型缺失或摘要不符，请运行scripts/fetch_identity_models.py --group person")
        from .onnx_backend import create_session
        self.net, self.execution_device = create_session(path, device, dynamic_batch=True)
        descriptor = self.net.get_inputs()[0]
        self.input_name, self.batch_size = descriptor.name, 16
        if descriptor.shape != ["batch", 3, 256, 128]:
            raise ValueError("OSNet输入声明与已验证模型不一致")

    def extract(self, crops):
        """输入裁剪列表，按固定256×128尺寸与ImageNet均值方差归一化，输出512维特征列表。"""
        features = []
        for start in range(0, len(crops), self.batch_size):
            group = crops[start:start + self.batch_size]
            # 运行前已规范为动态batch，按实际人数执行，最多16人；不再为一个人填充15份计算。
            batch = np.empty((len(group), 3, 256, 128), np.float32)
            for index, crop in enumerate(group):
                rgb = cv2.cvtColor(cv2.resize(crop, (128, 256)), cv2.COLOR_BGR2RGB).astype(np.float32) / 255
                rgb = (rgb - np.array([.485, .456, .406], np.float32)) / np.array([.229, .224, .225], np.float32)
                batch[index] = rgb.transpose(2, 0, 1)
            vectors = self.net.run(None, {self.input_name: batch})[0]
            if vectors.shape != (len(group), 512):
                raise ValueError("OSNet输出不是预期的512维，拒绝用未知模型继续识别")
            features.extend(normalize(vector) for vector in vectors[:len(group)])
        return features
