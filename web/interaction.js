/**
 * 两种视频模式共用的选中、长按、身份条和提示模块。
 * 输入客户端最新框/会话，输出锁定 HTTP 请求与 Canvas 样式；不采集或保存画面。
 */
import { logger } from "./logger.js";

// 只有用户主动打开相册后的短时间才保留视频会话；不能把任意切后台当成选照片。
const PHOTO_PICKER_TIMEOUT_MS = 60000;

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
    // 手机长按还会产生contextmenu；这段时间只允许手势计时器执行操作。
    this.contextMenuBlockedUntil = 0;
    this.interactionDiagnostics = false;
    this.identitiesKey = "";
    this.recordAllowed = false;
    this.recording = false;
    this.photoUploading = false;
    this.photoSelecting = false;
    this.photoDeadline = 0;
    this.photoTimer = null;
    this.photoController = null;
    this.photoIdentity = null;
    this.photoInput = document.getElementById("photo-file");
    document.getElementById("upload-photo").onclick = () => {
      if (this.session && !this.photoUploading && !this.photoSelecting) this.beginPhotoSelection();
      else this.toast("请先开始检测，再选择照片");
    };
    this.photoInput.onchange = () => { this.photoSelecting = false; void this.uploadPhoto(); };
    this.photoInput.addEventListener("cancel", () => {
      if (!this.photoSelecting) return;
      this.finishPhotoFlow();
      this.setPhotoStatus(this.photoIdentity ? "registered" : "idle",
        this.photoIdentity ? "已取消选择新照片，原登记目标保持不变。" : "已取消选择照片，尚未登记。");
    });
    document.getElementById("record-video").onclick = () => void this.toggleRecord();
    canvas.tabIndex = 0;
    canvas.setAttribute("aria-label", "目标操作：短按选中，长按或按 L 锁定");
    canvas.addEventListener("pointerdown", event => this.down(event));
    const finishPointer = event => {
      // 有些安卓浏览器在抬手后才补发菜单，松手后仍短暂屏蔽这一次重复事件。
      if (event.pointerType !== "mouse") this.contextMenuBlockedUntil = performance.now() + 1500;
      this.cancel(true, event.type === "pointercancel" ? "pointer_cancel" : "released_early");
    };
    canvas.addEventListener("pointerup", finishPointer);
    canvas.addEventListener("pointercancel", finishPointer);
    canvas.addEventListener("lostpointercapture", () => this.cancel(true, "capture_lost"));
    canvas.addEventListener("pointermove", event => {
      if (this.press && Math.hypot(event.clientX - this.press.clientX, event.clientY - this.press.clientY) > 12) this.cancel(true, "moved");
    });
    canvas.addEventListener("contextmenu", event => {
      event.preventDefault();
      // 触摸菜单不等于鼠标右键；否则600ms长按和系统菜单会先锁定再取消。
      if (this.press || event.pointerType === "touch" || event.sourceCapabilities?.firesTouchEvents ||
          performance.now() < this.contextMenuBlockedUntil) {
        this.sendInteraction("menu_suppressed", { reason: "duplicate_menu" });
        return;
      }
      const hit = this.hit(event);
      if (hit) { this.selected = hit.track_id; void this.lock(hit.track_id); }
    });
    canvas.addEventListener("keydown", event => {
      if (event.key.toLowerCase() === "l" && this.selected != null) {
        event.preventDefault(); void this.lock(this.selected);
      }
    });
    document.getElementById("identity-hint").textContent =
      "短按选中；按住0.6秒锁定，再按住绿框取消。锁定其他人会解除原目标，照片登记也会替换当前目标。";
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
    if (!box) { this.selected = null; this.redraw(); this.toast("请按住目标框内"); return; }
    this.selected = box.track_id;
    this.contextMenuBlockedUntil = performance.now() + 1500;
    this.canvas.focus({ preventScroll: true });
    this.canvas.setPointerCapture(event.pointerId);
    const action = box.state === "locked" ? "unlock" : "lock";
    this.press = { clientX: event.clientX, clientY: event.clientY, started: performance.now(),
      track: box.track_id, pointerId: event.pointerId };
    this.sendInteraction("press_start", { track_id: box.track_id,
      pointer: ["touch", "mouse", "pen"].includes(event.pointerType) ? event.pointerType : "unknown" });
    // 操作意图以按下时看到的状态为准，不在请求前重新翻转，重复lock请求也不会变成unlock。
    this.timer = setTimeout(() => {
      this.sendInteraction("press_commit", { track_id: box.track_id, reason: "hold_complete" });
      this.cancel(); void this.lock(box.track_id, action);
    }, 600);
    const animate = () => {
      this.redraw();
      if (this.press) this.animation = requestAnimationFrame(animate);
    };
    animate();
  }

  /** 终止手势和动画；停止视频时同样调用，禁止迟到的长按锁定。 */
  cancel(redraw = true, reason = null) {
    if (this.press && reason) this.sendInteraction("press_cancel", { track_id: this.press.track, reason });
    if (this.press) this.contextMenuBlockedUntil = performance.now() + 1500;
    clearTimeout(this.timer);
    cancelAnimationFrame(this.animation);
    this.press = null;
    if (redraw) this.redraw();
  }

  /** 输入同源接口与请求选项，输出 JSON；失败抛出服务端中文提示。 */
  async request(path, options = {}) {
    let response, body;
    try {
      response = await fetch(path, { cache: "no-store", signal: AbortSignal.timeout(15000), ...options });
    } catch (cause) {
      const timeout = ["TimeoutError", "AbortError"].includes(cause.name);
      const error = new Error(timeout ? "等待电脑响应超时，请检查连接后重试。" : "未能连接电脑，请检查热点和网页地址。", { cause });
      error.code = timeout ? "ACTION_TIMEOUT" : "ACTION_NETWORK_ERROR";
      throw error;
    }
    try {
      body = await response.json();
      if (!body || typeof body !== "object" || Array.isArray(body)) throw new Error("invalid response shape");
    }
    catch {
      const error = new Error(`电脑返回的内容无法解析（HTTP ${response.status}），请检查服务状态。`);
      error.code = "ACTION_BAD_RESPONSE";
      throw error;
    }
    // 只记录去掉查询凭据后的接口路径；请求编号可与电脑端同一操作关联，不序列化照片响应。
    logger.record(response.ok ? "info" : "warn", `操作 ${path.split("?")[0]} 状态${response.status}`,
      { source: "interaction", code: body.code || "ACTION_RESULT", seq: this.seq,
        traceId: response.headers.get("X-Request-ID") });
    if (!response.ok || body.ok === false) {
      const error = new Error(body.message || "操作失败，请重试");
      error.code = body.code;
      throw error;
    }
    return body;
  }

  /** 输入有限枚举/编号，在本页记录，并按服务能力传给同一电脑；不发送触点坐标或媒体。 */
  sendInteraction(event, details = {}) {
    if (!this.session) return;
    const record = { session_id: this.session, seq: this.seq, event, ...details };
    // 本地文字中只包含枚举、帧号和轨迹号；控制会话的凭据不会写入日志。
    logger.record("info", `交互 ${event} 帧${this.seq} 轨迹${details.track_id ?? "-"} ${details.reason || ""}`,
      { source: "interaction", code: event.toUpperCase(), seq: this.seq });
    if (!this.interactionDiagnostics) return;
    void fetch("/api/interaction-events", { method: "POST", cache: "no-store",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify(record),
      signal: AbortSignal.timeout(4000) }).catch(() => {
        // 诊断请求失败不能阻塞正常锁定，也不递归发送更多诊断请求。
        logger.record("warn", "交互诊断未送达电脑", { source: "interaction", code: "TRACE_UNAVAILABLE" });
      });
  }

  /** 从健康接口读取保存策略，默认禁用；页面操作不能绕过服务端禁止保存设置。 */
  configure(health) {
    this.interactionDiagnostics = health.diagnostics?.interaction_events === true;
    this.hybridMode = health.identity?.mode === "hybrid";
    document.querySelector(".photo-hint").textContent = this.hybridMode
      ? "实验模式：支持清晰单人人脸照或上半身/全身照。转头看不清脸时结合行人外观与连续运动跟踪；停止后清除全部模板。"
      : "当前按人物整体外观匹配，请使用上半身或全身清楚的单人照片；脸部特写尚不支持。停止检测后清除登记内容。";
    this.recordAllowed = health.recording?.allowed === true;
    document.getElementById("record-hint").textContent = this.recordAllowed
      ? "录制会在电脑保存带框视频。只有同意保存时才使用；停止检测会同时结束录制。"
      : "当前禁止保存画面，录制不可用。";
  }

  /** 用户点击且再次确认后才请求保存；默认策略下按钮和接口均拒绝录制。 */
  async toggleRecord() {
    if (!this.recordAllowed || !this.session) return;
    if (!this.recording && !window.confirm("录制将在这台电脑保存带标注的视频，不上传到互联网。是否同意本次保存？")) return;
    const session = this.session;
    try {
      const body = await this.request("/api/record/" + (this.recording ? "stop" : "start"),
        { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: session, confirm: true }) });
      if (session !== this.session) return;
      this.recording = body.active;
      document.getElementById("record-video").textContent = this.recording ? "停止录制" : "开始录制";
      const link = document.getElementById("download-record");
      link.hidden = this.recording || !body.filename;
      if (body.filename) link.href = "/api/record/file/" + encodeURIComponent(body.filename) +
        "?session_id=" + encodeURIComponent(session);
      this.toast(this.recording ? "正在录制" : "录制已停止：" + (body.filename || "暂无文件"));
    } catch (error) { if (session === this.session) this.toast(error.message); }
  }

  /** 输入轨迹号，携带会话和已显示帧号锁定；异步结果不得改变新会话。 */
  async lock(trackId, intendedAction = null) {
    if (!this.session || this.busy) return;
    const session = this.session;
    // 根据用户实际看到的状态表达操作意图，避免请求重试把“锁定”意外变成“取消”。
    const current = this.readState().boxes.find(box => box.track_id === trackId);
    const action = intendedAction || (current?.state === "locked" ? "unlock" : "lock");
    this.busy = true;
    document.getElementById("lock-action-status").textContent = action === "unlock" ? "正在发送取消请求…" : "正在发送锁定请求…";
    try {
      const body = await this.request("/api/lock", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: session, track_id: trackId, seq: this.seq, action }) });
      if (this.session !== session) return;
      if (body.action === "unlocked") this.selected = null;
      document.getElementById("lock-action-status").textContent = body.action === "unlocked"
        ? "最近操作：已取消锁定。" : `最近操作：${body.identity_id} 锁定请求成功；后续画面仍需身份核验。`;
      this.toast(body.message || (body.action === "unlocked" ? "已取消锁定" : body.identity_id + " 已锁定"));
      this.redraw();
      navigator.vibrate?.(50);
    } catch (error) {
      if (this.session === session) {
        document.getElementById("lock-action-status").textContent = "锁定操作失败：" + error.message;
        this.toast(error.message);
      }
    } finally { this.busy = false; }
  }

  /** 输入最新结果，刷新会话与身份卡片；文本使用 textContent，避免名字被当作 HTML。 */
  accept(result) {
    if (this.session !== result.session_id) { this.reset(); this.session = result.session_id || null; }
    this.seq = result.seq;
    document.getElementById("upload-photo").disabled = !this.session || this.photoUploading || this.photoSelecting;
    document.getElementById("record-video").disabled = !this.recordAllowed || !this.session;
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
    this.updatePhotoMatch(result);
    const target = identities[0];
    const matched = result.boxes?.find(box => box.state === "locked");
    const confirming = result.boxes?.some(box => box.state === "candidate");
    document.getElementById("target-status").textContent = !target ? "当前尚未登记跟踪目标。"
      : matched ? matched.verification === "continuity" ? `${target.id}：连续跟踪中，人脸暂未重新确认。` : `${target.id}：当前身份匹配通过。`
      : confirming ? `${target.id}：正在连续确认身份，尚未完成锁定。`
      : result.boxes?.some(box => box.cls === 0) ? `${target.id}：画面有人，但身份暂未确认；继续搜索，不代表你已离开。`
      : `${target.id}：当前未检出人物，继续等待。`;
    for (const event of result.events || []) {
      if (event.name === "relocked") {
        this.toast(event.identity_id + " 重新匹配成功"); navigator.vibrate?.(50);
      } else if (event.name === "lost") this.toast(event.identity_id + " 身份匹配暂时中断，继续等待确认");
    }
  }

  /** 输入框，输出样式与标签；分数保持当前模型值，颜色只表达交互/匹配状态。 */
  style(box) {
    if (box.state === "locked") return { color: "#41e18b", width: 3, dash: [], text: box.identity_id + (box.verification === "continuity" ? " 跟踪中" : "") };
    if (box.state === "candidate") return { color: "#41e18b", width: 2, dash: [6, 4], text: "识别中…" };
    return { color: box.track_id === this.selected ? "#ffe166" : "#ffffff", width: 2, dash: [],
      text: box.name.slice(0, 40) + (box.track_id == null ? "" : " #" + box.track_id) + " " + box.score.toFixed(2) };
  }

  /** 输入登记阶段和中文消息，输出常驻状态；不依赖3.5秒后会消失的短暂提示。 */
  setPhotoStatus(state, message) {
    const status = document.getElementById("photo-status");
    status.dataset.state = state;
    status.textContent = message;
  }

  /** 输入本帧身份与框，单独说明照片是否匹配；迟到的旧帧不能否定刚收到的登记成功响应。 */
  updatePhotoMatch(result) {
    if (!this.photoIdentity) return;
    const identity = (result.identities || []).find(item => item.id === this.photoIdentity.id);
    const message = document.getElementById("photo-match-status");
    if (!identity && !this.photoIdentity.seen) return;
    if (!identity) {
      this.photoIdentity = null;
      const preview = document.getElementById("photo-preview");
      preview.hidden = true; preview.removeAttribute("src");
      this.setPhotoStatus("idle", "照片目标已删除或被其他锁定替换。");
      message.textContent = "需要时可重新选择照片登记。";
      return;
    }
    this.photoIdentity.seen = true;
    message.textContent = (result.boxes || []).some(box => box.state === "locked" && box.identity_id === identity.id)
      ? `${identity.id}：已在视频中匹配成功。`
      : `${identity.id}：已登记，但视频中尚未确认同一人；不会据此显示实线绿框。`;
  }

  /** 只有明确的选照/上传操作在时限内才成立，供app.js区分系统相册和一般切后台。 */
  get photoFlowActive() {
    return (this.photoSelecting || this.photoUploading) && Date.now() < this.photoDeadline;
  }

  /** 用户点上传后先标记相册流程，再打开原生选择器，避免visibilitychange先清空会话。 */
  beginPhotoSelection() {
    // 使上一次已经超时但尚未结束的请求失效，防止它回来覆盖这一次选照状态。
    this.photoController?.abort();
    this.photoController = null;
    this.photoSelecting = true;
    this.photoDeadline = Date.now() + PHOTO_PICKER_TIMEOUT_MS;
    this.photoInput.value = "";
    document.getElementById("upload-photo").disabled = true;
    this.setPhotoStatus("selecting", "请选择照片；系统相册打开期间暂停传帧，最多等待60秒。");
    clearTimeout(this.photoTimer);
    this.photoTimer = setTimeout(() => {
      this.photoController?.abort();
      this.finishPhotoFlow();
      this.setPhotoStatus("error", "选择照片已超时，请返回页面后重新操作。");
    }, PHOTO_PICKER_TIMEOUT_MS);
    try { this.photoInput.click(); }
    catch {
      this.finishPhotoFlow();
      this.setPhotoStatus("error", "浏览器未能打开相册，请使用浏览器的照片访问权限后重试。");
    }
  }

  /** 清理一次选照流程和按钮；视频模块独立限制后台暂停时长，不依赖安卓事件先后顺序。 */
  finishPhotoFlow() {
    this.photoSelecting = false;
    this.photoUploading = false;
    this.photoDeadline = 0;
    clearTimeout(this.photoTimer);
    this.photoTimer = null;
    document.getElementById("upload-photo").disabled = !this.session;
  }

  /** 用户手动选照片后才传给同一电脑；FormData只存在内存，请求结束清理文件输入。 */
  async uploadPhoto() {
    const file = this.photoInput.files?.[0];
    const session = this.session;
    if (this.photoUploading) return;
    if (!file || !session) {
      this.finishPhotoFlow();
      if (file && !session) {
        this.photoInput.value = "";
        this.setPhotoStatus("error", "选照期间视频会话已结束，请重新开始检测后再选择照片。");
      }
      return;
    }
    if (file.size > 6 * 1024 * 1024 - 2048) {
      this.finishPhotoFlow();
      this.sendInteraction("photo_too_large", { reason: "size_limit" });
      this.setPhotoStatus("error", "本次未登记：请选择小于 6 MiB 的 JPEG/PNG 照片。");
      this.toast("请选择小于 6 MiB 的 JPEG/PNG 照片"); this.photoInput.value = ""; return;
    }
    this.photoUploading = true;
    // 没有经过相册点击标记的文件变更，也只允许有限时间上传，不能无限等待。
    if (!this.photoDeadline) this.photoDeadline = Date.now() + 30000;
    const controller = new AbortController();
    this.photoController = controller;
    const timer = setTimeout(() => controller.abort(), 30000);
    document.getElementById("upload-photo").disabled = true;
    const form = new FormData(); form.append("photo", file);
    try {
      this.setPhotoStatus("uploading", "正在上传到这台电脑并提取人物特征，请稍候…");
      this.toast("正在提取照片中的人物…");
      const body = await this.request("/api/identities/photo?session_id=" + encodeURIComponent(session),
        { method: "POST", body: form, signal: controller.signal });
      if (session === this.session && controller === this.photoController) {
        this.photoIdentity = { id: body.identity_id, seen: false };
        this.setPhotoStatus("registered", `${body.identity_id} 照片登记成功。${body.message}`);
        document.getElementById("photo-match-status").textContent = "等待后续视频帧确认是否为同一人；无需手动长按。";
        const preview = document.getElementById("photo-preview");
        if (typeof body.thumb === "string" && body.thumb.startsWith("/api/identities/")) {
          preview.src = body.thumb; preview.hidden = false;
        }
        this.toast(body.message);
      }
    } catch (error) {
      if (session === this.session && controller === this.photoController) {
        logger.captureError("照片登记失败", error, { source: "interaction", code: error.code || "PHOTO_UPLOAD_FAILED" });
        const hint = error.code === "NO_TARGET_IN_PHOTO" ? " 当前版本不支持脸部特写，请使用上半身或全身清楚的照片。" : "";
        this.setPhotoStatus("error", "本次登记失败：" + error.message + hint);
        this.toast(error.message);
      }
    } finally {
      clearTimeout(timer);
      // 停止后即使旧上传请求才返回，也不能清空新会话的文件选择或修改其按钮。
      if (session === this.session && controller === this.photoController) {
        this.photoController = null;
        this.finishPhotoFlow();
        this.photoInput.value = "";
      }
    }
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

  /** 绿框角上的脉冲点表示正在跟踪，输入画布坐标与缩放；不改变检测分数。 */
  drawMarker(context, box, x, y, scale) {
    if (box.state !== "locked") return;
    context.save(); context.setLineDash([]);
    context.globalAlpha = .55 + .45 * Math.sin(performance.now() / 250) ** 2;
    context.fillStyle = "#41e18b";
    context.beginPath(); context.arc(x + 6 * scale, y + 6 * scale, 3 * scale, 0, 2 * Math.PI);
    context.fill(); context.restore();
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
    this.photoController?.abort();
    this.photoController = null;
    this.finishPhotoFlow();
    this.recording = false;
    this.photoUploading = false; this.photoIdentity = null;
    this.setPhotoStatus("idle", "尚未登记照片。开始检测后，点击顶部“上传照片”。");
    document.getElementById("photo-match-status").textContent = "登记成功与匹配成功分别显示；只有确认匹配后才会出现实线绿框。";
    const preview = document.getElementById("photo-preview");
    preview.hidden = true; preview.removeAttribute("src");
    document.getElementById("lock-action-status").textContent = "尚未发送手动锁定请求。";
    document.getElementById("target-status").textContent = "当前尚未登记跟踪目标。";
    this.cancel(true, "stopped");
    document.getElementById("identity-list").replaceChildren();
    document.getElementById("identity-empty").hidden = false;
    document.getElementById("upload-photo").disabled = true;
    document.getElementById("record-video").disabled = true;
    document.getElementById("record-video").textContent = "开始录制";
    document.getElementById("download-record").hidden = true;
    document.getElementById("download-record").removeAttribute("href");
    this.photoInput.value = "";
  }
}
