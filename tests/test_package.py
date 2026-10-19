"""检查源码白名单不会收集环境、证书、私有输出或额外加入的人物照片。"""
import json
import zipfile

import pytest

from scripts.package_source import collect_files, make_package, source_version


def test_package_excludes_private_and_generated_files(tmp_path):
    """构造目录边界，确认只收入源码和明确列出的公开样例。"""
    names = ["app/main.py", "web/index.html", "web/icons/icon-192.png", "docs/user_guide.md", "README.md",
             "data/samples/test.jpg", "data/samples/private_person.jpg", ".env", "certs/key.pem",
             "envs/vitrack/secret.py", "outputs/recordings/private.mp4", "work/camera.jpg", "docs/private.jpg", "docs/private.txt"]
    for name in names:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")
    result = {path.relative_to(tmp_path).as_posix() for path in collect_files(tmp_path)}
    assert result == {"app/main.py", "web/index.html", "web/icons/icon-192.png", "docs/user_guide.md", "README.md", "data/samples/test.jpg"}


def test_hybrid_package_requires_models_and_records_runtime_version(tmp_path):
    """打包实验模式不能遗漏三份额外模型；版本从源码解析，测试不会加载这些假权重。"""
    root = tmp_path / "source"
    names = ["app/main.py", "web/index.html", "README.md", ".env.example", "requirements.txt",
             "weights/yolo11n.pt", "weights/mobilenet_v3_small-047dcff4.pth"]
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")
    (root / "app/main.py").write_text('application = FastAPI(version="0.3.5-face-enrollment")', encoding="utf-8")
    output = tmp_path / "hybrid.zip"
    with pytest.raises(FileNotFoundError):
        make_package(output, root, "hybrid")
    assert not output.exists()
    for name in ("osnet_x0_25_msmt17.onnx", "face_detection_yunet_2023mar.onnx", "face_recognition_sface_2021dec.onnx"):
        (root / "weights" / name).write_text("fixture", encoding="utf-8")
    report = make_package(output, root, "hybrid")
    with zipfile.ZipFile(output) as archive:
        manifest = json.loads(archive.read("vitrack/SOURCE_MANIFEST.json"))
    assert report["identity_mode"] == manifest["identity_mode"] == "hybrid"
    assert manifest["source"]["runtime_version"] == "0.3.5-face-enrollment"
    assert manifest["source"]["git"] == {"branch": None, "commit": None, "modified": None}
    assert source_version(root)["git"]["commit"] is None  # 不误用work外层项目的Git提交。
