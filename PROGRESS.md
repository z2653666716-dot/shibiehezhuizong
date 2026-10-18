# ViTrack 实施进度

本文件记录已经实际完成的工作、验证结果和下一步，不把计划视为已完成。
需求依据：`docs/ViTrack-视觉目标检测与跟踪-实施方案.md`。
教学和协作方式：`AGENTS.md`。

## 当前状态

- 日期：2026-10-18。
- 当前大阶段：P0（环境与骨架）验收已通过，下一阶段为 P1。
- 已完成：项目规则、独立环境、项目依赖、GPU 实测、模型下载、镜像检查、单图 GPU 检测及当前需要的目录与说明文件。
- 当前可运行入口是 `scripts/setup_env.ps1` 和 `scripts/verify_env.py`；尚无业务服务入口、手机页面或实时跟踪。

## 已完成：保存项目规则

- 新增根目录 `AGENTS.md`，保存中文注释、初学者讲解、分里程碑暂停、目录分类、清晰命名和默认交付位置等要求。
- 已完整阅读实施方案；原文件保持不变。

## 已完成：基础环境检查

### 检查方式与实际结果

1. 使用 `C:\Users\mi\miniconda3\Scripts\conda.exe --version`：输出 `conda 26.7.1`。
2. 使用上述 Conda 的 `env list --json`：当前只有 `base`、`d2l-zh`、`uavloc`，没有 `vitrack`。
3. 使用上述 Conda 的 `info --json`：当前活动环境为 `base`，Python 版本为 `3.14.7`。
4. 使用 PowerShell `Get-Command python,git`：默认 Python 指向 `C:\Users\mi\miniconda3\python.exe`；Git 指向 `E:\Git\cmd\git.exe`。
5. 使用 `git --version`：输出 `git version 2.54.0.windows.1`。
6. 使用 `nvidia-smi --query-gpu=name,driver_version,memory.total,memory.free --format=csv,noheader`：
   - 显卡：`NVIDIA GeForce RTX 3060 Laptop GPU`。
   - 驱动：`616.56`。
   - 总显存：`6144 MiB`；本次查询空闲显存 `3682 MiB`，该数值会随其他程序运行变化。
7. 使用 `nvidia-smi`：命令正常，显示驱动报告的 `CUDA UMD Version: 13.4`。
8. 使用 `Get-PSDrive -PSProvider FileSystem`：E 盘剩余约 455 GiB，可用于后续环境、依赖和模型文件。
9. 前次执行 `git status --short`：项目还不是 Git 仓库；本轮未初始化仓库。

### 初次检查时的解释（后续结果见下方）

- Conda 和 Git 已具备，无需重新安装。
- 后续新建项目专用 Python 3.11 环境，不向现有 `base`、`d2l-zh` 或 `uavloc` 安装依赖。
- 驱动可以识别 GPU；尚未安装项目 PyTorch，因此不能宣称 `torch.cuda.is_available()` 为真。
- 初次检查未验证 Toolkit；本轮已补充运行 `E:\CUDA\bin\nvcc.exe --version`，确认 CUDA Toolkit 为 13.3（编译器 V13.3.73，`E:\CUDA\version.json` 中 SDK 为 13.3.1）。未重装或修改 Toolkit。
- 未修改全局 Conda 或 pip 配置，未安装任何软件包，未下载模型。

## 已完成：环境准备脚本

- 初版 `scripts/setup_env.ps1` 只负责创建或复用 Python 3.11 与 pip；本轮已扩展 `-InstallDependencies`，支持依赖安装、GPU 验收与生成锁文件。
- 环境位置为项目内的 `envs/vitrack`，缓存位置为 `work/conda/packages`，临时文件位置为 `work/temp`。
- 使用 `conda create --prefix` 指定位置，不使用默认 C 盘环境目录；运行后应直接调用 `envs/vitrack/python.exe` 或使用路径激活，不假定 `conda activate vitrack` 能找到该环境。
- 已有环境先验证 Python 版本、实际环境位置和 pip，检查不通过时停止，不自动覆盖或删除。
- 下载依次尝试清华 Conda main 镜像、官方 main 源，每个源一次；若出现部分安装的 Python，则停止并保留现场。
- 下载超时、缓存位置等仅通过进程环境变量临时设置，并在 `finally` 中恢复；不改写全局软件源配置。
- 脚本使用 UTF-8 BOM 保存，供当前 Windows PowerShell 5.1 正确读取中文注释与提示。
- 验证：保存前使用 PowerShell 5.1 的 `System.Management.Automation.Language.Parser.ParseInput` 解析完整源文本，退出码 `0`，输出 `PowerShell 5.1 syntax check passed; environment creation was not executed.`。
- 初版完成时尚未执行安装；本轮已执行创建、重复运行复用、完整依赖安装和实际 GPU 验收。未人为模拟全部失败分支。

## P0 验收清单

环境安装补充记录（已完成）：
- 用户已明确允许环境准备连续执行，无需逐步暂停，已同步到 `AGENTS.md`。
- 清华 Conda 镜像创建成功：Python 3.11.17；脚本再次执行成功复用环境。
- 清华 PyPI 的 torch 2.9.1 Windows 包大小约 111 MB，尚待安装后确认其 CUDA 能力。
- 方案中阿里云 PyTorch wheels 的 cu128/torch 路径探测返回 HTTP 404；官方 cu128 索引可访问，存在对应 Python 3.11 Windows 包。
- 如镜像构建无法使用 CUDA，改从官方 cu128 索引安装相同版本的 torch/torchvision；这是安装来源调整，不改变模型或技术栈。
- 普通 PyPI 构建安装完成后实际检查不能使用 GPU；官方索引的大文件连接随后停在约 52.5 MiB，已停止该项目下载进程。
- 用临时脚本 `work/download_torch.py` 从同一 PyTorch 官方来源分段下载，未更改系统代理。整包 SHA256 为 `633005a3700e81b5be0df2a7d3c1d48aced23ed927653797a3bd2b144a3aeeb6`，与官方索引一致；已从本地 wheel 安装成功。
- YOLO11n 已通过 ghfast 下载，大小 5,613,764 字节，已检查大小、ZIP 文件头并完成单图 GPU 推理。
- 镜像脚本运行结果：清华 Conda、清华 PyPI、阿里 PyPI、PyTorch CUDA、ghfast 均返回 200；HF 镜像 HEAD 检查未成功，状态 308，不能据此直接推断 GET 下载是否可用。

- [x] 检查 Conda、默认 Python、已有环境、Git、GPU 和磁盘空间。
- [x] 编写 Python 3.11 环境准备脚本并通过源文本语法检查。
- [x] 执行环境准备脚本，创建项目专用 Python 3.11 环境并验证重复执行可复用。
- [x] 安装项目依赖并实际验证 PyTorch CUDA。
- [x] 实现镜像可用性检查脚本并执行。
- [x] 下载 YOLO11n 权重并通过单图 GPU 检测验收。
- [x] 补充当前需要的目录、`.gitignore`、`requirements.txt` 和 `README.md`。
- [x] 初始化 Git；P0 阶段提交通过 `git log --oneline` 查看。

## P0 实际验收结果

- 完整安装入口：`powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/setup_env.ps1 -InstallDependencies`，最终退出码 0。
- Python：3.11.17；torch：2.9.1+cu128；torchvision：0.24.1+cu128；Ultralytics：8.4.182。
- 为避免后续 ByteTrack 首次运行时自动联网，已在依赖清单中加入并安装 `lap`（本次为 0.5.13）。尚未进行实时跟踪功能验收。
- `pip check` 输出 `No broken requirements found.`。
- `torch.cuda.is_available()` 为 True；GPU 为 RTX 3060 Laptop。
- CPU/GPU 矩阵结果最大误差为 0；GPU NMS 返回预期索引 `[0, 2]`。
- 环境报告：`outputs/environment/environment_report.json`；精确依赖版本：`requirements.lock.txt`。
- 单图验收等价于方案命令：`YOLO('weights/yolo11n.pt').predict('data/samples/test.jpg', device=0, imgsz=640, conf=0.35, classes=[0])`。
- 实际结果：4 个 person，检测结果位于 `cuda:0`；单次模型推理 15.2 ms。该数字不是稳定 FPS 或端到端延迟测试结果。
- 已查看标注图片，确认人物框已绘出。结果：`outputs/detection/test_detection.jpg`；结构化数据：`outputs/detection/detection_report.json`。
- 单图样例来自已安装 Ultralytics 包的 `assets/bus.jpg`，不是自建重识别实验素材。
- 模型 SHA256：`0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1`（本次文件指纹，不冒充官方公布摘要）。
- 原始安装与模型日志保存在 `work/`；环境、缓存和生成结果已由 `.gitignore` 排除，模型与样例图随源码记录。

## 下一里程碑

进入 P1，先编写 `app/config.py`，集中读取检测参数、路径和设备配置。
环境准备免逐步暂停的例外已执行完毕，业务代码恢复 `AGENTS.md` 的逐里程碑讲解与暂停要求。

## 尚未验证

- 持续运行时的 FPS、端到端延迟与资源占用。
- 摄像头、HTTPS、手机连通性、轨迹跟踪、锁定和重识别效果。
- 所有 P1～P7 功能与验收。
