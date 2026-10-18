# ViTrack：视觉目标检测与跟踪

当前工作分支含身份保持实验版，使用方法与验收边界见 [身份保持升级说明](docs/tracking_upgrade.md)。`scripts/run_identity.ps1`明确启用新方法，普通启动仍保持appearance模式；实验尚未通过用户实拍验收。

手机负责采集和显示，电脑执行YOLO11n检测、ByteTrack跟踪与外观匹配。支持浏览器推帧和IP Webcam两种接入方式。

已实现短按选中、600ms长按锁定、右键/L锁定、身份条与删除、丢失后重识别、照片注册、镜像、可选录制、PWA、性能测试和源码打包。

**功能已实现，不代表现场准确率已验收。** 本轮自动检查只用公开样例和合成画面，没有重新访问摄像头。真实人物10秒重入、两人交叉、照片跨场景匹配和安卓主屏安装仍需人工检查。衣物误检提高像素后无改善，按用户要求暂缓。

默认禁止保存实拍内容。照片、人物裁剪和缩略图仅在内存；停止视频或断开会话后清除身份。录制按钮和接口默认均拒绝保存，服务启动不会自动打开摄像头。

0.2.2界面会在实时画面上方常驻显示照片登记成功/失败、ID和缩略图；登记成功与视频中匹配成功分别显示。当前照片按人物整体外观匹配，脸部特写不属于已支持的人脸注册。手动锁定请求的结果与后续身份核验状态也分别显示，“暂未确认身份”不再表述为本人已离开。

定位绿框一闪即消失时，可运行 `envs/vitrack/python.exe -X utf8 scripts/analyze_tracking.py`。脚本读取现有轮换文字记录，输出 `outputs/tracking/diagnostic_report.json`，区分手势取消、操作拒绝以及锁定后因何种分数/门槛撤销绑定；报告不含图片或向量，次数统计不等于识别准确率。

## 三步启动

在项目根目录打开PowerShell。已配置好的本机不必重复安装。

```powershell
# 1. 在项目专用环境安装依赖，不改变其他conda环境
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup_env.ps1 -InstallDependencies

# 2. 准备本地检测与外观权重，已有完整模型时复用
powershell.exe -NoProfile -File .\scripts\fetch_weights.ps1
.\envs\vitrack\python.exe -X utf8 scripts/fetch_reid_weights.py

# 3. 启动服务，之后由用户决定是否开始检测
powershell.exe -NoProfile -File .\scripts\run.ps1 -Mode pc
```

打开终端输出的 `http://localhost:8000/pc`。只有你点击“开始检测”并授予浏览器权限后才使用摄像头。没有授权时可运行后面的公开样例检查。

本轮自动审批阻止了重启已有8443/8001服务，这两个后台服务尚未升级。使用新版源码时，可在终端用 `scripts/run.ps1 -Mode pc -Port 8002` 启动独立端口；手机模式可改用 `-Mode phone -Port 8444`。这些命令不会自动打开摄像头。

配置优先级：进程环境变量 > 项目 `.env` > `app/config.py` 默认值。需要持久配置时复制 `.env.example` 为 `.env`，不要把私有配置放进源码包。

## 手机接入

浏览器模式：手机和电脑接同一Wi-Fi，生成证书，再启动手机服务。

```powershell
.\envs\vitrack\python.exe -X utf8 scripts/gen_cert.py
powershell.exe -NoProfile -File .\scripts\run.ps1 -Mode phone
```

脚本输出手机HTTPS地址。多网卡时按提示用 `-LanIP` 指定与手机相连的电脑地址。手机需要信任证书，显示安全环境就绪后，仍由你手动开始和授权。自签证书兼容性以手机实际显示为准。

IP Webcam降级模式：在本次明确同意使用手机摄像头后，由你启动手机App，关闭云广播、录制和音频，把App显示的视频地址填入配置。

```powershell
# 替换成手机实际地址；配置本身不会连接设备
$env:SOURCE = 'ipcam'
$env:IPCAM_URL = 'http://手机实际地址:8080/video'
powershell.exe -NoProfile -File .\scripts\run.ps1 -Mode pc
```

电脑打开输出地址，勾选同意并点击“开始读取”。停止电脑读取后，还要在手机停止IP Webcam，确认摄像头使用提示结束。此模式不会打开电脑浏览器摄像头。

## 操作方法

- 白框是当前检测，`#1` 是本次视频里的轨迹号。
- 短按框内变黄；按住0.6秒、右键或选中后按L，登记为 `ID-01` 并显示绿框。同一时间只锁一个人，锁第二个人会解除第一个；再次长按绿框取消，取消后不会自动恢复旧目标。目标太新、消失或太小时会说明失败原因。
- 绿色虚线表示匹配确认中，绿色实线表示已绑定身份。消失目标不补画框，身份条显示离线。
- 轨迹过期不删除身份；停止视频或断开会话后清除身份。匹配依据外观，不是身份认证，不保证换衣后仍能匹配。
- 先开始检测，再上传照片。照片登记也会替换当前锁定目标。接受小于6MiB、宽高不超过4096的JPEG/PNG。多人取最大人物并提示，无人明确报错。照片仅发给提供页面的电脑，在内存处理。
- 镜像同时处理画面、框和触点，标签保持正向。可取消“左右镜像”。
- 浏览器提供安装入口时，可添加到主屏幕。离线只能打开界面，检测仍需连接电脑；缓存不含帧、照片、缩略图或视频。
- 当前录制禁用。只有以后另行明确允许保存、修改保存策略并在页面确认后才录制本机标注MP4；功能存在不等于已获保存授权。

## 项目结构与阅读顺序

```text
app/
  main.py           # 后端入口app.main:app，启停与路由
  config.py         # 配置读取和检查
  schemas.py        # 请求、检测框和结果格式
  detector.py       # BGR图像转YOLO像素框
  tracker.py        # 每路视频的ByteTrack关联
  session.py        # 观测、锁定、候选与身份状态
  reid.py           # 裁剪转外观和颜色特征
  gallery.py        # 多模板身份库与候选排序
  pipeline.py       # 解码、检测、跟踪、重识别的共享入口
  photos.py         # 限大小的内存照片解析
  recorder.py       # 明确允许后才录制
  ipcamera.py       # 确认后读取IP源，停止时释放
web/
  index.html        # 页面结构
  start.js          # 前端入口，选择唯一视频模式
  app.js / camera.js # 浏览器取流与设备管理
  ipcam.js          # IP源观看和停止
  interaction.js    # 共用手势、照片、身份条
  box_smoother.js   # 仅平滑显示坐标
  style.css         # 手机和电脑布局
  manifest.webmanifest / sw.js / icons/ # PWA
scripts/            # 安装、启动、标定、基准、打包
tests/              # 自动检查
docs/               # 原方案、使用和交付说明
weights/            # 本地模型
outputs/            # 数值报告和源码包
work/               # 临时检查，不作为交付
```

建议先读 `schemas.py` 理解一帧结果，再读 `main.py → pipeline.py → session.py`，最后读 `tracker.py/reid.py/gallery.py` 和 `web/interaction.js`。逐函数的用途、输入、输出和关键步骤见[代码阅读指南](docs/code_guide.md)。

## 常见参数

- `DET_CONF=0.35`：检测门槛，调高也可能漏人。保持默认，不再围绕衣物反复调整。
- `DET_IMGSZ=640`：模型内部尺寸；`MAX_SIDE=640` 是传输最长边。持续慢时建议传输降到480，模型仍为640。
- `DET_DEVICE=0`：第一张GPU；`cpu` 用于无GPU电脑，通常更慢。
- `TRACK_MAX_AGE=30`：轨迹保留的处理帧数，不是秒数。
- `REID_TAU_HIGH=0.90`：默认更保守，当前帧、登记锚点和外观分量都需支持匹配，可能增加漏匹配。`REID_TAU_LOW=0.45`保留兼容旧配置，新流程不再用它允许旧绿框持续。
- `REID_MARGIN=0.05`：候选接近或更像登记反例时不绑定；`REID_CONFIRM_FRAMES=6`要求连续确认，`REID_COLOR_MIN=0.60`单独检查颜色。不确定时回白框，不用旧EMA维持绿框。
- `REID_EMA=0.9`：特征平滑，越大越保留旧外观；`REID_MAX_TEMPLATES=5` 限制模板数。
- `IDENTITY_LIMIT=20`：会话身份上限，日常建议不超过5人。
- `ALLOW_MEDIA_SAVE=false`：当前保持禁止保存，不因启动或长按自动改变。

实际采用8×4×4=128维HSV颜色特征和576维外观特征。原方案HSV分箱与维度互相矛盾，实际实现已在进度中注明。纯颜色模式须显式选择，权重缺失不会静默降级。

## 不使用摄像头的验证

```powershell
.\envs\vitrack\python.exe -X utf8 -m pytest tests --basetemp=work/pytest -q
.\envs\vitrack\python.exe -X utf8 scripts/verify_stream.py --duration 60 --report outputs/acceptance/full_stream_60s.json
.\envs\vitrack\python.exe -X utf8 scripts/bench.py --frames 10
.\envs\vitrack\python.exe -X utf8 scripts/calibrate_reid.py --diagnostic --output outputs/reid/public_diagnostic.json
.\envs\vitrack\python.exe -X utf8 scripts/calibrate_reid.py --diagnostic --backend color_histogram --output outputs/reid/color_diagnostic.json
```

浏览器检查使用独立Edge和公开样例，始终拒绝摄像头、麦克风权限，不退回真实设备。未装Edge时，浏览器检查明确跳过。

基准默认比较本地n/s模型、480/640/800和CPU/GPU。可选s模型用 `scripts/fetch_weights.ps1 -Model s` 获取；缺失时标记unavailable，不隐式下载。检测器FPS不等于完整链路FPS。

正式标定使用 `--pairs 配对清单.json`。格式为 `{"same":[["同人A.jpg","同人B.jpg"]],"diff":[["人物A.jpg","人物C.jpg"]]}`，路径相对清单，输入应为有授权的既有人物裁剪。每类至少15对、无重复/冲突才允许 `--write-env`。公开图增强诊断禁止自动修改生产门槛。

实际记录：公开样例完整链路约60秒、1190帧、19.837FPS，内存RSS增加0.36MiB，最多1帧在途；12组检测器基准已生成。详细结果以 `PROGRESS.md` 和数值报告为准，不能作为实拍准确率。

## 源码交付

```powershell
.\envs\vitrack\python.exe -X utf8 scripts/package_source.py
.\envs\vitrack\python.exe -X utf8 scripts/verify_package.py
```

第一条生成 `outputs/delivery/vitrack_source.zip` 和SHA256清单，包含必要模型与指定公开样例，排除环境、证书、.env、work、outputs和实拍内容，检查体积不超过200MiB。

第二条在独立解压目录核对摘要，用现有Python环境启动包内服务，实际加载模型、检测公开图、锁定并检查默认禁止保存。它不连接摄像头，也不代表已在另一台电脑重新安装依赖。

源码包不包含全部课程材料。论文正文、课堂实验报告、最终演示视频和个人信息按[交付指南](docs/delivery_guide.md)准备，汇报材料应按实际验收结果整理。第三方资源见[来源说明](docs/third_party.md)。
