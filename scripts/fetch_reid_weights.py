"""下载并校验官方 MobileNetV3-Small 权重，输出到 weights，不在应用运行时隐式联网。"""
import hashlib
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
NAME = "mobilenet_v3_small-047dcff4.pth"


def main():
    """输入官方公开权重，验证 SHA256 文件名摘要前缀后保存；网络失败明确退出。"""
    target = ROOT / "weights" / NAME
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest().startswith("047dcff4"):
        print("verified:", target)
        return
    temporary = ROOT / "work/downloads" / (NAME + ".download")
    temporary.parent.mkdir(parents=True, exist_ok=True)
    # 方案规定 torchvision 权重先走官方直连；不尝试不兼容的模型格式。
    request = urllib.request.Request("https://download.pytorch.org/models/" + NAME,
                                     headers={"User-Agent": "ViTrack/1.0"})
    with urllib.request.urlopen(request, timeout=45) as response:
        content = response.read(20 * 1024 * 1024)
    if not hashlib.sha256(content).hexdigest().startswith("047dcff4"):
        raise RuntimeError("权重摘要不符，未写入模型目录")
    temporary.write_bytes(content)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary.replace(target)
    print("verified:", target, "bytes:", len(content))


if __name__ == "__main__":
    main()
