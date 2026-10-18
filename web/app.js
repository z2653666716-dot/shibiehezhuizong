/**
 * ViTrack 前端检测入口：摄像头取帧 → JPEG/Base64 → WebSocket → Canvas 检测框。
 * 复用 camera.js 的设备管理和后端 /ws/stream，不在浏览器运行检测模型。
 * 一次只保留一帧请求；box_smoother.js 平滑显示坐标，停止/换尺寸时清除历史。
 */
import { camera } from "./camera.js";
import { logger } from "./logger.js";
import { BoxSmoother } from "./box_smoother.js";
import { TargetInteraction } from "./interaction.js";

const MAX_SIDE = 640;
const JPEG_QUALITY = 0.65;
const TARGET_FPS = 30;
const CONNECT_TIMEOUT_MS = 10000;
const RESPONSE_TIMEOUT_MS = 15000;
const ENCODE_TIMEOUT_MS = 10000;
const MAX_RETRIES = 3;

/** 输入画布，异步输出纯 JPEG Base64；超时/失败时拒绝，不留下无限等待。 */
function encodeFrame(canvas, quality = JPEG_QUALITY) {
  return new Promise((resolve, reject) => {
    let settled = false;
    let reader = null;
    const finish = (error, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (reader && reader.readyState === FileReader.LOADING) reader.abort();
      if (error) reject(error);
      else resolve(value);
    };
    const timer = setTimeout(() => finish(new Error("图像编码超时")), ENCODE_TIMEOUT_MS);
    try {
      canvas.toBlob((blob) => {
        if (settled) return;
        if (!blob) return finish(new Error("无法生成摄像头 JPEG"));
        reader = new FileReader();
        reader.onload = () => {
          const prefix = "data:image/jpeg;base64,";
          if (typeof reader.result !== "string" || !reader.result.startsWith(prefix)) {
            finish(new Error("摄像头图片格式不正确"));
          } else {
            finish(null, reader.result.slice(prefix.length));
          }
        };
        reader.onerror = () => finish(new Error("读取摄像头图片失败"));
        reader.onabort = () => finish(new Error("读取摄像头图片已取消"));
        reader.readAsDataURL(blob);
      }, "image/jpeg", quality);
    } catch (error) {
      finish(error);
    }
  });
}

/** 输入服务端数据，检查结果字段与归一化坐标，输出可安全绘制的同一结果。 */
function checkResult(data) {
  const finite = (value) => typeof value === "number" && Number.isFinite(value);
  if (!data || data.type !== "result" || !Number.isSafeInteger(data.seq) || data.seq < 0 ||
      !finite(data.fps) || data.fps < 0 || !finite(data.latency_ms) || data.latency_ms < 0 ||
      !Array.isArray(data.boxes) || data.boxes.length > 1000) {
    throw new Error("检测结果字段不正确");
  }
  for (const box of data.boxes) {
    if (!box || !Number.isInteger(box.cls) || box.cls < 0 || box.cls > 79 ||
        typeof box.name !== "string" || !box.name.trim() ||
        !finite(box.score) || box.score < 0 || box.score > 1 ||
        (box.track_id != null && (!Number.isSafeInteger(box.track_id) || box.track_id < 0)) ||
        !Array.isArray(box.xyxy) || box.xyxy.length !== 4 ||
        !box.xyxy.every((value) => finite(value) && value >= 0 && value <= 1) ||
        box.xyxy[0] >= box.xyxy[2] || box.xyxy[1] >= box.xyxy[3]) {
      throw new Error("检测框坐标或类别不正确");
    }
  }
  return data;
}

/**
 * 接收共享 Camera，管理网络会话、单帧等待和叠框；start 绑定事件后由摄像头驱动。
 * 输出是发给后端的帧消息、页面指标及画布，不保存图片文件。
 */
export class DetectionClient {
  constructor(sourceCamera) {
    this.camera = sourceCamera;
    this.socket = null;
    this.generation = 0;
    this.sequence = 0;
    this.received = 0;
    this.maxSide = MAX_SIDE;
    this.jpegQuality = JPEG_QUALITY;
    this.pending = null;
    this.encoding = false;
    this.state = "idle";
    this.retryCount = 0;
    this.retryTimer = null;
    this.connectTimer = null;
    this.responseTimer = null;
    this.animation = null;
    this.lastCaptureAt = -Infinity;
    this.boxes = [];
    this.smoother = new BoxSmoother();
    this.started = false;
    this.captureCanvas = document.createElement("canvas");
    this.captureContext = this.captureCanvas.getContext("2d");
    this.overlayContext = this.camera.overlay.getContext("2d");
    if (!this.captureContext || !this.overlayContext) throw new Error("浏览器无法创建绘图画布");
    this.nodes = {
      connection: document.getElementById("connection-status"),
      page: document.getElementById("page-status"),
      hint: document.getElementById("camera-hint"),
      result: document.getElementById("result-summary"),
      fps: document.getElementById("fps-value"),
      latency: document.getElementById("latency-value"),
      count: document.getElementById("frame-count"),
      frame: document.getElementById("latest-frame"),
    };
    this.interaction = new TargetInteraction(this.camera.overlay,
      () => ({ boxes: this.boxes, mirrored: this.camera.mirrored }), () => this.drawBoxes());
  }

  /** 绑定一次生命周期，准备控件并读取设备信息；不自动请求摄像头权限。 */
  start() {
    if (this.started) return;
    this.started = true;
    this.camera.addEventListener("started", () => {
      this.received = 0;
      this.nodes.count.textContent = "0";
      this.retryCount = 0;
      if (document.hidden) this.stop("页面在后台，已暂停检测。", "paused");
      else this.connect();
    });
    this.camera.addEventListener("stopped", () => {
      this.stop("检测已停止，可以重新开始。");
    });
    this.camera.addEventListener("resize", () => {
      this.boxes = [];
      this.interaction.cancel(false);
      this.interaction.selected = null;
      this.smoother.reset();
      this.drawBoxes();
    });
    this.camera.addEventListener("mirrorchange", () => { this.interaction.cancel(false); this.drawBoxes(); });
    window.addEventListener("resize", () => this.drawBoxes());
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) {
        if (this.camera.state === "running") this.stop("页面在后台，已暂停检测。", "paused");
      } else if (this.camera.state === "running") {
        this.retryCount = 0;
        this.connect();
      }
    });
    window.addEventListener("offline", () => {
      if (this.camera.state === "running") this.stop("网络离线，请恢复网络后重试。", "error");
    });
    window.addEventListener("online", () => {
      if (this.camera.state === "running" && !document.hidden && !this.socket) {
        this.retryCount = 0;
        this.connect();
      }
    });
    window.addEventListener("pagehide", () => this.closeTransport());
    document.getElementById("start-detection").textContent = "开始检测";
    document.getElementById("stop-detection").textContent = "停止检测";
    document.getElementById("controls-hint").textContent = "开始后会开启摄像头，并将画面交给电脑检测。";
    this.setStatus("idle", "点击“开始检测”，允许摄像头访问后即可检测。");
    void this.loadHealth();
  }

  /** 读取同一服务的健康信息，更新设备/模型；失败不阻止用户稍后重试检测。 */
  async loadHealth() {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch("/api/health", { signal: controller.signal, cache: "no-store" });
      const data = await response.json();
      if (!response.ok || data.ok !== true) {
        logger.record("error", data.message || "无法读取检测服务信息", {
          source: "api", code: data.code || "HEALTH_FAILED",
          traceId: response.headers.get("X-Request-ID"),
        });
        document.getElementById("health-status").textContent = "服务尚未就绪";
        return;
      }
      document.getElementById("health-status").textContent = "服务就绪";
      document.getElementById("device-name").textContent = data.device_name || "未知设备";
      document.getElementById("model-name").textContent = data.model || "未知模型";
    } catch (error) {
      document.getElementById("health-status").textContent = "暂时无法读取";
      logger.captureError("读取检测服务信息失败", error, { source: "api", code: "HEALTH_FAILED" });
    } finally {
      clearTimeout(timer);
    }
  }

  /** 输入状态和中文提示，更新连接标记与可见提示，不修改摄像头本身。 */
  setStatus(state, message) {
    this.state = state;
    const labels = {
      idle: "未连接", connecting: "连接中", connected: "已连接",
      retrying: "重连中", paused: "已暂停", error: "连接异常",
    };
    this.nodes.connection.textContent = labels[state];
    this.nodes.connection.dataset.state = state === "retrying" ? "connecting" : state;
    this.nodes.page.textContent = message;
    this.nodes.hint.textContent = message;
  }

  /** 摄像头准备好后连接同一服务；HTTP 自动选 ws，HTTPS 自动选 wss。 */
  connect() {
    if (this.camera.state !== "running" || document.hidden) return;
    this.closeTransport();
    const generation = this.generation;
    this.setStatus("connecting", "摄像头已开启，正在连接检测服务…");
    let socket;
    try {
      const url = new URL("/ws/stream", location.href);
      url.protocol = location.protocol === "https:" ? "wss:" : "ws:";
      socket = new WebSocket(url);
    } catch (error) {
      this.fail("无法建立检测连接，请检查服务是否启动。", "WS_CONNECT_FAILED", true);
      return;
    }
    this.socket = socket;
    const current = () => this.socket === socket && this.generation === generation;
    this.connectTimer = setTimeout(() => {
      if (current()) this.fail("连接检测服务超时。", "WS_CONNECT_TIMEOUT", true);
    }, CONNECT_TIMEOUT_MS);
    socket.addEventListener("open", () => {
      if (!current()) return;
      clearTimeout(this.connectTimer);
      this.connectTimer = null;
      this.setStatus("connected", "已连接检测服务，正在处理摄像头画面。");
      this.lastCaptureAt = -Infinity;
      this.tick(performance.now(), generation);
    });
    socket.addEventListener("message", (event) => {
      if (current()) this.receive(event.data);
    });
    socket.addEventListener("error", () => {
      if (current()) this.fail("检测连接失败，请检查电脑服务与网络。", "WS_ERROR", true);
    });
    socket.addEventListener("close", () => {
      if (current()) this.fail("检测连接已断开。", "WS_CLOSED", true);
    });
  }

  /**
   * 浏览器每次准备绘制页面时调用；忙于编码或等待结果就跳过，不排队。
   * 输入时间与会话编号，无返回值；只有当前会话可以安排下一次调用。
   */
  tick(now, generation) {
    if (generation !== this.generation || this.state !== "connected") return;
    this.animation = requestAnimationFrame((time) => this.tick(time, generation));
    if (this.pending || this.encoding || this.socket.bufferedAmount > 0 ||
        this.camera.state !== "running" || document.hidden ||
        now - this.lastCaptureAt < 1000 / TARGET_FPS) return;
    this.lastCaptureAt = now;
    void this.capture(generation);
  }

  /** 缩放当前视频，编码 JPEG，再发送一帧；异步结束后重新核对会话，防止迟到发送。 */
  async capture(generation) {
    this.encoding = true;
    try {
      const sourceWidth = this.camera.video.videoWidth;
      const sourceHeight = this.camera.video.videoHeight;
      if (!sourceWidth || !sourceHeight) throw new Error("摄像头尺寸尚未就绪");
      const scale = Math.min(1, this.maxSide / Math.max(sourceWidth, sourceHeight));
      const width = Math.max(1, Math.round(sourceWidth * scale));
      const height = Math.max(1, Math.round(sourceHeight * scale));
      this.captureCanvas.width = width;
      this.captureCanvas.height = height;
      this.captureContext.drawImage(this.camera.video, 0, 0, width, height);
      const image = await encodeFrame(this.captureCanvas, this.jpegQuality);
      if (generation !== this.generation || this.state !== "connected" ||
          this.camera.state !== "running" || document.hidden) return;
      const seq = ++this.sequence;
      this.pending = { seq, sourceWidth, sourceHeight };
      this.socket.send(JSON.stringify({
        type: "frame", seq, ts: Date.now(), w: width, h: height, img: image,
      }));
      this.responseTimer = setTimeout(() => {
        if (generation === this.generation) this.fail("等待检测结果超时，正在尝试恢复连接。", "FRAME_TIMEOUT", true);
      }, RESPONSE_TIMEOUT_MS);
    } catch (error) {
      if (generation === this.generation) {
        logger.captureError("摄像头帧发送失败", error, { source: "stream", code: "FRAME_SEND_FAILED" });
        this.fail("无法准备或发送摄像头画面，请停止后重试。", "FRAME_SEND_FAILED");
      }
    } finally {
      if (generation === this.generation) this.encoding = false;
    }
  }

  /** 输入 WebSocket 文本，检查帧号、回收等待位置，更新真实指标并绘制检测框。 */
  receive(text) {
    try {
      if (typeof text !== "string") throw new Error("检测服务返回了非文本消息");
      const data = JSON.parse(text);
      if (data && data.ok === false && typeof data.message === "string") {
        this.fail(data.message, typeof data.code === "string" ? data.code : "SERVER_ERROR");
        return;
      }
      const result = checkResult(data);
      if (!this.pending || result.seq !== this.pending.seq) throw new Error("检测结果帧号与请求不一致");
      const pending = this.pending;
      clearTimeout(this.responseTimer);
      this.responseTimer = null;
      this.pending = null;
      this.retryCount = 0;
      this.received += 1;
      this.interaction.accept(result);
      if (result.capture_max_side && result.capture_max_side < this.maxSide) {
        this.maxSide = result.capture_max_side;
        this.interaction.toast("处理较慢，已降低传输尺寸以保持流畅");
      }
      this.nodes.fps.textContent = result.fps.toFixed(1);
      this.nodes.latency.textContent = result.latency_ms.toFixed(1);
      this.nodes.count.textContent = String(this.received);
      this.nodes.frame.textContent = String(result.seq);
      // 旋转/换尺寸后回来的旧尺寸结果可以计数，但不能画到当前尺寸的视频上。
      if (pending.sourceWidth === this.camera.video.videoWidth &&
          pending.sourceHeight === this.camera.video.videoHeight) {
        // 只平滑已通过校验的同尺寸框；人数和 score 仍属于当前帧，镜像在绘制时处理。
        this.boxes = this.smoother.update(result.boxes, pending.sourceWidth, pending.sourceHeight);
      } else {
        this.boxes = [];
        this.smoother.reset();
      }
      const summary = this.boxes.length ? "检测到 " + this.boxes.length + " 个目标。" : "当前画面未检测到目标。";
      if (this.nodes.result.textContent !== summary) this.nodes.result.textContent = summary;
      this.drawBoxes();
    } catch (error) {
      logger.captureError("检测结果无法解析", error, { source: "stream", code: "BAD_RESULT" });
      this.fail("检测服务返回的数据不正确，请停止后重试。", "BAD_RESULT");
    }
  }

  /** 根据当前框与实际画布绘制白框/标签；镜像只换算横坐标，不反转标签文字。 */
  drawBoxes() {
    const canvas = this.camera.overlay;
    const context = this.overlayContext;
    context.clearRect(0, 0, canvas.width, canvas.height);
    const displayWidth = canvas.getBoundingClientRect().width;
    if (!displayWidth || this.camera.state !== "running") return;
    // 把屏幕上约 2px 的线宽换算到画布像素，手机缩放后标签仍可读。
    const scale = canvas.width / displayWidth;
    const padding = 4 * scale;
    const labelHeight = 22 * scale;
    context.lineWidth = 2 * scale;
    context.font = Math.round(13 * scale) + "px sans-serif";
    context.textBaseline = "middle";
    context.setLineDash([]);
    for (const box of this.boxes) {
      let [left, top, right, bottom] = box.xyxy;
      if (this.camera.mirrored) [left, right] = [1 - right, 1 - left];
      const x = left * canvas.width;
      const y = top * canvas.height;
      const style = this.interaction.style(box);
      context.strokeStyle = style.color;
      context.lineWidth = style.width * scale;
      context.setLineDash(style.dash.map(value => value * scale));
      context.globalAlpha = box.score < 0.45 ? 0.35 : 1;
      context.strokeRect(x, y, (right - left) * canvas.width, (bottom - top) * canvas.height);
      // # 后面是当前视频里的轨迹号，不是身份识别；score 仍是当前检测原始分数。
      const track = box.track_id == null ? "" : " #" + box.track_id;
      const text = style.text;
      const labelWidth = Math.min(canvas.width, context.measureText(text).width + 2 * padding);
      const labelX = Math.max(0, Math.min(x, canvas.width - labelWidth));
      const labelY = Math.max(0, Math.min(y >= labelHeight ? y - labelHeight : y, canvas.height - labelHeight));
      context.fillStyle = box.state === "locked" ? "rgba(18, 77, 45, 0.94)" : "rgba(24, 28, 32, 0.88)";
      context.fillRect(labelX, labelY, labelWidth, labelHeight);
      context.fillStyle = style.color;
      context.fillText(text, labelX + padding, labelY + labelHeight / 2, Math.max(1, labelWidth - 2 * padding));
      this.interaction.drawMarker(context, box, x, y, scale);
    }
    context.globalAlpha = 1;
    this.interaction.drawProgress(context);
  }

  /** 使旧会话失效，清计时器和待回帧；旧编码/旧连接回调随后完成也不能生效。 */
  closeTransport() {
    this.generation += 1;
    cancelAnimationFrame(this.animation);
    this.animation = null;
    clearTimeout(this.retryTimer);
    clearTimeout(this.connectTimer);
    clearTimeout(this.responseTimer);
    this.retryTimer = this.connectTimer = this.responseTimer = null;
    const socket = this.socket;
    this.socket = null;
    if (socket && socket.readyState < WebSocket.CLOSING) {
      try { socket.close(1000, "client stopped"); } catch { /* 连接已关闭时无需再次处理。 */ }
    }
    this.pending = null;
    this.encoding = false;
    this.boxes = [];
    this.smoother.reset();
    this.interaction.reset();
    this.drawBoxes();
    this.nodes.fps.textContent = "--";
    this.nodes.latency.textContent = "--";
    this.nodes.frame.textContent = "--";
  }

  /** 停止当前检测连接，不主动改变摄像头；用于手动停止和切后台。 */
  stop(message = "检测已停止。", state = "idle") {
    this.closeTransport();
    this.nodes.result.textContent = state === "paused" ? "检测已暂停。" : "尚未收到检测结果。";
    this.setStatus(state, message);
  }

  /** 显示中文错误；只有网络类故障有限重连，服务端明确报错则等待用户重新开始。 */
  fail(message, code, retry = false) {
    logger.record("error", message, { source: "stream", code });
    this.closeTransport();
    this.nodes.result.textContent = "检测已暂停。";
    if (retry && this.retryCount < MAX_RETRIES &&
        this.camera.state === "running" && !document.hidden) {
      const delay = 1000 * 2 ** this.retryCount++;
      this.setStatus("retrying", message + " 将自动重连（" + this.retryCount + "/" + MAX_RETRIES + "）。");
      this.retryTimer = setTimeout(() => this.connect(), delay);
    } else {
      this.setStatus("error", message + (retry ? " 请停止后重新开始。" : ""));
    }
  }
}

export const client = new DetectionClient(camera);
client.start();
