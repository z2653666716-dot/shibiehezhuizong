"""检查源码白名单不会收集环境、证书、私有输出或额外加入的人物照片。"""
from scripts.package_source import collect_files


def test_package_excludes_private_and_generated_files(tmp_path):
    """构造目录边界，确认只收入源码和明确列出的公开样例。"""
    names = ["run.py", "app/main.py", "web/index.html", "web/icons/icon-192.png", "docs/user_guide.md", "README.md",
             "data/samples/test.jpg", "data/samples/private_person.jpg", ".env", "certs/key.pem",
             "envs/vitrack/secret.py", "outputs/recordings/private.mp4", "work/camera.jpg", "docs/private.jpg", "docs/private.txt"]
    for name in names:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")
    result = {path.relative_to(tmp_path).as_posix() for path in collect_files(tmp_path)}
    assert result == {"run.py", "app/main.py", "web/index.html", "web/icons/icon-192.png", "docs/user_guide.md", "README.md", "data/samples/test.jpg"}
