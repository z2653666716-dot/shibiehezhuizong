"""用已知相似度验证标定统计含义，避免把误接率和漏接率写反。"""
from scripts.calibrate_reid import evaluate


def test_acceptance_rates():
    """0.8门槛时两组各接受一半；统计不能改变样本分数。"""
    rows = evaluate([0.7, 0.9], [0.6, 0.85])
    row = next(item for item in rows if item["threshold"] == 0.8)
    assert row["tar"] == row["far"] == 0.5
