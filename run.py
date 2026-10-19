"""ViTrack 一键手机演示入口：在编辑器打开本文件，点击右上角运行即可启动服务。

先用标准库切换到项目专用Python，再复用app/config.py和scripts/gen_cert.py检查配置。
输入是下面的演示参数，输出手机网址和服务状态；不自动打开浏览器、摄像头或IP视频源。
"""
import argparse
import os
from pathlib import Path
import socket
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
PROJECT_PYTHON = ROOT / "envs" / "vitrack" / "python.exe"

# 日常演示只需点击运行。热点地址与此前实测一致；地址改变时证书也必须包含新地址。
PHONE_IP = "192.168.137.1"
PORT = 8450
CERTIFICATE_DIR = ROOT / "certs" / "hotspot"


def project_environment():
    """无输入，返回子进程配置副本；沿用已验证的新方法，禁止保存，不改.env或系统设置。"""
    environment = os.environ.copy()
    environment.update({
        "PYTHONUTF8": "1", "SOURCE": "ws", "IDENTITY_MODE": "hybrid",
        "IDENTITY_DEVICE": "cpu", "REID_MODEL": "osnet_x0_25", "TRACKER": "botsort.yaml",
        "ALLOW_MEDIA_SAVE": "false", "HTTPS_CERT": str(CERTIFICATE_DIR / "cert.pem"),
        "HTTPS_KEY": str(CERTIFICATE_DIR / "key.pem"),
    })
    return environment


def use_project_python(arguments):
    """输入原启动参数，输出项目Python的退出码；编辑器选错环境时也不用重新安装依赖。"""
    print("正在使用项目专用 Python 启动……", flush=True)
    # 参数使用列表，不拼接Shell命令，因此路径含空格也能正常传递。
    process = subprocess.Popen(
        [str(PROJECT_PYTHON), "-X", "utf8", str(ROOT / "run.py"), *arguments],
        cwd=ROOT, env=project_environment(),
    )
    try:
        return process.wait()
    except KeyboardInterrupt:
        # 同一终端中的子服务也会收到Ctrl+C，先让它正常收尾；只清理本入口创建的进程。
        try:
            return process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                return process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                return process.wait()


def prepare_server():
    """检查热点、证书、模型及端口，返回配置对象；由main调用，不加载推理模型或访问相机。"""
    # 第三方依赖延迟到这里导入，保证编辑器误选base环境时仍能先完成解释器切换。
    from app.config import load_config
    from scripts.gen_cert import check_certificate, local_ips

    settings = load_config()
    if PHONE_IP not in local_ips():
        raise ValueError(f"电脑没有热点地址 {PHONE_IP}。请开启电脑移动热点、让手机连接后再运行。")
    certificate = check_certificate(settings.https_cert, settings.https_key, [PHONE_IP, "127.0.0.1"])
    if "localhost" not in certificate["dns_names"]:
        raise ValueError("热点证书缺少localhost地址，请按项目证书说明处理。")
    models = [settings.det_model, settings.person_weights,
              settings.face_detector_weights, settings.face_recognizer_weights]
    missing = [path.name for path in models if not path.is_file()]
    if missing:
        raise ValueError("缺少本地模型：" + "、".join(missing) + "。请按README准备模型后再运行。")
    try:
        # 只试绑定端口并立即释放，不终止已有程序，也不自动换端口让手机访问到旧服务。
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            # Windows可能允许不同网卡重复绑定同一端口；独占检查才能识别回环上已有的服务。
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind(("0.0.0.0", PORT))
    except OSError as error:
        raise ValueError(f"端口 {PORT} 不可用，可能已有服务在运行。请先在原终端按Ctrl+C停止。") from error
    return settings


def main(arguments=None):
    """入口：选择项目环境→检查启动条件→启动HTTPS服务，返回退出码；--check只检查。"""
    # 编辑器可能以系统代码页运行全局Python；本进程统一UTF-8，避免转交前的中文提示乱码。
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    arguments = sys.argv[1:] if arguments is None else arguments
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="只检查启动条件，不启动服务")
    options = parser.parse_args(arguments)
    try:
        if not PROJECT_PYTHON.is_file():
            raise ValueError("找不到项目环境envs/vitrack/python.exe，请先按README准备环境。")
        if Path(sys.executable).resolve() != PROJECT_PYTHON.resolve():
            return use_project_python(arguments)
        # 只改变本次运行进程。工作目录固定为项目根目录，不受编辑器从哪个目录运行影响。
        os.chdir(ROOT)
        os.environ.update(project_environment())
        settings = prepare_server()
        print(f"项目 Python：{sys.executable}", flush=True)
        print(f"手机访问：https://{PHONE_IP}:{PORT}", flush=True)
        print("身份模式：人脸 + 身体联合跟踪；媒体保存：禁止。", flush=True)
        if options.check:
            print("启动检查通过；未启动服务，未打开摄像头。", flush=True)
            return 0
        print("正在加载服务，看到Application startup complete后再用手机打开页面。", flush=True)
        print("手机点击开始检测并授权后才采集；结束时先停止检测，再在此终端按Ctrl+C。", flush=True)
        import uvicorn

        # workers=1且不使用热重载，避免重复载入GPU模型；服务配置与run_identity.ps1一致。
        uvicorn.run("app.main:app", host="0.0.0.0", port=PORT, workers=1,
                    ssl_certfile=str(settings.https_cert), ssl_keyfile=str(settings.https_key))
        return 0
    except KeyboardInterrupt:
        print("服务已停止。", flush=True)
        return 0
    except (ValueError, OSError, ImportError) as error:
        print(f"启动失败：{error}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
