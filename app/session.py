"""?????????????????????? Pipeline ?????
????????????????/??????????????
"""
from dataclasses import dataclass
from secrets import token_urlsafe
from time import monotonic
from datetime import datetime, timezone
import json
from uuid import uuid4

from .config import PROJECT_ROOT

from .gallery import Gallery
from .reid import crop_target
from .tracker import Tracker


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
        output = []
        for box in self.boxes:
            track = self.observations.get(box.track_id)
            state, similarity = 'none', None
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
                    if identity_id and best >= self.config.reid_tau_high and best - second >= self.config.reid_margin:
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
        return output

    def write_events(self):
        """只记录事件名、匿名编号、时间和帧号；无图片、向量或控制会话凭据。"""
        if not self.events:
            return
        self.event_path.parent.mkdir(parents=True, exist_ok=True)
        if self.event_path.exists() and self.event_path.stat().st_size > 2 * 1024 * 1024:
            return  # 限制单会话事件文件大小，不让长时间反复进出无限占用磁盘。
        with self.event_path.open("a", encoding="utf-8") as stream:
            for event in self.events:
                stream.write(json.dumps({**event, "seq": self.seq,
                    "at": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False) + "\n")

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
        return self.gallery.summaries({box.identity_id for box in self.boxes if box.identity_id})

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
