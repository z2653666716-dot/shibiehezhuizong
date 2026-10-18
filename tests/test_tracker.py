"""用合成检测框验证真实 ByteTrack 的编号与生命周期，不读取图像或物理设备。

pytest 调用 Tracker.update；覆盖顺序变化、短暂丢失、过期、类别、会话与尺寸隔离。
"""

import pytest

from app.config import AppConfig
from app.schemas import Detection
from app.tracker import Tracker


def detection(left=20.0, score=0.91, category=0):
    """输入位置/分数/类别，输出合成像素框，供真实关联算法使用。"""
    return Detection(cls=category, name="person" if category == 0 else "car",
                     score=score, xyxy=(left, 20.0, left + 40.0, 140.0))


def test_small_motion_and_detection_order_preserve_ids():
    """两个分离目标的检测顺序交换时，编号应跟位置走，原始分数不能被跟踪器改写。"""
    tracker = Tracker(AppConfig())
    first = tracker.update([detection(), detection(200.0)], 400, 300)
    second = tracker.update([detection(202.0, 0.73), detection(22.0)], 400, 300)
    assert [box.track_id for box in second] == [first[1].track_id, first[0].track_id]
    assert second[0].score == 0.73 and second[0].xyxy[0] == 202.0 / 400


def test_short_missing_gap_reuses_id_without_drawing_ghost():
    """空帧不输出框，保留期内重新出现时才恢复原编号。"""
    tracker = Tracker(AppConfig(track_max_age=3))
    original = tracker.update([detection()], 400, 300)[0].track_id
    assert tracker.update([], 400, 300) == []
    assert tracker.snapshot()["lost_ids"] == [original]
    assert tracker.update([detection(22.0)], 400, 300)[0].track_id == original


def test_expired_track_does_not_reuse_old_id():
    """超出保留帧数后重新进入必须分配新编号，当前阶段不把它当成长时重识别。"""
    tracker = Tracker(AppConfig(track_max_age=2))
    original = tracker.update([detection()], 400, 300)[0].track_id
    for _ in range(4):
        tracker.update([], 400, 300)
    assert tracker.snapshot()["lost_ids"] == []
    tracker.update([detection()], 400, 300)
    current = tracker.update([detection()], 400, 300)[0].track_id
    assert current is not None and current != original


def test_categories_and_tracker_instances_are_isolated():
    """重合的不同类别不能共享轨迹；创建另一个会话也不能重置已运行会话的计数。"""
    tracker = Tracker(AppConfig())
    boxes = tracker.update([detection(), detection(category=2)], 400, 300)
    assert boxes[0].track_id != boxes[1].track_id
    other = Tracker(AppConfig())
    other.update([detection()], 400, 300)
    current = tracker.update([detection(21.0), detection(21.0, category=2), detection(300.0)], 400, 300)
    current = tracker.update([detection(22.0), detection(22.0, category=2), detection(301.0)], 400, 300)
    assert current[0].track_id == boxes[0].track_id
    assert current[1].track_id == boxes[1].track_id
    assert current[2].track_id not in {boxes[0].track_id, boxes[1].track_id}


def test_reset_and_size_changes_discard_history_without_reusing_ids():
    """手动重置或旋转画面后旧轨迹失效，避免旧选择错误绑定新场景。"""
    tracker = Tracker(AppConfig())
    first = tracker.update([detection()], 400, 300)[0].track_id
    second = tracker.update([detection()], 300, 400)[0].track_id
    tracker.reset()
    assert tracker.snapshot() == {"active_ids": [], "lost_ids": [], "frame_count": 0}
    third = tracker.update([detection()], 400, 300)[0].track_id
    assert len({first, second, third}) == 3


def test_second_stage_accepts_a_low_score_current_detection():
    """已有轨迹可用低分框继续关联；仍输出真实低分，不把它修改成高置信度。"""
    tracker = Tracker(AppConfig())
    original = tracker.update([detection()], 400, 300)[0].track_id
    current = tracker.update([detection(21.0, 0.2)], 400, 300)[0]
    assert current.track_id == original and current.score == 0.2


def test_unsupported_tracker_and_invalid_size_are_rejected():
    """不自动下载未知配置，也不接受错误尺寸。"""
    with pytest.raises(ValueError, match="bytetrack"):
        Tracker(AppConfig(tracker="unknown.yaml"))
    tracker = Tracker(AppConfig())
    with pytest.raises(ValueError, match="正整数"):
        tracker.update([], 0, 300)
