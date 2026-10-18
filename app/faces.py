"""YuNet人脸检测、质量筛选与SFace特征：只处理内存，不保存或传输人脸内容。

Pipeline在实验模式创建一个FaceEncoder，HybridSession按帧调用；照片注册共用相同质量规则。
输出仅供内部匹配的FaceSample，绝不写进日志或返回给网页。
"""
from dataclasses import dataclass
import hashlib

import cv2
import numpy as np

from .reid import normalize

DETECTOR_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
RECOGNIZER_SHA256 = "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79"


@dataclass
class FaceSample:
    """一张脸的像素位置、质量原因及可选128维特征；没有图片或历史帧。"""
    xyxy: tuple
    feature: object
    reason: str
    confidence: float = 0.


class FaceEncoder:
    """输入BGR帧，输出经质量筛选的人脸列表；看不清的脸只报告质量不足，不当作另一个人。"""

    def __init__(self, config):
        self.config = config
        for path, digest in ((config.face_detector_weights, DETECTOR_SHA256),
                             (config.face_recognizer_weights, RECOGNIZER_SHA256)):
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError("人脸模型缺失或摘要不符，请运行scripts/fetch_identity_models.py --group face")
        self.detector = cv2.FaceDetectorYN.create(str(config.face_detector_weights), "", (320, 320), .9)
        self.recognizer = cv2.FaceRecognizerSF.create(str(config.face_recognizer_weights), "")
        self.feature_session, self.execution_device = None, "cpu"
        if config.identity_device == "cuda":
            from .onnx_backend import create_session
            session, device = create_session(config.face_recognizer_weights, config.det_device if config.det_device != "cpu" else 0)
            if device.startswith("cuda"):
                self.feature_session, self.execution_device = session, device

    def read(self, frame, recognize=True):
        """检测并将坐标还原到原帧；过小、模糊或极端侧脸不提特征，避免把质量差误当身份冲突。"""
        height, width = frame.shape[:2]
        scale = min(1., 960 / max(height, width))
        image = cv2.resize(frame, (round(width * scale), round(height * scale))) if scale < 1 else frame
        self.detector.setInputSize((image.shape[1], image.shape[0]))
        _, rows = self.detector.detect(image)
        output = []
        for original in ([] if rows is None else rows):
            row = original.copy()
            row[:14] /= scale
            x, y, w, h = row[:4]
            x1, y1 = max(0, int(x)), max(0, int(y))
            x2, y2 = min(width, int(x + w)), min(height, int(y + h))
            feature, reason = None, "READY"
            if min(x2 - x1, y2 - y1) < self.config.face_min_side:
                reason = "FACE_TOO_SMALL"
            else:
                patch = cv2.resize(frame[y1:y2, x1:x2], (112, 112))
                sharpness = cv2.Laplacian(cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY), cv2.CV_32F).var()
                # 鼻子远离双眼中点通常表示角度极端；此时继续运动跟踪，避免用不可靠脸做反向拒绝。
                eye_distance = float(np.linalg.norm(row[4:6] - row[6:8]))
                offset = abs(float(row[8] - (row[4] + row[6]) / 2)) / max(eye_distance, 1.)
                if sharpness < self.config.face_min_sharpness:
                    reason = "FACE_BLURRED"
                elif offset > .65:
                    reason = "FACE_EXTREME_ANGLE"
                elif recognize:
                    # 这是关键点几何的粗略姿态类别，不是精确角度；侧脸相似度低不能直接当作换人反证。
                    reason = "FACE_PROFILE" if offset > .2 else "READY"
                    aligned = self.recognizer.alignCrop(frame, row)
                    if self.feature_session is None:
                        feature = normalize(self.recognizer.feature(aligned).reshape(-1))
                    else:
                        # 与OpenCV官方feature()一致：原始0..255的RGB、NCHW；归一化已包含在SFace图中。
                        blob = cv2.cvtColor(aligned, cv2.COLOR_BGR2RGB).transpose(2, 0, 1)[None].astype(np.float32)
                        inputs = {self.feature_session.get_inputs()[0].name: blob}
                        feature = normalize(self.feature_session.run(None, inputs)[0].reshape(-1))
                else:
                    reason = "FACE_OBSERVATION_INTERVAL"
            output.append(FaceSample((x1, y1, x2, y2), feature, reason, float(original[-1])))
        return output

    @staticmethod
    def associate(faces, boxes, width, height):
        """将脸分给唯一包含其中心的上半身框；两个人框都包含同一张脸时不给任何人身份依据。"""
        assigned = {}
        for face in faces:
            center_x = (face.xyxy[0] + face.xyxy[2]) / (2 * width)
            center_y = (face.xyxy[1] + face.xyxy[3]) / (2 * height)
            owners = [box for box in boxes if box.cls == 0
                      and box.xyxy[0] <= center_x <= box.xyxy[2]
                      and box.xyxy[1] <= center_y <= box.xyxy[1] + .8 * (box.xyxy[3] - box.xyxy[1])]
            # 刚进入画面的白框可能尚无轨迹号，也必须计入歧义，不能把它的脸分给旧目标。
            if len(owners) == 1 and owners[0].track_id is not None:
                key = owners[0].track_id
                if key not in assigned or (face.xyxy[2] - face.xyxy[0]) * (face.xyxy[3] - face.xyxy[1]) > (
                        assigned[key].xyxy[2] - assigned[key].xyxy[0]) * (assigned[key].xyxy[3] - assigned[key].xyxy[1]):
                    assigned[key] = face
        return assigned
