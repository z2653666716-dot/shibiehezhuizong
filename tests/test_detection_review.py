"""验证离线诊断的评分与输入边界，不加载 YOLO、不读取摄像头、不请求网络。

pytest 调用本文件；用合成框检查重复框、衣物区域和误检/漏检取舍，公开文件只做校验。
"""

import json
from types import SimpleNamespace

import pytest

from app.schemas import Box
from scripts.evaluate_detection import PROJECT_ROOT, compare_runs, load_cases, prepare_image, score_boxes
from scripts import evaluate_detection


def person(coordinates, score=0.87):
    """输入合成坐标与分数，输出协议框，供评分测试使用，不代表真实检测结果。"""
    return Box(cls=0, name="person", xyxy=coordinates, score=score)


def test_duplicate_prediction_is_not_a_second_true_person():
    """同一个真实人物被框两次时，只能记一次检出，另一个必须算误检。"""
    truth = [(0.1, 0.1, 0.4, 0.9)]
    boxes = [person(truth[0]), person(truth[0], 0.73)]
    result = score_boxes(boxes, truth, [], 0.5)
    assert result["matched_people"] == 1
    assert result["false_positives"] == 1
    assert result["missed_people"] == 0


def test_unworn_clothing_high_score_remains_a_false_positive():
    """无人场景即使得分高也必须记误检，不能把高分当成真值。"""
    result = score_boxes([person((0.2, 0.1, 0.6, 0.8), 0.91)], [], [(0, 0, 1, 1)], 0.5)
    assert result["matched_people"] == 0
    assert result["false_positives"] == result["clothing_region_false_positives"] == 1
    assert result["clothing_false_positive_scores"] == [0.91]


def test_missed_person_and_wrong_location_are_both_counted():
    """框数量相同但位置错误时，不能仅靠人数相等宣称检测正确。"""
    result = score_boxes([person((0.7, 0.1, 0.95, 0.8))], [(0.1, 0.1, 0.4, 0.9)], [], 0.5)
    assert result["false_positives"] == result["missed_people"] == 1


def test_parameter_comparison_rejects_fewer_boxes_with_more_misses():
    """门槛升高导致真人漏检时，即便误检减少，也不能列为无损改善候选。"""
    def row(size, confidence, false_positives, missed_people):
        return {"image_size": size, "confidence": confidence,
                "totals": {"false_positives": false_positives, "missed_people": missed_people}}
    result = compare_runs([row(640, 0.35, 2, 0), row(640, 0.8, 0, 2), row(960, 0.35, 1, 0)])
    assert result["fewer_false_positives_without_more_misses_on_this_set"] == [{"image_size": 960, "confidence": 0.35}]
    assert result["production_config_changed"] is False


def test_public_manifest_and_memory_preprocessing():
    """检查实际公开样例 SHA 和标注，并确认缩放/JPEG 往返只产生内存图像。"""
    cases = load_cases(PROJECT_ROOT / "data/samples/detection_cases.json")
    assert len(cases) == 4 and sum(len(case.persons) for case in cases) == 6
    for case in cases:
        image = prepare_image(case, 640, 65)
        assert max(image.shape[:2]) <= 640 and image.shape[2] == 3


def test_modified_sample_is_rejected(tmp_path):
    """清单里的 SHA 与已有图片不符时必须停止，防止不同版本样例混用。"""
    document = json.loads((PROJECT_ROOT / "data/samples/detection_cases.json").read_text(encoding="utf-8"))
    document["cases"][0]["sha256"] = "0" * 64
    manifest = tmp_path / "invalid_cases.json"
    manifest.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="SHA256"):
        load_cases(manifest)


def test_annotation_bounds_are_checked(tmp_path):
    """标注出现反向坐标时不能继续评分。"""
    document = json.loads((PROJECT_ROOT / "data/samples/detection_cases.json").read_text(encoding="utf-8"))
    document["cases"][0]["persons"] = [[0.8, 0.1, 0.2, 0.9]]
    manifest = tmp_path / "invalid_box.json"
    manifest.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="正面积"):
        load_cases(manifest)


def test_error_report_cannot_overwrite_broken_manifest(tmp_path, monkeypatch):
    """输入本身已损坏时，失败报告也不能覆盖它，保留原始内容供排查。"""
    manifest = tmp_path / "broken.json"
    manifest.write_text("invalid input", encoding="utf-8")
    monkeypatch.setattr(evaluate_detection, "parse_args", lambda: SimpleNamespace(
        manifest=manifest, model=tmp_path / "model.pt", output=manifest,
    ))
    assert evaluate_detection.main() == 1
    assert manifest.read_text(encoding="utf-8") == "invalid input"
