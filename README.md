# ViTrack：视觉目标检测与跟踪

目标是让手机采集画面，由电脑执行人物检测、跟踪和外观重识别。
完整需求见 `docs/ViTrack-视觉目标检测与跟踪-实施方案.md`，实际实施状态见 `PROGRESS.md`。
P0 环境准备和单图 GPU 检测已通过；尚无实时检测服务或手机页面，不能直接进行目标跟踪演示。
本机 CUDA Toolkit 13.3 保持不变，项目环境使用 PyTorch 自带的 CUDA 12.8 运行库。

本次验收：Python 3.11.17、torch 2.9.1+cu128，样例图中检测到 4 个人物。
检测图片在 `outputs/detection/test_detection.jpg`，单图数据在同目录的 `detection_report.json`。

`scripts/check_mirrors.ps1` 集中保存下载地址。镜像失效时优先修改该文件顶部的地址，
`setup_env.ps1` 和 `fetch_weights.ps1` 会读取同一份配置。

## 环境准备入口

在项目根目录打开 PowerShell，运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup_env.ps1 -InstallDependencies
```

这条命令先准备 Python 3.11 环境，再安装依赖、检查 GPU 运算，并生成依赖锁文件。
`ExecutionPolicy Bypass` 仅用于这次启动的 PowerShell 进程，不会修改电脑的全局执行策略。
如果只准备 Python 和 pip，不安装依赖，可以省略 `-InstallDependencies`。

如果 Miniconda 不在默认位置，添加实际的 Conda 路径，例如：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup_env.ps1 -InstallDependencies -CondaPath 'D:\Miniconda3\Scripts\conda.exe'
```

脚本会复用已经通过检查的项目环境，不向 `base`、`d2l-zh` 或 `uavloc` 安装依赖。
环境创建使用清华 Conda 镜像，失败后切换官方源；依赖安装先使用清华 PyPI，再尝试阿里云 PyPI。
Windows 普通 PyPI 包不一定支持 CUDA：脚本会实际检查，必要时安装官方 CUDA 12.8 构建。
实际使用的 CUDA 运行库由 PyTorch 包提供，不需要为了匹配它而更改本机 CUDA Toolkit。

## 单独复查环境

```powershell
& .\envs\vitrack\python.exe -I .\scripts\verify_env.py
& .\envs\vitrack\python.exe -I -m pip check
```

第一条命令检查 Python 版本、依赖导入、GPU 矩阵计算和 GPU NMS。
NMS 的用途是去除重复检测框；这里检查其 CUDA 扩展能否正常运行。
第二条命令检查已安装包之间的版本要求是否冲突。
通过环境检查不代表已经完成模型推理、摄像头接入或人物重识别验收。

检查结果保存在 `outputs/environment/environment_report.json`。
需要另存检查报告时，可给 `verify_env.py` 添加 `--output` 路径。

## 目录与文件职责

```text
homework3/
├─ AGENTS.md                 # 编程、注释和教学协作规则
├─ PROGRESS.md               # 实际完成情况、问题与下一步
├─ README.md                 # 本说明，当前只提供环境准备与复查入口
├─ requirements.txt          # 项目直接依赖与兼容版本范围
├─ requirements.lock.txt     # 成功验收后生成：实际安装的精确版本
├─ .gitignore                # 防止本机环境和生成结果混入源码提交
├─ scripts/
│  ├─ setup_env.ps1          # 环境准备入口
│  ├─ verify_env.py          # 环境检查入口
│  ├─ check_mirrors.ps1      # 统一下载地址与镜像连通性检查
│  └─ fetch_weights.ps1      # 最多三源下载 YOLO11n
├─ weights/yolo11n.pt        # 检测模型
├─ data/samples/test.jpg     # 官方单图样例，用于基础检测验收
├─ envs/vitrack/             # 运行时生成：独立 Python 环境
├─ work/                     # 运行时生成：下载缓存、临时文件和第三方配置
├─ outputs/environment/      # 运行时生成：环境检查结果
├─ outputs/detection/        # 运行时生成：单图检测图片和数据
└─ docs/                     # 原实施方案和后续项目说明
```

`envs`、`work` 和 `outputs` 不属于源码，不应放入最终课程源码压缩包。
`requirements.lock.txt` 会在完整环境检查通过后生成，记录本次真正安装的版本，方便以后复现。
锁文件内的官方 CUDA 附加索引用于获取带 `+cu128` 标记的 GPU 包。

## 模型与镜像准备

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_mirrors.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\fetch_weights.ps1
```

第一条命令只检查地址能否响应，不安装软件；网络状态会变化，HEAD 检查失败也不一定代表 GET 下载失败。
第二条命令按 GitHub 代理、备用代理、Hugging Face 镜像的顺序，最多尝试三个模型来源。
它先检查文件大小和 ZIP 文件头，下载完成才保存为 `weights/yolo11n.pt`。
这一步只是基础文件检查，仍须通过真实 YOLO 推理确认模型可用。

`data/samples/test.jpg` 来自所安装 Ultralytics 包内的 `assets/bus.jpg`，
用于单图检测验收，不属于自录的重识别实验数据，也不能用于证明重识别成功率。

## 初学者阅读顺序

先读本说明，了解运行命令和目录；再读 `setup_env.ps1`，最后读 `verify_env.py`。

`setup_env.ps1` 的输入是可选的 Conda 路径和安装依赖开关，输出是项目环境与验收结果。
主流程先计算项目路径，调用 `Assert-ProjectEnvironment` 检查已有环境；需要创建时再调用 Conda。
安装依赖后调用 `verify_env.py`，只有检查成功才输出锁文件。
循环负责按顺序尝试软件源；`try/finally` 保证临时环境变量在成功或失败后都被恢复。

`verify_env.py` 的 `main` 接收报告输出路径，调用 `collect_environment_report`。
后者导入依赖，比较 CPU 和 GPU 的矩阵计算结果，再检查重复框是否被正确去除，返回结果字典。
`main` 把字典转换为 JSON 文本并写入报告；检查失败时返回错误，不写出一份误称成功的新报告。

可以安全调整 `-CondaPath` 来匹配自己的安装位置，或调整 `--output` 来另存报告。
Python 3.11 以及 torch/torchvision 的对应版本暂时保持不变，避免破坏本项目已验证的兼容组合。

`check_mirrors.ps1` 加 `-GetSources` 时只返回地址字典，不发网络请求，供其他脚本使用。
不带该开关时，它循环检查各地址，并分别捕获错误，使一个失败的镜像不会中断其余检查。
`fetch_weights.ps1` 的 `Test-ModelFile` 接收文件路径，返回是否通过大小和 ZIP 文件头检查。
它用 `finally` 关闭文件，确保下载成功后能移动文件；主流程负责按来源顺序下载和保存。

若将来再次遇到官方大文件下载停滞，本次保留的官方 wheel 位于 `work/wheels`，可以作为本机离线恢复材料。
安装排错临时脚本和分段均位于 `work`，不作为课程源码提交。

在 VS Code 中执行“Python: Select Interpreter”，选择项目下 `envs\vitrack\python.exe`。
由于环境通过完整路径创建，不要假定 `conda activate vitrack` 可以定位到它；可直接使用上面的 Python 路径运行命令。
