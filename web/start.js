/**
 * ViTrack 页面入口：先读取服务配置，再选择浏览器摄像头或 IP 视频源模块。
 * index.html 只加载本文件；浏览器模式才动态导入 app.js/camera.js，
 * IP 模式只导入 ipcam.js，配置不明或接口失败时不开放任何摄像头操作。
 */
import { logger } from "./logger.js";

export let client = null;

// Worker只缓存界面文件，不会开启设备。离线可打开界面，模型仍需连接电脑。
if ("serviceWorker" in navigator && window.isSecureContext) {
  navigator.serviceWorker.register("/sw.js").catch(error =>
    logger.captureError("离线界面准备失败", error, { source: "pwa", code: "SW_FAILED" }));
}
let installPrompt = null;
window.addEventListener("beforeinstallprompt", event => {
  event.preventDefault(); installPrompt = event;
  document.getElementById("install-app").hidden = false;
});
document.getElementById("install-app").onclick = async () => {
  if (!installPrompt) return;
  await installPrompt.prompt(); installPrompt = null;
  document.getElementById("install-app").hidden = true;
};

/** 无输入，读取健康接口并初始化唯一客户端；输出真实模式/设备信息，不自动开启视频源。 */
export async function initializePage() {
  if (client) return client;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 5000);
  try {
    const response = await fetch("/api/health", { signal: controller.signal, cache: "no-store" });
    const health = await response.json();
    if (!response.ok || health.ok !== true || !["ws", "ipcam"].includes(health.source)) {
      throw new Error("服务未就绪或未返回可用的视频来源");
    }
    if (health.locking?.mode !== "single") {
      // 网页文件立即更新，而旧Python进程不会自动重载；不要把新按钮接到不兼容的旧接口。
      const error = new Error("检测服务仍是旧版本，请在电脑重启服务后刷新手机页面。");
      error.code = "SERVICE_UPDATE_REQUIRED";
      throw error;
    }
    document.getElementById("health-status").textContent = "服务就绪";
    // 显示实际响应的后端版本；切换Git分支后，旧进程仍可能运行，不能只凭网址判断版本。
    const versionLabel = document.getElementById("app-version");
    if (versionLabel) versionLabel.textContent = "运行版本：" + health.version;
    document.getElementById("device-name").textContent = health.device_name || "未知设备";
    document.getElementById("model-name").textContent = health.model || "未知模型";
    document.getElementById("source-name").textContent =
      health.source === "ipcam" ? "已配置的手机 IP 视频流" : "当前浏览器摄像头";
    // 这里只检查 API 是否可用，不请求权限或打开设备，便于手机先验证 HTTPS 环境。
    const cameraSupported = window.isSecureContext &&
      typeof navigator.mediaDevices?.getUserMedia === "function";
    document.getElementById("camera-support").textContent = health.source === "ipcam"
      ? "本模式不使用浏览器摄像头"
      : cameraSupported ? "安全环境已就绪，开启前仍需授权" : "当前环境不支持，请检查 HTTPS 与证书信任";
    if (health.source === "ipcam") {
      const { IpCameraClient } = await import("./ipcam.js");
      client = new IpCameraClient(
        document.getElementById("ipcam-preview"), document.getElementById("detection-overlay"),
      );
      client.bind();
    } else {
      // 动态导入使 IP 模式根本不加载本机摄像头绑定代码。
      const module = await import("./app.js");
      client = module.client;
    }
    client.interaction.configure(health);
    client.maxSide = health.capture?.max_side || 640;
    client.jpegQuality = health.capture?.jpeg_quality ?? 0.65;
    return client;
  } catch (error) {
    document.getElementById("health-status").textContent = "初始化失败";
    document.getElementById("page-status").textContent = error.code === "SERVICE_UPDATE_REQUIRED"
      ? error.message : "无法连接电脑。界面可离线打开，检测需要连接电脑服务后刷新。";
    document.getElementById("start-detection").disabled = true;
    document.getElementById("stop-detection").disabled = true;
    logger.captureError("页面初始化失败", error, { source: "startup", code: "PAGE_INIT_FAILED" });
    return null;
  } finally {
    clearTimeout(timer);
  }
}

void initializePage();
