"""在固定公开样例上测CPU/GPU×分辨率×本地模型，输出实测JSON/CSV，不读取设备。

这是检测器基准，不冒充完整网络/重识别帧率；缺失模型会明确标记，不自动下载。
"""
import argparse
import csv
import json
from pathlib import Path
import statistics
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2

from app.config import AppConfig
from app.detector import Detector


def main():
    """读取本地模型与样例，预热后同步计时，每种组合单独报告冷启动/均值/95分位。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", default=["yolo11n.pt", "yolo11s.pt"])
    parser.add_argument("--sizes", nargs="+", type=int, default=[480, 640, 800])
    parser.add_argument("--devices", nargs="+", default=["cpu", "0"])
    parser.add_argument("--frames", type=int, default=10)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/bench/detection_benchmark.json")
    args = parser.parse_args()
    if not 1 <= args.frames <= 300:
        parser.error("frames应为1～300")
    image = cv2.imread(str(ROOT / "data/samples/test.jpg"))
    if image is None:
        raise FileNotFoundError("缺少公开样例")
    rows = []
    for model in args.models:
        for size in args.sizes:
            for device in args.devices:
                row = {"model": model, "imgsz": size, "device": device, "status": "ok"}
                try:
                    config = AppConfig(det_model=ROOT / "weights" / model, det_imgsz=size, det_device=device)
                    started = perf_counter()
                    detector = Detector(config)
                    detector.detect(image)
                    row["load_and_first_ms"] = round((perf_counter() - started) * 1000, 2)
                    for _ in range(2): detector.detect(image)
                    times = []
                    for _ in range(args.frames):
                        started = perf_counter()
                        detections = detector.detect(image)
                        # detect已把张量搬到CPU，同步完成；不只测异步GPU命令提交耗时。
                        times.append((perf_counter() - started) * 1000)
                    mean = statistics.mean(times)
                    row.update(mean_ms=round(mean, 2), p95_ms=round(sorted(times)[min(len(times)-1, int(len(times)*.95))], 2),
                               fps=round(1000 / mean, 2), frames=args.frames, boxes=len(detections))
                except Exception as error:
                    row.update(status="unavailable", reason=str(error))
                rows.append(row)
                print(json.dumps(row, ensure_ascii=False), flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"scope": "detector_only_public_still_image", "rows": rows,
        "limitations": "短样例检测器吞吐，不含摄像头、网络、特征提取或现场人物变化"}, ensure_ascii=False, indent=2), encoding="utf-8")
    fields = ["model", "imgsz", "device", "status", "frames", "mean_ms", "p95_ms", "fps", "boxes", "load_and_first_ms", "reason"]
    with args.output.with_suffix(".csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader(); writer.writerows(rows)


if __name__ == "__main__":
    main()
