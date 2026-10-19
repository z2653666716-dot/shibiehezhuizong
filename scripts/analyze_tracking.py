"""读取跟踪诊断文字，汇总“手势取消、请求拒绝、锁定后核验失败”等原因。

入口为本文件main；输入已有app.log及轮换文件，输出outputs/tracking/diagnostic_report.json。
只保留匿名编号、枚举和标量，不读取摄像头、不访问媒体、不改变匹配门槛。
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SAFE_FIELDS = {"event", "session", "seq", "track_id", "identity_id", "action", "reason", "code",
               "client_seq", "frame_age_ms", "ema_score", "frames", "required", "source", "hits", "gaps"}


def read_events(paths):
    """输入日志路径列表，输出去重的诊断字典；不接收任意嵌套数据或控制会话凭据。"""
    events, seen = [], set()
    for path in paths:
        with Path(path).open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                if "TRACK_DIAG " not in line or len(line) > 8192:
                    continue
                try:
                    raw = json.loads(line.split("TRACK_DIAG ", 1)[1])
                except (ValueError, TypeError):
                    continue
                if not isinstance(raw, dict) or not re.fullmatch(r"[a-f0-9]{12}", str(raw.get("session", ""))):
                    continue
                # 明确白名单，诊断工具也不能把意外混入的图片、向量或token复制到报告。
                event = {key: value for key, value in raw.items() if key in SAFE_FIELDS
                         and isinstance(value, (str, int, float, bool, type(None)))}
                if isinstance(raw.get("check"), dict):
                    event["check"] = {key: value for key, value in raw["check"].items()
                                      if key in {"accepted", "reason", "score", "anchor_score", "high", "color_min",
                                                 "margin", "appearance_score", "color_score", "nearest_other", "other_margin",
                                                 "best", "second", "body_score", "face_score", "face_quality", "mode",
                                                 "face_threshold", "body_threshold", "body_hold_threshold",
                                                 "other_body_score", "body_unique", "motion_ok", "observation_gap"}
                                      and isinstance(value, (str, int, float, bool, type(None)))}
                if isinstance(raw.get("client"), dict):
                    event["client"] = {key: value for key, value in raw["client"].items()
                                       if key in {"event", "seq", "track_id", "reason", "pointer"}
                                       and isinstance(value, (str, int, type(None)))}
                # 日志可能同时从轮换文件与终端副本读取，以原始行去重而不合并真实的重复操作。
                if line in seen:
                    continue
                seen.add(line)
                events.append(event)
    return events


def summarize(events):
    """输入按发生顺序排列的诊断，输出原因计数与锁定后失效链路；不把原因统计当识别准确率。"""
    counts, reasons, attempts, failures = Counter(), Counter(), {}, []
    for event in events:
        name, session = event.get("event"), event.get("session")
        counts[name] += 1
        if name == "client_gesture":
            client = event.get("client", {})
            if client.get("event") == "press_cancel":
                reasons["gesture_" + str(client.get("reason"))] += 1
        if name in {"lock_rejected", "photo_rejected", "candidate_reset", "candidate_rejected"}:
            reasons[str(event.get("code") or event.get("reason") or event.get("check", {}).get("reason"))] += 1
        if name == "identity_cleared":
            attempts = {key: value for key, value in attempts.items() if key[0] != session}
        if name == "lock_result":
            if event.get("action") == "locked":
                attempts[(session, event.get("track_id"))] = event
            else:
                attempts = {key: value for key, value in attempts.items() if key[0] != session}
        if name == "identity_confirmed":
            # 照片自动匹配和手动锁定都可能在后续姿态变化时失效，不能只关联手动请求。
            attempts[(session, event.get("track_id"))] = event
        if name == "identity_unbound":
            reason = event.get("check", {}).get("reason", "UNKNOWN")
            reasons[reason] += 1
            locked = attempts.pop((session, event.get("track_id")), None)
            if locked:
                failures.append({"session": session, "track_id": event.get("track_id"),
                                 "locked_seq": locked.get("seq"), "rejected_seq": event.get("seq"),
                                 "binding_event": locked.get("event"),
                                 "reason": reason, "check": event.get("check", {})})
    return {"events": dict(counts), "reasons": dict(reasons), "locked_then_rejected": failures,
            "scope": "diagnostic_events_not_identity_accuracy", "contains_media_or_vectors": False}


def main():
    """命令行输入日志和输出位置，打印简短计数；报告保留原因链路，默认不复制整份日志。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--logs", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/tracking/diagnostic_report.json")
    args = parser.parse_args()
    # 轮换编号越大越旧，按旧到新读取，再读当前文件，保证帧链路的时间顺序。
    paths = args.logs or sorted((ROOT / "outputs/logs").glob("app.log*"), reverse=True)
    report = summarize(read_events(paths))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(args.output), "events": report["events"], "reasons": report["reasons"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
