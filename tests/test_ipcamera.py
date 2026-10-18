"""P2 网络视频读取与接口验证：只使用官方样例搭建本机 MJPEG，不连接真实摄像头。

运行：项目 Python -m pytest tests/test_ipcamera.py --basetemp=work/ipcam_pytest。
覆盖启动确认、卡住时停止、断流、同帧预览/结果、模式隔离及真实检测；不保存样例之外的媒体。
"""

import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import subprocess
import threading
import time

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.config import AppConfig
from app.ipcamera import IpCamera
from app.schemas import Detection


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def sample_stream():
    """用项目官方图片在回环地址提供 MJPEG；输出地址、计数和断流开关，退出时释放服务。"""
    jpeg = (PROJECT_ROOT / "data/samples/test.jpg").read_bytes()
    stopping, disconnect = threading.Event(), threading.Event()
    state = {"requests": 0}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            """测试服务器不记录 URL 或响应图像。"""

        def do_GET(self):
            """只在测试客户端连接后提供固定图片；stall 路径故意不响应以验证超时停止。"""
            state["requests"] += 1
            if self.path == "/stall":
                stopping.wait(10)
                return
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=sample")
            self.end_headers()
            self.connection.settimeout(1)
            try:
                while not stopping.is_set() and not disconnect.is_set():
                    self.wfile.write(b"--sample\r\nContent-Type: image/jpeg\r\nContent-Length: " +
                                     str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n")
                    self.wfile.flush()
                    stopping.wait(0.025)
            except (OSError, BrokenPipeError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state.update(url="http://127.0.0.1:" + str(server.server_port), jpeg=jpeg,
                 disconnect=disconnect)
    try:
        yield state
    finally:
        stopping.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def wait_for(condition, seconds=10):
    """限时轮询测试条件；条件不满足就失败，不让网络测试永久挂起。"""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = condition()
        if value:
            return value
        time.sleep(0.03)
    raise AssertionError("test condition timed out")


def read_frame(camera):
    """读取一帧并立即报告错误状态，让失败原因不会被通用等待超时掩盖。"""
    frame = camera.read(0.1)
    assert camera.status()["state"] != "error", camera.status()
    return frame


def test_reader_lifecycle_and_latest_frame(sample_stream):
    """验证构造不连接、一次连接、多余旧帧丢弃、停止与再次启动。"""
    camera = IpCamera(sample_stream["url"] + "/video")
    assert sample_stream["requests"] == 0
    assert camera.status()["state"] == "idle"
    try:
        camera.start()
        first = wait_for(lambda: read_frame(camera))
        assert first.image.dtype == np.uint8 and first.image.shape[2] == 3
        camera.start()
        time.sleep(0.4)
        latest = wait_for(lambda: camera.read(0.1))
        assert latest.seq > first.seq + 1
        assert sample_stream["requests"] == 1
        stopped = time.monotonic()
        camera.stop()
        assert time.monotonic() - stopped < 3
        camera.stop()
        assert camera.read() is None and camera.status()["state"] == "idle"
        camera.start()
        assert wait_for(lambda: camera.read(0.1))
        assert sample_stream["requests"] == 2
    finally:
        camera.stop()


@pytest.mark.parametrize("url", ["0", "file:///camera.mp4", "ftp://127.0.0.1/video", "http://"])
def test_reader_rejects_non_camera_url(url):
    """本模块只接受网络流，不能把配置误解成本机物理摄像头编号或磁盘文件。"""
    with pytest.raises(ValueError):
        IpCamera(url)


def test_reader_stop_while_open_is_blocked(sample_stream):
    """网络端不返回响应时，父进程仍能主动释放本次读取。"""
    camera = IpCamera(sample_stream["url"] + "/stall", open_timeout_ms=10000)
    try:
        camera.start()
        wait_for(lambda: sample_stream["requests"] == 1)
        started = time.monotonic()
        camera.stop()
        assert time.monotonic() - started < 3
        assert camera.status()["state"] == "idle"
    finally:
        camera.stop()


def test_reader_reports_disconnect(sample_stream):
    """固定样例服务中途断开，读取器应给出错误而非无限返回旧帧。"""
    camera = IpCamera(sample_stream["url"] + "/video", read_timeout_ms=500)
    try:
        camera.start()
        assert wait_for(lambda: camera.read(0.1))
        sample_stream["disconnect"].set()

        def disconnected():
            camera.read(0.1)
            return camera.status()["state"] == "error"

        wait_for(disconnected)
        assert camera.status()["error_code"].startswith("IPCAM_")
    finally:
        camera.stop()


def test_reader_abrupt_exit_is_bounded(sample_stream):
    """模拟原生读取进程突然退出：读者应限时返回，不能卡在半个图像消息里。"""
    camera = IpCamera(sample_stream["url"] + "/video")
    try:
        camera.start()
        assert wait_for(lambda: read_frame(camera))
        process = camera._process
        process.terminate()
        process.join(timeout=2)
        started = time.monotonic()
        for _ in range(3):
            camera.read(0.1)
        assert time.monotonic() - started < 1
        assert camera.status()["state"] == "error"
    finally:
        camera.stop()


@pytest.fixture
def service(monkeypatch, tmp_path):
    """隔离接口测试输出，退出时关闭处理器，避免 Windows 临时文件仍被占用。"""
    import logging
    import app.main as module
    monkeypatch.setattr(module, "LOG_DIR", tmp_path / "diagnostics")
    yield module
    for name in ("app", "uvicorn.error"):
        parent = logging.getLogger(name)
        for handler in list(parent.handlers):
            if (handler.name or "").startswith("vitrack."):
                parent.removeHandler(handler)
                handler.close()


class TestDetector:
    """接口流程专用的简单检测器：输入图像，输出一个已知比例的框，不冒充模型检测效果。"""

    __test__ = False
    cuda_available = False
    device_name = "test detector"

    def __init__(self, settings):
        """接口测试不重复加载模型；真实模型另有独立测试。"""

    def detect(self, image):
        """固定输出用于验证坐标与同帧打包，略作等待以模拟推理期间有新图进入。"""
        time.sleep(0.02)
        height, width = image.shape[:2]
        return [Detection(cls=0, name="person", score=0.9,
                          xyxy=(width * 0.2, height * 0.2, width * 0.8, height * 0.8))]


def test_service_confirmation_and_packets(service, monkeypatch, sample_stream):
    """确认启动后才连接；校验同帧 JPEG/坐标、双观看连接、停止、重启与单调序号。"""
    monkeypatch.setattr(service, "Detector", TestDetector)
    settings = AppConfig(source="ipcam", ipcam_url=sample_stream["url"] + "/video")
    app = service.create_app(settings)
    with TestClient(app) as client:
        assert client.get("/api/health").json()["ipcam"]["state"] == "idle"
        assert client.get("/api/ipcam/status").json()["has_frame"] is False
        page = client.get("/pc")
        assert page.status_code == 200
        assert b'/static/start.js' in page.content and b'ipcam-consent' in page.content
        assert client.get("/static/ipcam.js").status_code == 200
        with client.websocket_connect("/ws/ipcam") as viewer:
            viewer.send_json({"type": "next", "after": 0})
            assert viewer.receive_json()["code"] == "IPCAM_NOT_STARTED"
        for data, expected in [({}, 422), ({"confirm": False}, 400), ({"confirm": 1}, 422)]:
            assert client.post("/api/ipcam/start", json=data).status_code == expected
        assert sample_stream["requests"] == 0
        assert client.post("/api/ipcam/start", json={"confirm": True}).status_code == 200
        with client.websocket_connect("/ws/ipcam") as viewer:
            viewer.send_json({"type": "next", "after": 0})
            packet = viewer.receive_json()
            assert packet["type"] == "ipcam_frame" and packet["seq"] == packet["result"]["seq"]
            image = cv2.imdecode(np.frombuffer(base64.b64decode(packet["img"]), np.uint8), cv2.IMREAD_COLOR)
            assert image.shape[:2] == (packet["h"], packet["w"]) and max(image.shape[:2]) <= 640
            assert packet["result"]["boxes"][0]["xyxy"] == pytest.approx([0.2, 0.2, 0.8, 0.8])
            track_id = packet["result"]["boxes"][0]["track_id"]
            assert isinstance(track_id, int) and track_id > 0
            viewer.send_json({"type": "next", "after": packet["seq"]})
            next_packet = viewer.receive_json()
            assert next_packet["seq"] > packet["seq"]
            assert next_packet["result"]["boxes"][0]["track_id"] == track_id
            viewer.send_text("not json")
            assert viewer.receive_json()["code"] == "BAD_REQUEST"
            viewer.send_json({"type": "next", "after": -1})
            assert viewer.receive_json()["code"] == "BAD_REQUEST"
            with client.websocket_connect("/ws/ipcam") as second:
                second.send_json({"type": "next", "after": 0})
                second_packet = second.receive_json()
                assert second_packet["type"] == "ipcam_frame"
                assert second_packet["result"]["boxes"][0]["track_id"] == track_id
            assert sample_stream["requests"] == 1
        with client.websocket_connect("/ws/stream") as wrong:
            assert wrong.receive_json()["code"] == "SOURCE_MISMATCH"
        assert client.post("/api/ipcam/stop").json()["has_frame"] is False
        assert client.post("/api/ipcam/stop").json()["state"] == "idle"
        assert client.post("/api/ipcam/start", json={"confirm": True}).status_code == 200
        with client.websocket_connect("/ws/ipcam") as viewer:
            viewer.send_json({"type": "next", "after": next_packet["seq"]})
            assert viewer.receive_json()["seq"] > next_packet["seq"]
        # 不显式调用 stop，验证退出 lifespan 也能释放正在读取的进程。
    assert app.state.ipcam_reader.status()["state"] == "idle"
    assert app.state.ipcam_packet is None


def test_service_connection_failure(service, monkeypatch):
    """连接不到样例地址时给出错误，停止后可清除错误；URL/账号不出现在状态中。"""
    monkeypatch.setattr(service, "Detector", TestDetector)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    settings = AppConfig(source="ipcam", ipcam_url="http://secret:password@127.0.0.1:" + str(port) + "/video")
    with TestClient(service.create_app(settings)) as client:
        assert client.post("/api/ipcam/start", json={"confirm": True}).status_code == 200
        status = wait_for(lambda: (value if (value := client.get("/api/ipcam/status").json())["state"] == "error" else None))
        assert status["error_code"].startswith("IPCAM_")
        assert "password" not in json.dumps(status) and "secret" not in json.dumps(status)
        assert client.post("/api/ipcam/stop").json()["state"] == "idle"


def test_browser_source_regression(service, monkeypatch, sample_stream):
    """原浏览器推帧仍能处理图像，IP 源控制接口在 ws 模式下拒绝启动。"""
    monkeypatch.setattr(service, "Detector", TestDetector)
    with TestClient(service.create_app(AppConfig())) as client:
        assert client.get("/pc").status_code == 200
        assert client.post("/api/ipcam/start", json={"confirm": True}).status_code == 409
        with client.websocket_connect("/ws/ipcam") as viewer:
            assert viewer.receive_json()["code"] == "SOURCE_MISMATCH"
        image = cv2.imdecode(np.frombuffer(sample_stream["jpeg"], np.uint8), cv2.IMREAD_COLOR)
        with client.websocket_connect("/ws/stream") as viewer:
            viewer.send_json({"type": "frame", "seq": 123, "ts": 0, "w": image.shape[1], "h": image.shape[0],
                              "img": base64.b64encode(sample_stream["jpeg"]).decode("ascii")})
            assert viewer.receive_json()["seq"] == 123
    assert sample_stream["requests"] == 0


def test_real_detection_from_sample_ip_stream(service, sample_stream):
    """真实检测器读取本机样例流并返回人物框；没有物理摄像头或实拍画面。"""
    import torch
    settings = AppConfig(source="ipcam", ipcam_url=sample_stream["url"] + "/video",
                         det_device=0 if torch.cuda.is_available() else "cpu")
    with TestClient(service.create_app(settings)) as client:
        assert sample_stream["requests"] == 0
        client.post("/api/ipcam/start", json={"confirm": True}).raise_for_status()
        with client.websocket_connect("/ws/ipcam") as viewer:
            viewer.send_json({"type": "next", "after": 0})
            packet = viewer.receive_json()
            assert packet["type"] == "ipcam_frame"
            assert len(packet["result"]["boxes"]) == 4
        client.post("/api/ipcam/stop").raise_for_status()


def test_launcher_plan_does_not_start_source(sample_stream):
    """启动计划接受 ipcam 的 PC 模式，拒绝 phone 模式；检查阶段不连接样例源。"""
    import os
    environment = os.environ.copy()
    environment.update(SOURCE="ipcam", IPCAM_URL=sample_stream["url"] + "/video")
    script = PROJECT_ROOT / "scripts/run.ps1"
    for mode, expected in [("pc", 0), ("phone", 1)]:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                                 "-File", str(script), "-Mode", mode, "-CheckOnly"],
                                env=environment, capture_output=True, timeout=25,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        assert (result.returncode == 0) == (expected == 0)
    assert sample_stream["requests"] == 0
