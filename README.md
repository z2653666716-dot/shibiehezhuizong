# ViTrack：视觉目标检测与跟踪

当前交付包含按功能保留的身份保持版本。用户指定的开发基线是原8446的`0.3.1-experimental`，固定于`baseline/user-tested-v0.3.1`和`v0.3.1-user-baseline`。A/B/C/D依次修复人脸归属、短漏检、身体等待和远处走近后补充人脸，最后由用户集中验收再决定合并。分支与启动顺序见[集中测试说明](docs/branch_testing.md)，算法说明见[身份保持升级说明](docs/tracking_upgrade.md)。

手机负责采集和显示，电脑执行检测与身份保持。`run_identity.ps1`明确启用YOLO11n、BoT-SORT、OSNet与YuNet/SFace实验组合；普通`run.ps1`仍按`.env`启动，默认appearance为ByteTrack与MobileNet/颜色方案。支持浏览器推帧和IP Webcam两种接入方式。

已实现短按选中、600ms长按锁定、右键/L锁定、身份条与删除、丢失后重识别、照片注册、镜像、可选录制、PWA、性能测试和源码打包。

**功能实现与现场效果分别记录。** 用户基线已反馈照片登记、本人入镜自动变绿、两人轻微移动通过，侧脸没有明显问题；姿态与远近仍会丢失，是后续分支的修复目标。包含A/B/C/D的完整自动回归87项通过，真实姿态/距离、10秒重入、交叉、正式准确率和安卓主屏安装留待集中验收。衣物误检按用户要求暂缓。

默认禁止保存实拍内容。照片、人物裁剪、缩略图和有限人脸/身体特征只在会话内存；停止视频或断开后清除。录制按钮和接口默认均拒绝保存，服务启动不会自动打开摄像头。

实时画面上方常驻显示照片登记状态、ID和缩略图。hybrid支持清晰单人人脸照或单人上半身/全身照，拒绝多人物歧义；appearance按整体外观匹配、多人照片取最大人物，脸部特写不作为其支持范围。登记成功与视频匹配成功分别显示，“暂未确认身份”不等于本人已离开。页面顶部显示实际响应的后端版本，切换Git分支后须重启测试服务。

定位绿框一闪即消失时，可运行 `envs/vitrack/python.exe -X utf8 scripts/analyze_tracking.py`。脚本读取现有轮换文字记录，输出 `outputs/tracking/diagnostic_report.json`，区分手势取消、操作拒绝以及锁定后因何种分数/门槛撤销绑定；报告不含图片或向量，次数统计不等于识别准确率。

## 三步启动

在项目根目录打开PowerShell。已配置好的本机不必重复安装。

```powershell
# 1. 在项目专用环境安装依赖，不改变其他conda环境
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup_env.ps1 -InstallDependencies

# 2. 准备本地检测与外观权重，已有完整模型时复用
powershell.exe -NoProfile -File .\scripts\fetch_weights.ps1
.\envs\vitrack\python.exe -X utf8 scripts/fetch_reid_weights.py
.\envs\vitrack\python.exe -X utf8 scripts/fetch_identity_models.py

# 3. 启动服务，之后由用户决定是否开始检测
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_identity.ps1 -Mode pc -Port 8002
```

打开终端输出的 `http://localhost:8002/pc`。只有你点击“开始检测”并授予浏览器权限后才使用摄像头。没有授权时可运行后面的公开样例检查。

当前后台8446保留用户指定的0.3.1基线，不因切换源码自动升级。集中手机测试建议使用独立8450端口，按分支说明依次停止测试服务、切分支、重新启动并核对页面版本。源码包没有Git历史，分支比较请使用GitHub仓库。

配置优先级：进程环境变量 > 项目 `.env` > `app/config.py` 默认值。需要持久配置时复制 `.env.example` 为 `.env`，不要把私有配置放进源码包。

## 手机接入

浏览器模式：手机连接电脑移动热点，先确认当前网关地址。以下假设热点网关仍为192.168.137.1；现有热点证书可复用，不必重复生成。

```powershell
# 仅首次准备证书或地址确实改变时运行；已有证书先复用
.\envs\vitrack\python.exe -X utf8 scripts/gen_cert.py --output-dir certs/hotspot --ip 192.168.137.1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_identity.ps1 -Mode phone -Port 8450 -LanIP 192.168.137.1
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
- 先开始检测，再上传照片。照片登记也会替换当前锁定目标。接受小于6MiB、宽高不超过4096的JPEG/PNG；hybrid拒绝多人物歧义。安卓相册临时遮住页面时暂停取帧/传帧，最多等待60秒；返回后继续登记，上传最多等待30秒，失败常驻说明。照片仅发给提供页面的电脑，在内存处理。
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
  hybrid_session.py # 人脸/身体/运动证据与短漏检恢复
  faces.py          # YuNet/SFace与一对一归属
  person_features.py / onnx_backend.py # 本地OSNet与执行器
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
- `REID_MARGIN=0.05`：候选接近时不绑定；`REID_CONFIRM_FRAMES=6`在hybrid要求短窗口内6份真实成功证据，短缺失不凑数。`REID_COLOR_MIN=0.60`为appearance的颜色检查，不是人脸门槛。
- `FACE_MATCH_THRESHOLD=0.45`、`BODY_MATCH_THRESHOLD=0.75`：hybrid的人脸与行人门槛；`BODY_HOLD_THRESHOLD=0.55`用于已有连续目标。保持默认，不能直接与MobileNet的0.90比较。
- `IDENTITY_HOLD_SECONDS=2`：可靠证据短缺失时的等待期限；延长会增加沿用旧身份的风险，不推荐为保持绿框而随意增加。
- `REID_EMA=0.9`：特征平滑，越大越保留旧外观；`REID_MAX_TEMPLATES=5` 限制模板数。
- `IDENTITY_LIMIT=20`：底层库保留的容量设置，当前应用的锁定交互仍是同一时间一个目标。
- `ALLOW_MEDIA_SAVE=false`：当前保持禁止保存，不因启动或长按自动改变。

appearance采用576维MobileNet外观与128维HSV，hybrid的OSNet为512维身体特征并另有SFace人脸特征。原方案HSV分箱与维度互相矛盾，实际采用8×4×4。权重缺失不会静默改成随机特征；身份编码器默认CPU是本机实测选择，YOLO仍可在GPU运行。

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

历史appearance公开样例链路约60秒、19.837FPS；hybrid动态批公开640多人样例约12.636FPS，仍低于原15FPS目标。这些来自不同方法与时段，不能当作同一版本的手机帧率或准确率。12组检测器基准另见数值报告。

## 源码交付

```powershell
.\envs\vitrack\python.exe -X utf8 scripts/package_source.py --identity-mode hybrid --output outputs/delivery/vitrack_complete_features.zip
.\envs\vitrack\python.exe -X utf8 scripts/verify_package.py outputs/delivery/vitrack_complete_features.zip --identity-mode hybrid --report outputs/delivery/complete_features_check.json
```

第一条生成当前分支的源码ZIP及SHA256清单，记录模式、运行版本、Git分支/提交和是否有未提交变化；hybrid模式要求三份身份模型齐全。包含必要模型与指定公开样例，排除环境、证书、.env、work、outputs和实拍内容，体积不超过200MiB。该ZIP是当前完整功能源码，不包含所有分支的Git历史。

第二条在独立解压目录核对摘要，用现有Python环境启动包内服务，实际加载模型、检测公开图、锁定并检查默认禁止保存。它不连接摄像头，也不代表已在另一台电脑重新安装依赖。

源码包不包含全部课程材料。论文正文、课堂实验报告、最终演示视频和个人信息按[交付指南](docs/delivery_guide.md)准备，汇报材料应按实际验收结果整理。第三方资源见[来源说明](docs/third_party.md)。
