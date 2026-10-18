/**
 * ViTrack 浏览器日志模块：记录错误、更新诊断区，并导出可供排查的 JSON。
 * index.html 以 module 脚本加载本文件；后续 app.js 可导入 logger 调用 record/captureError。
 * 日志只存当前页面内存，不发送图片、不写服务端；后端日志仍通过原有链接下载。
 */

const MAX_ENTRIES = 200;
const MAX_VISIBLE = 50;
const MAX_MESSAGE_LENGTH = 600;
const MAX_STACK_LENGTH = 4000;
const LEVEL_NAMES = { info: "信息", warn: "警告", error: "错误" };

/** 输入可选日期，输出带 +08:00 的北京时间，页面显示与导出共用。 */
function beijingTime(date = new Date()) {
  return new Date(date.getTime() + 8 * 60 * 60 * 1000)
    .toISOString().replace("Z", "+08:00");
}

/**
 * 输入字符串与长度上限，输出适合写日志的文字。
 * 先限制扫描量，再省略图片/长 Base64；网址去掉账号、密码、查询参数和片段。
 * 不序列化任意对象，避免把调用方传来的整帧或照片意外保存。
 */
function cleanText(value, limit) {
  if (typeof value !== "string") return "";
  const cleaned = value.slice(0, 12000)
    .replace(/data:[^\s"'<>)]*/gi, "[已省略数据地址]")
    .replace(/[A-Za-z0-9+/]{160,}={0,2}/g, "[已省略长编码]")
    .replace(/https?:\/\/[^\s<>"']+/gi, (address) => {
      try {
        const url = new URL(address);
        url.username = "";
        url.password = "";
        url.search = "";
        url.hash = "";
        return url.toString();
      } catch {
        return "[无法解析的网址]";
      }
    })
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, "");
  return cleaned.length > limit ? cleaned.slice(0, limit - 1) + "…" : cleaned;
}

/**
 * 管理当前页面的日志；输入来自浏览器事件或后续摄像头/网络模块。
 * 输出是内存记录、诊断区文字及用户主动下载的文件，不请求任何检测接口。
 */
export class BrowserLogger {
  constructor() {
    this.entries = [];
    this.nextNumber = 1;
    this.started = false;
    this.nodes = null;
  }

  /**
   * 页面加载后调用一次，取得诊断元素、绑定按钮和全局错误监听。
   * 重复调用直接返回，避免同一个错误被重复记录；不启用摄像头按钮。
   */
  start() {
    if (this.started) return;
    this.nodes = {
      list: document.getElementById("client-log-list"),
      latest: document.getElementById("latest-error"),
      trace: document.getElementById("trace-id"),
      frame: document.getElementById("error-frame"),
      hint: document.getElementById("client-log-hint"),
      exportButton: document.getElementById("export-client-logs"),
      clearButton: document.getElementById("clear-client-logs"),
    };
    if (Object.values(this.nodes).some((node) => node === null)) {
      throw new Error("浏览器日志初始化失败：诊断区缺少必要元素");
    }
    this.started = true;
    this.nodes.hint.textContent =
      "记录保留在本页内存中：最多 " + MAX_ENTRIES + " 条，显示最近 " +
      MAX_VISIBLE + " 条；刷新后清空，需要保留时请导出。";
    this.nodes.exportButton.addEventListener("click", () => this.exportLogs());
    this.nodes.clearButton.addEventListener("click", () => this.clear());

    // 捕获模式也能看到脚本、样式等资源的加载错误；普通错误保留文件与行列信息。
    window.addEventListener("error", (event) => {
      if (event instanceof ErrorEvent) {
        this.captureError("页面脚本发生错误", event.error || event.message, {
          source: "browser", code: "SCRIPT_ERROR",
          file: event.filename, line: event.lineno, column: event.colno,
        });
      } else if (event.target instanceof Element) {
        const target = event.target;
        this.record("error", "页面资源加载失败，请检查服务连接。", {
          source: "browser", code: "RESOURCE_LOAD_FAILED",
          file: target.currentSrc || target.src || target.href,
        });
      }
    }, true);

    // Promise 中未处理的失败不会经过普通 error 事件，需单独监听。
    window.addEventListener("unhandledrejection", (event) => {
      this.captureError("异步操作未完成", event.reason, {
        source: "browser", code: "UNHANDLED_REJECTION",
      });
    });
    window.addEventListener("offline", () => {
      this.record("warn", "浏览器报告网络离线，请检查网络与检测服务连接。", {
        source: "network", code: "BROWSER_OFFLINE",
      });
    });
    window.addEventListener("online", () => {
      this.record("info", "浏览器报告网络已恢复，请确认检测服务连接。", {
        source: "network", code: "BROWSER_ONLINE",
      });
    });
    this.record("info", "浏览器日志已启动。", { source: "browser", code: "LOGGER_READY" });
  }

  /**
   * 输入级别、中文提示与少量上下文，返回本次记录的独立副本。
   * context 只接收下方白名单字段；图片、请求正文等其他字段不会进入日志。
   * 后续接口模块可直接传服务器 message，函数会提取其中的日志编号和帧号。
   */
  record(level, message, context = {}) {
    const safeContext = context && typeof context === "object" ? context : {};
    const cleanedMessage = cleanText(message, 12000);
    const text = cleanText(cleanedMessage, MAX_MESSAGE_LENGTH) || "未提供日志说明";
    const traceMatch = cleanedMessage.match(/日志编号[：:]\s*([a-f0-9]{12})\b/i);
    const frameMatch = cleanedMessage.match(/帧号[：:]\s*(\d+)/);
    const traceId = typeof safeContext.traceId === "string" &&
      /^[a-f0-9]{12}$/i.test(safeContext.traceId)
      ? safeContext.traceId : (traceMatch ? traceMatch[1] : "");
    const parsedFrame = frameMatch ? Number(frameMatch[1]) : null;
    const seq = Number.isSafeInteger(safeContext.seq) && safeContext.seq >= 0
      ? safeContext.seq : parsedFrame;
    const entry = {
      number: this.nextNumber++,
      time: beijingTime(),
      level: Object.hasOwn(LEVEL_NAMES, level) ? level : "info",
      message: text,
    };
    for (const [name, limit] of [
      ["source", 60], ["code", 80], ["file", 300],
      ["errorName", 80], ["stack", MAX_STACK_LENGTH],
    ]) {
      const value = cleanText(safeContext[name], limit);
      if (value) entry[name] = value;
    }
    if (traceId) entry.traceId = traceId;
    if (Number.isSafeInteger(seq) && seq >= 0) entry.seq = seq;
    for (const name of ["line", "column"]) {
      if (Number.isSafeInteger(safeContext[name]) && safeContext[name] > 0) {
        entry[name] = safeContext[name];
      }
    }
    this.entries.push(Object.freeze(entry));
    // 删除最旧的部分；显示数量与保存数量分开，页面不会一次插入数百条长堆栈。
    if (this.entries.length > MAX_ENTRIES) {
      this.entries.splice(0, this.entries.length - MAX_ENTRIES);
    }
    if (this.started) this.render();
    return { ...entry };
  }

  /**
   * 输入中文说明、Error/DOMException 或文字原因，再交给 record 统一处理。
   * 输出日志副本；全局事件与未来的摄像头/API 异常捕获均可调用。
   */
  captureError(message, error, context = {}) {
    const knownError = error instanceof Error || error instanceof DOMException;
    const detail = knownError ? error.message : (typeof error === "string" ? error : "");
    return this.record("error", message + (detail ? "：" + detail : ""), {
      ...context,
      errorName: knownError ? error.name : "",
      stack: knownError ? error.stack : "",
    });
  }

  /**
   * 把当前记录转换成页面节点，不接收外部输入、不返回数据。
   * 使用 textContent 而非 innerHTML，错误文字中的标签只显示为文字。
   */
  render() {
    const fragment = document.createDocumentFragment();
    const visible = this.entries.slice(-MAX_VISIBLE).reverse();
    if (visible.length === 0) {
      const empty = document.createElement("li");
      empty.id = "client-log-empty";
      empty.textContent = "暂无浏览器日志。";
      fragment.append(empty);
    }
    for (const entry of visible) {
      const item = document.createElement("li");
      const parts = [
        entry.time.replace("T", " "), "[" + LEVEL_NAMES[entry.level] + "]",
        entry.source || "app", entry.code || "", entry.message,
      ];
      if (entry.traceId) parts.push("日志编号：" + entry.traceId);
      if (entry.seq !== undefined) parts.push("帧号：" + entry.seq);
      if (entry.file) {
        parts.push(entry.file + (entry.line ? ":" + entry.line : "") +
          (entry.column ? ":" + entry.column : ""));
      }
      if (entry.stack) parts.push("\n" + entry.stack);
      item.textContent = parts.filter(Boolean).join(" ");
      fragment.append(item);
    }
    this.nodes.list.replaceChildren(fragment);
    const latestIssue = [...this.entries].reverse().find((entry) => entry.level !== "info");
    const reference = latestIssue || [...this.entries].reverse().find((entry) => entry.traceId);
    this.nodes.latest.textContent = latestIssue
      ? latestIssue.message + (latestIssue.code ? " [" + latestIssue.code + "]" : "")
      : "暂无错误或警告。";
    this.nodes.latest.dataset.level = latestIssue ? latestIssue.level : "info";
    // 新错误没有服务端编号时明确显示无编号，不误用上一条错误的编号和帧号。
    this.nodes.trace.textContent = reference && reference.traceId
      ? reference.traceId : "暂无关联编号";
    this.nodes.frame.textContent = latestIssue && latestIssue.seq !== undefined
      ? String(latestIssue.seq) : "--";
    this.nodes.exportButton.disabled = this.entries.length === 0;
    this.nodes.clearButton.disabled = this.entries.length === 0;
  }

  /** 输出按时间顺序排列的记录副本；修改返回值不会改动内部日志。 */
  getLogs() {
    return this.entries.map((entry) => ({ ...entry }));
  }

  /** 清空本页内存并刷新空状态，不删除电脑上的服务端日志。 */
  clear() {
    this.entries = [];
    if (this.started) this.render();
  }

  /**
   * 用户点击导出时调用：把当前记录打包成 UTF-8 JSON，返回建议文件名。
   * Blob 是浏览器内存中的文件；临时下载地址稍后释放，失败则记录中文错误。
   */
  exportLogs() {
    if (this.entries.length === 0) return null;
    try {
      const exportedAt = beijingTime();
      const report = {
        schema_version: 1,
        exported_at: exportedAt,
        time_zone: "Asia/Shanghai",
        page: location.pathname,
        browser: cleanText(navigator.userAgent, 300),
        max_entries: MAX_ENTRIES,
        logs: this.getLogs(),
      };
      const stamp = exportedAt.slice(0, 19).replace(/[-:]/g, "").replace("T", "_");
      const filename = "browser_logs_" + stamp + ".json";
      const blob = new Blob([JSON.stringify(report, null, 2)], {
        type: "application/json;charset=utf-8",
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.append(link);
      try {
        link.click();
      } finally {
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
      return filename;
    } catch (error) {
      this.captureError("浏览器日志导出失败", error, {
        source: "browser", code: "LOG_EXPORT_FAILED",
      });
      return null;
    }
  }
}

// ES module 在 HTML 解析完成后执行；浏览器会缓存同一模块，后续导入共享这一实例。
export const logger = new BrowserLogger();
logger.start();
