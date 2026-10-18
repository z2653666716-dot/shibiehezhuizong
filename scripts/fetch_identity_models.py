"""下载实验分支需要的公开模型，逐个校验固定SHA256，不在应用推理时隐式联网。

输入--group选择person/face/all，输出weights中的ONNX及outputs/models/identity_models.json。
临时下载放work/downloads；不接收、不保存用户照片或特征。
"""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MODELS = {
    "osnet_x0_25_msmt17.onnx": ("person", "e78604f4ccda49b8f41cd0f8f7303800ce75d2361895ebb0729513c1bf53d277",
        "https://huggingface.co/anriha/osnet_x0_25_msmt17/resolve/1e22b925c70caa5591e9fab3f5540af8484bcad8/osnet_x0_25_msmt17.onnx"),
    "face_detection_yunet_2023mar.onnx": ("face", "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
        "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"),
    "face_recognition_sface_2021dec.onnx": ("face", "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
        "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx"),
}


def download(name, expected_hash, url):
    """输入模型名、摘要和公开URL，输出验证信息；失败不覆盖已有模型，同源不反复重试。"""
    target = ROOT / "weights" / name
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == expected_hash:
        return {"name": name, "sha256": expected_hash, "bytes": target.stat().st_size, "verified": True}
    temporary = ROOT / "work/downloads" / (name + ".download")
    temporary.parent.mkdir(parents=True, exist_ok=True)
    digest, total = hashlib.sha256(), 0
    request = urllib.request.Request(url, headers={"User-Agent": "ViTrack-identity-experiment/1.0"})
    with urllib.request.urlopen(request, timeout=45) as response, temporary.open("wb") as output:
        while chunk := response.read(256 * 1024):
            total += len(chunk)
            if total > 48 * 1024 * 1024:
                raise ValueError("下载超出模型体积上限，未替换正式文件")
            digest.update(chunk)
            output.write(chunk)
    if digest.hexdigest() != expected_hash:
        raise ValueError("模型SHA256不符，未替换正式文件")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary.replace(target)
    return {"name": name, "url": url, "sha256": expected_hash, "bytes": total, "verified": True}


def main():
    """命令行入口：逐个下载选中的模型，并保存不含用户数据的来源与摘要报告。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", choices=["person", "face", "all"], default="all")
    args = parser.parse_args()
    results = []
    for name, (group, digest, url) in MODELS.items():
        if args.group in {group, "all"}:
            result = download(name, digest, url)
            results.append(result)
            print(json.dumps(result), flush=True)
    report = ROOT / "outputs/models/identity_models.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
