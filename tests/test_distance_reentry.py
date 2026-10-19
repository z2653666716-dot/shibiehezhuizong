"""远处锁定、逐步走近再重入的状态回归；只用合成图和已知向量，不访问摄像头。

真实BoT-SORT负责轨迹，受控编码器模拟距离造成的外观变化；不代表实拍识别准确率。
"""
import numpy as np

from app.faces import FaceEncoder, FaceSample
from app.hybrid_session import HybridSession
from app.reid import cosine, normalize
from app.schemas import Detection
from tests.test_hybrid_identity import KnownBodies, body_vector, config


class DistanceFaces:
    """输入合成帧，按设定返回小脸、清晰脸或无人；保留真实的每三帧提特征调度。"""
    associate = staticmethod(FaceEncoder.associate)

    def __init__(self):
        self.visible, self.clear = True, False
        self.feature = normalize([1., 0.])

    def read(self, frame, recognize=True):
        if not self.visible:
            return []
        reason = "FACE_TOO_SMALL" if not self.clear else "READY" if recognize else "FACE_OBSERVATION_INTERVAL"
        feature = self.feature if self.clear and recognize else None
        return [FaceSample((25, 15, 45, 45), feature, reason, .99)]


def advance(session, frame, seq, present=True, competitor=False):
    """推进完整处理流程；present模拟进出画面，competitor模拟身体同分的竞争者。"""
    session.face_encoder.visible = present
    coordinates = [(20., 10., 70., 150.)] if present else []
    if competitor:
        coordinates.append((140., 10., 190., 150.))
    detections = [Detection(cls=0, name="person", score=.95, xyxy=box) for box in coordinates]
    detections = session.prepare_frame(frame, detections)
    session.update(detections, frame.shape[1], frame.shape[0], frame)
    return session.process(frame, seq)


def distant_lock():
    """构造远处仅身体可登记的场景，返回会话、合成画面和用户锁定的原轨迹。"""
    session = HybridSession(config(), KnownBodies(), DistanceFaces())
    frame = np.full((160, 320, 3), 100, np.uint8)
    for seq in range(1, 7):
        advance(session, frame, seq)
    target = session.boxes[0].track_id
    session.lock(target, session.seq, "lock")
    assert not session.face_templates["ID-01"]
    return session, frame, target


def approach(session, frame):
    """逐步改变身体外观；相邻观测相近，但最后与原登记只约0.57，模拟远近差异。"""
    for index in range(1, 13):
        session.extractor.current = body_vector(float(np.cos(index * .08)))
        advance(session, frame, 6 + index)


def test_gradual_approach_learns_face_and_reentry_uses_fresh_face():
    """渐变外观不能阻断首份人脸学习；重入即使身体不同，也应靠新脸证据恢复原身份。"""
    session, frame, original = distant_lock()
    approach(session, frame)
    session.face_encoder.clear = True
    for seq in range(19, 40):
        advance(session, frame, seq)
    assert session.face_templates["ID-01"], "走近后清晰停留，应该已补充人脸模板"
    assert session.observations[original].face_seed is None
    assert len(session.gallery.items["ID-01"].templates) <= session.config.reid_max_templates
    for seq in range(40, 46):
        advance(session, frame, seq, present=False)
    # 身体刻意变成低匹配；必须重新取得六份正确人脸，不能把旧轨迹直接当成本人。
    session.extractor.current = body_vector(.1)
    for seq in range(46, 51):
        assert all(box.state != "locked" for box in advance(session, frame, seq))
    for seq in range(51, 57):
        result = advance(session, frame, seq)
    assert any(box.track_id != original and box.identity_id == "ID-01" for box in result)


def test_abrupt_appearance_change_or_competitor_cannot_add_body_templates():
    """突然大幅变化不能借连续轨迹学习；同帧身体同分者出现时也不能扩充模板。"""
    session, frame, _ = distant_lock()
    session.extractor.current = body_vector(.6)
    session.face_encoder.clear = True
    for seq in range(7, 28):
        advance(session, frame, seq)
    assert len(session.gallery.items["ID-01"].templates) == 1
    assert not session.face_templates["ID-01"]
    session, frame, _ = distant_lock()
    session.extractor.current = body_vector(.98)
    for seq in range(7, 15):
        advance(session, frame, seq, competitor=True)
    assert len(session.gallery.items["ID-01"].templates) == 1


def test_transition_cannot_drift_beyond_original_body_anchor():
    """相邻外观再相近，也不能无限远离最初登记；原始身体依据不足时禁止补入新脸。"""
    session, frame, _ = distant_lock()
    for index in range(1, 17):
        session.extractor.current = body_vector(float(np.cos(index * .08)))
        advance(session, frame, 6 + index)
    session.face_encoder.clear = True
    for seq in range(23, 44):
        advance(session, frame, seq)
    assert not session.face_templates["ID-01"]
    anchor = session.gallery.items["ID-01"].templates[0]
    assert all(cosine(item[:512], anchor[:512]) >= session.config.body_hold_threshold
               for item in session.gallery.items["ID-01"].templates)


def test_leaving_before_face_learning_does_not_authorize_new_track_learning():
    """人脸尚未补入就离开，后续相似身体的新轨迹不能继承原用户的学习许可。"""
    session, frame, original = distant_lock()
    for seq in range(7, 13):
        advance(session, frame, seq, present=False)
    for seq in range(13, 23):
        advance(session, frame, seq)
    assert session.boxes[0].track_id != original
    session.face_encoder.clear = True
    for seq in range(23, 46):
        advance(session, frame, seq)
    assert not session.face_templates["ID-01"]
