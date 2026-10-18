"""?????????????????????? Pipeline ?????
????????????????/??????????????
"""
from dataclasses import dataclass
from secrets import token_urlsafe
from time import monotonic
from datetime import datetime, timezone
import json
import logging
from uuid import uuid4

from .config import PROJECT_ROOT

from .gallery import Gallery
from .reid import crop_target
from .tracker import Tracker
from .recorder import Recorder


class SessionError(ValueError):
    """?????????????????????"""
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass
class Observation:
    """??????????EMA ????????????????"""
    hits: int = 0
    last_frame: int = 0
    identity_id: str | None = None
    feature: object = None
    candidate: str | None = None
    candidate_hits: int = 0
    bad_hits: int = 0


class VideoSession:
    """????/????????????????????????"""

    def __init__(self, config, extractor=None):
        self.config, self.extractor = config, extractor
        self.tracker = Tracker(config)
        self.token = token_urlsafe(32)
        self.gallery = Gallery(config)
        self.observations = {}
        self.boxes = []
        self.seq = -1
        self.frame_count = 0
        self.updated_at = monotonic()
        self.frame = None
        self.size = None
        self.events = []
        self.pending_events = []
        self.was_online = set()
        self.recorder = Recorder(config)
        self.event_path = PROJECT_ROOT / "outputs/events" / ("tracking_" + uuid4().hex + ".jsonl")

    def update(self, detections, width, height):
        """??????????????????????????????"""
        if self.size != (width, height):
            self.observations.clear()
            self.size = (width, height)
        self.boxes = self.tracker.update(detections, width, height)
        self.frame_count += 1
        self.updated_at = monotonic()
        for box in self.boxes:
            if box.track_id is None:
                continue
            track = self.observations.setdefault(box.track_id, Observation())
            continuous = track.last_frame == self.frame_count - 1
            track.hits = track.hits + 1 if continuous else 1
            if not continuous:
                track.candidate, track.candidate_hits = None, 0
            track.last_frame = self.frame_count
        self.observations = {key: value for key, value in self.observations.items()
                             if self.frame_count - value.last_frame <= self.config.track_max_age}
        return self.boxes

    def process(self, frame, seq):
        """?? BGR ????????????????????????????
        ??????????????????????????????????
        """
        self.frame, self.seq = frame, seq
        self.events, self.pending_events = self.pending_events, []
        crops, keys = [], []
        for box in self.boxes:
            if box.cls != 0 or box.track_id is None:
                continue  # ??????????????????????
            track = self.observations[box.track_id]
            if track.identity_id is None or self.frame_count % 3 == 0 or track.feature is None:
                crop = crop_target(frame, box.xyxy)
                if crop is not None:
                    crops.append(crop)
                    keys.append(box.track_id)
        fresh = {}
        if self.extractor is not None:
            fresh = dict(zip(keys, self.extractor.extract(crops)))
            for key, feature in fresh.items():
                track = self.observations[key]
                track.feature = self.extractor.smooth(track.feature, feature)
        visible = {box.track_id for box in self.boxes if box.track_id is not None}
        claimed = set()
        # ?????????????????????????????
        for key in sorted(visible):
            track = self.observations[key]
            if track.identity_id not in self.gallery.items or track.identity_id in claimed:
                track.identity_id = None
            if track.identity_id:
                claimed.add(track.identity_id)
        # 多个人都与同一身份相似时，先全局比较再分配，不能让检测数组中排在前面的人抢先变绿。
        contenders = {}
        for box in self.boxes:
            track = self.observations.get(box.track_id)
            if box.cls != 0 or track is None or track.identity_id or track.hits < 3 or box.track_id not in fresh:
                continue
            identity_id, best, second = self.gallery.rank(track.feature, claimed)
            if identity_id and best >= self.config.reid_tau_high and best - second >= self.config.reid_margin:
                contenders.setdefault(identity_id, []).append((best, box.track_id))
        winners = {}
        for identity_id, candidates in contenders.items():
            candidates.sort(reverse=True)
            # 身份之间要有差距，竞争同一身份的两个可见人物之间同样要有差距。
            if len(candidates) == 1 or candidates[0][0] - candidates[1][0] >= self.config.reid_margin:
                winners[candidates[0][1]] = identity_id
        output = []
        for box in self.boxes:
            track = self.observations.get(box.track_id)
            state, similarity = 'none', None
            if track is not None and track.identity_id is None and box.track_id not in fresh:
                # 裁剪太小等导致缺少本帧观测，也会中断连续确认，不能把不连续帧累计起来。
                track.candidate, track.candidate_hits = None, 0
            if box.cls == 0 and track is not None and track.feature is not None:
                if track.identity_id:
                    similarity = self.gallery.score(track.feature, track.identity_id)
                    # ??????????? EMA ????????????????
                    if box.track_id in fresh:
                        raw_score = self.gallery.score(fresh[box.track_id], track.identity_id)
                        track.bad_hits = track.bad_hits + 1 if raw_score < self.config.reid_tau_low else 0
                    if track.bad_hits >= 5:
                        claimed.discard(track.identity_id)
                        self.events.append({'type': 'event', 'name': 'unbound', 'identity_id': track.identity_id})
                        track.identity_id = None
                        track.feature = fresh.get(box.track_id, track.feature)
                        track.bad_hits = 0
                    else:
                        state = 'locked'
                if track.identity_id is None and track.hits >= 3 and box.track_id in fresh:
                    identity_id, best, second = self.gallery.rank(track.feature, claimed)
                    similarity = best if identity_id else None
                    if identity_id and winners.get(box.track_id) == identity_id:
                        track.candidate_hits = track.candidate_hits + 1 if track.candidate == identity_id else 1
                        track.candidate = identity_id
                        state = 'candidate'
                        if track.candidate_hits >= self.config.reid_confirm_frames:
                            # ???????????????????????
                            for other in self.observations.values():
                                if other is not track and other.identity_id == identity_id:
                                    other.identity_id = None
                            track.identity_id = identity_id
                            claimed.add(identity_id)
                            self.gallery.append(identity_id, track.feature)
                            self.events.append({'type': 'event', 'name': 'relocked', 'identity_id': identity_id})
                            track.candidate, track.candidate_hits = None, 0
                            state = 'locked'
                    else:
                        track.candidate, track.candidate_hits = None, 0
            output.append(box.model_copy(update={'state': state, 'sim': similarity,
                                                'identity_id': track.identity_id if state == 'locked' else None}))
        self.boxes = output
        online = {box.identity_id for box in output if box.identity_id}
        self.events.extend({'type': 'event', 'name': 'lost', 'identity_id': key}
                           for key in sorted(self.was_online - online))
        self.was_online = online
        # 冷启动特征提取可能耗时，过期判断以结果完成时间为准，不从推理开始计时。
        self.updated_at = monotonic()
        self.write_events()
        self.recorder.write(frame, output, seq, self.events)
        return output

    def start_record(self, confirm):
        """只有允许保存且请求确认时才启动；默认返回明确拒绝，不会创建文件。"""
        if self.frame is None:
            raise SessionError("TRACK_GONE", "请先开始检测，收到画面后再录制")
        height, width = self.frame.shape[:2]
        try:
            return {"ok": True, **self.recorder.start(width, height, confirm)}
        except PermissionError as error:
            raise SessionError("MEDIA_SAVE_FORBIDDEN", str(error)) from error

    def stop_record(self):
        """停止本会话录制并返回文件名，供页面显示。"""
        return {"ok": True, **self.recorder.stop()}

    def record_file(self, filename):
        """仅允许下载本会话已结束的录制文件；文件名必须精确匹配，不拼接输入路径。"""
        path = self.recorder.path
        if path is None or filename != path.name or not path.is_file():
            raise SessionError("RECORD_NOT_FOUND", "录制文件不存在")
        if self.recorder.writer is not None:
            raise SessionError("RECORD_ACTIVE", "请先停止录制再下载")
        return path

    def write_events(self):
        """只记录事件名、匿名编号、时间和帧号；无图片、向量或控制会话凭据。"""
        if not self.events:
            return
        try:
            self.event_path.parent.mkdir(parents=True, exist_ok=True)
            if self.event_path.exists() and self.event_path.stat().st_size > 2 * 1024 * 1024:
                return  # 单会话事件上限，防止反复进出无限占用磁盘。
            with self.event_path.open("a", encoding="utf-8") as stream:
                for event in self.events:
                    stream.write(json.dumps({**event, "seq": self.seq,
                        "at": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False) + "\n")
        except OSError:
            # 磁盘满等问题不应让内存中的检测和匹配一起停掉。
            logging.getLogger(__name__).exception("事件记录失败")

    def lock(self, track_id, seq):
        """?????/?????????????????????????"""
        box = next((item for item in self.boxes if item.track_id == track_id), None)
        if box is None or monotonic() - self.updated_at > 3 or seq > self.seq or self.seq - seq > 30:
            raise SessionError('TRACK_GONE', '???????????????????')
        if box.cls != 0:
            raise SessionError('UNSUPPORTED_TARGET', '?????????????? person ?')
        track = self.observations[track_id]
        if track.hits < 5 or track.feature is None:
            raise SessionError('REID_NOT_WARM', '???????????????????????????????')
        if track.identity_id not in self.gallery.items:
            crop = crop_target(self.frame, box.xyxy)
            if crop is None:
                raise SessionError('REID_NOT_WARM', '?????????????')
            feature = self.extractor.extract([crop], flip=True)[0]
            try:
                identity = self.gallery.register(feature)
            except ValueError as error:
                raise SessionError('IDENTITY_LIMIT', str(error)) from error
            track.identity_id = identity.id
            track.bad_hits = 0
            self.pending_events.append({'type': 'event', 'name': 'lock_created', 'identity_id': identity.id})
        return {'ok': True, 'identity_id': track.identity_id}

    def select(self, x, y, seq):
        """?????????????????????????"""
        hits = [box for box in self.boxes if box.track_id is not None
                and box.xyxy[0] <= x <= box.xyxy[2] and box.xyxy[1] <= y <= box.xyxy[3]]
        if not hits:
            raise SessionError('TRACK_GONE', '???????')
        box = min(hits, key=lambda item: (item.xyxy[2] - item.xyxy[0]) * (item.xyxy[3] - item.xyxy[1]))
        return self.lock(box.track_id, seq)

    def summaries(self):
        """???????????????????????"""
        return [summary.model_copy(update={"thumb": self.thumbnail_url(summary.id)
                if self.gallery.items[summary.id].thumbnail else None})
                for summary in self.gallery.summaries({box.identity_id for box in self.boxes if box.identity_id})]

    def thumbnail_url(self, identity_id):
        """输出当前会话专用缩略图地址，访问凭据不可用于其他视频。"""
        return f"/api/identities/{identity_id}/thumbnail?session_id={self.token}"

    def thumbnail(self, identity_id):
        """返回该身份的内存 JPEG；不存在或已删除时拒绝，绝不从任意磁盘路径读取。"""
        item = self.gallery.items.get(identity_id)
        if item is None or item.thumbnail is None:
            raise SessionError("IDENTITY_NOT_FOUND", "身份缩略图不存在或已清除")
        return item.thumbnail

    def delete(self, identity_id):
        """??????/??????????????"""
        if identity_id not in self.gallery.items:
            raise SessionError('IDENTITY_NOT_FOUND', '?????')
        del self.gallery.items[identity_id]
        for track in self.observations.values():
            if track.identity_id == identity_id:
                track.identity_id = None
            if track.candidate == identity_id:
                track.candidate, track.candidate_hits = None, 0

    def reset(self):
        """???????????????????? Tracker ??????"""
        self.recorder.stop()
        self.tracker.reset()
        self.observations.clear()
        self.gallery.items.clear()
        self.boxes = []
        self.frame = None
        self.events.clear()
        self.pending_events.clear()
        self.was_online.clear()

    def snapshot(self):
        """????????????/???"""
        return self.tracker.snapshot()
