/**
 * IP 视频源观看模块：只接收电脑返回的 JPEG 与同帧检测结果，不调用 getUserMedia。
 * start.js 在确认服务为 ipcam 模式后创建本类，HTML 提供预览画布、叠框画布及操作控件。
 * 图像只在内存绘制，box_smoother.js 平滑坐标；开始需同意，停止要等待服务端确认。
 */
import { logger } from "./logger.js";
import { BoxSmoother } from "./box_smoother.js";
import { TargetInteraction } from "./interaction.js";

const API_TIMEOUT_MS = 10000;
const CONNECT_TIMEOUT_MS = 10000;
const RESPONSE_TIMEOUT_MS = 20000;
const DECODE_TIMEOUT_MS = 10000;
const MAX_JPEG_LENGTH = 4 * Math.ceil(4 * 1024 * 1024 / 3);

/** 输入服务端包，输出通过检查的原包；尺寸、序号、框和图像必须来自同一帧。 */
export function checkIpPacket(data) {
  const finite = (value) => typeof value === "number" && Number.isFinite(value);
  if (!data || data.type !== "ipcam_frame" || !Number.isSafeInteger(data.seq) || data.seq < 1 ||
      !Number.isInteger(data.w) || !Number.isInteger(data.h) ||
      data.w < 1 || data.h < 1 || data.w > 2048 || data.h > 2048 ||
      typeof data.img !== "string" || !data.img.startsWith("/9j/") ||
      data.img.length > MAX_JPEG_LENGTH || !/^[A-Za-z0-9+/]+={0,2}$/.test(data.img)) {
    throw new Error("IP 视频源返回的图像或尺寸不正确");
  }
  const result = data.result;
  if (!result || result.type !== "result" || result.seq !== data.seq ||
      !finite(result.fps) || result.fps < 0 || !finite(result.latency_ms) || result.latency_ms < 0 ||
      !Array.isArray(result.boxes) || result.boxes.length > 1000) {
    throw new Error("IP 图像与检测结果不对应");
  }
  for (const box of result.boxes) {
    if (!box || !Number.isInteger(box.cls) || box.cls < 0 || box.cls > 79 ||
        typeof box.name !== "string" || !box.name.trim() ||
        !finite(box.score) || box.score < 0 || box.score > 1 ||
        (box.track_id != null && (!Number.isSafeInteger(box.track_id) || box.track_id < 0)) ||
        !Array.isArray(box.xyxy) || box.xyxy.length !== 4 ||
        !box.xyxy.every((value) => finite(value) && value >= 0 && value <= 1) ||
        box.xyxy[0] >= box.xyxy[2] || box.xyxy[1] >= box.xyxy[3]) {
      throw new Error("IP 检测框格式不正确");
    }
  }
  return data;
}

/** 输入纯 JPEG Base64，异步返回解码后的 Image；图片解码失败或超时都结束等待。 */
function decodeImage(jpeg) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    let settled = false;
    const finish = (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (error) reject(error);
      else resolve(image);
    };
    const timer = setTimeout(() => finish(new Error("IP 图像解码超时")), DECODE_TIMEOUT_MS);
    image.src = "data:image/jpeg;base64," + jpeg;
    image.decode().then(() => finish(), () => finish(new Error("无法解码 IP 视频源图像")));
  });
}

/**
 * 输入两个 Canvas，输出当前页的网络视频预览和指标。
 * bind 只绑定界面；start 才请求启动源；每绘制完一帧才 requestNext，保持一帧在途。
 */
export class IpCameraClient {
  constructor(preview, overlay) {
    this.preview = preview;
    this.overlay = overlay;
    this.context = preview.getContext("2d");
    this.overlayContext = overlay.getContext("2d");
    if (!this.context || !this.overlayContext) throw new Error("浏览器无法创建 IP 预览画布");
    this.socket = null;
    this.generation = 0;
    this.state = "idle";
    this.sourceRequested = false;
    this.startRequest = null;
    this.stopRequest = null;
    this.connectTimer = null;
    this.responseTimer = null;
    this.pending = false;
    this.decoding = false;
    this.lastSeq = 0;
    this.received = 0;
    this.boxes = [];
    this.smoother = new BoxSmoother();
    this.lastImage = null;
    this.mirrored = false;
    this.bound = false;
    this.nodes = {};
    for (const [name, id] of Object.entries({
      start: "start-detection", stop: "stop-detection", consent: "ipcam-consent",
      mirror: "mirror-preview", controls: "camera-controls", facing: "camera-facing",
      video: "camera-video", placeholder: "camera-placeholder", camera: "camera-status",
      connection: "connection-status", page: "page-status", hint: "camera-hint",
      result: "result-summary", fps: "fps-value", latency: "latency-value",
      count: "frame-count", frame: "latest-frame", size: "frame-size",
    })) {
      this.nodes[name] = document.getElementById(id);
      if (!this.nodes[name]) throw new Error("页面缺少 IP 视频源控件：" + id);
    }
  }

  /** 绑定一次事件并显示模式；初始不发启动请求，也不连接任何摄像头。 */
  bind() {
    if (this.bound) return;
    this.bound = true;
    this.interaction = new TargetInteraction(this.overlay,
      () => ({ boxes: this.boxes, mirrored: this.mirrored }), () => this.render());
    this.nodes.video.hidden = true;
    document.getElementById("ipcam-consent-panel").hidden = false;
    document.getElementById("camera-heading").textContent = "IP 视频源画面";
    this.nodes.start.textContent = "开始读取";
    this.nodes.stop.textContent = "停止读取";
    document.getElementById("controls-hint").textContent =
      "电脑读取已配置的手机视频流；请先勾选同意，再开始。";
    this.nodes.controls.disabled = false;
    this.nodes.facing.disabled = true;
    this.nodes.consent.checked = false;
    // 与浏览器采集模式共用开关默认值；未收到图像时只记状态，不连接视频源。
    this.mirrored = this.nodes.mirror.checked;
    this.nodes.start.addEventListener("click", () => void this.start());
    this.nodes.stop.addEventListener("click", () => void this.stop());
    this.nodes.consent.addEventListener("change", () => {
      if (!this.nodes.consent.checked && this.sourceRequested) void this.stop("已取消同意，电脑已停止读取。");
      else this.updateControls();
    });
    this.nodes.mirror.addEventListener("change", () => {
      this.mirrored = this.nodes.mirror.checked;
      this.render();
    });
    window.addEventListener("resize", () => this.render());
    document.addEventListener("visibilitychange", () => {
      if (document.hidden && this.sourceRequested) void this.stop("页面已切到后台，电脑已停止读取。");
    });
    window.addEventListener("offline", () => {
      if (this.sourceRequested) void this.stop("网络离线，已停止读取。", true);
    });
    window.addEventListener("pagehide", () => {
      this.generation += 1;
      this.closeTransport();
      this.clearPreview();
      // 页面退出时只能尽力发送停止；没有响应就不能宣称已关闭手机 App。
      if (this.sourceRequested) {
        void fetch("/api/ipcam/stop", { method: "POST", keepalive: true }).catch(() => {});
      }
    });
    this.setStatus("idle", "勾选同意后，可开始读取已配置的手机视频源。");
    this.nodes.hint.textContent = "画面只供本机处理和显示，不保存照片或视频。";
  }

  /** 根据实际状态启用按钮；停止未确认时保留重试停止入口，不能允许再次开始。 */
  updateControls() {
    this.nodes.start.disabled = !this.nodes.consent.checked || this.sourceRequested ||
      !["idle", "error"].includes(this.state);
    this.nodes.stop.disabled = !this.sourceRequested || this.state === "stopping";
  }

  /** 输入状态/提示，更新界面；不把“连接中”显示成已有检测结果。 */
  setStatus(state, message) {
    this.state = state;
    this.nodes.connection.dataset.state = state === "connected" ? "connected" :
      state === "error" ? "error" : state === "opening" || state === "stopping" ? "connecting" : "idle";
    this.nodes.connection.textContent = {
      idle: "未连接", opening: "连接中", connected: "已连接", stopping: "停止中", error: "需要处理",
    }[state] || state;
    this.nodes.page.textContent = message;
    this.nodes.camera.textContent = message;
    this.updateControls();
  }

  /** 输入同源控制地址与可选确认数据，输出 JSON；限定等待，不记录图像或请求正文。 */
  async requestControl(path, body) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), API_TIMEOUT_MS);
    try {
      const response = await fetch(path, {
        method: "POST", signal: controller.signal, cache: "no-store",
        ...(body === undefined ? {} : {
          headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
        }),
      });
      let data;
      try { data = await response.json(); }
      catch { throw new Error("IP 控制接口返回的内容无法解析"); }
      if (!response.ok || data.ok !== true) {
        throw new Error(typeof data.message === "string" ? data.message.slice(0, 1000) : "IP 视频源控制请求失败");
      }
      return data;
    } catch (error) {
      if (error.name === "AbortError") throw new Error("IP 视频源控制请求超时");
      if (error instanceof TypeError) throw new Error("无法连接 IP 视频源控制接口");
      throw error;
    } finally {
      clearTimeout(timer);
    }
  }

  /** 无额外输入；只在当前页明确勾选同意后启动源，再连接观看接口。 */
  async start() {
    if (!this.nodes.consent.checked || this.sourceRequested || this.stopRequest ||
        !["idle", "error"].includes(this.state)) return;
    const generation = ++this.generation;
    this.closeTransport();
    this.clearPreview();
    this.lastSeq = 0;
    this.received = 0;
    this.nodes.count.textContent = "0";
    this.sourceRequested = true;
    this.setStatus("opening", "正在启动已配置的 IP 视频源，等待画面。");
    const operation = this.requestControl("/api/ipcam/start", { confirm: true });
    this.startRequest = operation;
    try {
      await operation;
      if (generation !== this.generation) return;
      this.connect(generation);
    } catch (error) {
      if (generation !== this.generation) return;
      logger.captureError("IP 视频源启动失败", error, { source: "ipcam", code: "IPCAM_START_FAILED" });
      // 即使启动响应丢失，服务器也可能已经开启；继续请求停止，不冒充已经释放。
      void this.stop(error.message || "IP 视频源启动失败。", true);
    } finally {
      if (this.startRequest === operation) this.startRequest = null;
    }
  }

  /** 输入当前会话编号，只建立同源 WS/WSS；旧连接回调不能恢复已停止的画面。 */
  connect(generation) {
    const url = new URL("/ws/ipcam", location.href);
    url.protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(url);
    this.socket = socket;
    const current = () => this.socket === socket && this.generation === generation;
    this.connectTimer = setTimeout(() => {
      if (current()) void this.stop("连接 IP 观看接口超时。", true);
    }, CONNECT_TIMEOUT_MS);
    socket.onopen = () => {
      if (!current()) return socket.close();
      clearTimeout(this.connectTimer);
      this.connectTimer = null;
      this.setStatus("connected", "已连接，正在等待新的 IP 检测画面。");
      this.requestNext(generation);
    };
    socket.onmessage = (event) => {
      if (current()) void this.receive(event.data, generation);
    };
    socket.onerror = () => {
      if (current()) void this.stop("IP 观看连接发生网络错误。", true);
    };
    socket.onclose = () => {
      if (current()) void this.stop("IP 观看连接已断开，请重新确认后开始。", true);
    };
  }

  /** 输入会话编号，仅在上一帧解码绘制完成后发送 next；不向服务端推送任何图像。 */
  requestNext(generation) {
    if (generation !== this.generation || !this.socket ||
        this.socket.readyState !== WebSocket.OPEN || this.pending || this.decoding) return;
    this.pending = true;
    try {
      this.socket.send(JSON.stringify({ type: "next", after: this.lastSeq }));
      this.responseTimer = setTimeout(() => {
        if (generation === this.generation) void this.stop("等待 IP 检测画面超时。", true);
      }, RESPONSE_TIMEOUT_MS);
    } catch (error) {
      logger.captureError("请求 IP 画面失败", error, { source: "ipcam", code: "IPCAM_SEND_FAILED" });
      void this.stop("无法请求 IP 画面。", true);
    }
  }

  /** 输入响应文本/会话编号，校验、解码并绘制同帧图像和框，然后才请求下一帧。 */
  async receive(text, generation) {
    if (generation !== this.generation) return;
    try {
      if (!this.pending || this.decoding) throw new Error("收到未请求的 IP 画面");
      clearTimeout(this.responseTimer);
      this.responseTimer = null;
      this.pending = false;
      let data;
      try { data = JSON.parse(text); }
      catch { throw new Error("IP 观看接口返回的内容不是有效 JSON"); }
      if (data?.ok === false) throw new Error(typeof data.message === "string" ? data.message.slice(0, 1000) : "IP 视频源已停止");
      const packet = checkIpPacket(data);
      if (packet.seq <= this.lastSeq) throw new Error("IP 画面序号没有更新");
      this.decoding = true;
      const image = await decodeImage(packet.img);
      if (generation !== this.generation) return;
      if (image.naturalWidth !== packet.w || image.naturalHeight !== packet.h) {
        throw new Error("IP 图像实际尺寸与返回结果不一致");
      }
      if (this.preview.width !== packet.w || this.preview.height !== packet.h) {
        this.preview.width = this.overlay.width = packet.w;
        this.preview.height = this.overlay.height = packet.h;
      }
      this.lastImage = image;
      // 收到并解码当前图像后才更新平滑；尺寸改变时模块自动丢弃旧历史。
      this.boxes = this.smoother.update(packet.result.boxes, packet.w, packet.h);
      this.interaction.accept(packet.result);
      this.lastSeq = packet.seq;
      this.received += 1;
      this.render();
      this.nodes.fps.textContent = packet.result.fps.toFixed(1);
      this.nodes.latency.textContent = packet.result.latency_ms.toFixed(1);
      this.nodes.count.textContent = String(this.received);
      this.nodes.frame.textContent = String(this.lastSeq);
      this.nodes.size.textContent = packet.w + " × " + packet.h;
      this.nodes.result.textContent = this.boxes.length
        ? "检测到 " + this.boxes.length + " 个目标。" : "当前画面未检测到目标。";
      this.nodes.hint.textContent = "正在显示手机 IP 视频源，电脑浏览器没有开启本机摄像头。";
      this.decoding = false;
      this.requestNext(generation);
    } catch (error) {
      if (generation !== this.generation) return;
      logger.captureError("IP 画面处理失败", error, { source: "ipcam", code: "IPCAM_BAD_PACKET" });
      void this.stop(error.message || "IP 画面处理失败。", true);
    } finally {
      if (generation === this.generation) this.decoding = false;
    }
  }

  /** 无输入，重绘缓存中的一帧；镜像分别处理图像与框，标签文字保持正向。 */
  render() {
    const width = this.preview.width, height = this.preview.height;
    this.context.clearRect(0, 0, width, height);
    this.overlayContext.clearRect(0, 0, width, height);
    if (!this.lastImage) return;
    this.preview.hidden = false;
    this.overlay.hidden = false;
    this.nodes.placeholder.hidden = true;
    this.context.save();
    if (this.mirrored) {
      this.context.translate(width, 0);
      this.context.scale(-1, 1);
    }
    this.context.drawImage(this.lastImage, 0, 0, width, height);
    this.context.restore();
    const context = this.overlayContext;
    const scale = width / Math.max(1, this.overlay.getBoundingClientRect().width);
    const padding = 4 * scale, labelHeight = 22 * scale;
    context.lineWidth = 2 * scale;
    context.font = Math.round(13 * scale) + "px sans-serif";
    context.textBaseline = "middle";
    context.setLineDash([]);
    for (const box of this.boxes) {
      let [left, top, right, bottom] = box.xyxy;
      if (this.mirrored) [left, right] = [1 - right, 1 - left];
      const x = left * width, y = top * height;
      const style = this.interaction.style(box);
      context.strokeStyle = style.color;
      context.lineWidth = style.width * scale;
      context.setLineDash(style.dash.map(value => value * scale));
      context.globalAlpha = box.score < 0.45 ? 0.35 : 1;
      context.strokeRect(x, y, (right - left) * width, (bottom - top) * height);
      // 轨迹号与当前分数都来自当前结果，镜像仅影响位置，不反转文字。
      const track = box.track_id == null ? "" : " #" + box.track_id;
      const text = style.text;
      const labelWidth = Math.min(width, context.measureText(text).width + 2 * padding);
      const labelX = Math.max(0, Math.min(x, width - labelWidth));
      const labelY = Math.max(0, Math.min(y >= labelHeight ? y - labelHeight : y, height - labelHeight));
      context.fillStyle = "rgba(24, 28, 32, 0.88)";
      context.fillRect(labelX, labelY, labelWidth, labelHeight);
      context.fillStyle = style.color;
      context.fillText(text, labelX + padding, labelY + labelHeight / 2, Math.max(1, labelWidth - 2 * padding));
    }
    context.globalAlpha = 1;
    this.interaction.drawProgress(context);
  }

  /** 无输入，关闭观看连接与计时器；sourceRequested 要等待停止接口确认后再清除。 */
  closeTransport() {
    clearTimeout(this.connectTimer);
    clearTimeout(this.responseTimer);
    this.connectTimer = this.responseTimer = null;
    const socket = this.socket;
    this.socket = null;
    if (socket && socket.readyState < WebSocket.CLOSING) {
      try { socket.close(1000, "viewer stopped"); } catch { /* 旧连接可能已经关闭。 */ }
    }
    this.pending = false;
    this.decoding = false;
  }

  /** 无输入，清空画面和指标，不留下停止前的截图冒充实时画面。 */
  clearPreview() {
    this.lastImage = null;
    this.boxes = [];
    this.smoother.reset();
    this.interaction?.reset();
    this.context.clearRect(0, 0, this.preview.width, this.preview.height);
    this.overlayContext.clearRect(0, 0, this.overlay.width, this.overlay.height);
    this.preview.hidden = this.overlay.hidden = true;
    this.nodes.placeholder.hidden = false;
    this.nodes.fps.textContent = this.nodes.latency.textContent = this.nodes.frame.textContent = "--";
    this.nodes.size.textContent = "--";
    this.nodes.result.textContent = "尚未收到检测结果。";
  }

  /** 输入结束提示/是否故障；先清本地画面，再等待启动请求收尾，最后确认服务端停止。 */
  stop(message = "电脑已停止读取；手机摄像头 App 需你自行结束。", failed = false) {
    if (this.stopRequest) return this.stopRequest;
    this.generation += 1;
    this.closeTransport();
    this.clearPreview();
    this.nodes.consent.checked = false;
    if (!this.sourceRequested) {
      this.setStatus(failed ? "error" : "idle", message);
      return Promise.resolve();
    }
    this.setStatus("stopping", "正在停止电脑读取 IP 视频源。");
    const startRequest = this.startRequest;
    const operation = (async () => {
      try {
        // 启动请求可能迟到；先等其完成，再停，避免“停止后又被迟到启动重新打开”。
        if (startRequest) await startRequest.catch(() => {});
        await this.requestControl("/api/ipcam/stop");
        this.sourceRequested = false;
        this.setStatus(failed ? "error" : "idle", message);
        this.nodes.hint.textContent = "已停止电脑读取；手机摄像头 App 是否关闭需在手机上确认。";
      } catch (error) {
        logger.captureError("无法确认 IP 视频源停止", error, { source: "ipcam", code: "IPCAM_STOP_FAILED" });
        this.setStatus("error", "无法确认电脑读取已停止，请重试“停止读取”，或在电脑按 Ctrl+C 停止服务。");
      } finally {
        this.stopRequest = null;
        this.updateControls();
      }
    })();
    this.stopRequest = operation;
    return operation;
  }
}
