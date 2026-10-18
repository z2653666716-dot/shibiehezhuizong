# ViTrack · 视觉目标检测与跟踪 —— 课程设计实施方案

> 本文件是交给 **Codex / 编码智能体** 执行的施工蓝图，同时也可作为本人开发时的 CheckList。
> 目标机器：Windows + VS Code，工作目录 `E:\course_task\homework3`，项目根目录 `E:\course_task\homework3`。
> 已有环境：Miniconda(`C:\Users\mi\miniconda3`)、Python 3.14(base，**不可用**)、conda envs: `d2l-zh` / `uavloc`、
> Git 2.54、NVIDIA RTX 3060 Laptop 6GB、CUDA Toolkit 13.3。

---

## 0. 给 Codex 的开工指令（先读这一节）

1. **工作范围**：只在 `E:\course_task\homework3` 内创建和修改文件，不要动 `d2l-zh` / `uavloc` 两个 conda 环境。
2. **执行顺序**：严格按 **第 9 节的 Phase P0 → P7** 推进，不要跳阶。每个 Phase 结束必须跑通该 Phase 的「验收命令」，失败就自己修，修完再继续。
3. **进度留痕**：每完成一个 Phase，更新 `PROGRESS.md`（记录：完成项、验收输出、遇到的问题、下一步），并 `git commit` 一次。
4. **不要擅自扩大范围**：本方案已冻结技术选型（见第 3 节「关键决策」）。若某决策在实测中不可行，先在 `PROGRESS.md` 写明原因 + 替代方案，再执行替代方案，不要静默换技术栈。
5. **网络**：任何下载一律优先走 **第 13 节国内镜像表**。下载失败不要反复重试同一个源，按表里的顺序切换，最多 3 个源，然后降级到「离线/自实现」方案。
6. **需要我人工介入的只有这几件事**（其余全部自己搞定）：用手机实际打开页面、把手机加入同一 WiFi、安装手机端证书、录制最终演示视频、撰写论文与报告正文。
7. **每一阶段产出可运行的东西**，不要写一堆没跑过的代码。宁可功能少，也要端到端能演示。

---

## 1. 原始要求（PPT 转录，不可改动的事实）

**《课程设计资料提交要求：视觉目标检测与跟踪相关内容》**

| # | 要求 |
|---|---|
| 1 | 最后一次课 **算法原理（可 PPT 展示）+ 成果展示（需运行源程序演示）**，**每人 5 分钟** |
| 2 | 每人提交 **源码电子版 1 份**、**学术论文电子版 1 份**（含题目、中英文摘要、研究现状分析并引用参考文献、详细描述的研究方法、实验结果分析、结论、参考文献，**不少于 3000 字**）、**录制视频演示 1 份** |
| 3 | 另需提交 **课上编写实践程序软件实验报告电子版 1 份**、**录制视频演示 1 份** |
| — | 压缩文件以 **「学号+姓名」** 命名，**大小不超过 200M**，**2026 年 11 月**在乐学平台提交 |

**时间推算**：照片时间戳为 10 月中，距 11 月提交约 **2–3 周**。计划按"2 周出可演示版本 + 1 周写材料"排布，P4（重识别）是唯一的技术风险点，必须最早验证。

---

## 2. 需求分析与目标拆解

### 2.1 用户需求（本人提出的交互需求，这是本项目的"创新点"）

| 编号 | 需求 | 技术含义 |
|---|---|---|
| R1 | 用**手机摄像头**采集画面 | 手机只做"摄像头 + 显示端"，算力放在 PC |
| R2 | 实时做**物体检测**，画出识别框 | 通用目标检测（COCO 80 类），重点 `person` |
| R3 | **长按识别框锁定**，框变**绿色** | 交互 + 身份注册（把外观特征存进"身份库"） |
| R4 | 目标**离开画面**后**重新出现**，仍能重新锁定，框仍是绿色 | **跨轨迹长时重识别（ReID）** —— 全项目最难点 |
| R5 | **给一张照片**，能从画面中识别出这个人并锁定追踪 | 单样本身份检索（query-by-example） |
| R6 | 最终形态是一个 **App** | 手机浏览器 PWA（可"添加到主屏幕"全屏运行） |

### 2.2 必须做 vs 可以砍

- **必须做（不做就没有分数）**：R1 R2 R3 R4（R4 至少要在"离开 10 秒内回来"成立）、源码可运行、5 分钟现场演示。
- **应该做**：R5 照片注册、PWA 全屏、服务端录制标注视频。
- **可以砍（时间不够时）**：多类别（只留 person）、WebRTC 低延迟、模型量化、多机部署。

### 2.3 场景边界（写进论文的"适用范围"）

- 单摄像头、固定或缓慢移动的拍摄者、室内光照；
- 同一人**同一次穿着**离开再回来能认出来；**换衣服不保证**（这是 ReID 的正常边界，论文里要主动写明，属于加分而不是减分）；
- 同时跟踪 **≤ 5 人**，画面中不同时出现两个长得极像且同色衣服的人。

---

## 3. 总体技术方案

### 3.1 架构

```
┌──────────────────────┐   HTTPS/WSS (局域网)    ┌────────────────────────────────┐
│  手机浏览器 (PWA)     │ ───── JPEG 帧 ────────> │  PC: FastAPI + Uvicorn          │
│  getUserMedia 取流    │                          │  ├─ YOLO11n  检测 → JSON boxes  │
│  canvas 叠框/长按手势 │ <──── boxes JSON ──────  │  ├─ ByteTrack 帧间跟踪          │
│  绿色锁定视觉反馈     │                          │  ├─ ReID 身份库（长时重识别）    │
└──────────────────────┘                          │  └─ Recorder 录制标注视频        │
                                                   └────────────────────────────────┘
```

**关键设计：计算全部在 PC，手机只做采集 + 绘制。** 理由：
- 手机上跑 YOLO（TFLite/NCNN）需要额外工具链，且手机性能差异大、演示日不可控；
- 只回传 JSON 框坐标（每帧约 1KB），不回传视频，带宽省、画质由手机决定；
- 前端用 canvas 叠层绘制，框的位置是"服务器算的、客户端画的"，帧率跟显示解耦，视觉上不卡。

### 3.2 关键决策（已冻结，不要随意改）

| 决策点 | 选择 | 理由 |
|---|---|---|
| 后端框架 | FastAPI + Uvicorn（WebSocket） | 异步、轻、Python 生态 |
| 检测模型 | **Ultralytics YOLO11n**（`yolo11n.pt`） | 5.4MB，3060 上 640 输入约 5–8ms，够用且好讲原理 |
| 帧间跟踪 | **ByteTrack**（ultralytics 内置 `tracker=bytetrack.yaml`） | 零额外依赖，论文里好写 |
| 长时重识别 | **自实现外观特征 + 余弦相似度 + 多模板身份库（MVP）**，进阶对比 **OSNet-x0.25** | torchreid/boxmot 权重多托管在 Google Drive，国内难拉；先用 torchvision 权重保交付，OSNet 作为"对比实验" |
| 前端 | 原生 HTML/JS + Canvas（无 npm/无打包） | 零构建，手机直接开，避免 Node 环境折腾 |
| App 形态 | PWA（manifest + service worker + 全屏） | 满足"一个 App"，且不需要 Android 打包 |
| 摄像头接入 | 主：手机浏览器 getUserMedia（HTTPS）；备：IP 摄像头 App + OpenCV | 见第 8 节，**必须有降级路径**，演示日不能翻车 |
| Python 环境 | **新建 conda env `vitrack`，Python 3.11** | base 是 3.14，PyTorch/Ultralytics 无适配轮子 |

### 3.3 主数据流（一次推理）

```
手机 canvas → 缩放至长边 640 → JPEG(q=0.65) ~45KB → WS 发送
      → 服务器 cv2.imdecode
      → YOLO11n 检测(person) → ByteTrack 分配 track_id
      → 每条轨迹：crop → MobileNetV3 特征 → EMA 平滑
      → 与身份库做余弦匹配（无身份的轨迹）
      → 组装 result JSON → WS 回传（含 norm 坐标 + identity_id + 颜色状态）
      → 手机 canvas 按归一化坐标叠框（绿/白/黄）
```

预算：GPU 端 15–25 FPS（640 输入），端到端延迟 150–300ms（同 WiFi）。这是可接受、也刚好能"演示出真实感"的数字。

---

## 4. 环境搭建

### 4.1 新建 conda 环境（务必新建，不要用 base / d2l-zh / uavloc）

```powershell
# 配置国内 conda 源（清华）
conda config --set show_channel_urls yes
conda config --add channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main/
conda config --add channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge/

# 新建环境：Python 3.11（关键，不要用 3.14）
conda create -n vitrack python=3.11 -y
conda activate vitrack
python -V    # 期望 Python 3.11.x
```

### 4.2 pip 国内源

```powershell
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
pip config set global.trusted-host pypi.tuna.tsinghua.edu.cn
# 备用： https://mirrors.aliyun.com/pypi/simple/
```

### 4.3 安装依赖

```powershell
# Windows 版 PyPI torch 自带 CUDA 运行库，直接装即可
pip install torch torchvision
python -c "import torch;print(torch.__version__, torch.cuda.is_available())"   # 期望 True

pip install ultralytics
pip install fastapi "uvicorn[standard]" python-multipart python-dotenv
pip install opencv-python numpy pillow cryptography pytest
```

> 注意：ultralytics 会拉 `opencv-python-headless`，与本项目的 `opencv-python` 冲突时，先 `pip uninstall -y opencv-python-headless` 再装 `opencv-python`。
> 生成锁文件：`pip freeze > requirements.lock.txt`（提交材料里带 `requirements.txt` 即可，锁文件进 .gitignore 之外单独保留）。

### 4.4 权重下载（走国内链路，见第 13 节）

```powershell
mkdir weights
# 方案 A：gh 代理直连 GitHub Release
curl.exe -L -o weights\yolo11n.pt "https://ghfast.top/https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n.pt"
# 方案 B：HuggingFace 镜像
$env:HF_ENDPOINT="https://hf-mirror.com"
hf download Ultralytics/YOLO11 yolo11n.pt --local-dir weights
```
校验：文件约 5.4MB，`yolo predict model=weights\yolo11n.pt source=<任意图片>` 能出框。

### 4.5 VS Code

- 装 `Python` + `Pylance` 扩展；
- `Ctrl+Shift+P → Python: Select Interpreter` 选 `vitrack` 环境的 `python.exe`
  （路径形如 `C:\Users\mi\miniconda3\envs\vitrack\python.exe`）；
- 加 `.vscode/launch.json` 支持 F5 调试 `app/main.py`（可选，不阻塞）。

---

## 5. 项目结构

```
E:\course_task\homework3\
├─ app\
│  ├─ main.py            # FastAPI 入口：路由 + WS + 静态文件 + 生命周期
│  ├─ config.py          # 全部阈值/路径集中在此（读 .env）
│  ├─ schemas.py         # pydantic 模型：Box / FrameResult / Identity
│  ├─ pipeline.py        # 编排：帧 → 检测 → 跟踪 → 重识别 → 结果
│  ├─ detector.py        # YOLO11n 封装
│  ├─ tracker.py         # ByteTrack 包装 + 轨迹生命周期
│  ├─ reid.py            # 特征提取（MobileNetV3 / 颜色直方图 / 可选 OSNet）
│  ├─ gallery.py         # 身份库：注册、匹配、多模板、淘汰
│  ├─ recorder.py        # 服务端录制标注视频
│  └─ utils.py           # 画框、NMS 后处理、crop 扩边、计时
├─ web\
│  ├─ index.html         # 主界面（手机端）
│  ├─ app.js             # 取流、发送、叠框、长按手势、状态机
│  ├─ style.css
│  ├─ manifest.webmanifest
│  ├─ sw.js              # 离线缓存（PWA）
│  └─ icons\             # 192/512 图标（先用纯色方块占位）
├─ scripts\
│  ├─ setup_env.ps1      # 一键建环境+装依赖（幂等）
│  ├─ fetch_weights.ps1  # 多源下载权重
│  ├─ gen_cert.py        # 生成 HTTPS 自签证书（含 LAN IP 的 SAN）
│  ├─ run.ps1            # 启动服务（自动挑 IP、打印手机访问地址）
│  ├─ check_mirrors.ps1  # 探测各镜像可用性，输出推荐源
│  ├─ calibrate_reid.py  # 阈值标定：跑同一人/不同人相似度分布，出表格
│  └─ bench.py           # 性能基准：FPS/延迟 vs 分辨率/模型/设备
├─ weights\              # yolo11n.pt（+ 可选 osnet）
├─ data\
│  ├─ samples\           # 测试图片、照片注册样本
│  └─ clips\             # 自录测试视频（出画再入画等场景）
├─ outputs\              # 录制的 mp4、身份缩略图、日志
├─ tests\                # pytest：reid 余弦、gallery 匹配、协议解析
├─ certs\                # 证书（.gitignore）
├─ docs\                 # 本方案 + 论文/报告大纲 + 截图
├─ requirements.txt
├─ .env.example
├─ .gitignore
├─ PROGRESS.md
└─ README.md             # 安装、运行、手机接入三步走
```

---

## 6. 模块规格与接口契约

### 6.1 配置（`.env.example` → `.env`）

```ini
APP_HOST=0.0.0.0
APP_PORT=8443
HTTPS_CERT=certs/cert.pem
HTTPS_KEY=certs/key.pem
# 视频源：ws=手机浏览器推送；ipcam=OpenCV 拉 IP 摄像头（降级方案）
SOURCE=ws
IPCAM_URL=http://192.168.1.23:8080/video

DET_MODEL=weights/yolo11n.pt
DET_IMGSZ=640
DET_CONF=0.35
DET_IOU=0.5
DET_DEVICE=0            # 0=GPU, cpu=CPU
TARGET_CLASSES=0        # 0=person；留空=全部 COCO 类

TRACKER=bytetrack.yaml
TRACK_MAX_AGE=30        # 帧数，轨迹丢失后保留时长

REID_MODEL=mobilenet_v3_small   # 或 osnet_x0_25
REID_EMA=0.9                    # 特征指数平滑系数
REID_TAU_HIGH=0.65              # 判定"同一个人"的余弦阈值
REID_TAU_LOW=0.45               # 低于此值解绑（防误绑）
REID_MARGIN=0.05                # 与次优身份的最小差距
REID_CONFIRM_FRAMES=3           # 连续几帧通过才确认绑定
REID_MAX_TEMPLATES=5            # 每个身份最多保留几个模板特征
REID_W_APPEAR=0.85              # 融合权重：外观
REID_W_COLOR=0.15               # 融合权重：颜色直方图

JPEG_QUALITY=0.65
MAX_SIDE=640
RECORD_FPS=15
```

### 6.2 WebSocket 协议（`/ws/stream`）

**客户端 → 服务器**
```json
{ "type": "frame", "seq": 128, "ts": 1734567890123,
  "w": 960, "h": 540, "img": "<base64 JPEG>" }
```

**服务器 → 客户端**
```json
{ "type": "result", "seq": 128,
  "fps": 18.4, "latency_ms": 62,
  "boxes": [
    { "track_id": 7, "cls": 0, "name": "person", "score": 0.91,
      "xyxy": [0.31, 0.22, 0.58, 0.94],          // 归一化 0~1，前端乘画布尺寸
      "identity_id": "ID-01",                      // 未绑定为 null
      "state": "locked",                           // none | candidate | locked
      "sim": 0.71 }                                // 匹配相似度（调试用）
  ],
  "identities": [ { "id": "ID-01", "name": "长按锁定",
                    "thumb": "/outputs/identities/ID-01.jpg", "online": true } ] }
```

**事件通道**：同一 WS 也承载 `{"type":"event","name":"lock_created"|"relocked"|"lost","identity_id":"ID-01"}`
—— 前端据此弹 Toast、震动（`navigator.vibrate(50)`）。

### 6.3 HTTP 路由

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/` | 主页面（手机端） |
| GET | `/pc` | 桌面调试页（本地摄像头 `getUserMedia`，localhost 免 HTTPS） |
| POST | `/api/lock` | `{track_id, seq}` → 把该轨迹当前特征注册为身份，返回 `{identity_id}` |
| POST | `/api/select` | `{x, y}`（归一化点）→ 服务器挑最近框锁定（长按点空时的兜底） |
| POST | `/api/identities/photo` | multipart 上传照片 → 检测最大人 → 建身份，返回 `{identity_id, thumb, quality}` |
| GET | `/api/identities` | 列出身份库 |
| DELETE | `/api/identities/{id}` | 删除身份（含缩略图） |
| POST | `/api/record/start` \| `/stop` | 服务端录制标注视频 → 返回文件路径 |
| GET | `/api/health` | 返回设备、模型、FPS、镜像配置状态 |
| GET | `/outputs/*` | 静态：缩略图、录制视频 |

**错误约定**：统一 `{"ok": false, "code": "...", "message": "中文提示"}`。前端必须把 `message` 直接显示给用户（不要只 console）。

关键错误码：`NO_TARGET_IN_PHOTO`（照片里没检测到人）、`MULTI_PERSON_PHOTO`（多人，已自动取最大并提示）、`TRACK_GONE`（锁定目标已消失，锁定失败）、`REID_NOT_WARM`（轨迹观测太少，等 0.3 秒再锁）。

### 6.4 检测（`detector.py`）

```python
class Detector:
    def __init__(cfg): self.model = YOLO(cfg.DET_MODEL)
    def detect(self, frame_bgr) -> list[Box]:
        r = self.model.predict(frame_bgr, imgsz=cfg.DET_IMGSZ, conf=cfg.DET_CONF,
                               iou=cfg.DET_IOU, classes=cfg.TARGET_CLASSES,
                               device=cfg.DET_DEVICE, verbose=False)[0]
        return [Box(xyxy=..., cls=..., score=...) for ...]
```
- 首次调用前 `torch.cuda.is_available()` 探测，写日志。
- **不要**在 `detect` 里做跟踪；跟踪只走 `tracker.py`。

### 6.5 跟踪（`tracker.py`）

用 ultralytics 的 `model.track(..., persist=True, tracker=cfg.TRACKER)` 拿到 `Boxes.id`，然后由本项目维护轨迹状态表：

```python
@dataclass
class TrackState:
    track_id: int
    first_seen: int      # 帧号
    last_seen: int
    hits: int
    emb: np.ndarray|None # EMA 外观特征
    emb_n: int           # 已累积观测数
    identity_id: str|None
    cand_id: str|None    # 候选匹配
    cand_hits: int
    last_box: tuple
```

生命周期：
- 新 `track_id` 出现 → 建 State，`hits=1`；
- 每帧更新 `last_seen/hits`，抽特征更新 `emb`；
- `now - last_seen > TRACK_MAX_AGE` → 删 State，但**身份库里保留身份**（这就是 R4 的基础）；
- `hits < 5` 时不允许锁定（特征不稳），返回 `REID_NOT_WARM`。

### 6.6 重识别（`reid.py` + `gallery.py`）—— 核心

**特征提取**
```
crop（按框扩 10% 边）→ resize 128×256 → ImageNet 归一化
→ MobileNetV3-Small(pretrained) 倒数第二层 → 576 维 → L2 归一化
颜色特征：HSV 直方图（H:16, S:8, V:8）→ 128 维 → L2 归一化
embedding = concat，相似度 = W_APPEAR*cos(appear) + W_COLOR*cos(color)
```
- **水平翻转 TTA**（正反各前向一次取平均）只在注册身份/照片注册时用，实时帧不用（省算力）。
- **EMA**：`emb = α*emb + (1-α)*new`（α=0.9），抑制单帧抖动。
- 只对"本帧未绑定身份"或"每 3 帧"的轨迹算特征，控制开销。

**身份库（Gallery）**
```python
@dataclass
class Identity:
    id: str                 # "ID-01"
    name: str               # 默认"长按锁定"/"照片注册"
    templates: list[np.ndarray]   # 多模板，最多 5 个
    source: str             # lock | photo
    thumb_path: str
    created_at: float
    last_seen: float
    online: bool
```

**匹配算法（伪代码，务必与文字一致，论文要照这个写）**
```
for track in tracks_without_identity:
    if track.emb is None or track.hits < 3: continue
    sims = [max(cos(track.emb, t) for t in ident.templates) for ident in gallery]
    best, second = top2(sims)
    if best >= TAU_HIGH and (best - second) >= MARGIN:
        track.cand_id, track.cand_hits = best.id, track.cand_hits + 1
        if track.cand_hits >= CONFIRM_FRAMES:
            bind(track, best)                       # 变绿 + 发 relocked 事件
            append_template(best, track.emb)        # 多模板扩展（提升再次出现的鲁棒性）
    else:
        track.cand_hits = 0; track.cand_id = None

# 已绑定轨迹的反向校验：防止绑错
for track in bound_tracks:
    if sim(track.emb, track.identity) < TAU_LOW for K=5 连续帧:
        unbind(track)                                # 回白色，身份留在库里
```

**为什么这样能实现 R4**：目标离开画面 → ByteTrack 的 `track_id` 消失 → 但 `Identity` 仍留在库里；人再次进入 → 得到**新的 track_id** → 逐帧算特征 → 与库里模板余弦相似度超阈值 → 连续 3 帧确认 → 重新绑定同一 `ID-01` → **框依旧绿色**。用户看到的就是"系统仍然认识这个人"。

**阈值标定（必做，这是论文的实验数据来源）**：`scripts/calibrate_reid.py`
- 输入：`data/samples/pairs/same/*.jpg`（同一人不同帧，≥15 对）、`diff/*.jpg`（不同人，≥15 对）
- 输出：相似度分布直方图 + 一张表（阈值 0.50/0.55/…/0.75 对应的 TAR/FAR），自动推荐 `REID_TAU_HIGH`
- 结论写进论文「实验结果分析」

### 6.7 前端交互（`web/app.js`）

**颜色状态机（必须严格按此实现，这是需求 R3/R4 的可见证据）**

| 状态 | 画法 |
|---|---|
| `none` 未绑定 | 白色 2px 实线 + 灰底标签 `person 0.91` |
| `selected` 短按选中 | 黄色 2px 实线 |
| `candidate` 匹配确认中（<0.5s） | 绿色 2px **虚线** + 标签 `识别中…` |
| `locked` 已锁定 | 绿色 3px 实线 + 绿底标签 `ID-01` + 左上角小绿点脉冲 |
| 身份离线 | 不画框，身份条里显示为灰色头像 |

**长按锁定**
```js
let pressTimer = null, pressTarget = null;
canvas.addEventListener('pointerdown', e => {
  const hit = hitTest(e, lastBoxes);           // 归一化坐标命中测试
  pressTarget = hit;
  if (!hit) return;
  pressStart = performance.now();
  pressTimer = setTimeout(() => {
    sendLock(hit.track_id);                    // → POST /api/lock
    navigator.vibrate?.(50);
    drawProgressRing(hit);                     // 0.6s 进度环动画
  }, 600);
});
canvas.addEventListener('pointerup', () => {
  clearTimeout(pressTimer);
  if (pressTarget && performance.now() - pressStart < 600) selectBox(pressTarget);
});
// pc 端快捷：右键 / 字母 L 锁定当前选中框
```
- 长按判定 **600ms**，进度环在 600ms 内画满，给用户"按住了"的反馈；
- 长按点在空白处 → Toast「请按住目标框内」；
- 发送帧的节流：`requestAnimationFrame` 里判断"上一帧结果还没回来就跳过"，保证不堆积。

**取流**
```js
const stream = await navigator.mediaDevices.getUserMedia({
  video: { facingMode: { ideal: 'environment' },
           width: { ideal: 1280 }, height: { ideal: 720 } },
  audio: false });
```
- 可见 `<video muted playsinline autoplay>`，**叠一个同尺寸 `<canvas>` 画框**；
- 发送时用离屏 canvas 缩放至长边 640 再 `toBlob('image/jpeg', 0.65)`；
- 熄屏/切后台（`visibilitychange`）暂停发送，回来重连 WS。

**UI 元素**：顶部 FPS/延迟、右上「上传照片」、底部身份条（头像 + 名字 + 删除）、录制按钮、镜像/前后摄切换。

### 6.8 录制（`recorder.py`）

- `/api/record/start` 后，服务器把"画了框的帧"写 `cv2.VideoWriter('outputs/rec_YYYYmmdd_HHMMSS.mp4', fourcc('mp4v'), 15, (w,h))`；
- 同时每 30 帧写一行 `outputs/rec_*.jsonl`（track→identity 绑定事件日志），方便写论文时统计 ID switch；
- 这个文件是「录屏之外的第二种素材」，演示视频可以直接用它做画中画。

---

## 7. 手机摄像头接入方案（4 选 1，按顺序尝试）

> **这是最容易翻车的一步，必须提前一天验证完。** 核心矛盾：浏览器调摄像头要求**安全上下文**（HTTPS 或 localhost），而局域网 IP 访问是 HTTP。

| 优先级 | 方案 | 做法 | 适用/风险 |
|---|---|---|---|
| **A（首选）** | `mkcert` 本地 CA + 手机安装根证书 | 1) 用 gh 代理下 `mkcert.exe`；2) `mkcert -install`；3) `mkcert -cert-file certs\cert.pem -key-file certs\key.pem 192.168.x.x localhost 127.0.0.1`；4) 把 `rootCA.pem` 发到手机，设置→安全→安装 CA 证书；5) 手机访问 `https://192.168.x.x:8443` | 最干净，Chrome 对用户安装的 CA 是信任的，摄像头可用 |
| B | 纯自签证书 | `scripts/gen_cert.py` 用 cryptography 生成带 SAN(IP) 的自签证书，uvicorn 加载；手机点「高级 → 继续访问」 | 少数 Android/Chrome 版本即使点继续，`getUserMedia` 仍被拒绝 → 只用 5 分钟验证，不行立刻转 A/C |
| C | Chrome 白名单 | 手机 Chrome 打开 `chrome://flags/#unsafely-treat-insecure-origin-as-secure`，填入 `http://192.168.x.x:8000`，重启 Chrome | 免证书；但 flag 位置随版本变化，且部分厂商浏览器没有 |
| **D（保底）** | IP 摄像头 App + OpenCV 拉流 | 手机装「IP 摄像头 / IP Webcam」（国内应用商店均有），启动得 `http://手机IP:8080/video`；本项目设 `SOURCE=ipcam`，PC 端 OpenCV 直接读；**UI 在 PC 浏览器 `http://localhost:8000` 打开（localhost 天然是安全上下文）**，鼠标长按代替手指长按 | 100% 能跑通，完全不依赖证书。**演示日兜底就用这个** |

实现要求：
- `SOURCE=ws` 与 `SOURCE=ipcam` 两条路径都要在 `pipeline.py` 里支持，共用同一套检测/跟踪/重识别；
- `scripts/run.ps1` 打印 3 行可直接复制的地址（PC localhost、手机 https、ipcam 模式）；
- `GET /api/health` 里显示当前 `SOURCE` 与证书状态，方便现场排障。

---

## 8. 交互与体验细节（容易被忽略但影响演示效果）

1. **锁定失败要有解释**：轨迹太新（`hits<5`）→「请让目标在画面中停 0.3 秒后再按住」；目标已消失 →「目标已离开画面」。
2. **身份条**：底部横向滚动的绿色小卡片（缩略图 + ID），点击可高亮该目标，长按可删除。
3. **重识别成功时要"有戏"**：框从绿色虚线 → 实线 + Toast「ID-01 重新识别成功」+ 短震动。这是评分老师唯一会记住的瞬间。
4. **不要画满屏框**：只画 `TARGET_CLASSES` 内的类；置信度 < 0.45 的框淡化处理（alpha 0.35）。
5. **画面镜像**：前置摄像头要 `scaleX(-1)` 处理，否则左右反了，长按会点错框。
6. **横竖屏**：手机竖屏时视频会旋转，前端要按 `videoWidth/videoHeight` 正确设置 canvas 尺寸（不要用 CSS 尺寸算坐标）。

---

## 9. 分阶段任务计划

> 每个 Phase 都写了「验收命令」，Codex 必须实际跑出结果再进入下一阶段。
> 天数按"每天 4 小时有效投入"估算。

### P0 · 环境与骨架（0.5 天）
- [ ] `conda create -n vitrack python=3.11`，装依赖，`torch.cuda.is_available()==True`
- [ ] 下载 `weights/yolo11n.pt`，跑通单图检测
- [ ] 创建目录结构、`.gitignore`、`requirements.txt`、`README.md`、`PROGRESS.md`、`git init` + 首次提交
- [ ] `scripts/check_mirrors.ps1` 输出各镜像可用性表

**验收**：`python -c "from ultralytics import YOLO; m=YOLO('weights/yolo11n.pt'); print(m.predict('data/samples/test.jpg', device=0)[0].boxes)"` 有输出；`git log --oneline` 有提交。

### P1 · PC 端闭环（1 天）
- [ ] `detector.py` + `pipeline.py` + FastAPI 起服务
- [ ] `/pc` 页面：PC 摄像头 → 送帧 → 回框 → 叠框，显示 FPS
- [ ] `/api/health` 可用

**验收**：PC 浏览器打开 `http://localhost:8000/pc`，画面里人和物体有白框，FPS ≥ 15（GPU）。

### P2 · 手机接入（1 天）
- [ ] HTTPS 证书方案落地（先 B 试 5 分钟，不行转 A，再不行转 D）
- [ ] 手机页面可用：取流、叠框、FPS/延迟显示
- [ ] `SOURCE=ipcam` 模式并联调通
- [ ] `scripts/run.ps1` 一键启动并打印网址

**验收**：手机浏览器上看到自己的画面且有稳定白框；连续运行 5 分钟不断流。**必须两种模式都能跑。**

### P3 · 跟踪 + 长按锁定（1 天）
- [ ] ByteTrack 接入，框上带 `track_id`
- [ ] 长按 600ms → `/api/lock` → 框变绿 → 跟随移动
- [ ] 短按选中（黄框）、Toast、震动
- [ ] 轨迹丢失后 30 帧内重新捕获（同一 track_id 之外的情况此时允许变白）

**验收**：长按后框变绿并跟随；人走出画面 3 秒内回来 → 允许出现"短暂白框再变绿"（P4 才彻底解决）；`TRACK_GONE`/`REID_NOT_WARM` 提示正确。

### P4 · 长时重识别（2–3 天，核心）
- [ ] `reid.py` 特征提取（含 EMA、翻转 TTA）
- [ ] `gallery.py` 身份库、多模板、margin 判定、反向校验解绑
- [ ] `calibrate_reid.py` 标定阈值，写入 `.env`
- [ ] 前端 `candidate`（绿虚线）→ `locked`（绿实线）状态机
- [ ] 绑定事件日志写入 `outputs/*.jsonl`

**验收（三条，缺一不可）**
1. 长按锁定 A → A 走出画面 **10 秒**后走回 → **≤0.5 秒内**重新变绿，ID 不变；
2. 画面里同时出现两个人，锁定 A，B 从 A 身前走过 → **B 不变绿**（不串号）；
3. **反向用例**：锁定 A 后换一个穿着差异明显的人进入画面 → **不变绿**（不误认）。

### P5 · 照片注册（0.5 天）
- [ ] `/api/identities/photo`：检测最大人 → 扩边 crop → 特征入库 → 生成缩略图
- [ ] 前端上传按钮 + 身份条展示
- [ ] 边界处理：无人 / 多人 / 非人照片 → 对应错误码与中文提示

**验收**：上传一张照片 → 3 秒内视频里出现该人时自动变绿锁定；上传一张风景图 → 提示「照片中没有检测到人物」。

### P6 · 录制、PWA、性能打磨（1 天）
- [ ] 服务端录制 mp4 + 事件日志
- [ ] PWA：manifest + sw + 图标，`添加到主屏幕` 后全屏无地址栏
- [ ] `bench.py` 出一张性能表（CPU/GPU × imgsz 480/640 × n/s 模型）
- [ ] 降级开关：帧率不足时自动把 `MAX_SIDE` 降到 480
- [ ] 冷启动 60 秒长稳测试（内存不涨、FPS 不塌）

**验收**：手机主屏图标点开全屏运行；`outputs/` 里有可播放的标注 mp4；bench 表已生成。

### P7 · 交付材料（3 天，可与 P5/P6 并行）
- [ ] `README.md`：三步走（装环境 / 下权重 / 起服务+手机接入）
- [ ] 论文（≥3000 字，见第 11 节大纲）
- [ ] 实验报告（课上实践程序）
- [ ] PPT（算法原理 3–4 页 + 成果 1–2 页）
- [ ] 演示视频（3–5 分钟，脚本见第 14 节）
- [ ] 打包 `学号+姓名.zip` ≤ 200MB

**总工期：约 8–10 个工作日开发 + 3 天写作。** 建议顺序：**P0→P1→P2 先把"能演示的骨架"立起来（3 天）**，然后 P4 尽早试（有风险），P3/P5 穿插。

---

## 10. 测试与实验（论文的"实验结果分析"直接取这里的数）

### 10.1 自建测试集（不用下载任何数据集，规避网络问题）

在 `data/clips/` 录 8–10 段 30 秒的视频，每段标注一个"考察点"：

| 编号 | 场景 | 预期 |
|---|---|---|
| C1 | 单人出画 5s 后回来 | 重新变绿 |
| C2 | 单人出画 15s 后回来 | 重新变绿 |
| C3 | 单人出画 60s 后回来 | 尽量绿（记为边界） |
| C4 | 两人交叉行走 | 不串号 |
| C5 | 不同人（同色衣服）先后入画 | 不误认 |
| C6 | 侧面/背影 | 记录成功率 |
| C7 | 光照变化（开/关灯） | 记录成功率 |
| C8 | 部分遮挡（走过柱子） | 轨迹连续 |
| C9 | 快速穿过画面（1s 内） | 记录是否漏检 |
| C10 | 手机走动（拍摄者移动） | 记录抖动下稳定性 |

### 10.2 指标

| 指标 | 定义 | 工具 |
|---|---|---|
| 重识别成功率 | 重入画后 1s 内正确变绿的比例（人工计数） | 手工表 |
| 误绑定率 | 不同人被绑成已知身份的次数 / 总进入次数 | 手工表 |
| ID 切换次数 | 同一人在一段视频里 identity 变更次数 | `outputs/*.jsonl` |
| 延迟 | 手机按下到框更新（录屏逐帧看） | 手机秒表 + 录屏 |
| FPS | 服务端 `fps` 字段 | `/api/health` |
| GPU/CPU 占用 | 任务管理器截图 | — |

### 10.3 必须做的两组对比（论文的核心图表）

1. **特征后端对比**：`MobileNetV3-Small` vs `OSNet-x0.25`（若能装上）/ vs `纯颜色直方图`，在同一批 pairs 上的 TAR@FAR。
2. **分辨率-帧率权衡**：imgsz 480 / 640 / 800 × CPU/GPU 的 FPS 表格。

> OSNet 装不上不阻塞：在论文里写"受国内网络限制未能获取 OSNet 预训练权重，改用 ImageNet 预训练 MobileNetV3 作为外观编码器，并在第 X 节讨论其局限"——这是**诚实且专业**的处理，比编造数据好得多。

---

## 11. 交付物清单（对齐 PPT 要求）

| PPT 要求 | 本项目产出 | 备注 |
|---|---|---|
| 源码电子版 1 份 | `vitrack/` 源码（`git archive` 或直接压缩，**排除** `envs/`、`certs/`、`outputs/*.mp4`、`data/clips/`） | `weights/yolo11n.pt` 5.4MB 建议**一起打包**，老师那边不一定能下 |
| 学术论文（≥3000 字） | `docs/论文-视觉目标检测与跟踪.docx` | 大纲见下 |
| 录制视频 1 份（成果） | `docs/演示视频-成果.mp4` | 3–5 分钟 |
| 课上实践程序软件实验报告 | `docs/实验报告.docx` | 按课堂上发的模板写，**先确认模板格式** |
| 录制视频（实践） | 可选，与上面视频合并 | 与老师确认是否需要两份 |
| PPT 5 分钟 | `docs/汇报.pptx` | 原理 3 页 + 演示 2 页 |
| 压缩包 | `学号+姓名.zip` ≤ 200MB | 打包前跑第 11.2 检查表 |

### 11.1 论文大纲（≥3000 字，建议 4500 字）

```
题目：基于 YOLO 检测与外观重识别的移动端视觉目标跟踪系统
摘要（中文 300 字 + 英文 Abstract）
1 引言
  1.1 研究背景与意义（视频监控、智能交互、机器人跟随）
  1.2 本文工作与贡献（手机为采集端的轻量方案 + 长按注册的交互式 ReID）
2 研究现状分析（**引用真实文献，禁止编造**）
  2.1 目标检测：两阶段(Faster R-CNN) → 单阶段(YOLO 系列/SSD) → Transformer(DETR)
  2.2 多目标跟踪：SORT → DeepSORT → ByteTrack → BoT-SORT
  2.3 行人重识别：表征学习(OSNet/FastReID) → 度量学习 → 无监督聚类；文献计量
  2.4 现有工作不足 → 本文定位
3 研究方法（详细，占篇幅 1/3）
  3.1 系统总体架构（架构图）
  3.2 检测模块：YOLO11 结构、损失、推理参数
  3.3 跟踪模块：ByteTrack 的两阶段关联、卡尔曼滤波、轨迹生命周期
  3.4 重识别模块：外观编码器、颜色特征融合、EMA、多模板身份库、双阈值+margin+连续帧确认（伪代码）
  3.5 交互式注册：长按锁定、照片注册
  3.6 系统实现：前后端分工、WebSocket 协议、PWA、时延预算
4 实验结果与分析
  4.1 实验环境（RTX 3060 Laptop 6GB / i7 / 手机型号）
  4.2 数据与测试场景（10.1 的 C1–C10）
  4.3 重识别性能（阈值标定曲线 + 成功率表）
  4.4 跟踪稳定性（ID 切换、两人交叉）
  4.5 性能分析（分辨率×设备 FPS 表 + 延迟）
  4.6 失败案例分析（换衣、强逆光、极小目标）
5 结论与展望
参考文献（≥10 篇，GB/T 7714 格式）
```

**参考文献（真实存在，务必自己核对卷期页码后引用）**：Redmon 等 YOLO/CVPR 2016；Ultralytics YOLO11 技术报告；Bewley 等 SORT/ICIP 2016；Wojke 等 DeepSORT/ICIP 2017；Zhang 等 ByteTrack/ECCV 2022；Aharon 等 BoT-SORT/2022；Zhou 等 OSNet/ICCV 2019；Wang 等 FastReID/CVPR 2020；Ren 等 Faster R-CNN；Carion 等 DETR。
> ⚠️ 引用必须自己核实（作者、年份、会议、页码）。写"研究现状"时用自己的话总结，不要大段搬运。

### 11.2 打包检查表（≤200MB，逐项打勾）

- [ ] `envs/`、`.git/`、`certs/`、`__pycache__/`、`outputs/*.mp4`、`data/clips/` **已排除**
- [ ] `weights/yolo11n.pt` 在包里（5.4MB）
- [ ] `.env.example` 在包里，`.env` 不在（不含本机密码/路径）
- [ ] `README.md` 能从零跑通（在干净目录实测一遍）
- [ ] `requirements.txt` 版本可解析
- [ ] 论文 / 视频 / PPT / 实验报告 都在包里
- [ ] 文件名 `学号+姓名.zip`
- [ ] 解压后体积与压缩包体积都 ≤ 200MB

---

## 12. 风险与预案

| 风险 | 概率 | 影响 | 预案 |
|---|---|---|---|
| 手机打不开摄像头（HTTPS） | **高** | 演示不了 | 第 7 节 A→B→C→D 四级降级，**D 必须提前验证** |
| 重识别认不出来 | 中 | R4 失败 | 降 `TAU_HIGH` 到 0.55 + 加 `MARGIN`；多模板；把要求改成"同一位置附近重入"；最坏情况退化为"颜色+体型"启发式 |
| 重识别认错人 | 中 | 反向丢分 | 提高 `TAU_HIGH` + 连续帧确认 + 空间门限（短时丢失加位置距离约束） |
| 帧率低（<10fps） | 中 | 体验差 | `MAX_SIDE=480`、`imgsz=480`、`DET_CONF=0.45`、跳帧检测（每 2 帧检测 1 次，中间用跟踪预测） |
| 权重/依赖下不下来 | 中 | 卡进度 | 第 13 节镜像表；YOLO 权重必有一个源可用；torch 用 PyPI 清华源 |
| 局域网不通（WiFi AP 隔离） | 中 | 连不上 | 手机开热点让 PC 连；USB 共享网络；`adb reverse` |
| 演示日现场没网 | 高 | 装不了依赖 | 提前 `pip download -d offline_pkgs` 全量离线包，README 写离线安装步骤 |
| 200MB 超限 | 低 | 提交被打回 | 视频压到 1080p/8Mbps 以内；不打包 venv 和数据 |

---

## 13. 国内镜像替换总表（Codex 按此顺序尝试）

| 资源 | 官方地址 | 国内替代（按优先顺序） | 备注 |
|---|---|---|---|
| Miniconda 安装包 | repo.anaconda.com | 清华 `https://mirrors.tuna.tsinghua.edu.cn/anaconda/miniconda/` | 已装，可跳过 |
| pip 包 | pypi.org | 清华 `https://pypi.tuna.tsinghua.edu.cn/simple` → 阿里云 `https://mirrors.aliyun.com/pypi/simple/` | `pip config set` |
| conda 频道 | repo.anaconda.com | 清华 anaconda 镜像（见 4.1） | — |
| PyTorch | download.pytorch.org | ① 直接 `pip install torch`（Windows 版自带 CUDA，走清华源，最省事）② 阿里云 `https://mirrors.aliyun.com/pytorch-wheels/` ③ 官方 cu121 索引 | 先试 ① |
| YOLO11 权重 | github.com/ultralytics/assets/releases | ① `https://ghfast.top/https://github.com/...`（前缀法）② `https://gh-proxy.com/https://github.com/...` ③ HF 镜像 `HF_ENDPOINT=https://hf-mirror.com` + `hf download Ultralytics/YOLO11 yolo11n.pt` ④ ModelScope | 参考 [hf-mirror](https://hf-mirror.com)、[gh 加速列表](https://cloud.tencent.cn/developer/article/2652607) |
| OSNet 权重（可选） | torchreid Releases / Google Drive | ① boxmot 自带下载（`HF_ENDPOINT` 生效）② ModelScope 搜 osnet ③ **跳过，用 MobileNetV3 代替** | Google Drive 直链基本不可用，别浪费超过 10 分钟 |
| torchvision 预训练权重 | download.pytorch.org/models | ① 直连（多数情况可通）② `HF_ENDPOINT=https://hf-mirror.com` + timm 的 `mobilenetv3_small_100` ③ 把 `.pth` 手工放到 `%TORCH_HOME%` | 失败就用方案 C 的等价初始化 + 只用颜色特征兜底 |
| mkcert | github.com/FiloSottile/mkcert/releases | `https://ghfast.top/https://github.com/FiloSottile/mkcert/releases/download/v1.4.4/mkcert-v1.4.4-windows-amd64.exe` | 或 `choco install mkcert`（源慢） |
| HuggingFace | huggingface.co | `$env:HF_ENDPOINT="https://hf-mirror.com"` | 全局设一次 |
| 手机 IP 摄像头 App | Google Play「IP Webcam」 | 国内应用商店搜「IP 摄像头 / IP Webcam」，或 `pip install` 不适用 | D 方案保底 |
| 参考论文 | 各会议官网 | 知网 / 万方 / 学校图书馆 VPN；arXiv 可直连 | 论文引用务必核实 |

**落地要求**：把 URL 前缀统一抽到 `scripts/check_mirrors.ps1` 的变量里，并在 `README.md` 写「如果 ghfast.top 失效，改这一个变量即可」。

---

## 14. 演示脚本（现场 5 分钟，逐句可照读）

| 时间 | 动作 | 台词要点 |
|---|---|---|
| 0:00–0:40 | 打开手机主屏图标（PWA 全屏） | "这是一个跑在手机浏览器里的 Web App，算力在 PC，手机只负责采集和显示。" |
| 0:40–1:20 | 画面出现多个白框 | "YOLO11n 做检测，ByteTrack 做帧间关联，白色框表示还没建立身份。" |
| 1:20–2:00 | 长按某人 0.6s → 框变绿 | "长按即注册：系统提取该目标的外观特征存入身份库，框变绿表示身份已绑定。" |
| 2:00–2:40 | 该人走出画面 → 停 5–10 秒 → 走回 → 绿框恢复 | **（此处故意停顿，制造"它真的记得"的效果）**"轨迹已经断了，但身份库还在，所以它重新认出这就是 ID-01。" |
| 2:40–3:10 | 另一人从前面走过 | "第二个人没有变绿，说明系统没有串号。" |
| 3:10–3:50 | 上传一张照片 → 该人入画自动变绿 | "也支持用照片注册，用于'我要找这个人'的场景。" |
| 3:50–4:30 | 展示 `outputs/` 里的标注视频 + FPS/延迟数据 | "服务端同步录制带标注的视频，端到端延迟约 200ms。" |
| 4:30–5:00 | 收尾 | "后续可扩展到多人长期跟踪、跨摄像头检索。" |

---

## 15. 待确认事项（本人需要回答的）

1. **提交截止的具体日期**？（PPT 写"2026 年 11 月"，具体哪天？）
2. **"课上编写实践程序软件实验报告"** 是否有独立模板/题目？是同一套系统的报告，还是课堂小练习的报告？
3. 论文是否要求**知网查重**？（如要求，第 2 节"研究现状"必须完全自己改写）
4. 老师是否允许**手机作为采集端**（有的课要求"必须用本机摄像头"）—— 如果不允许，改用笔记本摄像头演示，架构不变。
5. 演示现场是否有稳定 WiFi/热点？
6. 是否需要支持**多个目标同时锁定**（当前设计支持，靠多次长按）？

---

## 附录 A：`README.md` 应包含的三步走（Codex 实现后补齐实际命令）

```powershell
# 1) 环境
conda create -n vitrack python=3.11 -y && conda activate vitrack
pip install -r requirements.txt

# 2) 权重
powershell -File scripts\fetch_weights.ps1

# 3) 启动
powershell -File scripts\run.ps1
#   PC 调试 : http://localhost:8000/pc
#   手机访问: https://<PC局域网IP>:8443   （先按第 7 节装好证书）
```

## 附录 B：最小可行版本（如果只剩 3 天）

砍掉：照片注册(R5)、PWA、服务端录制、OSNet 对比、多类别。
保留：手机取流 → YOLO 检测 → ByteTrack → 长按锁定 → ReID 重识别 → 绿色/白色状态。
这样仍能拿满"核心要求"，只是加分项少。**宁可小，必须能演示。**
