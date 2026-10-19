"""按白名单打包可运行源码和公开样例，排除环境、证书、输出和所有实拍素材。

默认输出outputs/delivery/vitrack_source.zip及清单；只有同时提供学号和姓名才用课程命名。
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 200 * 1024 * 1024


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
                    and "__pycache__" not in path.parts):
                files.add(path)
    named = ["README.md", "PROGRESS.md", "AGENTS.md", ".gitignore", ".env.example", "requirements.txt", "requirements.lock.txt",
             "web/icons/icon-192.png", "web/icons/icon-512.png",
             "weights/yolo11n.pt", "weights/mobilenet_v3_small-047dcff4.pth", "weights/yolo11s.pt",
             "weights/osnet_x0_25_msmt17.onnx", "weights/face_detection_yunet_2023mar.onnx",
             "weights/face_recognition_sface_2021dec.onnx",
             "docs/licenses/yunet_license.txt", "docs/licenses/sface_license.txt",
             "data/samples/test.jpg", "data/samples/detection_cases.json", "data/samples/clothing/README.md",
             "data/samples/clothing/closet_clothes.jpg", "data/samples/clothing/window_jacket.jpg", "data/samples/clothing/gallery_jacket.jpg"]
    files.update(root / name for name in named if (root / name).is_file() and not (root / name).is_symlink())
    return sorted(files)


def source_version(root):
    """只解析入口源码及当前根仓库元信息，输出版本/提交；不导入模型或读取私有配置。"""
    root = Path(root).resolve()
    version = None
    source = ast.parse((root / "app/main.py").read_text(encoding="utf-8-sig"))
    for node in ast.walk(source):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "FastAPI":
            for item in node.keywords:
                if item.arg == "version" and isinstance(item.value, ast.Constant) and isinstance(item.value.value, str):
                    version = item.value.value
    git = {"branch": None, "commit": None, "modified": None}
    try:
        def query(*arguments):
            """按参数列表调用Git，避免把文件内容拼接为可执行shell命令。"""
            return subprocess.check_output(["git", "-C", str(root), *arguments],
                                           stderr=subprocess.DEVNULL, text=True, encoding="utf-8").strip()
        # 解压目录可能恰好位于原仓库work下，不能误把外层仓库的提交号写成解压源码的版本。
        if Path(query("rev-parse", "--show-toplevel")).resolve() == root:
            git.update(branch=query("branch", "--show-current"), commit=query("rev-parse", "HEAD"),
                       modified=bool(query("status", "--porcelain")))
    except (OSError, subprocess.CalledProcessError):
        pass  # 无Git的解压源码仍可打包，元信息如实保持未知，不伪造提交号。
    return {"runtime_version": version, "git": git}


def make_package(output, root=ROOT, identity_mode="appearance"):
    """校验指定身份模式的必要模型，生成带版本/SHA256清单的源码ZIP，返回数值报告。"""
    root, output = Path(root).resolve(), Path(output).resolve()
    if identity_mode not in {"appearance", "hybrid"}:
        raise ValueError("未知身份模式")
    files = collect_files(root)
    required = ["app/main.py", "web/index.html", "README.md", ".env.example", "requirements.txt",
                "weights/yolo11n.pt", "weights/mobilenet_v3_small-047dcff4.pth"]
    if identity_mode == "hybrid":
        required.extend(["weights/osnet_x0_25_msmt17.onnx", "weights/face_detection_yunet_2023mar.onnx",
                         "weights/face_recognition_sface_2021dec.onnx"])
    if any(not (root / name).is_file() for name in required):
        raise FileNotFoundError("缺少入口、配置或必要权重，拒绝生成不完整源码包")
    total = sum(path.stat().st_size for path in files)
    if total > MAX_BYTES:
        raise ValueError("解压源码文件超过200MiB，未生成压缩包")
    entries = [{"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in files]
    version = source_version(root)
    manifest = {"kind": "source_package_not_final_course_submission", "files": entries,
                "identity_mode": identity_mode, "source": version,
                "contains_user_media": False, "contains_env_or_certificates": False,
                "manual_deliverables": ["论文正文", "实验报告正文与课堂模板", "最终演示视频", "课程汇报PPT", "学号姓名及截止日期"]}
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
              "identity_mode": identity_mode, "source": version,
              "archive_bytes": output.stat().st_size, "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
              "scope": manifest["kind"], "contains_user_media": False}
    output.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main():
    """读取可选命名参数；没有学号姓名时用中性名称，不编造课程个人信息。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--student-id")
    parser.add_argument("--student-name")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--identity-mode", choices=["appearance", "hybrid"], default="appearance")
    args = parser.parse_args()
    if bool(args.student_id) != bool(args.student_name):
        parser.error("学号与姓名必须同时填写")
    name = (args.student_id + args.student_name) if args.student_id else "vitrack_source"
    if not re.fullmatch(r"[\w\-\u4e00-\u9fff]+", name):
        parser.error("文件名只能包含中英文、数字、下划线或短横线")
    output = args.output or ROOT / "outputs/delivery" / (name + ".zip")
    print(json.dumps(make_package(output, identity_mode=args.identity_mode), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
