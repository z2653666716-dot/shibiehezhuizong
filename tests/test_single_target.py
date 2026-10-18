"""单目标锁定/取消与防误认回归，输入合成色块或已知向量，不访问任何设备。"""
import numpy as np
import pytest

from app.config import AppConfig
from app.gallery import Gallery
from app.reid import FeatureExtractor, normalize, cosine
from app.schemas import Detection
from app.session import SessionError, VideoSession


def detection(left):
    """输入横向位置，输出两个互不相交的测试人物框之一。"""
    return Detection(cls=0, name="person", score=.9, xyxy=(float(left), 10., float(left + 50), 140.))


def colored_session():
    """返回真实颜色后端和两个颜色不同的合成人物，用于验证状态而非实拍准确率。"""
    config = AppConfig(det_device="cpu", reid_model="color_histogram")
    session = VideoSession(config, FeatureExtractor(config))
    frame = np.zeros((160, 320, 3), np.uint8)
    frame[:, :160] = (0, 0, 240)
    frame[:, 160:] = (240, 0, 0)
    for seq in range(1, 7):
        session.update([detection(20), detection(200)], 320, 160)
        session.process(frame, seq)
    return session, frame


def advance(session, frame, boxes=None):
    """前进一步真实ByteTrack+会话状态，返回身份化检测框。"""
    session.update([detection(20), detection(200)] if boxes is None else boxes, 320, 160)
    return session.process(frame, session.seq + 1)


def test_lock_switch_and_toggle_stay_single_target():
    """A绿、锁B后只B绿；再按B全白，后续帧也不能自动恢复已取消身份。"""
    session, frame = colored_session()
    first, second = [box.track_id for box in session.boxes]
    assert session.lock(first, session.seq)["action"] == "locked"
    assert [box.state for box in advance(session, frame)] == ["locked", "none"]
    reply = session.lock(second, session.seq)
    assert reply["identity_id"] == "ID-02"
    assert len(session.gallery.items) == 1
    assert len(session.gallery.items[reply["identity_id"]].distractors) == 1
    assert [box.state for box in advance(session, frame)] == ["none", "locked"]
    assert session.lock(second, session.seq)["action"] == "unlocked"
    assert not session.gallery.items
    for _ in range(12):
        assert all(box.state == "none" for box in advance(session, frame))


def test_explicit_actions_are_idempotent_and_failed_switch_preserves_target():
    """HTTP明确操作可重试；无效的新目标不能先把原目标清掉，迟到取消也不能取消另一人。"""
    session, frame = colored_session()
    first, second = [box.track_id for box in session.boxes]
    assert session.lock(first, session.seq, "lock")["identity_id"] == "ID-01"
    assert session.lock(first, session.seq, "lock")["identity_id"] == "ID-01"
    with pytest.raises(SessionError): session.lock(999, session.seq, "lock")
    assert list(session.gallery.items) == ["ID-01"]
    session.lock(second, session.seq, "lock")
    assert session.lock(first, session.seq, "unlock")["action"] == "unlocked"
    assert [box.state for box in advance(session, frame)] == ["none", "locked"]
    session.lock(second, session.seq, "unlock")
    session.lock(second, session.seq, "unlock")
    assert not session.gallery.items


def test_same_track_wrong_appearance_loses_green_immediately():
    """即使旧EMA仍很像登记者，同一轨迹的本帧突然换人时也必须立即撤掉绿框。"""
    session, frame = colored_session()
    first = session.boxes[0].track_id
    session.lock(first, session.seq, "lock")
    assert advance(session, frame)[0].state == "locked"
    changed = frame.copy()
    changed[:, :160] = (240, 0, 0)
    result = advance(session, changed)
    assert result[0].track_id == first and result[0].state == "none"
    assert all(box.state != "locked" for box in result)
    assert len(session.gallery.items) == 1  # 搜索目标保留，禁止的是把错误人物继续画绿。


def test_fresh_features_override_old_ema_and_registration_distractors():
    """一个与目标有0.95相似度的已知旁人，不得靠宽松门槛或旧EMA被接受。"""
    config = AppConfig(reid_tau_high=.90)
    gallery = Gallery(config)
    anchor = normalize([1., 0.])
    other = normalize([.95, np.sqrt(1 - .95**2)])
    identity = gallery.register(anchor, distractors=[other])
    assert gallery.supports(anchor, identity.id)
    assert gallery.score(other, identity.id) > config.reid_tau_high
    assert not gallery.supports(other, identity.id)
    # 后续模板很像旁人也不能盖过原始注册锚点。
    gallery.append(identity.id, normalize([.8, .6]))
    assert not gallery.supports(normalize([.8, .6]), identity.id)


def test_photo_replaces_manual_target_and_clear_removes_all_candidates():
    """照片与长按遵守同一个单目标规则，取消后没有残留候选继续计数。"""
    session, frame = colored_session()
    session.lock(session.boxes[0].track_id, session.seq)
    feature = session.extractor.extract([frame[:, 160:]])[0]
    photo = session.register_identity(feature, name="照片注册", source="photo")
    assert list(session.gallery.items) == [photo.id] and photo.id == "ID-02"
    assert all(track.identity_id is None and track.candidate_hits == 0 for track in session.observations.values())
    session.clear_lock()
    for _ in range(10): assert all(box.state == "none" for box in advance(session, frame))


def test_moderate_similarity_cannot_hide_behind_old_ema():
    """0.85高于旧0.45解绑线但低于新0.90接受线，不能靠0.99的旧EMA继续显示绿框。"""
    config = AppConfig(det_device="cpu", reid_ema=.9)

    class KnownExtractor:
        def __init__(self):
            self.config = config
            self.current = normalize([1., 0.])

        def extract(self, crops, flip=False):
            return [self.current.copy() for _ in crops]

        def smooth(self, old, new):
            return FeatureExtractor.smooth(self, old, new)

    extractor = KnownExtractor()
    session = VideoSession(config, extractor)
    frame = np.full((160, 320, 3), 120, np.uint8)
    for seq in range(1, 7):
        session.update([detection(20)], 320, 160)
        session.process(frame, seq)
    track = session.boxes[0].track_id
    session.lock(track, session.seq, "lock")
    advance(session, frame, [detection(20)])
    anchor = extractor.current.copy()
    extractor.current = normalize([.85, np.sqrt(1 - .85**2)])
    assert cosine(extractor.smooth(anchor, extractor.current), anchor) > .99
    assert config.reid_tau_low < cosine(extractor.current, anchor) < config.reid_tau_high
    for _ in range(10):
        result = advance(session, frame, [detection(20)])
        assert result[0].track_id == track and result[0].state == "none"


@pytest.mark.parametrize("appearance_weight,high,appearance_similarity,color_similarity", [
    (.85, .8, 1., 0.), (.2, .9, .7, 1.)])
def test_fused_score_cannot_mask_one_wrong_component(appearance_weight, high, appearance_similarity, color_similarity):
    """融合分数过线但外观或颜色明显不符时也拒绝，避免一个分量弥补另一个分量。"""
    config = AppConfig(reid_w_appear=appearance_weight, reid_w_color=1 - appearance_weight, reid_tau_high=high)
    appear = np.zeros(576, np.float32); appear[0] = 1
    color = np.zeros(128, np.float32); color[0] = 1
    changed_appear = np.zeros_like(appear)
    changed_appear[:2] = appearance_similarity, np.sqrt(1 - appearance_similarity**2)
    changed_color = np.zeros_like(color)
    changed_color[:2] = color_similarity, np.sqrt(1 - color_similarity**2)
    anchor = np.r_[appear * np.sqrt(appearance_weight), color * np.sqrt(1 - appearance_weight)]
    changed = np.r_[changed_appear * np.sqrt(appearance_weight), changed_color * np.sqrt(1 - appearance_weight)]
    gallery = Gallery(config)
    identity = gallery.register(anchor)
    assert gallery.score(changed, identity.id) > high
    assert not gallery.supports(changed, identity.id)
