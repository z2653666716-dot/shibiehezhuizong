"""会话内的多模板身份库；仅保存特征和小缩略图内存，不把用户内容写入磁盘。"""
from dataclasses import dataclass, field

import numpy as np

from .reid import cosine, normalize
from .schemas import IdentitySummary


@dataclass
class Identity:
    """一个登记身份，模板数量有限；公开摘要不包含模板或原图。"""
    id: str
    name: str
    source: str
    templates: list = field(default_factory=list)
    thumbnail: bytes | None = None
    distractors: list = field(default_factory=list)


class Gallery:
    """输入注册特征/待匹配特征，输出身份编号或最优与次优相似度。"""

    def __init__(self, config):
        self.config = config
        self.items = {}
        self.next_id = 1

    def register(self, feature, name="长按锁定", source="lock", thumbnail=None, distractors=()):
        """登记一个特征，返回新身份；上限检查由会话转成业务错误。"""
        if len(self.items) >= self.config.identity_limit:
            raise ValueError("身份数量已达上限，请先删除不用的身份")
        identity_id = f"ID-{self.next_id:02d}"
        self.next_id += 1
        identity = Identity(identity_id, name, source, [normalize(feature).copy()], thumbnail)
        # 反例来自用户登记时可见的其他人，只留有限特征，既不保存裁剪也不返回给页面。
        identity.distractors = [normalize(item).copy() for item in list(distractors)[:self.config.reid_max_templates]]
        self.items[identity_id] = identity
        return identity

    def score(self, feature, identity_id):
        """将输入特征与该身份的多个模板逐一比较，返回最高相似度。"""
        return max(cosine(feature, template) for template in self.items[identity_id].templates)

    def supports(self, feature, identity_id):
        """输入本帧特征与身份号，输出是否有足够证据；绑定和重入都调用此检查。

        同时检查原始注册模板、融合分数、独立外观/颜色和登记反例，防止旧EMA或后续模板掩盖换人。
        """
        identity = self.items[identity_id]
        anchor = identity.templates[0]
        if self.score(feature, identity_id) < self.config.reid_tau_high or cosine(feature, anchor) < self.config.reid_tau_high:
            return False
        if len(feature) == 704 and len(anchor) == 704:
            if self.config.reid_w_appear and cosine(feature[:576], anchor[:576]) < self.config.reid_tau_high:
                return False
            if self.config.reid_w_color and cosine(feature[576:], anchor[576:]) < self.config.reid_color_min:
                return False
        if identity.distractors:
            nearest_other = max(cosine(feature, item) for item in identity.distractors)
            if cosine(feature, anchor) - nearest_other < self.config.reid_margin:
                return False
        return True

    def rank(self, feature, excluded=()):
        """保留完整身份库的第一/第二名来做 margin，在线身份也参与歧义比较。

        excluded 身份不能再绑定给其他轨迹，但不能从第二名竞争中消失，否则可能误认次优身份。
        """
        scores = sorted(((self.score(feature, key), key) for key in self.items), reverse=True)
        if not scores or scores[0][1] in excluded:
            return None, -1.0, -1.0
        return scores[0][1], scores[0][0], scores[1][0] if len(scores) > 1 else -1.0

    def append(self, identity_id, feature):
        """输入确认匹配的特征，保留原始注册模板，再用有限滚动模板补充新姿态。"""
        identity = self.items[identity_id]
        if self.config.reid_max_templates <= 1:
            return
        if max(cosine(feature, template) for template in identity.templates) > 0.995:
            return
        identity.templates.append(normalize(feature).copy())
        if len(identity.templates) > self.config.reid_max_templates:
            del identity.templates[1]

    def summaries(self, online):
        """输入本帧在线身份集合，输出页面摘要，不泄露内部向量。"""
        return [IdentitySummary(id=item.id, name=item.name, online=item.id in online)
                for item in self.items.values()]
