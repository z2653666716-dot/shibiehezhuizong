/**
 * 两种视频模式共用的选中、长按、身份条和提示模块。
 * 输入客户端最新框/会话，输出锁定 HTTP 请求与 Canvas 样式；不采集或保存画面。
 */
export class TargetInteraction {
  constructor(canvas, readState, redraw) {
    this.canvas = canvas;
    this.readState = readState;
    this.redraw = redraw;
    this.session = null;
    this.seq = 0;
    this.selected = null;
    this.press = null;
    this.busy = false;
    this.identitiesKey = "";
    this.photoInput = document.getElementById("photo-file");
    document.getElementById("upload-photo").onclick = () => {
      if (this.session) this.photoInput.click();
      else this.toast("请先开始检测，再选择照片");
    };
    this.photoInput.onchange = () => void this.uploadPhoto();
    canvas.tabIndex = 0;
    canvas.setAttribute("aria-label", "目标操作：短按选中，长按或按 L 锁定");
    canvas.addEventListener("pointerdown", event => this.down(event));
    canvas.addEventListener("pointerup", () => this.cancel());
    canvas.addEventListener("pointercancel", () => this.cancel());
    canvas.addEventListener("lostpointercapture", () => this.cancel());
    canvas.addEventListener("pointermove", event => {
      if (this.press && Math.hypot(event.clientX - this.press.clientX, event.clientY - this.press.clientY) > 12) this.cancel();
    });
    canvas.addEventListener("contextmenu", event => {
      event.preventDefault();
      const hit = this.hit(event);
      if (hit) { this.selected = hit.track_id; void this.lock(hit.track_id); }
    });
    canvas.addEventListener("keydown", event => {
      if (event.key.toLowerCase() === "l" && this.selected != null) {
        event.preventDefault(); void this.lock(this.selected);
      }
    });
    document.getElementById("identity-hint").textContent =
      "短按选中黄框，按住 0.6 秒锁定绿框；电脑也可右键或选中后按 L。身份仅在本次视频会话保留。";
  }

  /** 输入触点，按画布屏幕大小归一化，再还原镜像；只命中实际框。 */
  hit(event) {
    const rect = this.canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    let x = (event.clientX - rect.left) / rect.width;
    const y = (event.clientY - rect.top) / rect.height;
    const state = this.readState();
    if (state.mirrored) x = 1 - x;
    return state.boxes.filter(box => box.track_id != null &&
      x >= box.xyxy[0] && x <= box.xyxy[2] && y >= box.xyxy[1] && y <= box.xyxy[3])
      .sort((a, b) => (a.xyxy[2] - a.xyxy[0]) * (a.xyxy[3] - a.xyxy[1]) -
        (b.xyxy[2] - b.xyxy[0]) * (b.xyxy[3] - b.xyxy[1]))[0] || null;
  }

  /** 按下立即黄框；计时达到 600ms 才发送锁定，移动/抬起会取消计时。 */
  down(event) {
    if (event.button !== 0 || this.press) return;
    const box = this.hit(event);
    if (!box) { this.toast("请按住目标框内"); return; }
    this.selected = box.track_id;
    this.canvas.focus({ preventScroll: true });
    this.canvas.setPointerCapture(event.pointerId);
    this.press = { clientX: event.clientX, clientY: event.clientY, started: performance.now(),
      track: box.track_id, pointerId: event.pointerId };
    this.timer = setTimeout(() => { this.cancel(); void this.lock(box.track_id); }, 600);
    const animate = () => {
      this.redraw();
      if (this.press) this.animation = requestAnimationFrame(animate);
    };
    animate();
  }

  /** 终止手势和动画；停止视频时同样调用，禁止迟到的长按锁定。 */
  cancel() {
    clearTimeout(this.timer);
    cancelAnimationFrame(this.animation);
    this.press = null;
    this.redraw();
  }

  /** 输入同源接口与请求选项，输出 JSON；失败抛出服务端中文提示。 */
  async request(path, options = {}) {
    const response = await fetch(path, { cache: "no-store", signal: AbortSignal.timeout(15000), ...options });
    const body = await response.json();
    if (!response.ok || body.ok === false) throw new Error(body.message || "操作失败，请重试");
    return body;
  }

  /** 输入轨迹号，携带会话和已显示帧号锁定；异步结果不得改变新会话。 */
  async lock(trackId) {
    if (!this.session || this.busy) return;
    const session = this.session;
    this.busy = true;
    try {
      const body = await this.request("/api/lock", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: session, track_id: trackId, seq: this.seq }) });
      if (this.session !== session) return;
      this.toast(body.identity_id + " 已锁定");
      navigator.vibrate?.(50);
    } catch (error) {
      if (this.session === session) this.toast(error.message);
    } finally { this.busy = false; }
  }

  /** 输入最新结果，刷新会话与身份卡片；文本使用 textContent，避免名字被当作 HTML。 */
  accept(result) {
    if (this.session !== result.session_id) { this.reset(); this.session = result.session_id || null; }
    this.seq = result.seq;
    document.getElementById("upload-photo").disabled = !this.session;
    const identities = result.identities || [];
    const key = JSON.stringify(identities);
    if (key !== this.identitiesKey) {
      this.identitiesKey = key;
      const list = document.getElementById("identity-list");
      list.replaceChildren();
      document.getElementById("identity-empty").hidden = identities.length > 0;
      for (const identity of identities) {
        const card = document.createElement("li");
        card.className = "identity-card " + (identity.online ? "online" : "offline");
        const name = document.createElement("button");
        if (typeof identity.thumb === "string" && identity.thumb.startsWith("/api/identities/")) {
          const image = document.createElement("img");
          image.src = identity.thumb; image.alt = "登记照片缩略图";
          image.width = 48; image.height = 64; card.append(image);
        }
        name.textContent = identity.id + " · " + identity.name + (identity.online ? " · 在线" : " · 离线");
        name.onclick = () => {
          this.selected = this.readState().boxes.find(box => box.identity_id === identity.id)?.track_id ?? null;
          this.redraw();
        };
        const remove = document.createElement("button");
        remove.textContent = "删除";
        remove.onclick = async () => {
          try { await this.request("/api/identities/" + encodeURIComponent(identity.id) +
            "?session_id=" + encodeURIComponent(this.session), { method: "DELETE" }); }
          catch (error) { this.toast(error.message); }
        };
        card.append(name, remove); list.append(card);
      }
    }
    for (const event of result.events || []) {
      if (event.name === "relocked") {
        this.toast(event.identity_id + " 重新匹配成功"); navigator.vibrate?.(50);
      } else if (event.name === "lost") this.toast(event.identity_id + " 已离开画面");
    }
  }

  /** 输入框，输出样式与标签；分数保持当前模型值，颜色只表达交互/匹配状态。 */
  style(box) {
    if (box.state === "locked") return { color: "#41e18b", width: 3, dash: [], text: box.identity_id };
    if (box.state === "candidate") return { color: "#41e18b", width: 2, dash: [6, 4], text: "识别中…" };
    return { color: box.track_id === this.selected ? "#ffe166" : "#ffffff", width: 2, dash: [],
      text: box.name.slice(0, 40) + (box.track_id == null ? "" : " #" + box.track_id) + " " + box.score.toFixed(2) };
  }

  /** 用户手动选照片后才传给同一电脑；FormData只存在内存，请求结束清理文件输入。 */
  async uploadPhoto() {
    const file = this.photoInput.files?.[0];
    const session = this.session;
    if (!file || !session) return;
    if (file.size > 6 * 1024 * 1024 - 2048) {
      this.toast("请选择小于 6 MiB 的 JPEG/PNG 照片"); this.photoInput.value = ""; return;
    }
    const form = new FormData(); form.append("photo", file);
    try {
      this.toast("正在提取照片中的人物…");
      const body = await this.request("/api/identities/photo?session_id=" + encodeURIComponent(session),
        { method: "POST", body: form });
      if (session === this.session) this.toast(body.message);
    } catch (error) {
      if (session === this.session) this.toast(error.message);
    } finally { this.photoInput.value = ""; }
  }

  /** 画长按进度环；按屏幕位置映射画布，镜像前后触点均与手指保持一致。 */
  drawProgress(context) {
    if (!this.press) return;
    const rect = this.canvas.getBoundingClientRect();
    const scale = this.canvas.width / rect.width;
    context.save(); context.strokeStyle = "#41e18b"; context.lineWidth = 3 * scale;
    context.setLineDash([]); context.beginPath();
    context.arc((this.press.clientX - rect.left) * scale, (this.press.clientY - rect.top) * scale,
      20 * scale, -Math.PI / 2, -Math.PI / 2 + 2 * Math.PI * Math.min(1, (performance.now() - this.press.started) / 600));
    context.stroke(); context.restore();
  }

  /** 短文字提示，不保存任何用户画面。 */
  toast(message) {
    const node = document.getElementById("toast");
    node.textContent = message; node.hidden = false;
    clearTimeout(this.toastTimer);
    this.toastTimer = setTimeout(() => { node.hidden = true; }, 3500);
  }

  /** 停止/切换视频清理会话、选择和身份卡片，禁止旧操作落到新视频。 */
  reset() {
    this.session = null; this.selected = null; this.identitiesKey = "";
    this.cancel();
    document.getElementById("identity-list").replaceChildren();
    document.getElementById("identity-empty").hidden = false;
    document.getElementById("upload-photo").disabled = true;
    this.photoInput.value = "";
  }
}
