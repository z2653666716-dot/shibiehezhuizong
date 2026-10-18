"""离线检查人物检测的误检与漏检，属于 ViTrack 的公开样例诊断工具。

输入为带 SHA256/粗略人物框的本地图片清单和候选参数，输出仅含数值的 JSON。
复用 app.Detector 与 Box 坐标转换，不启动服务、摄像头或下载，不修改正式配置。
main 是命令行入口；结果只适用于这组小样例，不能作为通用准确率或现场验收。
"""

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from importlib.metadata import version
from io import BytesIO
import json
import math
from pathlib import Path
import re
import sys
from time import perf_counter

import cv2
import numpy as np
from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
# 直接运行 scripts 内的文件时，Python 首先查找 scripts；补入项目根目录以复用 app。
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import AppConfig
from app.detector import Detector
from app.schemas import Box


@dataclass(frozen=True)
class DetectionCase:
    """load_cases 的输出：本地文件、校验值、来源及人工标注，供预处理与评分使用。"""

    name: str
    path: Path
    sha256: str
    source: str
    persons: list[tuple[float, ...]]
    clothing_regions: list[tuple[float, ...]]


def checked_box(value: object) -> tuple[float, ...]:
    """输入清单中的框，输出有效的 0～1 坐标；非法标注立即失败，避免污染评估。"""
    if (not isinstance(value, list) or len(value) != 4 or
            any(isinstance(item, bool) or not isinstance(item, (int, float)) or
                not math.isfinite(item) or not 0 <= item <= 1 for item in value)):
        raise ValueError("标注坐标必须是四个有限的 0～1 数字")
    if value[0] >= value[2] or value[1] >= value[3]:
        raise ValueError("标注框必须有正面积")
    return tuple(float(item) for item in value)


def load_cases(manifest: Path) -> list[DetectionCase]:
    """读取清单并验证文件与 SHA256，输出案例列表；这里只读项目内文件，不执行下载。"""
    document = json.loads(manifest.read_text(encoding="utf-8-sig"))
    if document.get("version") != 1 or not isinstance(document.get("cases"), list) or not document["cases"]:
        raise ValueError("清单必须包含 version=1 和非空 cases 列表")
    cases = []
    names = set()
    for item in document["cases"]:
        name = item["id"]
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", name) or name in names:
            raise ValueError("案例 id 必须是唯一的英文小写名称")
        names.add(name)
        relative_path = Path(item["file"])
        path = (PROJECT_ROOT / relative_path).resolve()
        if relative_path.is_absolute() or not path.is_relative_to(PROJECT_ROOT):
            raise ValueError("样例路径必须位于本项目内")
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png"} or not path.is_file():
            raise ValueError("找不到本地 JPG/PNG 样例：" + name)
        if path.stat().st_size > 12 * 1024 * 1024:
            raise ValueError("样例不能超过 12 MiB：" + name)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != item["sha256"]:
            raise ValueError("SHA256 不一致，不能混用不同图片：" + name)
        if not isinstance(item["persons"], list) or not isinstance(item["clothing_regions"], list):
            raise ValueError("persons 和 clothing_regions 必须是列表")
        cases.append(DetectionCase(
            name, path, digest, item["source"],
            [checked_box(box) for box in item["persons"]],
            [checked_box(box) for box in item["clothing_regions"]],
        ))
    return cases


def prepare_image(case: DetectionCase, max_side: int, jpeg_quality: int | None) -> np.ndarray:
    """输入公开案例与传输参数，输出 BGR 图像；模拟最长边缩放及可选 JPEG 往返，不写图片。"""
    payload = case.path.read_bytes()
    with Image.open(BytesIO(payload)) as header:
        if header.width * header.height > 32_000_000:
            raise ValueError("公开原图超过 3200 万像素：" + case.name)
        header.verify()
    # 与应用一样忽略 EXIF 自动旋转，使手工标注和解码后的方向一致。
    image = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
    if image is None:
        raise ValueError("不能解码公开样例：" + case.name)
    height, width = image.shape[:2]
    scale = min(1.0, max_side / max(height, width))
    if scale < 1:
        image = cv2.resize(image, (max(1, round(width * scale)), max(1, round(height * scale))))
    if jpeg_quality is not None:
        # 在内存里压缩再解码，观察浏览器 JPEG 传输对检测的影响；没有临时图片落盘。
        ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
        if not ok:
            raise ValueError("样例 JPEG 编码失败")
        image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("样例 JPEG 解码失败")
    return image


def box_overlap(first, second) -> float:
    """输入两个归一化框，输出交并比，供预测框与手工人物框配对。"""
    width = max(0.0, min(first[2], second[2]) - max(first[0], second[0]))
    height = max(0.0, min(first[3], second[3]) - max(first[1], second[1]))
    intersection = width * height
    area = lambda box: (box[2] - box[0]) * (box[3] - box[1])
    return intersection / (area(first) + area(second) - intersection)


def score_boxes(boxes: list[Box], persons, clothing_regions, match_iou: float) -> dict:
    """输入预测框和手工标注，输出配对数、误检、漏检及衣物区域误检；每个框最多匹配一次。"""
    pairs = []
    for prediction_index, box in enumerate(boxes):
        for person_index, person in enumerate(persons):
            overlap = box_overlap(box.xyxy, person)
            if overlap >= match_iou:
                pairs.append((overlap, prediction_index, person_index))
    used_predictions, used_persons = set(), set()
    # 优先取重合最多的配对；重复框不能靠指向同一人物被重复记作正确检出。
    for _, prediction_index, person_index in sorted(pairs, reverse=True):
        if prediction_index not in used_predictions and person_index not in used_persons:
            used_predictions.add(prediction_index)
            used_persons.add(person_index)
    false_boxes = [box for index, box in enumerate(boxes) if index not in used_predictions]
    clothing_false = []
    for box in false_boxes:
        center_x = (box.xyxy[0] + box.xyxy[2]) / 2
        center_y = (box.xyxy[1] + box.xyxy[3]) / 2
        if any(left <= center_x <= right and top <= center_y <= bottom
               for left, top, right, bottom in clothing_regions):
            clothing_false.append(box.score)
    return {
        "matched_people": len(used_persons),
        "false_positives": len(false_boxes),
        "missed_people": len(persons) - len(used_persons),
        "clothing_region_false_positives": len(clothing_false),
        "clothing_false_positive_scores": clothing_false,
        "false_positive_scores": [box.score for box in false_boxes],
    }


def compare_runs(runs: list[dict]) -> dict:
    """输入各参数统计，列出相对默认值误检更少且不增加漏检的候选；输出建议，不改配置。"""
    baseline = next((row for row in runs if row["image_size"] == 640 and row["confidence"] == 0.35), None)
    candidates = []
    if baseline is not None:
        for row in runs:
            if (row["totals"]["false_positives"] < baseline["totals"]["false_positives"] and
                    row["totals"]["missed_people"] <= baseline["totals"]["missed_people"]):
                candidates.append({"image_size": row["image_size"], "confidence": row["confidence"]})
    return {
        "baseline_present": baseline is not None,
        "fewer_false_positives_without_more_misses_on_this_set": candidates,
        "production_config_changed": False,
        "decision": "keep_defaults_pending_broader_evidence",
        "limitation": "Small public set with coarse manual boxes; not general accuracy or a reproduction of the user's private scene.",
    }


def run_evaluation(cases: list[DetectionCase], args, report: dict) -> None:
    """输入案例/参数，逐项调用真实 Detector，填写报告；循环不读取网络或运行中的摄像头。"""
    images = {case.name: prepare_image(case, args.input_max_side, args.jpeg_quality) for case in cases}
    report["runs"] = []
    for image_size in args.image_sizes:
        for confidence in args.thresholds:
            detector = Detector(AppConfig(det_model=args.model, det_device=args.device,
                                          det_imgsz=image_size, det_conf=confidence, target_classes=(0,)))
            row = {"image_size": image_size, "confidence": confidence, "cases": []}
            for case in cases:
                image = images[case.name]
                height, width = image.shape[:2]
                started = perf_counter()
                detections = detector.detect(image)
                elapsed = (perf_counter() - started) * 1000
                boxes = [Box.from_detection(item, width, height) for item in detections]
                row["cases"].append({
                    "id": case.name, "input_size": [width, height], "expected_people": len(case.persons),
                    "detected_boxes": len(boxes), "detect_ms": round(elapsed, 2),
                    **score_boxes(boxes, case.persons, case.clothing_regions, args.match_iou),
                })
            counts = ("matched_people", "false_positives", "missed_people", "clothing_region_false_positives")
            row["totals"] = {key: sum(item[key] for item in row["cases"]) for key in counts}
            report["runs"].append(row)
            print(json.dumps({key: row[key] for key in ("image_size", "confidence", "totals")}), flush=True)
            del detector
    report["comparison"] = compare_runs(report["runs"])


def parse_args():
    """接收命令行输入，检查尺寸/门槛/压缩范围，输出参数；模型加载前完成校验。"""
    parser = argparse.ArgumentParser(description="离线评估公开衣物/人物样例，不使用摄像头")
    parser.add_argument("--manifest", type=Path, default=Path("data/samples/detection_cases.json"))
    parser.add_argument("--model", type=Path, default=Path("weights/yolo11n.pt"))
    parser.add_argument("--device", default="0")
    parser.add_argument("--image-sizes", type=int, nargs="+", default=[640, 960])
    parser.add_argument("--thresholds", type=float, nargs="+", default=[0.35, 0.5, 0.65, 0.8])
    parser.add_argument("--input-max-side", type=int, default=640)
    parser.add_argument("--jpeg-quality", type=int, default=None)
    parser.add_argument("--match-iou", type=float, default=0.5)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("outputs/detection_review/parameter_comparison.json"))
    args = parser.parse_args()
    if any(size < 32 or size > 2048 or size % 32 for size in args.image_sizes):
        parser.error("--image-sizes 必须为 32～2048 内的 32 倍数")
    if not 32 <= args.input_max_side <= 2048:
        parser.error("--input-max-side 必须为 32～2048")
    if any(not math.isfinite(value) or not 0 < value <= 1 for value in [*args.thresholds, args.match_iou]):
        parser.error("检测门槛和配对交并比必须大于 0 且不超过 1")
    if args.jpeg_quality is not None and not 1 <= args.jpeg_quality <= 100:
        parser.error("--jpeg-quality 必须为 1～100；省略表示不额外压缩")
    for name in ("manifest", "model", "output"):
        path = getattr(args, name)
        setattr(args, name, (PROJECT_ROOT / path).resolve() if not path.is_absolute() else path.resolve())
    if args.output.suffix.lower() != ".json":
        parser.error("--output 必须是 JSON 文件，不能覆盖图片")
    args.image_sizes = sorted(set(args.image_sizes))
    args.thresholds = sorted(set(args.thresholds))
    return args


def main() -> int:
    """入口：检查清单 → 预处理/检测 → 保存数值报告；退出码 0 仅表示工具成功运行。"""
    args = parse_args()
    # 即使输入清单已损坏，也必须在读取之前拒绝覆盖清单/模型的报告路径。
    if args.output in {args.manifest, args.model}:
        print("报告路径不能覆盖输入文件", file=sys.stderr)
        return 1
    report = {
        "checked_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "status": "started", "physical_camera_access": False, "media_uploaded": False,
        "images_written_by_evaluator": False, "input_max_side": args.input_max_side,
        "jpeg_quality": args.jpeg_quality, "match_iou": args.match_iou,
        "timing_note": "Individual detect calls include cold startup; not end-to-end latency or sustained FPS.",
    }
    exit_code = 0
    try:
        cases = load_cases(args.manifest)
        # 不允许把报告覆盖到输入清单、权重或图片；失败时也不能写坏这些源文件。
        protected = {args.manifest, args.model, *(case.path for case in cases)}
        if args.output in protected:
            print("报告路径不能覆盖输入文件", file=sys.stderr)
            return 1
        report["manifest_sha256"] = hashlib.sha256(args.manifest.read_bytes()).hexdigest()
        report["cases"] = [{"id": case.name, "sha256": case.sha256, "source": case.source,
                            "expected_people": len(case.persons)} for case in cases]
        if args.check_only:
            for case in cases:
                prepare_image(case, args.input_max_side, args.jpeg_quality)
            report["status"] = "inputs_checked_no_model_loaded"
        else:
            report["model_sha256"] = hashlib.sha256(args.model.read_bytes()).hexdigest()
            report["versions"] = {name: version(name) for name in ("torch", "ultralytics", "opencv-python")}
            run_evaluation(cases, args, report)
            report["status"] = "evaluation_completed_not_acceptance"
    except Exception as error:
        report.update(status="failed", reason=str(error))
        exit_code = 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "report": str(args.output)}, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
