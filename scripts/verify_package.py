"""解压源码包到独立work目录，核对摘要并启动其中的服务；只发送包内公开样例。

使用现有项目Python环境，验证源码可迁移运行，不声称另一台电脑已重新安装依赖。
不请求浏览器/物理摄像头，也不读取IP源，默认禁止媒体保存。
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from uuid import uuid4
import zipfile

import cv2
import httpx
from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[1]


def verify(archive_path, report_path, identity_mode="appearance"):
    """输入ZIP、报告路径和可选身份模式，校验摘要，输出对应真实模型/锁定/保存限制结果。"""
    directory = ROOT / "work/package_checks" / uuid4().hex
    directory.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive_path) as archive:
        for item in archive.infolist():
            target = (directory / item.filename).resolve()
            if not target.is_relative_to(directory.resolve()):
                raise ValueError("压缩包包含越界路径，拒绝解压")
        archive.extractall(directory)
    source = directory / "vitrack"
    manifest = json.loads((source / "SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
    if manifest.get("identity_mode", identity_mode) != identity_mode:
        raise ValueError("验收身份模式与源码包清单不符，请按清单指定的模式运行")
    for item in manifest["files"]:
        path = (source / item["path"]).resolve()
        if not path.is_relative_to(source.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("源码清单摘要不一致")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0)); port = probe.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.update(SOURCE="ws", ALLOW_MEDIA_SAVE="false", DET_MODEL="weights/yolo11n.pt",
                       REID_WEIGHTS="weights/mobilenet_v3_small-047dcff4.pth",
                       IDENTITY_MODE=identity_mode, IDENTITY_DEVICE="cpu",
                       REID_MODEL="osnet_x0_25" if identity_mode == "hybrid" else "mobilenet_v3_small",
                       TRACKER="botsort.yaml" if identity_mode == "hybrid" else "bytetrack.yaml")
    server = None
    report = {"archive": str(archive_path), "archive_sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
              "files_verified": len(manifest["files"]), "used_existing_python_environment": True,
              "fresh_dependency_installation_performed": False, "physical_camera_access": False,
              "user_media_saved": False, "extracted_directory": str(source)}
    report["identity_mode"] = identity_mode
    report["source"] = manifest.get("source", {})
    try:
        with (directory / "service.txt").open("w", encoding="utf-8") as output:
            server = subprocess.Popen([sys.executable, "-X", "utf8", "-m", "uvicorn", "app.main:app",
                "--host", "127.0.0.1", "--port", str(port), "--workers", "1"], cwd=source, env=environment,
                stdout=output, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            with httpx.Client(base_url=base, trust_env=False, timeout=20) as client:
                deadline = time.monotonic() + 45
                while True:
                    if server.poll() is not None:
                        raise RuntimeError("解压后的服务提前退出，检查work/package_checks中的文本输出")
                    try:
                        response = client.get("/api/health")
                        if response.status_code == 200:
                            health = response.json(); break
                    except httpx.ConnectError:
                        pass
                    if time.monotonic() > deadline:
                        raise TimeoutError("解压服务未就绪")
                    time.sleep(.2)
                assert health["source"] == "ws" and health["recording"]["allowed"] is False
                assert health["identity"]["mode"] == identity_mode
                expected_version = manifest.get("source", {}).get("runtime_version")
                if expected_version is not None:
                    assert health["version"] == expected_version
                report["runtime_version"] = health["version"]
                assert health["processed_frames"] == 0
                for route in ("/pc", "/static/manifest.webmanifest", "/sw.js", "/static/icons/icon-512.png"):
                    assert client.get(route).status_code == 200
                image = cv2.imread(str(source / "data/samples/test.jpg"))
                height, width = image.shape[:2]
                encoded = base64.b64encode((source / "data/samples/test.jpg").read_bytes()).decode()
                with connect(f"ws://127.0.0.1:{port}/ws/stream", max_size=2**22) as ws:
                    for seq in range(1, 7):
                        ws.send(json.dumps({"seq": seq, "ts": 0, "w": width, "h": height, "img": encoded}))
                        result = json.loads(ws.recv(timeout=30))
                        assert result.get("type") == "result" and result["seq"] == seq
                    track = next(box["track_id"] for box in result["boxes"] if box["track_id"] is not None)
                    session = result["session_id"]
                    locked = client.post("/api/lock", json={"session_id": session, "track_id": track, "seq": 6}).json()
                    assert locked.get("identity_id") == "ID-01"
                    ws.send(json.dumps({"seq": 7, "ts": 0, "w": width, "h": height, "img": encoded}))
                    result = json.loads(ws.recv(timeout=30))
                    assert any(box["state"] == "locked" for box in result["boxes"])
                    denied = client.post("/api/record/start", json={"session_id": session, "confirm": True}).json()
                    assert denied.get("code") == "MEDIA_SAVE_FORBIDDEN"
                report.update(status="passed", stage=health["stage"], public_sample_people=len(result["boxes"]),
                              bundled_yolo_and_reid_loaded=True, lock_endpoint_and_green_state=True,
                              recording_default_denied=True, static_resources_available=True)
    except Exception as error:
        report.update(status="failed", reason=str(error))
        raise
    finally:
        if server is not None and server.poll() is None:
            server.terminate(); server.wait(timeout=20)
        report["temporary_service_stopped"] = server is None or server.poll() is not None
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main():
    """命令行入口，打印不含图像/特征/会话凭据的数值报告。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", nargs="?", type=Path, default=ROOT / "outputs/delivery/vitrack_source.zip")
    parser.add_argument("--report", type=Path, default=ROOT / "outputs/delivery/package_check.json")
    parser.add_argument("--identity-mode", choices=["appearance", "hybrid"], default="appearance")
    args = parser.parse_args()
    print(json.dumps(verify(args.archive, args.report, args.identity_mode), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
