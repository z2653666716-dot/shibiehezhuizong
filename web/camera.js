/**
 * ViTrack 摄像头模块：获取视频流、等待画面、同步画布和镜像设置，并可靠释放设备。
 * index.html 加载本模块后只绑定预览操作，不自动请求摄像头；必须由用户点击开启。
 * 后续 app.js 导入共享 camera，监听 started/stopped/resize 事件接入传帧与叠框。
 */
import { logger } from "./logger.js";

const PREVIEW_WIDTH = 1280;
const PREVIEW_HEIGHT = 720;
const READY_TIMEOUT_MS = 12000;

/** 保存可显示的摄像头错误码、中文说明及原始原因，供调用方捕获。 */
export class CameraError extends Error {
  constructor(code, message, cause) {
    super(message, { cause });
    this.name = "CameraError";
    this.code = code;
  }
}

/** 输入浏览器异常，输出统一摄像头错误；已转换的异常原样返回。 */
function cameraFailure(error) {
  if (error instanceof CameraError) return error;
  const messages = {
    NotAllowedError: ["CAMERA_DENIED", "未获得摄像头权限，请在浏览器的网站权限中允许访问后重试。"],
    SecurityError: ["CAMERA_DENIED", "浏览器阻止了摄像头访问，请检查网站权限与安全连接。"],
    NotFoundError: ["CAMERA_NOT_FOUND", "没有找到可用摄像头，请连接或启用摄像头后重试。"],
    NotReadableError: ["CAMERA_BUSY", "无法读取摄像头，请关闭占用它的程序并检查设备。"],
    AbortError: ["CAMERA_ABORTED", "摄像头启动被中断，请重试。"],
    OverconstrainedError: ["CAMERA_CONSTRAINTS", "摄像头不支持当前设置，请调整尺寸或方向。"],
  };
  const name = error && error.name;
  const [code, message] = Object.hasOwn(messages, name)
    ? messages[name] : ["CAMERA_FAILED", "摄像头操作失败，请检查设备和浏览器权限。"];
  return new CameraError(code, message, error);
}

/** 输入本次请求的视频流，停止其中全部轨道；空流无需处理。 */
function closeStream(stream) {
  if (stream) {
    for (const track of stream.getTracks()) track.stop();
  }
}

/**
 * 输入视频元素与取消信号，输出“已有第一帧”的 Promise。
 * 监听真实尺寸和加载事件，超时或停止时移除监听与计时器，避免一直等待黑屏。
 */
function waitForVideo(video, signal) {
  return new Promise((resolve, reject) => {
    let settled = false;
    let timer = null;
    let playbackStarted = false;
    const events = ["loadeddata", "canplay", "resize"];
    const finish = (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      for (const event of events) video.removeEventListener(event, check);
      video.removeEventListener("error", fail);
      signal.removeEventListener("abort", cancel);
      if (error) reject(error);
      else resolve();
    };
    const check = () => {
      if (playbackStarted && video.videoWidth > 0 && video.videoHeight > 0 &&
          video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) finish();
    };
    const fail = () => finish(new CameraError("CAMERA_VIDEO_FAILED", "摄像头画面无法播放，请重试。"));
    const cancel = () => finish(new CameraError("CAMERA_CANCELLED", "本次摄像头启动已取消。"));
    for (const event of events) video.addEventListener(event, check);
    video.addEventListener("error", fail);
    signal.addEventListener("abort", cancel, { once: true });
    timer = setTimeout(() => finish(new CameraError(
      "CAMERA_TIMEOUT", "已取得摄像头，但等待画面超时，请重试。",
    )), READY_TIMEOUT_MS);
    if (signal.aborted) {
      cancel();
    } else {
      try {
        // 播放完成与第一帧共同受上面的超时限制，任何一步卡住都能退出。
        video.play().then(() => {
          playbackStarted = true;
          check();
        }, finish);
      } catch (error) {
        finish(error);
      }
    }
  });
}

/**
 * 管理一组 video/canvas；输入为页面元素，输出为预览与尺寸、状态事件。
 * EventTarget 让后续检测模块监听摄像头生命周期，不需要接管设备释放逻辑。
 */
export class Camera extends EventTarget {
  constructor(video, overlay) {
    super();
    if (!(video instanceof HTMLVideoElement) || !(overlay instanceof HTMLCanvasElement)) {
      throw new TypeError("Camera 需要视频元素和画布元素");
    }
    this.video = video;
    this.overlay = overlay;
    this.stream = null;
    this.pausedTracks = [];
    this.controller = null;
    this.requestId = 0;
    this.state = "idle";
    this.mirrored = false;
    this.video.muted = true;
    this.video.playsInline = true;
  }

  /**
   * 输入期望方向与尺寸，异步返回实际 {width,height}。
   * ideal 表示尽量满足，设备可以返回不同分辨率；绘制始终使用实际尺寸。
   */
  async start({ facingMode = "environment", width = PREVIEW_WIDTH, height = PREVIEW_HEIGHT } = {}) {
    if (!["environment", "user"].includes(facingMode) ||
        !Number.isInteger(width) || !Number.isInteger(height) ||
        width < 32 || height < 32 || width > 4096 || height > 4096) {
      throw new CameraError("CAMERA_SETTINGS", "摄像头方向或尺寸不正确。");
    }
    if (!window.isSecureContext) {
      throw new CameraError("CAMERA_INSECURE", "请在电脑上使用 localhost，手机上使用受信任的 HTTPS 地址。");
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      throw new CameraError("CAMERA_UNSUPPORTED", "当前浏览器不支持摄像头访问，请使用新版浏览器。");
    }
    this.stop();
    const requestId = this.requestId;
    const controller = new AbortController();
    this.controller = controller;
    this.state = "opening";
    this.dispatchEvent(new CustomEvent("statechange", { detail: { state: this.state } }));
    let stream = null;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          facingMode: { ideal: facingMode },
          width: { ideal: width },
          height: { ideal: height },
        },
      });
      // getUserMedia 没有通用取消接口；过期请求返回时必须关闭它自己的流。
      if (requestId !== this.requestId || controller.signal.aborted) {
        throw new CameraError("CAMERA_CANCELLED", "本次摄像头启动已取消。");
      }
      this.stream = stream;
      this.video.srcObject = stream;
      // 同时等待播放成功和真实第一帧，超时与取消由同一处统一清理。
      await waitForVideo(this.video, controller.signal);
      if (requestId !== this.requestId || controller.signal.aborted) {
        throw new CameraError("CAMERA_CANCELLED", "本次摄像头启动已取消。");
      }
      const size = this.syncSize();
      if (!size) throw new CameraError("CAMERA_VIDEO_FAILED", "没有读取到有效的摄像头尺寸。");
      this.video.addEventListener("resize", () => this.syncSize(), { signal: controller.signal });
      for (const track of stream.getVideoTracks()) {
        track.addEventListener("ended", () => {
          if (this.stream !== stream) return;
          this.stop();
          this.dispatchEvent(new CustomEvent("ended", {
            detail: new CameraError("CAMERA_ENDED", "摄像头已断开，请检查设备后重新开启。"),
          }));
        }, { once: true, signal: controller.signal });
      }
      this.state = "running";
      this.dispatchEvent(new CustomEvent("statechange", { detail: { state: this.state } }));
      this.dispatchEvent(new CustomEvent("started", { detail: size }));
      return size;
    } catch (error) {
      if (requestId !== this.requestId || controller.signal.aborted) {
        closeStream(stream);
        throw new CameraError("CAMERA_CANCELLED", "本次摄像头启动已取消。", error);
      }
      this.stop();
      closeStream(stream);
      throw cameraFailure(error);
    }
  }

  /** 相册临时遮住网页时禁用原视频轨道；不打开新设备，不保存画面，只记原来启用的轨道。 */
  pauseCapture() {
    if (!this.stream || this.pausedTracks.length) return;
    this.pausedTracks = this.stream.getVideoTracks().filter(track => track.enabled && track.readyState === "live");
    for (const track of this.pausedTracks) track.enabled = false;
  }

  /** 返回前台后恢复本次仍存活的轨道；已经停止/替换的设备不会被重新开启。 */
  resumeCapture() {
    if (document.hidden) return;
    const current = this.stream?.getVideoTracks() || [];
    for (const track of this.pausedTracks) {
      if (current.includes(track) && track.readyState === "live") track.enabled = true;
    }
    this.pausedTracks = [];
  }

  /** 无输入；让未完成请求失效、取消画面等待、关闭设备，并清掉旧检测框。 */
  stop() {
    const wasActive = this.state !== "idle";
    this.requestId += 1;
    this.state = "idle";
    if (this.controller) this.controller.abort();
    this.controller = null;
    const stream = this.stream;
    this.stream = null;
    this.pausedTracks = [];
    closeStream(stream);
    this.video.pause();
    this.video.srcObject = null;
    this.video.load();
    const context = this.overlay.getContext("2d");
    if (context) context.clearRect(0, 0, this.overlay.width, this.overlay.height);
    if (wasActive) {
      this.dispatchEvent(new CustomEvent("statechange", { detail: { state: this.state } }));
      this.dispatchEvent(new CustomEvent("stopped"));
    }
  }

  /**
   * 从视频读取实际宽高，返回尺寸或 null；启动和视频尺寸改变时调用。
   * 修改 canvas 的像素尺寸会清空旧框，防止旋转画面后保留错误坐标。
   */
  syncSize() {
    const width = this.video.videoWidth;
    const height = this.video.videoHeight;
    if (!this.stream || width <= 0 || height <= 0) return null;
    if (this.overlay.width !== width || this.overlay.height !== height ||
        this.video.width !== width || this.video.height !== height) {
      this.video.width = width;
      this.video.height = height;
      this.overlay.width = width;
      this.overlay.height = height;
      this.dispatchEvent(new CustomEvent("resize", { detail: { width, height } }));
    }
    return { width, height };
  }

  /**
   * 输入是否镜像，只改变视频显示，不改变传给模型的原图。
   * 后续叠框模块读取 mirrored 换算横坐标，让标签文字仍保持正向。
   */
  setMirrored(enabled) {
    this.mirrored = Boolean(enabled);
    this.video.style.transform = this.mirrored ? "scaleX(-1)" : "";
    this.dispatchEvent(new CustomEvent("mirrorchange", { detail: { mirrored: this.mirrored } }));
  }
}

/**
 * 输入共享摄像头实例，将页面预览按钮与其生命周期连接。
 * 仅处理取流与预览，不连接检测服务；后续 app.js 可监听同一实例接入检测。
 */
function bindCameraPage(camera) {
  const start = document.getElementById("start-detection");
  const stop = document.getElementById("stop-detection");
  const controls = document.getElementById("camera-controls");
  const facing = document.getElementById("camera-facing");
  const mirror = document.getElementById("mirror-preview");
  const placeholder = document.getElementById("camera-placeholder");
  const status = document.getElementById("camera-status");
  const hint = document.getElementById("camera-hint");
  const frameSize = document.getElementById("frame-size");
  const result = document.getElementById("result-summary");

  // 界面跟随实际状态更新；等待权限时也允许停止，不把尚未开始的画面显示为成功。
  const update = () => {
    const opening = camera.state === "opening";
    const running = camera.state === "running";
    start.disabled = opening || running;
    stop.disabled = !opening && !running;
    controls.disabled = opening;
    camera.video.hidden = !running;
    camera.overlay.hidden = !running;
    placeholder.hidden = running;
    if (opening) {
      status.textContent = "等待摄像头授权与画面";
      hint.textContent = "请允许浏览器访问摄像头，也可以点击停止取消本次开启。";
    } else if (running) {
      hint.textContent = "摄像头预览中；目标检测将在接入电脑服务后开放。";
      result.textContent = "摄像头预览中，尚未启动目标检测。";
    } else {
      status.textContent = "摄像头未开启";
      hint.textContent = "点击“开启预览”，允许浏览器访问摄像头。";
      frameSize.textContent = "--";
      result.textContent = "尚未收到检测结果。";
    }
  };
  const showError = (error) => {
    if (error.code === "CAMERA_CANCELLED") return;
    hint.textContent = error.message;
    status.textContent = "摄像头开启失败";
    logger.captureError("摄像头操作失败", error, { source: "camera", code: error.code });
  };
  const open = async () => {
    try {
      await camera.start({ facingMode: facing.value });
    } catch (error) {
      showError(error);
    }
  };
  start.addEventListener("click", open);
  stop.addEventListener("click", () => camera.stop());
  facing.addEventListener("change", () => {
    if (camera.state === "running") open();
  });
  mirror.addEventListener("change", () => camera.setMirrored(mirror.checked));
  // 初始化时也读取开关：页面默认勾选不触发 change，必须主动同步显示与绘框使用的状态。
  // 这里只修改显示方向，不读取摄像头；后续 app.js 根据 camera.mirrored 换算框的位置。
  camera.setMirrored(mirror.checked);
  camera.addEventListener("statechange", update);
  camera.addEventListener("resize", (event) => {
    frameSize.textContent = event.detail.width + " × " + event.detail.height;
  });
  camera.addEventListener("started", (event) => {
    frameSize.textContent = event.detail.width + " × " + event.detail.height;
  });
  camera.addEventListener("ended", (event) => showError(event.detail));
  window.addEventListener("pagehide", () => camera.stop());
  start.textContent = "开启预览";
  stop.textContent = "停止预览";
  document.getElementById("controls-hint").textContent = "预览使用当前设备的摄像头；开启后可切换方向或镜像。";
  document.getElementById("page-status").textContent = "现在可以开启摄像头预览；目标检测将在下一步接入。";
  update();
}

// 模块加载只准备控件，用户点击后才会触发浏览器的权限请求。
export const camera = new Camera(
  document.getElementById("camera-video"),
  document.getElementById("detection-overlay"),
);
bindCameraPage(camera);
