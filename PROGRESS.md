# ViTrack 实施进度

本文件记录已经实际完成的工作、验证结果和下一步，不把计划视为已完成。
需求依据：`docs/ViTrack-视觉目标检测与跟踪-实施方案.md`。
教学和协作方式：`AGENTS.md`。

## 当前状态

- 日期：2026-10-18。
- 当前大阶段：P0 已验收并提交（cc20f2e）；P1 PC 人物检测闭环与 GPU FPS 基本验收已通过，本轮创建本地阶段提交；下一阶段为 P2 手机接入。
- 已完成：项目规则、独立环境、项目依赖、GPU 实测、模型下载、镜像检查、单图 GPU 检测及当前需要的目录与说明文件。
- 业务服务入口为 `app.main:app`，由 Uvicorn 加载；前端入口 web/index.html 加载 web/app.js。已实际验证 PC 摄像头、JPEG、WebSocket、GPU 检测和白框绘制；本次物理摄像头约用 36 秒，30 秒计时窗口约 27.4 FPS。手机、跟踪、锁定和重识别待后续阶段。
- 本次隐私范围：不保存或向外部上传实拍内容，只保留数值与结论。前面各里程碑按发生时状态记录，以本节和末尾最新实机记录为当前结论。

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

P1 基本验收完成后，下一里程碑为 P2 的手机访问启动与 HTTPS 准备；本轮不提前实现。再次使用摄像头等隐私设备时，仍须取得对应范围的明确授权。
后续单独接入样式、前端取流/传帧/叠框与诊断交互；保持逐关键里程碑讲解与暂停。

## P1：配置模块里程碑

- 新增 `app/__init__.py` 标识应用代码包，新增 `app/config.py` 集中管理方案第 6.1 节参数。
- 新增 `.env.example`：供用户复制为 `.env`，包含每组参数的中文说明；本轮没有创建或覆盖实际 `.env`。
- `AppConfig` 保存类型转换和范围检查后的只读设置；相对模型和证书路径以项目根目录为起点。
- `load_config` 的覆盖顺序为默认值、`.env`、进程环境变量；不改变 `os.environ`，也不加载 PyTorch 或模型。
- 配置检查包括检测尺寸、置信度、端口、设备编号、COCO 类别、高低相似度阈值、融合权重之和以及 ipcam 模式必填地址。
- 验证方式：保存前，在项目 Python 环境中将待保存的完整源文本作为模块执行，使用 `work` 内临时目录加载示例和自定义配置；检查完成后临时目录已自动清理。
- 实际输出：示例与默认值、文本类型转换、环境变量优先级、BOM、空类别、工作目录独立性、10 组错误输入、有效 IP 摄像头地址、配置只读检查全部通过，进程退出码 0。
- 源文本检查确认配置模块没有导入 torch；本轮已从磁盘实际导入 `app.config` 并调用 `load_config()`，输出 `CONFIG_IMPORT_OK`，模型绝对路径正确、设备为 0、类别为 `(0,)`，`torch_imported: False`，退出码 0。
- P1 整体尚未验收；本轮不创建阶段提交。

## P1：数据格式模块里程碑

- 新增 `app/schemas.py`；仅定义内部数据、通信格式与坐标转换，不执行模型推理、图片解码或网络操作。
- `DataModel` 统一检查未知字段、非有限数字和字段赋值；`Detection` 保存像素坐标，`Box` 保存前端需要的归一化坐标。
- 单独区分两种坐标是为消除内部裁剪与手机绘制的单位歧义，沿用方案的 JSON 字段，不改变检测、跟踪或通信技术。
- `Box.from_detection` 根据原图宽、高计算比例并限制到 0～1；完全位于画面外、裁剪后没有面积的框会被拒绝。
- `IdentitySummary` 仅包含对前端公开的编号、名称、缩略图和在线状态，不包含外观模板；真实身份库仍未实现。
- `FrameMessage` 对应浏览器输入，`FrameResult` 对应服务端结果，`ErrorResponse` 对应统一中文错误格式。
- 状态约束：P1 框默认 none、无轨迹和身份；candidate/locked 要有轨迹编号，locked 要有身份编号；前端 selected 不作为服务端身份状态发送。
- 保存前在项目 Python 环境执行完整待保存源文本：像素转换、边缘裁剪、方案 JSON 示例往返、输入帧格式、错误格式、每帧独立列表、负余弦相似度、非法坐标/状态/数值/尺寸等检查全部通过，退出码 0；未导入 torch。
- 保存时按要求暂停；本轮已实际导入 `app.schemas`，像素转换与 FrameResult JSON 往返通过，输出 `SCHEMAS_IMPORT_OK`、`torch_imported: False`，退出码 0。尚未建立 WebSocket 端点或解码浏览器图片。
- 更新 `app/__init__.py` 的包说明，以及 README 的模块阅读顺序；P1 整体未验收，本轮不创建阶段提交。

## P1：单帧检测模块里程碑

- 新增 `app/detector.py`：`Detector.__init__` 读取配置、检查本地权重和设备、准备第三方缓存并加载 YOLO；`detect` 接收 uint8 BGR 图像，返回像素坐标的 Detection 列表。
- 仅导入检测器模块不加载 PyTorch；创建实例时实际探测 CUDA 并记录日志。GPU 不可用或编号不存在时明确报错，不静默切换设备。
- 检测参数来自 AppConfig：模型路径、输入尺寸、置信度、IoU、类别过滤、设备。只使用 model.predict，未加入跟踪。
- 输入检查拒绝非 NumPy 对象、灰度图、四通道图、空图和浮点像素图；按需整理非连续的图像内存。
- 模型结果从 GPU 张量转换为 CPU 上的 Python 数字，再构造 Detection；丢弃无面积的退化框，无目标时返回空列表。
- 保存前在项目 Python 环境执行完整待保存源文本，使用真实 YOLO11n 权重和官方样例，全部检查退出码 0。
- GPU 实际设备 cuda:0，默认人物过滤得到 4 个检测；左右翻转的非连续图像也检测到 4 人；输入图像保持原内容；空白图返回空列表。
- CPU 加全部类别设置实测通过，输出类别包含 0（person）与 5（bus）。缺失权重及 5 组错误图像均按预期拒绝。
- 本次结果保存到 `outputs/detection/detector_module_report.json`，包含原始检测、归一化框和设备信息，属于单帧模块验证，不是实时 FPS、跟踪或重识别实验。
- 同步更新包说明和 schemas 的文字注释，README 增加检测器阅读说明；未改变 schemas 的字段或校验逻辑。
- 已保存检测器本轮实际导入并在 GPU 调用成功，输出 `DETECTOR_IMPORT_OK`、`persons: 4`、`device: cuda:0`，退出码 0。P1 整体未验收，尚未创建阶段提交。

## P1：帧处理流水线里程碑

- 新增 `app/pipeline.py`：`Pipeline` 接收已初始化的 Detector，共用同一个模型；不启动摄像头或网络监听。
- `process_message` 接收 FrameMessage，在线程中完成 JPEG 解码、尺寸核对、检测、归一化和 FrameResult 组装；`process_frame` 接收直接的 BGR 图像，为 P2 读取摄像头提供共同入口，当前尚无实际 IP 摄像头读取。
- 两个异步入口均通过 `asyncio.to_thread` 调用同步核心 `_run`。线程锁保护真正的工作，即使调用方取消等待，也不会在后台推理结束前让其他帧同时调用模型。
- 接收上限：JPEG 4 MiB，图像单边 4096 像素；Base64 必须有效，JPEG 头部尺寸必须与消息 w/h 一致，实际像素由 OpenCV 解码。
- `PipelineError` 提供错误码、中文提示和 `to_response`，区分 BAD_FRAME、FRAME_TOO_LARGE、INFERENCE_FAILED；模型异常记录日志并给出可显示的提示。
- FPS 使用最近 30 个成功完成帧的时间间隔，第一帧为 0；latency_ms 使用服务端单调时钟测量解码、检测和结果组装，不含等待处理锁的时间及手机/网络耗时。
- 保存前以完整待保存源文本运行真实 GPU 集成检查：480×640 JPEG/Base64 消息返回 4 人、seq 保持为 10；直接图像入口和空白图均通过，FrameResult 可往返转换为 JSON。
- 错误输入、尺寸不符、非 JPEG、超限图片、模拟模型失败均按预期返回错误；失败帧不更新成功计数。
- 模拟慢检测并取消调用方后，最大同时推理数仍为 1；后台处理期间事件循环能继续运行。已开始的取消请求仍可在后台完成并计入实际处理帧数。
- 本次首帧处理耗时约 2979 ms，包含 GPU 首次推理初始化，不能据此判定稳态性能。报告：`outputs/pipeline/frame_pipeline_report.json`；本轮没有浏览器或手机 FPS 验收。
- 排错发现当前 Ultralytics 接管了通用 `PIL.Image.open`，遇到损坏图片时自动安装 pi-heif。已移除该非必要插件，改用专门的 JpegImageFile 头解析器，并在 Detector 初始化及环境检查中关闭 YOLO_AUTOINSTALL。复查错误输入未触发插件安装。
- 环境维护：修正 setup_env 的锁文件生成方式，使用 `pip list --format=freeze`，把 torch/torchvision 的本机 file:/// 引用改为精确版本号；完整安装检查、GPU 运算检查及锁文件路径检查均通过。仍保留官方 CUDA 附加索引。
- 已保存流水线本轮实际导入并调用成功，输出 `PIPELINE_IMPORT_OK`、`persons: 4`、`processed_frames: 1`，退出码 0。P1 整体未验收，尚未创建阶段提交。

## P1：服务入口与日志里程碑

- 用户新增必做日志要求，已写入 AGENTS.md：最终 App 需提供前端诊断区域、近期错误和日志编号、前端记录导出及服务端日志下载。前端部分仍待实现。
- 新增 `app/main.py`：`create_app` 创建 FastAPI 应用，lifespan 在启动时配置日志、读取设置、在线程内加载 Detector，再创建 Pipeline。
- HTTP 提供 `/api/health`、`/api/logs`、`/api/logs/{name}`；`/` 与 `/pc` 在页面文件缺失时返回明确中文提示，不能冒充已完成摄像头页面。
- `/ws/stream` 校验消息类型、大小、JSON 和 FrameMessage，调用流水线返回 FrameResult。输入错误返回中文响应；超大消息返回错误并以 1009 关闭连接。
- HTTP 响应带 X-Request-ID；WS 按连接编号和帧号关联。ContextVar 将关联信息带入 Pipeline 工作线程，错误提示也附带同一编号。
- 文件日志位于 `outputs/logs/app.log` 与 `errors.log`，UTF-8、北京时间，默认每份 5 MiB，保留 3 个历史备份。INFO 只记录首帧与每 30 帧摘要，DEBUG 可记录每帧元信息，不记录图片正文。
- 异常堆栈、函数行号、请求/连接编号与 seq 均可在日志中查找。日志 API 只提供已知日志及有限备份的列表/下载。
- 保存前以完整源文本运行 FastAPI TestClient 的进程内 HTTP/WS 检查，共 14 类检查通过，真实 GPU 帧返回 4 人。
- 覆盖健康检查、未知地址、HTTP 意外异常、HTTP 参数错误、日志文件名限制、WS 坏消息、恢复发送、大小关闭、错误关联、UTF-8 下载、启动失败记录及有限轮换；未开启实际 TCP 监听。
- 模拟检测错误的 Traceback 带 `seq=30`，编号与客户端中文提示一致；模拟 HTTP 异常同样可按 X-Request-ID 在错误日志中找到。
- 检查报告：`outputs/server/server_module_report.json`；模拟错误日志已隔离到 `outputs/server/validation_logs/`，不是正式运行报错。
- 保存后按规则暂停，磁盘模块导入/启动与 TCP 检查留到下一轮。P1 页面闭环和帧率验收未完成，本轮不创建阶段提交。

## P1：真实网络验证与日志下载修复里程碑

- 使用项目 Python 执行 `-X utf8 -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1`，已保存服务实际启动成功并加载 RTX 3060。
- HTTP 健康接口和真实 WebSocket 图片处理通过：seq=101 返回 4 个 person，框坐标在 0～1；seq=102 坏帧返回 BAD_FRAME，提示编号与服务端日志一致；seq=103 恢复发送成功。
- 实测发现此前进程内检查未覆盖的问题：FileResponse 读取文件长度后，下载请求日志又让 app.log 增长，触发 Response content longer than Content-Length 并使客户端收到不完整响应。
- 本轮将关键里程碑调整为修复日志下载；原计划的页面结构顺延。首次故障日志保存在 `outputs/server/transport_failure_logs/`。
- 修改 `app/main.py`：新增 `read_log_snapshot(name)`，与对应 RotatingFileHandler 共用锁，将白名单查询和读取放在同一锁范围内；输出固定 bytes。无效或缺失文件返回 404，处理器未就绪返回 503。
- `download_log(name)` 在线程中读取副本，再用 Response 作为附件发送；长度取自固定副本，增加 no-store，避免持续写入、轮换或浏览器旧缓存影响下载。本次下载事件在副本完成后写入。
- 锁内不调用 logger，避免持有一个处理器锁时进入其他处理器；后台线程读取避免在异步事件循环中执行文件读操作。下载格式、允许的文件范围、5 MiB 与 3 份备份配置保持原值。
- 保存前以完整待保存源文本启动真实 Uvicorn 服务，httpx/WebSocket 客户端回归通过：真实 GPU、坏帧关联与恢复、日志列表、无效文件名 404、空 errors.log 下载均正常。
- 额外覆盖超过 64 KiB 的日志附件、12 次写入期间下载、24 次轮换期间下载、3 份历史日志下载；响应声明长度与实际字节数全部一致，中文 UTF-8 完整，验证服务 errors.log 为空。
- 轮换验证临时使用 32 KiB，不改正式配置；测试专用接口只存在于验证进程，未写入项目源码。
- 报告：`outputs/server/server_transport_report.json`；修复回归日志：`outputs/server/transport_validation_logs/`。正式日志目录将在下次启动时自动创建，验证日志已隔离。
- 验证进程已停止。更新 README 与本进度；保存后立即按规则暂停，磁盘修复接口复核留到下一轮。P1 页面闭环与帧率未验收，不创建阶段提交。

## P1：浏览器页面结构里程碑

- 首先实际运行已保存的 `app.main:app`，连续下载正在增长的 app.log 共 10 次，Content-Length 与实际字节数一致，UTF-8 完整；错误日志为空，白名单外文件返回带请求编号的中文 404。
- 保存模块复核报告：`outputs/server/saved_download_report.json`；该验证服务已停止，日志隔离至 `outputs/server/saved_download_logs/`。
- 新增前端源码 `web/index.html`，由已有 / 和 /pc 页面路由返回。没有修改后端业务逻辑，没有删除文件。
- 页面包括：顶部导航与照片入口；摄像头 video、叠框 canvas 和空画面提示；连接状态、FPS、处理耗时、结果数、尺寸、帧号；开始/停止、摄像头方向、镜像、录制；身份列表和日志诊断区。
- 日志诊断区预留最近错误、服务端日志编号、出错帧号、前端日志列表、导出和清空按钮，提供可直接访问的服务端日志下载、日志列表与健康接口链接。
- 未实现的按钮及设置组保持 disabled；无摄像头或检测数据时显示等待/--，不伪造连接或检测成功。前端日志采集和导出仍待实现。
- 使用原生 details/summary 展开收起诊断区；中文标签、锚点、说明关联及跳转主要内容链接支持基本键盘和辅助阅读。高频指标不逐帧实时播报。
- 本轮不创建 CSS/JavaScript，不引用缺失资源，也未提前实现摄像头、传帧、叠框或身份业务。后续样式将叠放 video/canvas，脚本按真实视频尺寸同步二者。
- 保存前验证完整源文本：125 个元素、53 个唯一 id；标签配对、引用、锚点、媒体属性、初始状态、禁用控件、日志下载链接等检查通过。
- 使用 work 临时目录中的页面副本，通过已有 FastAPI /、/pc 与 /static/index.html 路由的进程内 HTTP 检查，均为 200、内容与字节长度正确。临时副本已自动清理。
- 页面结构验证报告：`outputs/web/page_structure_report.json`。尚未执行浏览器渲染、摄像头、手机、前端日志或帧率验收。
- 同步更新 README 与本进度；新增 web 目录后，已运行服务需重启才会注册静态目录。
- 保存后按逐里程碑规则立即暂停；下一轮复核磁盘页面并建立样式。P1 PC 摄像头闭环尚未验收，不创建阶段提交。

## P1：响应式页面样式里程碑

- 首先从磁盘读取已有页面，通过现有 /、/pc、/static/index.html 路由复核，均为 200，字节内容正确；报告：`outputs/web/saved_page_report.json`。
- 新增前端样式源码 `web/style.css`，含中文分段注释：主题变量、全局与焦点、桌面网格、视频叠层、指标与控件、诊断区、窄屏与减少动态效果。
- 机械修改 `web/index.html`：引用 /static/style.css，为诊断子区域增加 diagnostic-grid 包装并更新文件说明；保留原有 id、文字和禁用状态。不修改后端代码，不删除文件。
- 桌面画面与操作并排，诊断区占满一行；900px 以下改单列，480px 以下缩小间距、指标换行。全局 border-box、min-width:0 与 minmax(0, 1fr) 避免内容撑宽。
- 视频按自身比例决定高度，绝对定位的 canvas 共用显示范围；只有空状态提示固定 16:9。hidden 规则具有高优先级，不让空视频/画布提前出现。
- 诊断编号与错误可换行，日志列表超过 240px 内部滚动。按钮/选择框至少 44px 高，键盘焦点可见；减少动态效果偏好关闭平滑滚动与按钮过渡。
- 连接成功/连接中/错误样式仅预留 data-state 选择器，不虚构当前状态。摄像头、传帧、叠框绘制与浏览器日志业务仍未实现。
- 保存前在临时目录提供完整待保存 HTML/CSS，通过已有 FastAPI 的 /、/pc、/static/index.html 与 /static/style.css 路由检查，状态及内容正确，CSS MIME 正确。
- 使用已安装的 Microsoft Edge 无界面浏览器检查，未安装新依赖：1365、768、390、320px 均无横向溢出，宽屏并排/窄屏纵排正确，78 条顶层 CSS 规则已由浏览器解析。
- 检查 video 的 640×360 与 360×640 尺寸属性，画布与视频的位置/宽高差均小于 1px；这不是实际摄像头验收。
- 4096 字符编号、长中文错误、50 条临时日志、200% 根字号均未撑宽页面；日志可滚动，Tab 跳转链接、Enter 原生折叠和减少动态效果检查通过。
- 已查看并修正预览中的列表空白和指标空格；最终截图：`outputs/web/style_desktop_preview.png`、`outputs/web/style_mobile_preview.png`。
- 报告：`outputs/web/style_preview_report.json`。预览浏览器自动请求 favicon.ico 得到 404；页面和 CSS 均正常加载，未将此请求记录到正式日志。
- 临时预览服务和浏览器均已停止，临时文件自动清理。同步更新 README 与本进度，最终源码保存后立即暂停。
- 下一轮复核磁盘样式并实现独立的前端诊断日志模块，再接摄像头；手机、实时检测与日志导出尚未验收，P1 不创建阶段提交。

## P1：浏览器诊断日志里程碑

- 首先复核已保存 HTML/CSS，通过 /、/pc、/static/index.html、/static/style.css 路由，内容与 MIME 正确；报告：`outputs/web/saved_style_report.json`。
- 新增 `web/logger.js`：BrowserLogger 管理当前页内存记录，模块导出共享 logger 并启动；start 重复调用不会增加事件监听。
- record 接收级别、中文说明和白名单元信息，提取服务端日志编号与帧号；captureError 接收 Error/DOMException/字符串；render 更新诊断区；getLogs 返回副本；clear 清空当前页；exportLogs 生成 UTF-8 JSON 并触发下载。
- 北京时间统一带 +08:00；默认保存最近 200 条、显示最近 50 条；消息和堆栈限制长度，刷新后清空，不使用持久存储。
- 文字通过 textContent 显示；省略数据地址与长编码，去掉网址账号/密码/查询参数/片段，只保留明确字段，不记录整帧或请求正文。
- 全局捕获脚本错误、资源加载失败、未处理 Promise，以及浏览器 online/offline 事件。摄像头、WebSocket、HTTP 接口的业务错误仍需后续模块显式调用。
- 修改 `web/index.html`：增加 module 脚本引用，更新文件说明、初始化提示与日志提示；摄像头/照片/录制保持禁用，日志按钮按记录数量启用。没有修改后端或 CSS，没有删除项目文件。
- 保存前用完整待保存源码、已有样式和本机 Edge 验证模块导入、重复启动、日志编号/帧号、超长错误、DOMException、无旧编号串用、白名单与文字清理。
- 浏览器真实脚本异常、未处理 Promise 和缺失脚本资源 404 均被捕获；online/offline 用合成事件验证，未宣称真实断网。测试用 404 不影响正常资源加载。
- 205 条输入保留最新 200 条、页面显示最新 50 条；getLogs 副本不会改动内部数据；清空按钮产生空状态并禁用导出；HTML 标签只显示为文字。
- 真实点击导出按钮，读取 Edge 实际下载 JSON，验证 UTF-8 中文、北京时间、两条记录、日志编号和帧号；临时下载地址按时释放；模拟导出失败能记录并显示。
- 390px 诊断区无横向溢出，重载后的正常初始界面已截图查看：`outputs/web/logger_diagnostics_preview.png`。
- 报告：`outputs/web/logger_preview_report.json`；`outputs/web/logger_export_sample.json` 仅是两条主动构造错误的导出示例，不代表实际摄像头/API 故障。
- 临时源码副本、验证脚本和浏览器下载目录已清理；浏览器与临时服务已停止。模拟错误未混入正式服务端日志。
- 更新 README 与本进度，最终源码保存后立即暂停。下轮复核磁盘模块并进入摄像头里程碑；PC 摄像头闭环、手机和实际业务错误联调未验收，P1 不提交。

## P1：摄像头预览里程碑

- 用户最新偏好已保存至 AGENTS.md；相关配套维护不再单独汇报，工作重点继续推进核心功能。
- 新增 web/camera.js，index.html 引用 module 脚本；Camera 接收 video/canvas，提供 start、stop、syncSize 和 setMirrored，共享 camera 实例并绑定页面预览操作。
- CameraError/cameraFailure 统一中文错误；waitForVideo 等待实际第一帧与播放成功，限时清理；closeStream 关闭所有轨道。
- 初始 idle 不请求设备，用户点击后才执行 getUserMedia，audio=false；默认理想尺寸 1280×720、后置或默认方向，实际宽高以视频为准。
- 使用状态事件驱动按钮、空状态、画面可见性与尺寸显示。方向切换先关闭旧流；镜像只改变视频显示；检测连接、FPS 仍保持未连接/--。
- 请求编号与 AbortController 防止过期异步结果覆盖当前预览。stop 可立即取消本地等待，迟到的授权结果返回后自行关闭，不影响较新的流。
- video resize 同步画布像素尺寸并清除旧框；轨道 ended 或页面 pagehide 时释放设备，重复 stop 安全。
- 保存前使用完整待保存 HTML/Camera 源码与已保存依赖，在现有 FastAPI 路由及 Edge 内置合成摄像头验证；正常模块和页面资源均通过。
- 实际合成 getUserMedia 返回 1280×720，能读取非空像素，无音轨；开启/停止、方向切换释放旧流、镜像与画布独立、模拟竖屏尺寸同步通过。
- 延迟授权取消后流被关闭；两个请求逆序完成时，旧流关闭且新流保持 live。没有自动打开设备。
- 权限拒绝、无设备、设备占用、约束失败、中断、非法参数、播放拒绝和超时均按预期返回并释放轨道；超时测试临时缩短等待，不修改正式 12 秒配置。
- 设备断开与 pagehide 使用合成事件检查，390px 无横向溢出。未打开物理摄像头，不把此检查当作实际硬件或手机验收。
- 报告：outputs/camera/camera_preview_report.json；已查看截图：outputs/camera/camera_preview.png，绿色图案为浏览器合成摄像头画面。
- 临时副本、验证脚本已清理，浏览器与预览服务已停止；同步更新 README、PROGRESS 与最新协作偏好，保存后立即暂停。
- 下一步接入 web/app.js 完成取帧、WebSocket 和叠框；物理摄像头、真实检测帧率和手机尚未验收，P1 不创建阶段提交。

## P1：浏览器实时检测闭环里程碑

- 新增 web/app.js 前端入口：DetectionClient 复用 camera.js，连接 /ws/stream，按比例缩放 JPEG、发送 FrameMessage、接收 FrameResult 并绘制 Canvas 白框和类别/置信度。
- index.html 改为加载 app.js，由其导入已保存 Camera，更新文件说明与初始化提示；没有修改后端、Camera 或 CSS 的业务逻辑。
- tick 在 requestAnimationFrame 中节流，pending/encoding/网络缓冲任一忙碌就跳过，保持每连接最多一帧在途；发送长边 640、JPEG 0.65、上限 30FPS，不把上限当实际性能。
- encodeFrame 使用 toBlob/FileReader 返回纯 Base64，带编码超时；capture 发送 seq、ts、w、h、img，异步完成后检查会话 generation，防止停止或重连后旧编码发送。
- receive 检查 JSON、有限数字、类别、归一化坐标和正面积，再核对等待帧号。更新服务器返回的 FPS/latency、接收数与帧号，不伪造数据。
- drawBoxes 根据画布像素换算坐标；镜像按 1-right/1-left 转换，文字保持正向；线宽/字号按显示比例调整。视频尺寸改变时清框，旧尺寸结果不叠到新画面。
- closeTransport/stop 清连接、计时器、动画、待回帧与旧框；后台暂停、前台且摄像头运行时重连。手动停止同时通过 Camera 释放轨道。
- 网络类错误最多按 1/2/4 秒重连 3 次，收到有效帧才重置预算；连接与回帧有超时。明确的服务端错误或坏结果直接显示中文并暂停检测。
- 保存前以完整待保存前端、真实 FastAPI/Pipeline/YOLO11n，在 Edge 用官方 bus.jpg 的 canvas.captureStream 合成视频进行实际 TCP/WebSocket/GPU 回环，稳定返回并画出 4 人。
- 样例流短时完成窗口约 20.99FPS；取样页面服务端 FPS=21.2、latency=20.8ms；首帧冷推理约 4902ms。此为合成静态样例流，非实拍摄像头、手机或长期性能结论。
- 测试 300ms 慢响应最多一帧在途，白框有实际画布像素，镜像位置正确；尺寸变化清框、后台暂停、前台重连、停止释放与不再发送均通过。
- 临时受控服务验证坏 JSON、非法坐标、错误帧号、服务端中文提示；握手即断开最多 4 次尝试（初次+3重连），回帧缺失超时、恢复连接、停止后迟到编码忽略、序号单调递增、390px 布局均通过。
- 临时故障入口与测试定时器只在验收环境，未写入交付源码；测试副本和脚本已清理，浏览器与服务已停止。
- 报告 outputs/stream/stream_preview_report.json；已查看截图 outputs/stream/detection_browser_preview.png，来源为官方样例，不是实拍。
- 更新 README 与本进度，源码保存后立即暂停。下一轮复核磁盘入口并执行物理摄像头/帧率验收，P1 整体验收与本地阶段提交尚未完成。

## P1：不访问隐私设备的保存版本复核里程碑

- 新增 scripts/verify_stream.py，提供可重复运行的检查入口；使用固定样例，不访问物理摄像头或麦克风。
- 使用已保存的 app.main:app、网页和前端模块；验证 /pc 与静态资源响应和磁盘内容相同。
- 独立浏览器先通过调试协议将 camera、microphone 均设为 denied，页面确认后才继续。
  测试页 getUserMedia 只返回样例 Canvas 合成流，不保留/调用原生设备函数，不使用自动授权参数。
- 端口被占用就退出，不接管用户服务；只关闭本次新建进程、清理本次 synthetic_check_* 临时目录。
  未重试先前被安全审核拒绝的清理动作。
- 验证命令：项目 Python -X utf8 work/verify_stream_preview.py；
  临时脚本与最终脚本行为一致，收尾仅删除无用导入/变量，临时脚本已删除。
- 实际报告时间 2026-10-18T18:06:58.835016+08:00，状态 passed；
  camera=denied、microphone=denied、physical_camera_access=false。
- 预热后采样 10.001 秒，完成 220 帧，实际完成吞吐 21.997 FPS；
  页面服务端 FPS=22.3、处理耗时=17.4ms，后者不代表完整端到端延迟。
- 样例返回 4 个人物，画布有实际叠框像素；JPEG 默认尺寸符合要求，最多一帧在途。
  停止后合成轨道已释放、检测连接已关闭、临时服务已停止。
- 报告：outputs/validation/synthetic_stream_report.json。未保存实拍照片或视频；
  结果不是物理摄像头或手机验收，先前未经授权的实机测试仍不计入正式验收。
- 同步 README 的入口、参数、函数与数据流说明；本次最终脚本和说明保存后按教学规则暂停。
- 下一步仍须单独取得明确授权，才可进行物理摄像头与正式持续帧率/端到端实机验收；
  P1 正式验收及阶段提交未完成，不提前进入 P2。

## P1：最终脚本磁盘运行复核

- 使用已保存的 scripts/verify_stream.py 实际运行，未修改业务源码或检查脚本。
- 命令：`& .\envs\vitrack\python.exe -X utf8 .\scripts\verify_stream.py --report outputs/validation/saved_stream_report.json`。
- 报告时间 2026-10-18T18:15:17.079716+08:00，进程退出码 0、status=passed。
- 摄像头和麦克风权限均为 denied，physical_camera_access=false；本轮仅使用项目固定样例合成流。
- 采样 10.001 秒完成 214 帧，实际完成吞吐 21.398 FPS；样例返回并叠加 4 个人物框，最多一帧在途。
- 页面服务端 FPS=20.9，服务端处理耗时=25.9ms；不将其解释为完整端到端延迟。
- 合成轨道已释放、临时服务已停止。报告保存为 outputs/validation/saved_stream_report.json，与上一轮临时源码验证报告分开。
- 无需隐私设备的保存版本复核已完成；下一项是正式 PC 摄像头验收，必须先取得明确同意。
  拟申请范围：仅摄像头、最多 60 秒、音频关闭；帧仅发往本机服务，不保存照片/视频，仅保存数值报告，结束立即释放设备。
- 当前“继续”不构成隐私授权；未打开物理设备，P1 尚未正式通过或创建阶段提交。

## P1：明确授权后的 PC 实机验收

- 用户本轮明确允许使用摄像头并亲自出现在画面中，要求未检出人物时如实报告，禁止保存和上传实拍内容。
- 本轮只允许独立浏览器的摄像头，麦克风 denied；实际音轨为 0。数据仅通过 127.0.0.1 本机服务在内存处理，不向外部网站或云端发送。
- 未保存照片、视频、截图、人物裁剪或实机 JSON 报告；本节只保存数值摘要。检查程序经标准输入在内存中执行，未创建可意外重跑的物理摄像头脚本。
- 第一次命令因 PowerShell 中文传递问题停在页面就绪检查，未开启摄像头；改用 ASCII 转义传递源文本后重试，不改应用检测参数。
- 实机检查时间 2026-10-18T18:21:55.553013+08:00；摄像头实际开启约 35.922 秒，实际尺寸 1280×720。
  设有页面 55 秒释放保护与独立进程退出保护，本轮正常主动停止早于保护期限。
- 预热后采样 30.011 秒，完成 821 帧，完成吞吐 27.357 FPS；末次服务端 FPS=27.1、处理耗时=21.4ms。
  后者不是完整端到端延迟，本轮未测量完整端到端延迟。
- 包含预热共收到 852 帧：812 帧检出人物、40 帧未检出人物，部分帧最多返回 2 个框，末次为 1 个 person。
  用户随后说明曾离开画面一段时间，与零检出相符；未保存逐帧时序，不能确认 40 帧全部对应离开时段，
  不把这些零检出直接计为漏检。无逐帧人工真值，不能将数量解释为准确率，也不能直接确认实际人数。
- 实机叠框画布有实际绘制像素，最多一帧在途；停止后真实视频轨道 ended、检测连接关闭。
- 初次检查整体退出码 1，原因是镜像断言重复计数：change 事件已触发 drawBoxes，检查程序又手动调用，
  因此捕获两轮 strokeRect。保留这次失败事实，不将它改写为原脚本一次性通过。
- 随后只用固定样例并将 camera/microphone 均 denied，移除检查代码重复绘制调用，验证镜像开关、
  视频变换与白框横坐标通过；离线复核退出码 0，mirror_event_check=true，未再打开物理摄像头。
- 实机和离线复核的独立浏览器、临时服务已退出，相关匹配进程数为 0；本轮临时目录已自动释放，
  未触碰此前被安全审核拒绝清理的旧目录。
- 结论：实施方案 P1 的 PC 人物检测→送帧→回框→叠框与 FPS≥15 基本验收通过。
  镜像检查程序问题已通过不访问隐私设备的复核定位；本轮不修改应用源码。
- 更新 AGENTS.md 的本次授权边界、禁止保存/外传实拍内容和如实报告要求；更新 README、PROGRESS，
  并按阶段要求创建 P1 本地 Git 提交，仅提交源码、配置和说明，不包含 outputs、work、envs 或任何实拍内容。
- 下一里程碑 P2：准备手机接入的启动和 HTTPS；手机实测、5 分钟稳定性、IP 摄像头模式仍未开始。

## 后续功能待验收

- 2026-10-18：本轮物理摄像头测试未先取得用户明确许可；用户指出后已停止，确认本任务相关测试进程全部退出。该轮不计入正式验收，没有保存实拍照片或视频。AGENTS.md 已加入隐私授权规则。测试文件和隔离浏览器目录清理命令被自动安全审核以 blocked by policy 拦截，不能宣称已经清理；不执行同一命令重试。

- 长时间持续实拍的 FPS、完整端到端延迟与资源占用；本轮仅验证约 36 秒的 PC 基本闭环。
- HTTPS、手机连通性、IP 摄像头模式、轨迹跟踪、锁定和重识别效果。
- 手机上的导出与服务端下载操作。
- P2～P7 功能与验收。
