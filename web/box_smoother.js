/**
 * 检测框显示平滑：减少相邻帧中框边缘的小幅抖动，由 app.js 和 ipcam.js 共用。
 * 输入是已校验的当前帧框、图像宽高和时间，输出同数量的新框，只调整 xyxy。
 * 不修改检测分数、不保存图像、不分配身份或轨迹编号；正式跟踪仍由后续 ByteTrack 负责。
 */

const MIN_OVERLAP = 0.5;
const AMBIGUOUS_MARGIN = 0.1;
const MAX_CENTER_SHIFT = 0.12;
const MAX_SIZE_RATIO = 1.3;
const MAX_GAP_MS = 500;

/** 输入两个归一化矩形，输出交并比：共同面积除以总覆盖面积，越接近 1 越重合。 */
function overlap(first, second) {
  const width = Math.max(0, Math.min(first[2], second[2]) - Math.max(first[0], second[0]));
  const height = Math.max(0, Math.min(first[3], second[3]) - Math.max(first[1], second[1]));
  const intersection = width * height;
  const area = (box) => (box[2] - box[0]) * (box[3] - box[1]);
  return intersection / (area(first) + area(second) - intersection);
}

/** 输入前后两帧框，输出是否仅为小幅变化；明显位移/缩放时直接跟随新框，减少拖尾。 */
function smallChange(previous, current) {
  for (let axis = 0; axis < 2; axis += 1) {
    const oldSize = previous[axis + 2] - previous[axis];
    const newSize = current[axis + 2] - current[axis];
    const centerShift = Math.abs((current[axis] + current[axis + 2] -
      previous[axis] - previous[axis + 2]) / 2);
    if (centerShift > MAX_CENTER_SHIFT * Math.min(oldSize, newSize) ||
        Math.max(oldSize, newSize) / Math.min(oldSize, newSize) > MAX_SIZE_RATIO) return false;
  }
  return true;
}

/**
 * 每个页面客户端拥有自己的 BoxSmoother；只保留上一帧框坐标，停止时 reset。
 * alpha 是当前帧坐标权重：越小越平稳，越大越灵敏，1 表示使用当前原始坐标。
 */
export class BoxSmoother {
  constructor({ alpha = 0.35 } = {}) {
    if (!Number.isFinite(alpha) || alpha <= 0 || alpha > 1) {
      throw new RangeError("框平滑 alpha 必须大于 0 且不超过 1");
    }
    this.alpha = alpha;
    this.reset();
  }

  /** 无输入，清除上帧数据；停止、重连或尺寸变化后不能混入旧场景的坐标。 */
  reset() {
    this.previous = [];
    this.sizeKey = null;
    this.lastTime = null;
  }

  /**
   * 输入已校验的 boxes、真实图像宽高和毫秒时间，输出供画布绘制的新框数组。
   * 先找明确重合的同类别框，再对小幅变化做加权平均；没有当前检测的目标立即移除。
   */
  update(boxes, width, height, now = performance.now()) {
    const sizeKey = width + "x" + height;
    if (sizeKey !== this.sizeKey || this.lastTime === null ||
        now < this.lastTime || now - this.lastTime > MAX_GAP_MS) this.reset();
    this.sizeKey = sizeKey;
    this.lastTime = now;
    // 复制坐标，避免修改服务端原始包；score、类别和未来的 track_id 始终来自当前帧。
    const output = boxes.map((box) => ({ ...box, xyxy: [...box.xyxy] }));
    const candidates = [];
    for (let currentIndex = 0; currentIndex < boxes.length; currentIndex += 1) {
      const current = boxes[currentIndex];
      const matches = [];
      for (let previousIndex = 0; previousIndex < this.previous.length; previousIndex += 1) {
        const previous = this.previous[previousIndex].raw;
        if (current.cls !== previous.cls) continue;
        // 后续接入真实轨迹编号时，只允许相同编号对应，不把换号目标混合。
        if ((current.track_id ?? null) !== (previous.track_id ?? null)) continue;
        const score = overlap(previous.xyxy, current.xyxy);
        if (score >= MIN_OVERLAP) matches.push({ currentIndex, previousIndex, score });
      }
      matches.sort((first, second) => second.score - first.score);
      // 两个旧框都很像当前框时，宁可原样显示，也不混合两个人的位置。
      if (matches.length && (matches.length === 1 ||
          matches[0].score - matches[1].score >= AMBIGUOUS_MARGIN)) candidates.push(matches[0]);
    }
    // 最重合的配对优先；一个旧框最多使用一次，不能把它复制给两个当前目标。
    candidates.sort((first, second) => second.score - first.score);
    const used = new Set();
    for (const { currentIndex, previousIndex } of candidates) {
      if (used.has(previousIndex)) continue;
      used.add(previousIndex);
      const previous = this.previous[previousIndex];
      const current = boxes[currentIndex];
      if (!smallChange(previous.raw.xyxy, current.xyxy)) continue;
      output[currentIndex].xyxy = current.xyxy.map((coordinate, index) =>
        this.alpha * coordinate + (1 - this.alpha) * previous.displayed[index]);
    }
    // 只记当前仍存在的框；当前 boxes 为空时历史也立即清空，不维持“幽灵人物框”。
    this.previous = boxes.map((box, index) => ({
      raw: { cls: box.cls, track_id: box.track_id, xyxy: [...box.xyxy] },
      displayed: [...output[index].xyxy],
    }));
    return output;
  }
}
