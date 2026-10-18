"""实验身份策略回归：合成已知向量验证状态规则，公开样例验证真实模型；不访问摄像头。"""
import asyncio
from pathlib import Path
from time import monotonic

import cv2
import numpy as np
import pytest

from app.config import AppConfig, PROJECT_ROOT
from app.faces import FaceEncoder, FaceSample
from app.hybrid_session import HybridSession
from app.reid import normalize
from app.schemas import Detection


def config():
    """返回明确选择新方法的实验配置，避免改变appearance基线的默认行为。"""
    return AppConfig(det_device="cpu", identity_mode="hybrid", reid_model="osnet_x0_25", tracker="botsort.yaml", track_max_age=2)


def body_vector(similarity=1.):
    """构造512维外观+128维颜色，精确控制与登记外观的相似度，用于策略而非视觉准确率。"""
    vector = np.zeros(640, np.float32)
    vector[:2] = np.sqrt(.85) * np.array([similarity, np.sqrt(1 - similarity ** 2)])
    vector[512] = np.sqrt(.15)
    return vector


class KnownBodies:
    """受控行人编码器；输入多少裁剪就返回多少份已知向量，不接触神经网络。"""
    def __init__(self):
        self.current = body_vector()

    def extract(self, crops, flip=False):
        return [self.current.copy() for _ in crops]


class KnownFaces:
    """受控人脸证据：可切换为侧脸质量不足或明确的另一张脸。"""
    associate = staticmethod(FaceEncoder.associate)

    def __init__(self):
        self.feature = normalize([1., 0.])
        self.reason = "READY"

    def read(self, frame, recognize=True):
        feature = self.feature if recognize else None
        return [FaceSample((25, 15, 45, 45), feature, self.reason, .99)]


def step(session, frame, seq, boxes=None):
    """推进真实BoT-SORT与实验状态；默认一个人物框，允许改变大小或模拟离开。"""
    detections = [Detection(cls=0, name="person", score=.95, xyxy=(20., 10., 70., 150.))] if boxes is None else boxes
    session.update(detections, frame.shape[1], frame.shape[0], frame)
    return session.process(frame, seq)


def ready_session():
    """返回已稳定观测且手动登记的合成人物、帧和轨迹号。"""
    session = HybridSession(config(), KnownBodies(), KnownFaces())
    frame = np.full((160, 320, 3), 100, np.uint8)
    for seq in range(1, 7):
        step(session, frame, seq)
    track_id = session.boxes[0].track_id
    session.lock(track_id, session.seq, "lock")
    return session, frame, track_id


def test_profile_pose_and_scale_use_continuity_without_same_template():
    """侧脸不可用且身体已不同于登记姿势时，连贯运动和足够的行人依据应维持身份。"""
    session, frame, track_id = ready_session()
    step(session, frame, 7)
    session.face_encoder.feature = None
    session.face_encoder.reason = "FACE_EXTREME_ANGLE"
    session.extractor.current = body_vector(.65)
    session.observations[track_id].last_verified = monotonic() - 10
    for seq in range(8, 18):
        box = Detection(cls=0, name="person", score=.95, xyxy=(20., 10., float(70 + seq - 8), 150.))
        result = step(session, frame, seq, [box])[0]
        assert result.identity_id == "ID-01" and result.state == "locked"
        assert result.verification == "continuity"
    # 只见头部的近距离侧脸，没有身体可比较；持续脸部位置观测不能被误当作“全身外观不符”。
    session.face_only_indices = {0}
    session.extractor.current = body_vector(.1)
    for seq in range(18, 24):
        result = step(session, frame, seq)[0]
        assert result.state == "locked" and result.verification == "continuity"
    # 普通侧脸仍能提到特征但相似度下降时，也不能拿正脸阈值当成同轨迹“换人”的直接反证。
    session.face_encoder.feature = normalize([.3, np.sqrt(1 - .3 ** 2)])
    session.face_encoder.reason = "FACE_PROFILE"
    assert step(session, frame, 24)[0].state == "locked"


def test_clear_different_face_overrules_identical_clothing():
    """轨迹号和身体特征都不变，但可靠人脸明确不同，必须撤绿且不污染身份模板。"""
    session, frame, track_id = ready_session()
    step(session, frame, 7)
    session.face_encoder.feature = normalize([0., 1.])
    result = step(session, frame, 8)[0]
    assert result.track_id == track_id and result.state == "none"
    assert len(session.face_templates["ID-01"]) == 1


def test_reentry_requires_new_face_evidence_and_recovers_same_identity():
    """目标消失后，单凭相同身体不能继承旧脸身份；可靠人脸回来并连续确认才重绑定。"""
    session, frame, original = ready_session()
    for seq in range(7, 12):
        step(session, frame, seq, [])
    session.face_encoder.feature = None
    for seq in range(12, 22):
        result = step(session, frame, seq)
        assert all(box.state != "locked" for box in result)
    assert result[0].track_id != original
    session.face_encoder.feature = normalize([1., 0.])
    for seq in range(22, 30):
        result = step(session, frame, seq)
    assert result[0].identity_id == "ID-01"


def test_body_failure_has_bounded_grace_and_overlap_never_inherits_face():
    """没有脸且身体也不足时只容忍短时；两个人重叠、脸归属不明时不能沿用旧绿框。"""
    session, frame, track_id = ready_session()
    session.face_encoder.feature = None
    session.extractor.current = body_vector(.1)
    assert step(session, frame, 7)[0].verification == "continuity"
    session.observations[track_id].last_verified = monotonic() - 3
    assert step(session, frame, 8)[0].state == "none"
    session, frame, _ = ready_session()
    boxes = [Detection(cls=0, name="person", score=.95, xyxy=coords)
             for coords in [(20., 10., 70., 150.), (25., 10., 75., 150.)]]
    result = step(session, frame, 7, boxes)
    assert all(box.state != "locked" for box in result)


def test_face_templates_and_pending_candidates_clear_on_cancel():
    """单目标取消仍清除人脸/身体身份，后续帧不能自己恢复。"""
    session, frame, track_id = ready_session()
    step(session, frame, 7)
    # 即使下一帧只看得到质量不足的脸，取消/重试语义也不能被“请正对镜头”拦住。
    session.face_only_ids.add(track_id)
    session.current_faces[track_id] = FaceSample((25, 15, 45, 45), None, "FACE_BLURRED", .95)
    session.lock(track_id, session.seq, "toggle")
    assert not session.face_templates and not session.body_valid and not session.gallery.items
    assert all(box.state == "none" for box in step(session, frame, 8))


MODELS_READY = all((PROJECT_ROOT / "weights" / name).is_file() for name in (
    "osnet_x0_25_msmt17.onnx", "face_detection_yunet_2023mar.onnx", "face_recognition_sface_2021dec.onnx"))


@pytest.mark.skipif(not MODELS_READY, reason="experimental models not downloaded")
def test_dynamic_batch_and_frozen_weights_preserve_original_outputs():
    """原图与规范图同一输入输出一致；只改变批大小/冻结元信息，不能偷偷改变模型权重或特征。"""
    import onnxruntime as runtime
    from app.onnx_backend import create_session
    runtime.set_default_logger_severity(3)
    options = runtime.SessionOptions()
    options.log_severity_level, options.intra_op_num_threads = 3, 2
    source = runtime.InferenceSession(str(config().person_weights), sess_options=options, providers=["CPUExecutionProvider"])
    images = np.random.default_rng(42).normal(size=(16, 3, 256, 128)).astype(np.float32)
    original = source.run(None, {source.get_inputs()[0].name: images})[0]
    dynamic, device = create_session(config().person_weights, "cpu", dynamic_batch=True)
    actual = dynamic.run(None, {dynamic.get_inputs()[0].name: images[:3]})[0]
    assert device == "cpu" and actual.shape == (3, 512)
    np.testing.assert_allclose(actual, original[:3], rtol=1e-4, atol=1e-5)


@pytest.mark.skipif(not MODELS_READY, reason="experimental models not downloaded")
def test_real_models_register_public_face_and_match_after_scale_change():
    """真实公开人脸照片→真实YOLO/BoT-SORT/SFace，改变输入尺度后仍恢复同ID；不代表实拍姿态验收。"""
    from app.detector import Detector
    from app.pipeline import Pipeline

    async def check():
        settings = config().model_copy(update={"det_device": 0})
        pipeline = Pipeline(Detector(settings), settings)
        session = pipeline.create_tracker()
        image = cv2.imread(str(PROJECT_ROOT / "data/samples/test.jpg"))
        try:
            for seq in range(1, 7):
                await pipeline.process_frame(image, seq, session)
            faces = [face for face in session.face_encoder.read(image) if face.feature is not None]
            assert faces
            face = max(faces, key=lambda item: (item.xyxy[2] - item.xyxy[0]) * (item.xyxy[3] - item.xyxy[1]))
            left, top, right, bottom = face.xyxy
            dx, dy = int((right - left) * .3), int((bottom - top) * .3)
            photo = image[max(0, top - dy):bottom + dy, max(0, left - dx):right + dx]
            body = cv2.imencode(".jpg", photo)[1].tobytes()
            registered = await pipeline.register_photo(session.token, body, "image/jpeg")
            assert registered["quality"]["face_registered"]
            for seq in range(7, 16):
                result = await pipeline.process_frame(image, seq, session)
            assert sum(box.identity_id == registered["identity_id"] for box in result.boxes) == 1
            # 分辨率变化会重建轨迹，身份库必须保留并靠新证据恢复，不能只复用旧轨迹号。
            resized = cv2.resize(image, None, fx=.85, fy=.85)
            for seq in range(16, 26):
                result = await pipeline.process_frame(resized, seq, session)
            assert sum(box.identity_id == registered["identity_id"] for box in result.boxes) == 1
            assert session.extractor.person_cache
        finally:
            await pipeline.reset_tracker(session)
        assert not session.gallery.items and not session.face_templates and not session.extractor.person_cache

    asyncio.run(check())
