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
        """按一张脸对应一个人进行几何归属，输出轨迹号到脸的字典；不使用身份相似度猜归属。

        人物框交叠时，某张脸可能同时落入两个框；若另一张脸只可能属于其中一人，
        整组的一对一约束就能排除错误归属。只有所有可行分配都一致的边才可使用。
        """
        candidates, owner_faces = {}, {}
        for index, face in enumerate(faces):
            center_x = (face.xyxy[0] + face.xyxy[2]) / (2 * width)
            center_y = (face.xyxy[1] + face.xyxy[3]) / (2 * height)
            owners = {owner for owner, box in enumerate(boxes) if box.cls == 0
                      and box.xyxy[0] <= center_x <= box.xyxy[2]
                      and box.xyxy[1] <= center_y <= box.xyxy[1] + .8 * (box.xyxy[3] - box.xyxy[1])}
            if owners:
                candidates[index] = owners
                for owner in owners:
                    owner_faces.setdefault(owner, set()).add(index)

        assigned, visited = {}, set()
        for start in candidates:
            if start in visited:
                continue
            # 只把互相有关的人脸/身体放在同一组，远处无关的一张脸不会阻碍这组的分配。
            group, owners, pending = set(), set(), [start]
            while pending:
                index = pending.pop()
                if index in group:
                    continue
                group.add(index)
                for owner in candidates[index]:
                    owners.add(owner)
                    pending.extend(owner_faces[owner] - group)
            visited.update(group)
            if len(group) > len(owners):
                continue  # 一个身体里挤了两张脸等情况，不选最大脸来冒认。

            def match_without(excluded=None):
                """给本组全部脸找不冲突的位置；可禁止一条边，输出分配或None。

                递归只是在数字编号间调整已占用位置，不读取图像；每次访问新身体编号，必然结束。
                """
                occupied = {}

                def place(index, seen):
                    """当前身体已被占用时，尝试给原来的脸找另一个位置，避免依赖数组顺序。"""
                    for owner in sorted(candidates[index]):
                        if owner in seen or excluded == (index, owner):
                            continue
                        seen.add(owner)
                        if owner not in occupied or place(occupied[owner], seen):
                            occupied[owner] = index
                            return True
                    return False

                for index in sorted(group, key=lambda item: len(candidates[item])):
                    if not place(index, set()):
                        return None
                return occupied

            matched = match_without()
            if matched is None:
                continue
            for owner, index in matched.items():
                # 删掉这条归属仍能排完所有脸，说明存在另一种解释；此时宁可不使用这张脸。
                if match_without((index, owner)) is None and boxes[owner].track_id is not None:
                    assigned[boxes[owner].track_id] = faces[index]
        return assigned
