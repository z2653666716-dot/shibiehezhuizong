"""检查一键启动入口的配置隔离与失败边界；不使用摄像头或保存用户媒体。"""
import socket
from types import SimpleNamespace

import pytest

import run as launcher


def test_launcher_forces_tested_mode_without_changing_parent(monkeypatch):
    """即使外部残留IP源或允许保存的设置，本次启动也应使用浏览器模式并禁止保存。"""
    monkeypatch.setenv("SOURCE", "ipcam")
    monkeypatch.setenv("ALLOW_MEDIA_SAVE", "true")
    environment = launcher.project_environment()
    assert environment["SOURCE"] == "ws"
    assert environment["ALLOW_MEDIA_SAVE"] == "false"
    assert environment["IDENTITY_MODE"] == "hybrid"
    assert environment["TRACKER"] == "botsort.yaml"
    assert environment["REID_MODEL"] == "osnet_x0_25"
    assert launcher.os.environ["SOURCE"] == "ipcam"


def test_launcher_requires_the_selected_hotspot(monkeypatch):
    """热点没开时应在启动模型之前拒绝，而不是随意挑一张不通的网卡。"""
    monkeypatch.setattr("scripts.gen_cert.local_ips", lambda: [])
    with pytest.raises(ValueError, match="开启电脑移动热点"):
        launcher.prepare_server()


def test_launcher_refuses_occupied_port(monkeypatch, tmp_path):
    """先用测试自己的Socket占用端口，确认入口报错且不接管已有服务。"""
    model = tmp_path / "model.bin"
    model.write_bytes(b"test")
    settings = SimpleNamespace(https_cert=tmp_path / "cert.pem", https_key=tmp_path / "key.pem",
                               det_model=model, person_weights=model,
                               face_detector_weights=model, face_recognizer_weights=model)
    monkeypatch.setattr("app.config.load_config", lambda: settings)
    monkeypatch.setattr("scripts.gen_cert.local_ips", lambda: [launcher.PHONE_IP])
    monkeypatch.setattr("scripts.gen_cert.check_certificate", lambda *args: {"dns_names": ["localhost"]})
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen(1)  # Windows仅bind尚未开始监听；这里模拟真正已运行的服务。
        monkeypatch.setattr(launcher, "PORT", occupied.getsockname()[1])
        with pytest.raises(ValueError, match="端口.*不可用"):
            launcher.prepare_server()
