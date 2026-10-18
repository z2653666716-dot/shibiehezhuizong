"""用明确标注的同人/异人图片对计算 TAR/FAR；公开图增强仅作诊断，不冒充真实标定。

入口：python scripts/calibrate_reid.py --pairs data/pairs.json，或 --diagnostic。
输出报告/CSV/分布图；只有人工标注足量 pairs 才允许 --write-env，默认不改阈值。
"""
import argparse
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2
import numpy as np

from app.config import load_config
from app.detector import Detector
from app.reid import FeatureExtractor, cosine, crop_target


def read_image(path):
    """输入图片路径，输出解码的 BGR；损坏图片立即拒绝，不以零分混入统计。"""
    image = cv2.imdecode(np.frombuffer(Path(path).read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"无法读取图片：{path}")
    return image


def evaluate(same, different):
    """输入两组真实相似度，输出各门槛下同人接受率 TAR 与异人误接率 FAR。"""
    if not same or not different:
        raise ValueError("同人和异人配对都不能为空")
    return [{"threshold": round(float(threshold), 2),
             "tar": float(np.mean(np.array(same) >= threshold)),
             "far": float(np.mean(np.array(different) >= threshold))}
            for threshold in np.arange(0.50, 1.001, 0.05)]


def main():
    """读取标注配对或公开样例诊断，计算实际分数后写报告；不创建或读取摄像头。"""
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--pairs", type=Path, help='JSON: {"same":[["a.jpg","b.jpg"]],"diff":[...]}，图片应为人物裁剪')
    group.add_argument("--diagnostic", action="store_true", help="只在公开 bus 图裁剪与增强上检查，不作为实拍标定")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/reid/calibration.json")
    parser.add_argument("--write-env", action="store_true", help="仅足量人工标注配对可更新 .env 高阈值")
    args = parser.parse_args()
    config = load_config()
    extractor = FeatureExtractor(config)
    same, different = [], []
    if args.diagnostic:
        if args.write_env:
            parser.error("公开样例增强诊断不允许修改生产阈值")
        frame = read_image(ROOT / "data/samples/test.jpg")
        detections = Detector(config).detect(frame)
        height, width = frame.shape[:2]
        crops = [crop_target(frame, (a / width, b / height, c / width, d / height))
                 for box in detections if box.cls == 0 for a, b, c, d in [box.xyxy]]
        crops = [crop for crop in crops if crop is not None]
        if len(crops) < 2:
            raise ValueError("公开样例不足两个可用人物框")
        features = extractor.extract(crops)
        for index, crop in enumerate(crops):
            for factor in (0.8, 0.9, 1.1, 1.2):
                changed = np.clip(crop.astype(np.float32) * factor, 0, 255).astype(np.uint8)
                same.append(cosine(features[index], extractor.extract([changed])[0]))
        different = [cosine(first, second) for index, first in enumerate(features) for second in features[index + 1:]]
    else:
        pairs = json.loads(args.pairs.read_text(encoding="utf-8-sig"))
        for key, output in (("same", same), ("diff", different)):
            for first_path, second_path in pairs[key]:
                images = [read_image(args.pairs.parent / name) for name in (first_path, second_path)]
                first, second = extractor.extract(images)
                output.append(cosine(first, second))
    rows = evaluate(same, different)
    eligible = len(same) >= 15 and len(different) >= 15 and not args.diagnostic
    candidates = [row for row in rows if row["far"] <= 0.05 and row["threshold"] > config.reid_tau_low]
    recommendation = max(candidates, key=lambda row: (row["tar"], -row["far"], row["threshold"])) if candidates else None
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {"mode": "public_augmented_diagnostic_only" if args.diagnostic else "labeled_pairs",
              "production_calibrated": eligible and recommendation is not None,
              "same_count": len(same), "diff_count": len(different), "rows": rows,
              "recommended_high": recommendation["threshold"] if recommendation and eligible else None,
              "same_scores": same, "different_scores": different,
              "limitations": "同一张公开照片的增强不代表跨时间、姿态或真实离开重入的性能" if args.diagnostic else "只适用于所提供标注配对的分布"}
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with args.output.with_suffix(".csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=["threshold", "tar", "far"])
        writer.writeheader(); writer.writerows(rows)
    # 标准绘图库生成可导出的分布图；不把用户照片写入图表。
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    figure, axis = plt.subplots()
    axis.hist(same, bins=15, alpha=0.6, label="same / augmented")
    axis.hist(different, bins=15, alpha=0.6, label="different")
    axis.set(xlabel="Cosine similarity", ylabel="Pair count", title=report["mode"])
    axis.legend(); figure.tight_layout(); figure.savefig(args.output.with_suffix(".png")); plt.close(figure)
    if args.write_env:
        if not eligible or recommendation is None:
            parser.error("不足每类15对或没有满足 FAR<=0.05 的门槛；已保存报告，未修改配置")
        env_path = ROOT / ".env"
        lines = env_path.read_text(encoding="utf-8-sig").splitlines() if env_path.exists() else []
        lines = [line for line in lines if not line.startswith("REID_TAU_HIGH=")]
        lines.append(f"REID_TAU_HIGH={recommendation['threshold']}")
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("mode", "same_count", "diff_count", "production_calibrated")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
