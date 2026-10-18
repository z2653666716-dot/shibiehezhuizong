"""用自带样例验证已保存的浏览器/GPU检测链路，不访问物理摄像头或麦克风。

运行入口：项目 Python scripts/verify_stream.py。
输入：项目官方样例、已保存服务/网页与命令行参数。
输出：控制台摘要和 outputs/validation/synthetic_stream_report.json；
不保存实时设备画面，不自动安装依赖，不授予浏览器隐私权限。
"""

import argparse
from datetime import datetime, timedelta, timezone
import base64
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

import httpx
import psutil
from websockets.sync.client import connect


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BEIJING = timezone(timedelta(hours=8))
DEFAULT_BROWSER = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


def parse_args() -> argparse.Namespace:
    """读取端口、采样时长和报告路径，返回参数对象；非法值由命令行直接拒绝。"""
    parser = argparse.ArgumentParser(description="仅用项目样例验证检测链路，不打开物理摄像头")
    parser.add_argument("--port", type=int, default=8000, help="本机临时服务端口，默认 8000")
    parser.add_argument("--duration", type=float, default=10, help="预热后的采样秒数，默认 10")
    parser.add_argument("--warmup-frames", type=int, default=30, help="预热成功帧数，默认 30")
    parser.add_argument("--min-fps", type=float, default=15, help="验收吞吐下限，默认 15")
    parser.add_argument("--browser", type=Path, default=DEFAULT_BROWSER, help="本机 Edge/Chromium 路径")
    parser.add_argument("--report", type=Path, default=Path("outputs/validation/synthetic_stream_report.json"))
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port 应在 1～65535")
    if not 1 <= args.duration <= 300:
        parser.error("duration 应在 1～300 秒")
    if not 1 <= args.warmup_frames <= 300:
        parser.error("warmup-frames 应在 1～300")
    if not 0 <= args.min_fps <= 120:
        parser.error("min-fps 应在 0～120")
    if not args.browser.is_file():
        parser.error("没有找到浏览器，可用 --browser 指定已安装浏览器的路径")
    if not args.report.is_absolute():
        args.report = PROJECT_ROOT / args.report
    return args


class BrowserSession:
    """连接独立浏览器调试端口，仅发送页面测试命令；不授予或绕过设备权限。"""

    def __init__(self, address: str):
        self.socket = connect(address, max_size=16 * 1024 * 1024, legacy=True)
        self.number = 0

    def call(self, method: str, params: dict | None = None) -> dict:
        """输入浏览器命令与参数，按编号等待响应，输出响应内容或抛出异常。"""
        self.number += 1
        expected = self.number
        self.socket.send(json.dumps({"id": expected, "method": method, "params": params or {}}))
        while True:
            response = json.loads(self.socket.recv(timeout=20))
            if response.get("id") == expected:
                if "error" in response:
                    raise RuntimeError(response["error"])
                return response.get("result", {})

    def evaluate(self, expression: str):
        """在受控页面执行表达式，只取明确返回的数据；支持等待异步结果。"""
        response = self.call("Runtime.evaluate", {
            "expression": expression, "returnByValue": True, "awaitPromise": True,
        })
        if "exceptionDetails" in response:
            raise RuntimeError(response["exceptionDetails"])
        return response["result"].get("value")

    def wait(self, expression: str, timeout: float = 25) -> None:
        """周期检查页面条件，满足后返回；失败显示现有中文提示，避免无限等待。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.evaluate(expression):
                return
            time.sleep(0.1)
        message = self.evaluate('document.getElementById("page-status")?.textContent || "页面未就绪"')
        raise RuntimeError("等待条件超时：" + message)

    def close(self) -> None:
        """停止受控页面的视频源并关闭独立浏览器，不操作用户日常浏览器。"""
        try:
            self.evaluate("window.testCamera?.stop(); window.stopSyntheticSource?.()")
            self.socket.send(json.dumps({"id": 999999, "method": "Browser.close"}))
        except Exception:
            pass
        self.socket.close()


def sample_source(sample: Path) -> str:
    """读取项目固定样例，输出页面启动前注入的合成视频代码；不保存原生设备调用。"""
    image_url = "data:image/jpeg;base64," + base64.b64encode(sample.read_bytes()).decode("ascii")
    # 把字符串交给 JSON 编码，避免文件数据被当成 JavaScript 语法解释。
    return """
      window.syntheticTracks = [];
      window.testMaxPending = 0;
      window.syntheticFrames = [];
      const NativeSocket = window.WebSocket;
      window.WebSocket = class extends NativeSocket {
        constructor(...args) {
          super(...args);
          this.testPending = 0;
          this.addEventListener("message", () => {
            this.testPending = Math.max(0, this.testPending - 1);
          });
        }
        send(text) {
          const frame = JSON.parse(text);
          this.testPending++;
          testMaxPending = Math.max(testMaxPending, this.testPending);
          syntheticFrames.push({seq:frame.seq,w:frame.w,h:frame.h,jpeg:frame.img.startsWith("/9j/")});
          if (syntheticFrames.length > 300) syntheticFrames.shift();
          return super.send(text);
        }
      };
      const image = new Image();
      image.src = IMAGE_URL;
      let repaint = null;
      const ready = image.decode().then(() => {
        const canvas = document.createElement("canvas");
        canvas.width = image.naturalWidth;
        canvas.height = image.naturalHeight;
        const context = canvas.getContext("2d");
        const draw = () => {
          context.drawImage(image,0,0);
          repaint = requestAnimationFrame(draw);
        };
        draw();
        return canvas;
      });
      // 只返回由项目样例生成的 MediaStream，绝不调用或保留原生 getUserMedia。
      navigator.mediaDevices.getUserMedia = async () => {
        const canvas = await ready;
        const stream = canvas.captureStream(30);
        syntheticTracks.push(...stream.getTracks());
        return stream;
      };
      window.stopSyntheticSource = () => {
        cancelAnimationFrame(repaint);
        for (const track of syntheticTracks) track.stop();
      };
    """.replace("IMAGE_URL", json.dumps(image_url))


def run_check(args: argparse.Namespace, report: dict) -> None:
    """启动已保存服务与独立浏览器，阻止隐私权限，用样例采样并填写报告，最后关闭进程。"""
    sample = PROJECT_ROOT / "data/samples/test.jpg"
    if not sample.is_file():
        raise RuntimeError("缺少项目样例 data/samples/test.jpg")
    # 不接管或停止用户原本运行的服务；端口占用时直接退出。
    with socket.socket() as port_probe:
        port_probe.bind(("127.0.0.1", args.port))
    base_url = "http://127.0.0.1:" + str(args.port)
    work_root = PROJECT_ROOT / "work"
    work_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="synthetic_check_", dir=work_root) as temporary:
        folder = Path(temporary).resolve()
        if not folder.is_relative_to(work_root.resolve()):
            raise RuntimeError("临时目录必须位于项目 work 内")
        server = browser = session = None
        with (folder / "server.log").open("w", encoding="utf-8") as server_log, (
            folder / "browser.log"
        ).open("w", encoding="utf-8") as browser_log:
            try:
                # 只使用本脚本所在的 Python，不影响用户其他环境；临时子进程不显示窗口。
                server = subprocess.Popen([
                    sys.executable, "-X", "utf8", "-m", "uvicorn", "app.main:app",
                    "--host", "127.0.0.1", "--port", str(args.port), "--workers", "1",
                ], cwd=PROJECT_ROOT, stdout=server_log, stderr=subprocess.STDOUT,
                   creationflags=subprocess.CREATE_NO_WINDOW)
                with httpx.Client(base_url=base_url, timeout=15, trust_env=False) as client:
                    deadline = time.monotonic() + 40
                    while True:
                        if server.poll() is not None:
                            raise RuntimeError("检测服务启动失败")
                        try:
                            response = client.get("/api/health")
                            if response.status_code == 200:
                                break
                        except httpx.ConnectError:
                            pass
                        if time.monotonic() >= deadline:
                            raise RuntimeError("检测服务启动超时")
                        time.sleep(0.2)
                    report["health"] = response.json()
                    if report["health"].get("ok") is not True:
                        raise RuntimeError("检测服务尚未就绪")
                    for route, path in [
                        ("/pc", "web/index.html"), ("/static/app.js", "web/app.js"),
                        ("/static/camera.js", "web/camera.js"), ("/static/style.css", "web/style.css"),
                        ("/static/start.js", "web/start.js"),
                    ]:
                        response = client.get(route)
                        if response.status_code != 200 or response.content != (PROJECT_ROOT / path).read_bytes():
                            raise RuntimeError("保存文件路由不一致：" + route)
                profile = folder / "browser_profile"
                browser = subprocess.Popen([
                    str(args.browser), "--headless=new", "--disable-gpu", "--no-first-run",
                    "--no-default-browser-check", "--disable-background-networking", "--disable-sync",
                    "--disable-extensions", "--disable-component-update", "--disable-background-mode",
                    "--remote-debugging-port=0", "--user-data-dir=" + str(profile), "about:blank",
                ], stdout=browser_log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
                active_port = profile / "DevToolsActivePort"
                deadline = time.monotonic() + 20
                while not active_port.is_file():
                    if browser.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError("独立浏览器启动失败")
                    time.sleep(0.1)
                debug_port = int(active_port.read_text().splitlines()[0])
                targets = httpx.get(
                    "http://127.0.0.1:" + str(debug_port) + "/json/list", trust_env=False,
                ).json()
                page = next(item for item in targets if item["type"] == "page")
                session = BrowserSession(page["webSocketDebuggerUrl"])
                session.call("Page.enable")
                session.call("Runtime.enable")
                # 明确拒绝隐私权限。即使合成源准备失败，也不允许回退到物理设备。
                for permission in ("camera", "microphone"):
                    session.call("Browser.setPermission", {
                        "permission": {"name": permission}, "setting": "denied", "origin": base_url,
                    })
                session.call("Page.addScriptToEvaluateOnNewDocument", {"source": sample_source(sample)})
                session.call("Page.navigate", {"url": base_url + "/pc"})
                session.wait('document.getElementById("source-name")?.textContent === "当前浏览器摄像头" && !document.getElementById("start-detection").disabled')
                permissions = session.evaluate("""(async () => ({
                  camera:(await navigator.permissions.query({name:"camera"})).state,
                  microphone:(await navigator.permissions.query({name:"microphone"})).state
                }))()""")
                if permissions != {"camera": "denied", "microphone": "denied"}:
                    raise RuntimeError("未确认隐私权限被拒绝，停止测试")
                report["permissions"] = permissions
                session.evaluate("""(async () => {
                  window.testClient=(await import("/static/app.js")).client;
                  window.testCamera=(await import("/static/camera.js")).camera;
                  return true;
                })()""")
                if session.evaluate("testCamera.state") != "idle":
                    raise RuntimeError("页面不应自动开启视频源")
                session.evaluate('document.getElementById("start-detection").click()')
                session.wait("testClient.received >= " + str(args.warmup_frames), timeout=40)
                first = session.evaluate("({count:testClient.received,time:performance.now(),track_ids:testClient.boxes.map(box=>box.track_id)})")
                # 只采集本次公开样例服务的内存数值，不读取或保存设备画面。
                process = psutil.Process(server.pid)
                memory_samples = [{"elapsed_s": 0.0, "rss_mib": round(process.memory_info().rss / 1024**2, 2)}]
                memory_started = time.monotonic()
                while time.monotonic() - memory_started < args.duration:
                    time.sleep(min(5, max(0, args.duration - (time.monotonic() - memory_started))))
                    memory_samples.append({"elapsed_s": round(time.monotonic() - memory_started, 2),
                                           "rss_mib": round(process.memory_info().rss / 1024**2, 2)})
                report["memory_samples"] = memory_samples
                report["rss_growth_mib"] = round(memory_samples[-1]["rss_mib"] - memory_samples[0]["rss_mib"], 2)
                result = session.evaluate("""({
                  count:testClient.received,time:performance.now(),state:testClient.state,
                  boxes:testClient.boxes.length,server_fps:Number(document.getElementById("fps-value").textContent),
                  server_latency_ms:Number(document.getElementById("latency-value").textContent),
                  max_pending:testMaxPending,frames:syntheticFrames,
                  smoothing_history:testClient.smoother.previous.length,
                  track_ids:testClient.boxes.map(box=>box.track_id)
                })""")
                elapsed = (result["time"] - first["time"]) / 1000
                fps = (result["count"] - first["count"]) / elapsed
                painted = session.evaluate("""(() => {
                  const canvas=testCamera.overlay,ctx=testClient.overlayContext;
                  const pixels=ctx.getImageData(0,0,canvas.width,canvas.height).data;
                  let count=0;for(let i=3;i<pixels.length;i+=4)if(pixels[i])count++;
                  return count;
                })()""")
                if result["state"] != "connected" or result["boxes"] != 4 or painted <= 0:
                    raise RuntimeError("样例结果或叠框不符合预期")
                if result["max_pending"] != 1:
                    raise RuntimeError("在途帧数超过 1")
                if result["smoothing_history"] != result["boxes"]:
                    raise RuntimeError("显示平滑未保存当前框，或混入已消失的目标")
                if (not all(isinstance(value, int) and value > 0 for value in result["track_ids"]) or
                        len(set(result["track_ids"])) != result["boxes"] or
                        sorted(first["track_ids"]) != sorted(result["track_ids"])):
                    raise RuntimeError("固定样例的轨迹号无效、重复或在采样前后改变")
                if not all(frame["jpeg"] and max(frame["w"], frame["h"]) <= 640 for frame in result["frames"]):
                    raise RuntimeError("发送图像格式或尺寸不符合默认设置")
                session.evaluate('document.getElementById("stop-detection").click();stopSyntheticSource()')
                if not session.evaluate("syntheticTracks.every(track=>track.readyState==='ended') && testClient.socket===null && testClient.smoother.previous.length===0"):
                    raise RuntimeError("停止后没有释放合成视频源或检测连接")
                report.update(
                    duration_s=round(elapsed, 3), completed_frames=result["count"] - first["count"],
                    completion_fps=round(fps, 3), server_fps=result["server_fps"],
                    server_latency_ms=result["server_latency_ms"], detected_persons=result["boxes"],
                    maximum_inflight=result["max_pending"], painted_pixels=painted,
                    synthetic_tracks_released=True, smoothing_history_reset=True, physical_camera_access=False,
                    track_ids=result["track_ids"], sample_track_ids_stable=True,
                )
                if fps < args.min_fps:
                    raise RuntimeError("样例流吞吐低于 --min-fps 设置")
            finally:
                # 只关闭本次新建的子进程，不查找或停止用户其他浏览器/服务。
                try:
                    if session:
                        session.close()
                finally:
                    try:
                        if browser:
                            try:
                                browser.wait(timeout=10)
                            except subprocess.TimeoutExpired:
                                browser.terminate()
                                browser.wait(timeout=10)
                    finally:
                        if server:
                            server.terminate()
                            server.wait(timeout=15)
                report["temporary_services_stopped"] = True


def main() -> int:
    """命令行入口：读取参数、执行检查、保存报告；成功返回 0，失败返回 1。"""
    args = parse_args()
    report = {
        "checked_at": datetime.now(BEIJING).isoformat(),
        "source": "official sample via canvas.captureStream; saved backend and frontend",
        "physical_camera_access": False,
        "physical_camera_acceptance": "not performed; explicit consent required",
        "requested_duration_s": args.duration,
    }
    try:
        run_check(args, report)
        report["status"] = "passed"
    except Exception as error:
        report["status"] = "failed"
        report["reason"] = str(error)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("报告：" + str(args.report))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
