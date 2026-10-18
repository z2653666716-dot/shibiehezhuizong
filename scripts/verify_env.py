"""检查 ViTrack 的依赖与 GPU，并将真实结果保存为 JSON。

属于 P0 环境准备：由 setup_env.ps1 调用，也可以单独运行。
不下载模型、不访问摄像头，因此通过本检查不等于整个项目已验收。
"""

import argparse
import importlib
import json
import os
from datetime import datetime, timedelta, timezone
from importlib.metadata import version
from pathlib import Path
import sys


def collect_environment_report() -> dict:
    """读取当前环境并实际执行 GPU 运算。

    输入：当前 Python 环境和已安装依赖；输出：可写入 JSON 的结果字典。
    由 main 调用；缺少依赖或运算错误时抛出异常，让调用脚本知道检查失败。
    """
    project_root = Path(__file__).resolve().parents[1]
    # 检查依赖时也不允许第三方库自动补装包，缺少依赖应明确报错。
    os.environ["YOLO_AUTOINSTALL"] = "false"
    # 把第三方库首次导入时产生的配置、缓存留在项目 work 目录。
    for variable, folder in {
        "YOLO_CONFIG_DIR": "ultralytics",
        "MPLCONFIGDIR": "matplotlib",
        "TORCH_HOME": "torch",
    }.items():
        cache_path = project_root / "work" / folder
        cache_path.mkdir(parents=True, exist_ok=True)
        os.environ[variable] = str(cache_path)

    if sys.version_info[:2] != (3, 11):
        raise RuntimeError("请使用项目 Python 3.11 环境运行检查。")
    if Path(sys.prefix).resolve() != (project_root / "envs" / "vitrack").resolve():
        raise RuntimeError("当前解释器不属于项目 envs/vitrack 环境。")

    # 安装成功不代表能导入：逐个导入实际要用的库，发现缺失 DLL 或版本冲突。
    modules = {
        "torch": "torch", "torchvision": "torchvision",
        "ultralytics": "ultralytics", "lap": "lap", "fastapi": "fastapi",
        "uvicorn": "uvicorn", "python-multipart": "python_multipart",
        "python-dotenv": "dotenv", "opencv-python": "cv2",
        "numpy": "numpy", "pillow": "PIL", "cryptography": "cryptography",
        "pytest": "pytest", "httpx": "httpx",
    }
    package_versions = {}
    for package, module in modules.items():
        importlib.import_module(module)
        package_versions[package] = version(package)

    import torch
    from torchvision.ops import nms

    if not torch.cuda.is_available():
        raise RuntimeError("PyTorch 尚不能使用 GPU，请检查 CUDA 构建和驱动。")

    # 同一组小整数矩阵分别在 CPU/GPU 计算，再比较结果，验证 GPU 确实完成运算。
    matrix = torch.arange(64, dtype=torch.float32).reshape(8, 8)
    expected = matrix @ matrix.T
    actual = (matrix.cuda() @ matrix.T.cuda()).cpu()
    torch.testing.assert_close(actual, expected)

    # NMS 会去掉重复检测框；验证 torchvision 的 CUDA 扩展，避免后续 YOLO 才报错。
    boxes = torch.tensor([[0, 0, 10, 10], [1, 1, 9, 9], [20, 20, 30, 30]],
                         dtype=torch.float32, device="cuda")
    scores = torch.tensor([0.9, 0.8, 0.7], device="cuda")
    kept = nms(boxes, scores, 0.5).cpu().tolist()
    if kept != [0, 2]:
        raise RuntimeError(f"GPU NMS 结果不符合预期：{kept}")
    torch.cuda.synchronize()

    device = torch.cuda.get_device_properties(0)
    return {
        "checked_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "python": sys.version.split()[0], "executable": sys.executable,
        "packages": package_versions, "cuda_available": True,
        "torch_cuda": torch.version.cuda,
        "gpu_name": device.name, "gpu_memory_mib": device.total_memory // (1024 ** 2),
        "matrix_max_error": (actual - expected).abs().max().item(),
        "gpu_nms_kept": kept,
        "scope": "环境与 GPU 运算检查；尚未验证模型推理、摄像头或重识别效果",
    }


def main() -> None:
    """读取输出路径参数，调用检查函数，保存报告并向终端显示结果。

    输入：命令行 --output 路径；输出：JSON 文件和简短状态。
    文件夹按需创建；检查抛出异常时不会写出一份误称成功的新报告。
    """
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="验证 ViTrack 依赖和 GPU")
    parser.add_argument("--output", type=Path,
                        default=project_root / "outputs/environment/environment_report.json")
    args = parser.parse_args()
    report = collect_environment_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"检查通过，报告已保存：{args.output}")


if __name__ == "__main__":
    main()
