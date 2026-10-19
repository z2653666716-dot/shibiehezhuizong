"""按白名单打包可运行源码和公开样例，排除环境、证书、输出和所有实拍素材。

默认输出outputs/delivery/vitrack_source.zip及摘要报告，支持--output指定目标文件。
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 200 * 1024 * 1024
# 这些文件仍可保留在开发者本机，但不进入面向其他使用者的源码包。
LOCAL_DOCS = {"docs/branch_testing.md", "docs/delivery_guide.md",
              "docs/ViTrack-视觉目标检测与跟踪-实施方案.md"}


def collect_files(root=ROOT):
    """输入项目根目录，输出可分发文件；公开样例逐一列出，不递归收集用户图片。"""
    root = Path(root).resolve()
    files = set()
    patterns = {"app": {".py"}, "web": {".js", ".css", ".html", ".webmanifest"},
                "scripts": {".py", ".ps1"}, "tests": {".py"}, "docs": {".md"}}
    for folder, extensions in patterns.items():
        directory = root / folder
        for path in directory.rglob("*"):
            if (path.is_file() and path.suffix in extensions and not path.is_symlink()
                    and path.resolve().is_relative_to(directory.resolve())
                    and path.relative_to(root).as_posix() not in LOCAL_DOCS
                    and "__pycache__" not in path.parts):
                files.add(path)
    named = ["run.py", "README.md", ".gitignore", ".env.example", "requirements.txt", "requirements.lock.txt",
             "web/icons/icon-192.png", "web/icons/icon-512.png",
             "weights/yolo11n.pt", "weights/mobilenet_v3_small-047dcff4.pth", "weights/yolo11s.pt",
             "weights/osnet_x0_25_msmt17.onnx", "weights/face_detection_yunet_2023mar.onnx",
             "weights/face_recognition_sface_2021dec.onnx",
             "docs/licenses/yunet_license.txt", "docs/licenses/sface_license.txt",
             "data/samples/test.jpg", "data/samples/detection_cases.json", "data/samples/clothing/README.md",
             "data/samples/clothing/closet_clothes.jpg", "data/samples/clothing/window_jacket.jpg", "data/samples/clothing/gallery_jacket.jpg"]
    files.update(root / name for name in named if (root / name).is_file() and not (root / name).is_symlink())
    return sorted(files)


def make_package(output, root=ROOT):
    """校验关键文件和体积，生成带SHA256清单的源码ZIP，返回数值报告。"""
    root, output = Path(root).resolve(), Path(output).resolve()
    files = collect_files(root)
    required = ["app/main.py", "web/index.html", "README.md", ".env.example", "requirements.txt",
                "weights/yolo11n.pt", "weights/mobilenet_v3_small-047dcff4.pth"]
    if any(not (root / name).is_file() for name in required):
        raise FileNotFoundError("缺少入口、配置或必要权重，拒绝生成不完整源码包")
    total = sum(path.stat().st_size for path in files)
    if total > MAX_BYTES:
        raise ValueError("解压源码文件超过200MiB，未生成压缩包")
    entries = [{"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in files]
    manifest = {"kind": "source_package", "files": entries,
                "contains_user_media": False, "contains_env_or_certificates": False}
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".zip.part")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, "vitrack/" + path.relative_to(root).as_posix())
        archive.writestr("vitrack/SOURCE_MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    if temporary.stat().st_size > MAX_BYTES:
        raise ValueError("压缩包超过200MiB；中间文件保留供检查，未覆盖最终包")
    temporary.replace(output)
    report = {"archive": str(output), "file_count": len(files), "source_bytes": total,
              "archive_bytes": output.stat().st_size, "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
              "scope": manifest["kind"], "contains_user_media": False}
    output.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main():
    """读取输出路径并打包；旧命名参数保留兼容，常规使用只需--output。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--student-id", help=argparse.SUPPRESS)
    parser.add_argument("--student-name", help=argparse.SUPPRESS)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if bool(args.student_id) != bool(args.student_name):
        parser.error("学号与姓名必须同时填写")
    name = (args.student_id + args.student_name) if args.student_id else "vitrack_source"
    if not re.fullmatch(r"[\w\-\u4e00-\u9fff]+", name):
        parser.error("文件名只能包含中英文、数字、下划线或短横线")
    output = args.output or ROOT / "outputs/delivery" / (name + ".zip")
    print(json.dumps(make_package(output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
