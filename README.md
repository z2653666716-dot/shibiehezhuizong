# ViTrack：视觉目标检测与跟踪

目标是让手机采集画面，由电脑执行人物检测、跟踪和外观重识别。
完整需求见 `docs/ViTrack-视觉目标检测与跟踪-实施方案.md`，实际实施状态见 `PROGRESS.md`。
P0 已通过；P1 的 PC 人物检测闭环已通过本次授权实机验收，阶段源码保存在本地 Git。
页面已接通摄像头取帧、WebSocket、GPU 检测、白框叠加和真实指标；可开始/停止检测、切换方向与镜像。
本次约 36 秒内完成实机检查，30 秒计时窗口约 27.4 FPS；手机接入、跟踪、锁定、重识别和长时间稳定性仍待后续阶段。
本项目默认只检测人物；“person”类别结果不代表确认了具体身份。
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
├─ app/
│  ├─ main.py               # Uvicorn 加载的服务入口，包含路由和日志
│  ├─ __init__.py           # 应用代码包标识
│  ├─ config.py             # 配置读取与检查
│  ├─ schemas.py            # 检测数据和通信格式
│  ├─ detector.py           # 可复用的 YOLO 单帧检测器
│  └─ pipeline.py           # 帧解码、检测、结果组装与统计
├─ web/
│  ├─ index.html            # 浏览器入口，画面、状态、操作与日志诊断结构
│  ├─ style.css             # 深色主题、宽窄屏布局、视频叠层和诊断区样式
│  ├─ logger.js             # 浏览器错误记录、诊断区显示与日志导出
│  ├─ camera.js             # 摄像头授权、预览、尺寸同步与设备释放
│  └─ app.js                # 前端检测入口：取帧、WebSocket、指标与叠框
├─ AGENTS.md                 # 编程、注释和教学协作规则
├─ PROGRESS.md               # 实际完成情况、问题与下一步
├─ README.md                 # 环境准备、服务启动和模块阅读说明
├─ requirements.txt          # 项目直接依赖与兼容版本范围
├─ requirements.lock.txt     # 成功验收后生成：实际安装的精确版本
├─ .gitignore                # 防止本机环境和生成结果混入源码提交
├─ .env.example              # 可复制为 .env 的参数示例
├─ scripts/
│  ├─ setup_env.ps1          # 环境准备入口
│  ├─ verify_env.py          # 环境检查入口
│  ├─ verify_stream.py       # 仅用固定样例复核浏览器检测链路
│  ├─ check_mirrors.ps1      # 统一下载地址与镜像连通性检查
│  └─ fetch_weights.ps1      # 最多三源下载 YOLO11n
├─ weights/yolo11n.pt        # 检测模型
├─ data/samples/test.jpg     # 官方单图样例，用于基础检测验收
├─ envs/vitrack/             # 运行时生成：独立 Python 环境
├─ work/                     # 运行时生成：下载缓存、临时文件和第三方配置
├─ outputs/environment/      # 运行时生成：环境检查结果
├─ outputs/detection/        # 运行时生成：单图检测图片和数据
├─ outputs/pipeline/         # 运行时生成：帧处理集成验证报告
├─ outputs/validation/       # 运行时生成：不访问隐私设备的样例流报告
├─ outputs/logs/             # 正式运行时生成：运行日志与错误堆栈
├─ outputs/server/           # 服务验证报告与隔离保存的模拟错误日志
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

## P1 配置模块

`app/__init__.py` 标识应用代码包，`app/config.py` 提供只读的 `AppConfig` 和配置读取入口 `load_config()`。
配置来自内置默认值、项目根目录 `.env` 和进程环境变量，优先级依次提高。
程序不会自动复制示例；需要修改参数时，将 `.env.example` 复制为项目根目录 `.env` 后再修改。

`load_config()` 先读取文件并检查参数名，然后按优先级选取文本值，交给 `AppConfig` 转换类型和检查。
例如 `.env` 中的 `DET_CONF=0.5` 会变成浮点数，`TARGET_CLASSES=0,2` 会变成整数元组 `(0, 2)`，留空则表示全部类别。
这里的元组可理解为不能直接增删元素的类别清单，避免后续模块意外改变共享设置。

`AppConfig` 的以下方法由 Pydantic 自动调用，业务模块无需自己依次调用：

- `resolve_project_path`：把相对模型、证书路径转换为项目内的绝对路径，不要求文件当前已存在。
- `parse_device`：把 `cpu` 或 GPU 编号转换为检测器能接收的值；不在配置阶段启动 GPU。
- `parse_classes`：把逗号分隔的类别文本拆开，之后由字段类型检查转换为整数。
- `check_relationships`：检查尺寸是否为 32 的倍数、类别是否有效，以及阈值和权重之间的关系。

后续应用入口读取一次配置，再把同一个对象传给检测器、流水线等模块。
业务服务入口为 `app/main.py`；跟踪、重识别和录制在后续阶段实现。
完整源文本已通过运行检查，已保存文件的实际包导入也已通过，未因此加载 PyTorch。

建议按 `.env.example` → `app/config.py` 中的 `AppConfig` → `load_config` → 校验方法的顺序阅读。
可先调整 `DET_CONF`（提高会过滤低置信度目标）、`DET_IMGSZ`（较小更省计算）、
`TARGET_CLASSES`（0 为人物，留空为全部类别）和 `DET_DEVICE`（cpu 或 GPU 编号）。
这些参数将在后续检测器接入配置后影响推理，不会改变此前已保存的 P0 检测图片。

## P1 数据格式模块

`app/schemas.py` 定义后续模块交换数据时使用的格式；当前不包含检测算法或网络端点。
`DataModel` 是共同基础：检查未知字段，拒绝 NaN/无穷大，并启用字段赋值检查。
`Annotated` 为数字附加范围约束，`Literal` 为消息类型或状态限定可选字符串。

- `Detection`：接收类别编号 `cls`、名称、置信度和像素坐标 `xyxy`，供未来检测器输出和内部裁剪使用。
- `Box`：接收相同的检测信息，但坐标必须为 0～1 的比例，可携带轨迹和身份状态，供前端绘制。
- `IdentitySummary`：身份编号、名字、缩略图地址、在线状态，供未来身份条显示；不包含内部特征向量。
- `FrameMessage`：浏览器发送的帧序号、毫秒时间戳、图片尺寸和 Base64 文本。图片解码与实际尺寸核对属于后续流水线。
- `FrameResult`：把帧序号、FPS、服务端处理耗时、目标框和身份摘要组合为一条返回消息。
- `ErrorResponse`：接收错误码和中文提示，生成 `ok=false`、`code`、`message` 这一统一格式。

两种框中的 `check_coordinates` 检查左小于右、上小于下，防止颠倒或零面积的框。
`Box.check_state` 检查状态关系：locked 必须有身份编号；candidate 尚未绑定身份；
candidate 与 locked 都要有轨迹编号。短按 selected 属于前端本地显示状态。
这些方法由 Pydantic 自动调用，不需要业务代码手动依次执行。

未来流水线调用 `Box.from_detection(detection, width, height)` 完成单位转换。
例如原图宽 400、高 500，像素坐标 `(100, 50, 300, 250)` 会变成 `(0.25, 0.1, 0.75, 0.5)`。
方法中的循环依次把四个比例限制到 0～1；前端再乘自己的画布尺寸，得到实际绘制位置。
完全在画面外的框无法得到正面积，会被拒绝，避免绘制无意义的框。

`FrameResult` 使用 `Field(default_factory=list)`，让每个结果对象有自己的框列表和身份列表。
后续服务可通过 `model_dump_json()` 把完整结果转换为 JSON，前端读取坐标数组；
`model_validate_json()` 用于把收到的 JSON 转成经过检查的数据对象。
`latency_ms` 是服务端处理耗时，端到端延迟还需在后续手机联调中另行测量。

阅读顺序建议：`Detection` → `Box.from_detection` → `FrameMessage`/`FrameResult` → 身份和错误格式。
字段名属于前后端共同约定，日常调参仍在 `.env` 中完成。
数据格式模块的完整源文本检查和已保存文件的实际导入均已通过，坐标转换与 JSON 往返正常。

## P1 单帧检测模块

`app/detector.py` 提供 `Detector`，供未来的流水线使用。创建一个实例后可重复处理多张图像，
避免每帧重新加载模型。服务入口 `main.py` 负责调用流水线，摄像头采集和跟踪按后续阶段实现。

`Detector.__init__(config)` 接收 `AppConfig`，依次检查本地 .pt 权重、准备缓存目录、
探测所选设备，再加载模型。找不到权重时直接提示文件路径；选用 GPU 时检查其可用性与编号。
日志记录 CUDA 能力和实际选择的设备，CPU 模式也会明确显示。
仅导入本模块不会初始化模型，真正创建 Detector 时才导入 PyTorch 和 Ultralytics。

`Detector.detect(frame_bgr)` 接收 OpenCV 图像数组：形状为 `(高度, 宽度, 3)`，
像素类型为 `uint8`。BGR 表示数组中的三个通道依次是蓝、绿、红，通常由 `cv2.imread` 或摄像头读取产生。
函数先检查输入，再调用模型的 `predict`，返回 `Detection` 列表；没有目标时返回空列表。
翻转或切片可能产生非连续存储，`np.ascontiguousarray` 会在需要时整理它。

预测结果中的坐标、置信度和类别原本可能位于 GPU。`detach().cpu().tolist()` 将它们转为普通 Python 数字：
先脱离计算梯度的记录，再搬到 CPU，最后转换成列表，供 Pydantic 数据对象使用。
循环按相同索引取出这三组字段，`zip(..., strict=True)` 会在长度不一致时报告错误，避免错配。
框的右边必须大于左边、下边必须大于上边；没有面积的退化框会被跳过。

当前模块协作顺序是：`load_config()` → 创建 `Detector(config)` → `detect(图像)` → `Detection` 列表。
下一步流水线将使用 `Box.from_detection` 进行归一化，并将框放入 `FrameResult`。
建议按 `Detector.__init__` → `detect` 的输入检查 → `model.predict` → 结果转换循环的顺序阅读。

检测参数统一调整 `.env`：`DET_CONF` 控制过滤置信度，`DET_IMGSZ` 控制模型输入尺寸，
`TARGET_CLASSES` 控制类别范围，`DET_DEVICE` 选择 CPU 或 GPU；`DET_IOU` 越低，越容易去除重叠框。
实例读取配置后，需要由后续应用重建实例或重启服务，新的配置才会生效。

本轮保存前真实 GPU/CPU 检查通过：默认 GPU 检测到 4 人；CPU 全类别检测包含人物与公交车；
空白图、翻转图和错误输入检查均通过。记录位于 `outputs/detection/detector_module_report.json`，
其中也保存了本次 Detection 数据和归一化框；它与 P0 的原始单图验收报告分开保存。
已保存检测器的实际包导入与 GPU 调用均已通过，样例中返回 4 个人物检测。

## P1 帧处理流水线

`app/pipeline.py` 将已有模块串成完整的单帧处理过程，`app/main.py` 的 WebSocket 路由负责调用它。
未来应用启动时创建 `Pipeline(detector)`，传入已经加载的检测器，避免重复加载权重。
`latest_result` 保存最近一次成功结果，`processed_frames` 记录成功完成的帧数，供后续健康接口读取。

主要入口与内部函数：

- `process_message(message)`：接收 FrameMessage，异步返回 FrameResult，供未来 WebSocket 接口调用。
- `process_frame(frame_bgr, seq)`：接收 BGR 数组和帧号，返回同样的结果，供后续摄像头读取流程调用；本方法自身不读取摄像头。
- `_run(source, seq)`：两个入口共用的后台核心，按顺序解码或接收图像、检查图像、调用 Detector、归一化、组装和统计。
- `_decode_message(message)`：检查 Base64，读取 JPEG 头部，核对尺寸，再用 OpenCV 得到 BGR 数组。
- `_check_frame(frame)`：检查类型、通道、非空及尺寸限制，通过时不返回数据，失败时抛出中文错误。
- `PipelineError(code, message)`：保存错误码与提示；`to_response()` 转成 ErrorResponse，由未来接口负责发送。

以 `_` 开头的方法供模块内部使用。建议先读两个公开入口，再顺着 `_run` 看解码和结果组装。
输入消息中的 `seq` 会原样放进结果，帮助前端知道结果属于哪一帧。
客户端时间戳 `ts` 不参与服务端耗时计算，因为手机和电脑的时钟未必同步。

异步代码中的 `await asyncio.to_thread(...)` 把耗时工作放到后台线程，等待时事件循环仍可处理其他请求。
真正的工作由线程锁依次放行，同一个检测器一次只处理一帧。
取消请求只能停止调用方等待，已经开始的后台推理仍会完成；线程锁持续生效，下一帧不会提前与它同时调用模型。
本次已用慢检测模拟和取消测试验证这一点。

JPEG 头部使用 Pillow 的专用 JpegImageFile 解析器，像素使用 cv2.imdecode 解码。
选择专用解析器可避免 Ultralytics 接管 Image.open 后为损坏图片尝试额外格式插件。
Detector 初始化前会关闭 YOLO_AUTOINSTALL，依赖安装由 setup_env.ps1 统一负责。

统计含义：第一帧 FPS 为 0，之后使用最近成功完成帧之间的实际时间间隔；空白图处理成功也会计入帧数。
`latency_ms` 从获得处理锁后开始，包含解码、检测和结果组装，不包含等待锁的时间、网络或手机绘制。
第一帧可能包含 GPU 初始化成本。本轮首帧约 3 秒，实时 FPS 和端到端延迟仍需后续联调实测。

常用检测参数仍在 `.env` 中设置。流水线顶部另有三个容易理解的限制：
`MAX_JPEG_BYTES` 默认为 4 MiB，`MAX_FRAME_SIDE` 默认为 4096；调大可接受更大输入，也会增加内存和处理开销。
`FPS_WINDOW` 默认为 30，保持为至少 2 的整数；窗口较大时帧率显示更平稳、反映变化也更慢。

集成结果保存在 `outputs/pipeline/frame_pipeline_report.json`，记录 Base64/JPEG 路径、直接图像路径及取消并发检查。
它与 `outputs/detection` 中只验证检测器的报告按功能分开保存。
流水线完整源文本集成检查和已保存模块的实际调用均已通过，GPU 样例返回 4 人。

本轮还修正了依赖锁文件的可移植性：用包版本号记录安装结果，避免依赖原电脑的 `work/wheels` 路径。

## P1 服务入口与日志

入口文件为 `app/main.py`，其中的 `app` 是交给 Uvicorn 运行的 ASGI 应用对象。
在项目根目录运行以下命令，可选择本机调试地址 8000；P2 再加入手机 HTTPS 启动流程。

```powershell
& .\envs\vitrack\python.exe -X utf8 -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

当前可检查 `http://localhost:8000/api/health` 和 `http://localhost:8000/api/logs`。
`/` 与 `/pc` 返回 `web/index.html`，加载前端入口 app.js；点击“开始检测”后请求当前设备的摄像头，准备好再连接电脑检测服务。
页面上的服务端日志链接可以直接使用，其余待接入按钮保持禁用。
新增 web 目录后须重新启动已有服务，才能注册 `/static` 路由。
当前服务仅接入 SOURCE=ws；P2 才实现 IP 摄像头读取，不能仅改配置就认为该功能已完成。

服务模块的阅读顺序：

1. `create_app(config)` 接收可选配置，输出 FastAPI 应用并注册路由；`app = create_app()` 提供加载入口。
2. `lifespan(application)` 由框架在启停时调用，先配置日志，再读取设置和在线程中加载模型；到 `yield` 时交给框架处理请求，停止时记录结束状态。
3. `stream(websocket)` 接收一条连接，循环读取文本，检查消息并调用 `Pipeline.process_message`，将结果转换为 JSON 返回。
4. `health` 返回现有设备与帧统计；`page` 返回后续页面文件；`logs` 和 `download_log` 分别提供日志列表与文件下载。

以 `@application.get`、`@application.websocket` 标记函数，是把函数注册到相应地址，随后由框架调用。
`request_log(request, call_next)` 是所有 HTTP 路由外层的处理函数：生成编号，调用下一层，记录响应状态与耗时。
`http_error` 接收 HTTP 异常并返回统一中文 JSON，`validation_error` 将 HTTP 参数问题转换为 422 响应。
未预期的 HTTP 异常和帧处理异常会记录完整堆栈，便于查看具体文件与行号。

日志辅助部分：

- `configure_logging()` 创建 UTF-8 文件和轮换处理器，并将本应用的日志接入终端与文件。
- `LogContextFilter.filter(record)` 接收日志记录，附加当前请求/连接编号和帧号。
- `error_body(code, message)` 返回统一错误字典，同时将可搜索的日志编号附在中文提示中。
- `log_files()` 返回当前存在的已知日志路径，供列表和下载接口共用。
- `read_log_snapshot(name)` 接收允许的日志名，短暂锁住对应日志处理器，返回固定的文件字节副本，供下载接口使用。

正式运行日志位于 `outputs/logs/app.log` 与 `errors.log`。前者记录运行摘要，后者记录 ERROR 及以上事件和异常堆栈。
所有时间使用北京时间。HTTP 响应的 `X-Request-ID` 与日志中的 `request=` 相同；
WS 错误提示带连接日志编号和帧号，对应 `request=` 与 `seq=`，搜索它们即可串起出错过程。
日志不保存 Base64、整帧 JPEG 或特征向量。

日志列表地址为 `/api/logs`，下载地址例如 `/api/logs/errors.log`。
默认每份文件达到约 5 MiB 后轮换，保留 `.1`～`.3`；日志列表也会包含存在的历史备份。
可以调整顶部 `LOG_MAX_BYTES` 与 `LOG_BACKUP_COUNT`，保持正整数；文件上限或备份数量越大，占用空间越多。
`LOG_LEVEL=logging.INFO` 为日常摘要，改成 `logging.DEBUG` 并重启可在文件中记录每帧元信息。

用户已要求最终 App 提供日志功能：后续页面必须加入诊断区域，显示近期浏览器/摄像头/网络错误与日志编号，
支持导出前端记录和下载服务端日志。浏览器日志模块和服务端接口现已具备，真实摄像头、网络与接口错误的业务接入仍须联调。

保存前服务源文本通过 14 类 ASGI 检查，GPU 帧返回 4 人；包括异常堆栈、关联编号、UTF-8 下载和轮换。
报告位于 `outputs/server/server_module_report.json`；模拟错误日志单独保存在 `outputs/server/validation_logs`，
其中 intentional_server_log_test 和 intentional_http_log_test 是验证时主动制造的错误，不代表正式运行故障。
上述 14 类检查为此前的进程内检查；本轮已实际启动磁盘服务并完成 HTTP/WebSocket 检查。

### 正在写入的日志如何下载

真实 TCP 检查发现：原来的 FileResponse 会先获取文件长度，稍后才发送内容；
中间的请求日志继续写入文件，会使实际发送长度大于 Content-Length，导致下载中断。
现改为固定内容的快照下载，下载地址保持不变：

1. `download_log(name)` 调用 `await asyncio.to_thread(read_log_snapshot, name)`，将读取放进后台线程，避免文件读取占住异步事件循环。
2. `read_log_snapshot` 找到对应的轮换日志处理器，持有其锁，检查文件白名单并读取字节；退出 `with` 后自动释放锁。写日志和轮换也使用这把锁，因此复制期间文件内容和名称保持稳定。
3. `Response(content=...)` 根据这份固定字节计算长度，作为附件发送。之后文件继续增长也不会影响本次下载；`Cache-Control: no-store` 避免浏览器缓存旧日志。
4. 文件不存在返回带日志编号的中文 404；日志处理器尚未就绪返回 503。文件名、下载范围和历史数量仍由既有规则限制。

副本只代表复制时刻已有的日志；本次“日志下载”事件在复制完成后写入，因此会在后续下载中出现。
读取当前日志或历史日志均共用对应日志组的锁；锁内不记录新日志，避免不同处理器互相等待。

修复后的完整待保存源文本已启动真实 Uvicorn 服务验证：GPU 返回 4 人、坏帧关联和恢复通过；
12 次写入期间下载、24 次轮换期间下载，以及 3 份历史日志下载均完整且 UTF-8 可解码。
验证时临时使用 32 KiB 轮换以覆盖轮换场景，正式配置仍为每份 5 MiB、3 个历史备份。
报告：`outputs/server/server_transport_report.json`。
首次发现故障的日志保存在 `outputs/server/transport_failure_logs/`；
修复验证日志位于 `outputs/server/transport_validation_logs/`，未混入正式日志目录。
验证专用写日志/调整轮换接口只存在于临时验证进程，没有加入项目源码；两个验证服务均已停止。
上述下载修复本轮已从磁盘实际启动复核：连续 10 次日志下载通过，内容长度与中文 UTF-8 完整，errors.log 为空。
报告为 `outputs/server/saved_download_report.json`；验证日志隔离在 `outputs/server/saved_download_logs/`。
该次验证服务已停止。浏览器摄像头、手机或实时帧率仍未验收。

## P1 浏览器页面结构

`web/index.html` 是前端入口，由 `app/main.py` 的页面路由读取并返回给浏览器。
页面结构由 HTML 定义，加载本地样式与 module 脚本；app.js 导入 camera.js，接通取帧、传输、结果绘制。
它没有业务函数；HTML 元素的 id 是后续脚本查找、更新页面的位置，class 供后续样式统一控制外观。

建议按以下顺序阅读各区域：

1. `page-status`：说明当前可用范围，不把未连接状态显示成正在检测。
2. `camera-stage`：容纳 camera-video 与 detection-overlay。camera.js 管理视频与尺寸，app.js 绘制后端返回的检测框；停止时清掉旧框。
3. `detection-metrics`：显示帧率、电脑处理耗时、结果数量、画面尺寸与最近帧号。初值 -- 表示尚无数据；后续由服务结果更新。处理耗时不等于端到端延迟。
4. `controls-section`：预览模块按实际状态启用开始、停止、摄像头方向与镜像设置；录制仍禁用。fieldset 的 disabled 一次禁用组内控件。
5. `identity-section`：独立的空状态提示与身份列表，等待后续锁定和照片注册功能填入真实身份。
6. `diagnostics`：浏览器原生 details/summary 提供展开收起；包含最近错误、服务端日志编号、出错帧号、前端日志列表与导出按钮，以及已可使用的服务端日志和健康信息链接。

video 的 muted、playsinline、autoplay 分别表示静音、尽量在手机页面内播放、允许自动播放；
这些属性本身不会请求摄像头权限，真正取流由 camera.js 在用户点击后完成。
canvas 初始尺寸与 video 一致；后续会按视频真实尺寸同步，并由 CSS 叠放。
aria-labelledby/aria-describedby 将区域或控件与其中文说明关联，帮助辅助阅读工具理解页面。
高频变化的帧率没有设为实时播报，避免逐帧重复朗读。

当前能直接使用的入口为 `/api/logs/app.log`、`/api/logs/errors.log`、`/api/logs` 和 `/api/health`。
浏览器错误记录、导出和清空已完成源文本浏览器验证；实际摄像头、WebSocket 和 API 错误仍需后续业务模块调用日志入口并联调。

可以安全修改页面标题、中文提示文字，以及 details 的 open 属性（保留时默认展开，删除时默认收起）。
暂时保持 id、日志链接、禁用状态及视频/画布尺寸一致，后续交互和坐标绘制会依赖这些约定。

此前页面结构里程碑保存前检查源文本：125 个元素、53 个唯一 id，标签配对、关联说明、锚点、
初始状态、禁用控件和日志链接检查通过；临时副本通过现有 FastAPI 的 /、/pc、/static/index.html 路由返回，
状态为 200，内容与字节长度正确。临时副本已自动清理，未安装额外依赖。
报告为 `outputs/web/page_structure_report.json`；该结果不是浏览器渲染、摄像头或前端日志验收。
已保存页面本轮通过现有 /、/pc、/static/index.html 路由复核，报告为 `outputs/web/saved_page_report.json`。

## P1 页面样式

新增 `web/style.css`，index.html 在 head 内使用 link 加载它，并将诊断子区域包在 diagnostic-grid 中。
本轮只修改布局和外观，不启用待实现按钮，不编写摄像头或日志业务逻辑。后端代码没有改动。

CSS 没有业务函数。浏览器读取规则，按选择器找到元素，再结合窗口宽度、元素属性和系统偏好计算显示效果。
例如 `#camera-video` 找到 id 为 camera-video 的元素；`.camera-stage` 找到对应 class 的容器。

建议按文件中的中文编号阅读：

1. `:root` 保存主题颜色、页面宽度和圆角。全局 border-box 让边框与内边距计入宽度；`[hidden]` 保持隐藏优先级，防止后续 display 规则意外显示空视频或画布。
2. 主布局使用 Grid，桌面左侧画面、右侧操作与身份，诊断区占满一行；minmax(0, 1fr) 允许内容收缩，避免长文字撑宽页面。
3. camera-stage 使用相对定位；video 宽度随容器、高度保持自身比例；canvas 使用绝对定位覆盖同一区域。只有等待提示使用 16:9，真实视频可横可竖，不强制裁切。
4. 指标、操作按钮和身份空状态统一间距。控件高度至少 44px；禁用外观仍保持文字可辨认。连接状态样式预留 data-state 属性，后续脚本按真实状态设置。
5. diagnostic-grid 将诊断内容分组；长编号与错误文本换行，前端日志列表超过 240px 可内部滚动。诊断折叠仍使用浏览器原生功能。
6. 900px 以下改为单列，480px 以下减小边距并让指标换行；键盘焦点有明显边框，系统选择减少动态效果时关闭平滑滚动和按钮过渡。

可安全调整 `--accent`（强调色）、`--page-bg`/`--panel-bg`（背景色）、`--radius`（圆角）和
`--page-width`（桌面最大宽度）；颜色变化应继续保证文字清楚。日志列表的 max-height 决定出现内部滚动的高度。
暂时保留视频与画布的尺寸、定位关系，以及 hidden 规则，后续坐标绘制会依赖它们。

保存前在 work 临时目录提供完整待保存 HTML/CSS，通过现有 FastAPI 路由和本机 Edge 无界面浏览器验证：
1365、768、390、320px 宽度无横向溢出，宽屏并排/窄屏纵排正确；
640×360 与 360×640 的视频尺寸属性场景中画布均对齐；
长错误、4096 字符编号、滚动日志、200% 根字号、键盘导航、原生折叠和减少动态效果检查通过。
该视频检查验证的是布局，不是实际摄像头采集。临时预览服务、浏览器已停止，临时文件已自动清理。

报告为 `outputs/web/style_preview_report.json`，已查看的预览截图为
`outputs/web/style_desktop_preview.png` 与 `outputs/web/style_mobile_preview.png`。
截图只显示真实初始状态，没有伪造检测画面或已连接状态。无界面 Edge 自动请求 favicon.ico 得到 404，不影响页面与样式加载。
手机浏览器、实际摄像头、检测叠框和前端日志功能仍待验收。
已保存样式本轮通过页面与静态资源路由复核，报告为 `outputs/web/saved_style_report.json`。

## P1 浏览器日志

新增 `web/logger.js`，由 index.html 的 `script type="module"` 加载。
模块创建共享的 logger 并启动诊断区；后续 app.js 可导入同一实例，不会重复初始化。
日志导出/清空按钮按记录数量启用；摄像头由 camera.js 管理，照片和录制仍未开放。

模块按以下顺序阅读：

1. `beijingTime(date)`：将日期转成带 +08:00 的北京时间，页面与导出统一使用。
2. `cleanText(value, limit)`：输入文字和长度上限，输出清理后的文字；省略数据地址与长编码，移除网址账号、密码、查询参数和片段，避免无意记录图片正文。
3. `BrowserLogger`：构造时创建空记录列表、流水编号与初始化状态；导出的 logger 是页面与后续模块共享的实例。
4. `start()`：查找诊断元素、绑定按钮，监听脚本错误、未处理 Promise、资源加载失败及浏览器网络状态事件；重复调用不增加监听。网络状态只代表浏览器报告，不等同于服务端已连通。
5. `record(level, message, context)`：接收 info/warn/error、中文说明和少量元信息，返回日志副本；只保留白名单字段，从服务器提示中提取日志编号和帧号，再保存、裁去旧记录并调用 render。
6. `captureError(message, error, context)`：接收 Error、DOMException 或文字原因，提取名称、说明和可用堆栈，然后交给 record；供未来摄像头与接口的 catch 分支调用。
7. `render()`：把最近日志变成文字节点插入列表，更新最近错误、编号、帧号及按钮状态。使用 textContent，不把错误内容当 HTML 执行。新错误没有编号时显示无关联编号，不借用旧错误的信息。
8. `getLogs()`：返回按时间顺序排列的记录副本；修改副本不会改变内部记录。页面列表按最新在前显示。
9. `clear()`：清空本页内存、更新空状态，不删除服务端文件。
10. `exportLogs()`：将当前记录、导出时间、浏览器信息和页面路径组成 JSON，使用 Blob 与临时下载链接触发浏览器下载，返回建议文件名；失败时记录中文错误，临时地址稍后释放。

后续调用示例：

```javascript
import { logger } from "/static/logger.js";

// 捕获摄像头异常时，传中文说明、异常对象和来源；不要传图像或整个请求。
logger.captureError("无法打开摄像头", error, {
  source: "camera",
  code: "CAMERA_OPEN_FAILED",
});
```

示例中的 error 来自调用方的 catch 分支；camera.js 已在预览失败时接入此入口。
接口模块可使用 `logger.record("error", response.message, {source: "api", code: response.code})`，
服务器提示中的“日志编号”和“帧号”会自动提取；也可通过 traceId、seq 明确传入。
其他可用字段为 file、line、column、errorName、stack；未列出的请求正文、图片或特征字段被忽略。

安全调整参数位于文件顶部：MAX_ENTRIES=200 控制内存条数，MAX_VISIBLE=50 控制页面显示条数；
增大会保留或显示更多记录，也会增加内存和页面更新开销，建议保持显示数不大于保存数。
MAX_MESSAGE_LENGTH=600、MAX_STACK_LENGTH=4000 限制每条文字长度，减小会丢失更多排查细节。
日志不持久化，刷新页面后清空；导出文件名为 browser_logs_日期_时间.json，保存位置由浏览器下载设置决定。

保存前用完整待保存模块与 HTML、已保存 CSS，在本机 Edge 中完成实际验证：
模块加载与重复启动、中文 DOMException、服务器编号/帧号提取、超长提示、HTML 文字显示、
图片编码省略、网址清理、真实脚本异常、真实未处理 Promise 和实际资源 404 均通过。
离线/恢复事件使用合成事件验证监听入口，不代表已经断开实际网络。
205 条容量检查保留 200 条、显示 50 条；清空后为空且导出禁用；getLogs 副本不影响内部记录。

已实际点击导出按钮并读取浏览器下载的 UTF-8 JSON，验证北京时间、日志内容和编号；
临时下载地址按时释放；模拟导出失败被记录并显示。390px 诊断区无横向溢出。
报告为 `outputs/web/logger_preview_report.json`，初始正常界面截图为 `outputs/web/logger_diagnostics_preview.png`。
`outputs/web/logger_export_sample.json` 是含两条主动构造错误的导出示例，不代表真实摄像头/API 故障。
测试用模块副本、测试脚本、浏览器和临时服务均已清理或停止，没有将模拟错误混入正式服务端日志。

## P1 摄像头预览

新增 `web/camera.js`，由 index.html 加载；模块准备控件但不自动请求摄像头。
camera.js 的预览阶段最初使用“开启预览/停止预览”；现由 app.js 将按钮设为“开始检测/停止检测”。
点击后请求当前设备的视频，不采集音频；视频准备好后连接后端检测。停止会关闭视频流与检测连接。

在项目根目录启动已有后端，再用电脑浏览器打开 http://localhost:8000/pc：

```powershell
& .\envs\vitrack\python.exe -X utf8 -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

允许浏览器访问摄像头后即可预览；手机 HTTPS 接入仍安排在 P2。

建议按以下顺序阅读：

1. `CameraError` 保存中文提示、错误码和原始原因；`cameraFailure(error)` 将权限拒绝、无设备、设备占用等异常转换成统一提示。
2. `Camera(video, overlay)` 接收视频/画布元素，初始化 idle 状态、流、取消控制器和请求编号。导出的共享 camera 供页面与未来检测模块复用。
3. `start(options)` 检查方向、尺寸、安全上下文和浏览器能力，关闭旧预览，再调用 getUserMedia。取得流后等待播放成功和实际第一帧，返回真实宽高并发出 started 事件。
4. `waitForVideo(video, signal)` 使用 Promise 等待加载/尺寸事件与播放完成；超时或取消时清理计时器和监听。await 让调用方等待结果，不阻塞浏览器处理“停止”按钮。
5. `stop()` 让旧请求编号失效、取消等待，通过 closeStream 停止所有轨道，清空视频来源和画布；重复调用安全。getUserMedia 本身不能通用取消，迟到的流会检查编号并立即释放。
6. `syncSize()` 读取 videoWidth/videoHeight，同步 video 属性和 canvas 像素尺寸；尺寸改变时发出 resize，供后续叠框模块使用。更改 canvas 尺寸会清掉旧框。
7. `setMirrored(enabled)` 只翻转视频显示，并保存 mirrored 状态；传给模型的原图方向不变。后续绘框需据此转换横坐标，标签文字保持正向。
8. `bindCameraPage(camera)` 将按钮、方向与镜像选择接到实例；通过 statechange 更新禁用状态、空画面与提示，通过 started/resize 更新尺寸。离开页面 pagehide 时停止设备。

模块使用 EventTarget/CustomEvent 发布 started、stopped、resize、mirrorchange、statechange、ended 事件；
app.js 监听这些事件接入 WebSocket，不需要重复实现设备管理。
取消或后发请求不会让早先返回的流覆盖新预览；权限请求取消后，浏览器自身的权限提示可能仍需用户关闭，
但即使稍后允许，过期流也不会重新显示或继续占用设备。

安全调整项：PREVIEW_WIDTH=1280、PREVIEW_HEIGHT=720 是期望预览尺寸，使用 ideal，实际值由设备决定；
增大可能提高画面细节和传输前缩放开销。READY_TIMEOUT_MS=12000 控制取得流后等待播放与第一帧的期限，
不限制用户阅读授权提示的时间。保留请求编号、轨道释放与画布尺寸同步逻辑。

保存前使用完整待保存源码，在 Edge 内置合成摄像头上完成实际 getUserMedia/播放检查：
默认返回 1280×720、画面非空、无音轨；启动/停止、方向切换、镜像、模拟尺寸改变均通过。
延迟授权后取消、旧请求晚于新请求返回、权限拒绝、无设备、占用、播放失败与超时都按预期退出并释放轨道。
设备 ended 与 pagehide 通过合成事件检查，390px 宽度无横向溢出。该模块初次验证时尚未进行实机测试；后续 PC 授权测试结果见本文末节，手机仍待实测。

报告：`outputs/camera/camera_preview_report.json`；
截图：`outputs/camera/camera_preview.png`，其中绿色图案是浏览器生成的合成画面，不是实际摄像头拍摄。
临时源码副本和验证脚本已清理，浏览器与预览服务已停止。
## P1 实时检测入口

新增 `web/app.js`，页面以 module 脚本加载；它导入共享 camera，以已有 Camera 的 started/stopped 等事件驱动检测。
无需额外前端构建或 npm。用前述 Uvicorn 命令启动后，在电脑浏览器打开 http://localhost:8000/pc，
点击“开始检测”并允许摄像头，便会连接同一服务的 /ws/stream。HTTPS 页面自动改用 wss。
当前默认只检测人物；跟踪、长按锁定与重识别尚未实现，目标框为白色。

建议按下列调用关系阅读：

1. `client = new DetectionClient(camera)` 与 `client.start()` 是前端入口；start 绑定摄像头、页面可见性与网络事件，设置按钮文字，并由 loadHealth 读取设备与模型信息，不自动请求摄像头。
2. `connect()` 创建当前页面同一主机的 WebSocket，连接后安排 tick；setStatus 更新中文状态和提示。
3. `tick(now, generation)` 在 requestAnimationFrame 中检查：尚有未回帧、正在编码、网络缓冲未清或发送间隔未到就跳过，不生成待发送队列。
4. `capture(generation)` 把视频按比例缩到长边最多 640，drawImage 到离屏画布，再调用 encodeFrame 异步生成 JPEG/Base64；发送 type、seq、ts、w、h、img。
5. `encodeFrame(canvas)` 使用 toBlob 与 FileReader，去掉 data:image 前缀后返回纯 Base64；编码/读取失败与超时都会结束等待，不把整张图片写入记录。
6. `receive(text)` 解析 JSON，使用 checkResult 检查数字、类别、坐标和框面积，并核对当前等待帧号；回收等待位置后更新服务端 FPS、处理耗时、结果数量与帧号。
7. `drawBoxes()` 将归一化坐标乘以画布宽高，绘制白框、灰底类别与置信度标签。镜像时使用 1-right、1-left 换算横坐标，文字不反转；线宽和字号按显示比例换算，窄屏仍可读。
8. `closeTransport()` 清理连接、动画、计时器和待回帧，并递增 generation。异步 JPEG 编码、旧连接消息完成后先比对编号，过期内容不再发送或显示。
9. `stop(message,state)` 关闭当前检测连接并提示停止/暂停；摄像头的设备释放仍由 Camera.stop 负责。
10. `fail(message,code,retry)` 显示服务端原始中文提示或网络问题；只有网络类故障按 1/2/4 秒最多重连 3 次，超过后等待停止再开始。收到有效结果才重置重试预算，避免握手成功却无结果时无限重试。

帧号 sequence 在页面内单调递增，pending 只保存一帧，encoding 表示正在准备 JPEG；
generation 标识当前连接生命周期，分别解决“结果属于哪帧”“是否可以再发一帧”“旧异步任务是否还有效”三个问题。
视频尺寸改变时立即清框；返回结果若属于旧尺寸，只计入处理数量，不绘制到新画面。
切后台时暂停连接并清框，回到前台且摄像头仍运行时重连；手动停止后不会自动开启摄像头。

可安全调整的前端参数在 app.js 顶部：
MAX_SIDE=640 控制发送图片最长边，JPEG_QUALITY=0.65 控制压缩质量，TARGET_FPS=30 是发送上限而非实际保证。
增大尺寸/质量可能提升细节，也会增加网络与处理开销。CONNECT_TIMEOUT_MS=10000、
RESPONSE_TIMEOUT_MS=15000 分别限制连接与回帧等待；首帧可能包含 GPU 初始化，等待时间不宜过短。
这些前端参数目前由 app.js 管理；.env 中同名参数尚未通过接口下发，修改 .env 不会改变浏览器压缩参数。
FPS 使用后端返回值，latency_ms 仅为电脑处理耗时，不含完整采集/网络/显示链路。

保存前以完整待保存 app.js/HTML、已保存的 Camera 与真实 FastAPI/Pipeline/YOLO11n，
在 Edge 中将官方 bus.jpg 反复绘入 canvas.captureStream 作为合成视频源，实际经 JPEG、TCP WebSocket、
RTX 3060 推理并回到页面，连续返回并绘出 4 个 person。
短时窗口实际完成约 20.99 帧/秒，取样时页面服务端 FPS 为 21.2、处理耗时 20.8ms；
初次冷推理约 4.9 秒。这是静态样例合成视频流的短时验证，不冒充物理摄像头或手机性能。

浏览器检查还覆盖：300ms 慢响应最多一帧在途；镜像坐标与标签正向；画布实际有绘制像素；
尺寸改变不画旧框；切后台/回来重连；停止后不再发送且轨道释放；坏 JSON、非法坐标、错误帧号和服务端错误提示；
连接拒绝最多初始 1 次加重连 3 次；无回帧超时；旧 JPEG 编码迟到不发送；390px 无横向溢出。
故障模式仅存在于临时验收服务，超时/重试等待在测试浏览器中临时缩短，不写入交付源码。

报告：`outputs/stream/stream_preview_report.json`；
已查看截图：`outputs/stream/detection_browser_preview.png`，画面来自官方单图样例，不是实拍。
临时源码与验证脚本已清理，浏览器及验收服务已停止。
保存版本的样例流复核方式见下节；其后的授权 PC 实机验收结果见本文末节。样例流数据与实机数据分开解释。

## 无需摄像头的检测链路检查

这个检查仅使用项目自带的 `data/samples/test.jpg`，不打开物理摄像头或麦克风。
在项目根目录运行：

```powershell
& .\envs\vitrack\python.exe -X utf8 .\scripts\verify_stream.py
```

脚本启动已保存的 FastAPI 服务和独立的无界面 Edge，先明确将摄像头、麦克风权限设为
`denied`，再把固定样例图片反复绘入 Canvas，使用 `captureStream(30)` 生成测试视频。
页面的测试取流函数只返回该合成流，不保留或调用原生设备函数；权限检查失败就停止。
它不会修改日常浏览器的个人资料，不安装新依赖；端口被占用时直接报错，不关闭现有服务。
完成或报错后，关闭本次创建的浏览器和服务，并清理本次新建的临时目录。

数据流为：固定样例 → 合成视频 → 已保存的 web/app.js → JPEG/WebSocket →
FastAPI/Pipeline/YOLO11n → 浏览器人物框。它检查默认 JPEG 尺寸、最多一帧在途、
人物数量、画布实际绘制，以及停止后的连接与合成轨道释放。

脚本的阅读顺序是 `main` → `parse_args` → `run_check`，再看辅助部分：

- `main()` 是检查入口，读取参数、调用检查、写 JSON 报告；成功返回退出码 0，失败返回 1。
- `parse_args()` 接收命令行输入，校验范围和浏览器路径，输出参数对象。
- `run_check(args, report)` 接收参数与待填写报告，顺序启动、检查、采样、停止；
  `try/finally` 使中途出错也进入资源释放流程。
- `sample_source(sample)` 接收样例路径，输出注入测试页的 JavaScript。
  图片先转为 Base64 数据地址，再由 Image 解码到 Canvas；
  `requestAnimationFrame` 循环重绘，以供合成视频持续产生画面。
- `BrowserSession` 接收独立浏览器的调试连接地址。
  `call()` 发送带编号的命令，循环等待对应响应；
  `evaluate()` 执行页面测试表达式并取回普通数据；
  `wait()` 在限时内反复检查页面条件；
  `close()` 停止合成源、关闭本次浏览器和连接。
  异步图片解码与页面操作必须等待完成，才能采样有效结果。

常用参数：

- `--duration 10`：预热后采样秒数，允许 1～300；更长可观察持续运行，但仍是固定样例。
- `--warmup-frames 30`：先完成多少帧再计时，降低初次 GPU 初始化对结果的影响。
- `--min-fps 15`：通过检查所需的最低完成吞吐；调低只改变判定标准，不会加速。
- `--port 8000`：临时本机服务端口，已占用时可改为 8001。
- `--browser '浏览器完整路径'`：指定已安装的 Edge/Chromium。
- `--report outputs/validation/synthetic_stream_report.json`：报告位置；相对路径以项目根目录为起点。
  默认每次覆盖同一报告，要保留多次结果可指定不同文件名。

本轮使用相同待保存源码的临时副本，调用已保存的后端和页面实际检查通过：
权限均为 `denied`，采样 10.001 秒完成 220 帧，实际完成吞吐约 22 FPS；
返回并绘出 4 个人物框，最多一帧在途；停止后合成轨道和临时服务均已释放。
报告见 `outputs/validation/synthetic_stream_report.json`。
页面的 17.4ms 是服务端处理耗时，不能解释为完整端到端延迟。

以上为固定样例验证，不能替代实机结果。后续在用户明确授权后完成了以下 PC 基本验收。

## P1 授权 PC 实机验收结果

用户在本轮明确允许使用摄像头，并要求禁止保存、上传画面。仅在本次独立浏览器中允许摄像头，
麦克风保持 denied；画面只经 127.0.0.1 本机服务在内存中处理，不发送到外部网站或云端。
未保存照片、视频、截图、人物裁剪或实机 JSON 报告；本节只保留数值摘要。

本次摄像头使用约 35.922 秒，实际尺寸 1280×720，音轨数量为 0。
预热后的 30.011 秒计时窗口完成 821 帧，实际完成吞吐 27.357 FPS，高于 P1 的 15 FPS 要求。
末次服务端 FPS 为 27.1、处理耗时为 21.4ms；处理耗时不是完整采集到显示的端到端延迟。

包含预热在内，共收到 852 帧检测结果：812 帧检出人物，40 帧未检出人物，部分帧最多返回 2 个框。
没有逐帧人工标注，不能把这些数量当成准确率，也不能确认零检出是人离开画面还是漏检，
或把两个框直接解释为两名真实人物。用户随后说明曾离开画面一段时间，这与零检出相符；
未保存逐帧时序，不能确认 40 帧全部对应离开时段，也不把它们直接计为漏检。
末次结果有 1 个 person 框，叠框画布确有绘制，最多一帧在途。

实机检查中的镜像断言首次失败；原因是检查程序在页面自动绘制后又手动绘制一次，
误把两次绘制当成多余人物框。去掉检查程序的重复调用后，以固定样例、camera/microphone 均 denied
复核镜像开关、视频变换和白框横坐标，检查通过；没有重新打开物理摄像头，也没有修改应用逻辑。

停止按钮已关闭视频轨道和检测连接，独立浏览器及临时服务已退出。
本次通过 P1 PC 人物检测、回框、叠框与 FPS 的基本验收；后续进入 P2 手机接入。
未验证长期实拍稳定性、完整端到端延迟、身份识别、跟踪、锁定和重识别。
后续再次使用隐私设备仍须取得对应范围的明确授权。
