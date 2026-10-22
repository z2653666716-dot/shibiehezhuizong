# 使用说明：从克隆到手机运行

本说明对应仓库默认分支`baseline/tested-v0.3.6`。电脑负责模型推理，手机浏览器负责采集和显示；配置完成后，可运行根目录`run.py`启动服务。

## 1. 需要准备什么

### 电脑和手机

- **Windows 10/11 64位电脑**。现有环境和启动脚本按Windows编写，macOS、Linux尚未验证。
- **Python 3.11**，由项目环境脚本创建，不要求先手动安装同一版本。
- 建议16GB内存，并预留约15GB磁盘空间给环境、PyTorch和安装缓存；这是配置建议，不是测得的最低硬件要求。
- 有受当前PyTorch构建支持的NVIDIA显卡时可使用GPU；没有NVIDIA显卡也可以走CPU安装步骤，速度会降低，不保证实时帧率。
- 一部能使用浏览器摄像头的手机。已有人工检查使用Android，推荐独立Chrome或Edge浏览器；其他手机系统尚未完整验证。
- 手机与电脑能够在局域网互相访问。推荐手机连接电脑移动热点，避免校园或公共Wi-Fi的设备隔离。

### 系统组件

1. [Git for Windows](https://git-scm.com/download/win)：用于克隆仓库。
2. [Miniconda](https://docs.conda.io/projects/miniconda/)或已有Conda：用于创建项目独立环境。默认安装位置通常是`C:\Users\你的用户名\miniconda3`。
3. Windows PowerShell 5.1或兼容的PowerShell环境。文中的命令在**PowerShell**执行。
4. [Microsoft Visual C++ 2015–2022 x64运行库](https://aka.ms/vs/17/release/vc_redist.x64.exe)：用于PyTorch、OpenCV、ONNX Runtime等原生扩展；安装程序会检查是否已有可用版本。
5. `mkcert`：推荐用于手机HTTPS证书，下文给出安装和Android信任步骤。
6. 使用GPU时，安装支持PyTorch CUDA 12.8构建的NVIDIA驱动，以后文实际CUDA检查为准。这里使用官方PyTorch wheel自带的运行库，不要求另装完整CUDA Toolkit或手工复制cuDNN。

编辑器可选VS Code及其Python扩展。项目没有前端构建步骤，不需要Node.js、npm、数据库或Docker。

## 2. 克隆项目

在准备保存项目的位置打开PowerShell，执行：

```powershell
git clone --branch baseline/tested-v0.3.6 https://github.com/z2653666716-dot/shibiehezhuizong.git
cd shibiehezhuizong
```

后续命令均在这个项目根目录执行。仓库包含源码、网页、公开样例和模型文件；`envs/`、`.env`、证书和运行结果不在Git中，需要在新电脑准备。

检查Git是否可用可运行`git --version`。没有识别到Git时，安装后重新打开终端。

## 3. 安装Python环境和依赖

以下**GPU、CPU两条路径选一条**。环境均创建在项目的`envs/vitrack`，不会安装到Conda的base环境。

### 路径A：NVIDIA GPU

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup_env.ps1 -InstallDependencies
```

该脚本创建Python 3.11环境、安装`requirements.txt`、按需要安装CUDA版PyTorch，并实际执行GPU矩阵运算和torchvision NMS。成功时会提示依赖、GPU运算检查和版本锁定完成。

Conda不在默认位置时，指定实际路径，例如：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup_env.ps1 -CondaPath 'D:\Miniconda3\Scripts\conda.exe' -InstallDependencies
```

这个脚本的`-InstallDependencies`流程**要求GPU检查通过**。仅仅安装过CUDA Toolkit、或`nvidia-smi`能看到显卡，不代表当前PyTorch已经能使用GPU。

### 路径B：CPU

没有NVIDIA显卡或准备先用CPU运行时，先只创建环境，再分别安装CPU版PyTorch和其余依赖：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup_env.ps1
.\envs\vitrack\python.exe -m pip install torch==2.9.1 torchvision==0.24.1 --index-url https://download.pytorch.org/whl/cpu
.\envs\vitrack\python.exe -m pip install -r requirements.txt
.\envs\vitrack\python.exe -m pip check
```

Conda位置不同时，第一条命令同样可以添加`-CondaPath`。CPU路径不要加`-InstallDependencies`，因为那会进入前面的GPU验证流程。

后文创建`.env`后，将`DET_DEVICE=0`改成`DET_DEVICE=cpu`。清单中的`onnxruntime-gpu`支持选择CPU执行器，本项目默认身份编码器就是CPU；不需要再同时安装另一份`onnxruntime`。

### 依赖包及版本

直接依赖以根目录[requirements.txt](../requirements.txt)为准，当前为：

```text
torch==2.9.1
torchvision==0.24.1
ultralytics>=8.3.0,<9
lap>=0.5.12,<1
fastapi>=0.115,<1
uvicorn[standard]>=0.34,<1
python-multipart>=0.0.20,<1
python-dotenv>=1.1,<2
opencv-python>=4.11,<5
onnxruntime-gpu==1.23.2
onnx>=1.17,<2
numpy>=2.0,<3
pillow>=11,<13
cryptography>=45,<49
pytest>=8.3,<10
httpx>=0.28,<1
psutil>=6,<8
```

PyTorch、torchvision和Ultralytics负责检测；ONNX Runtime、ONNX和OpenCV负责人脸与行人模型；FastAPI、Uvicorn和multipart负责接口、视频连接和照片请求；NumPy、Pillow处理图片，cryptography处理证书，dotenv读取配置，psutil读取本机网卡和运行信息。pytest、httpx用于测试；WebSocket等间接依赖由`uvicorn[standard]`等包安装。

`requirements.lock.txt`记录一次已运行环境的具体版本，包含CUDA构建信息，不适合作为CPU路径的通用安装命令。当前已运行的组合包括Python 3.11.17、PyTorch 2.9.1+cu128、torchvision 0.24.1+cu128、ONNX Runtime 1.23.2和RTX 3060 Laptop GPU；这些记录不代表所有硬件组合均已验证。

### 检查环境

```powershell
.\envs\vitrack\python.exe --version
.\envs\vitrack\python.exe -m pip check
.\envs\vitrack\python.exe -c "import torch, cv2, onnxruntime, fastapi, uvicorn; print('torch:', torch.__version__, 'CUDA:', torch.cuda.is_available()); print('YuNet:', hasattr(cv2, 'FaceDetectorYN'), 'SFace:', hasattr(cv2, 'FaceRecognizerSF'))"
```

Python应为3.11，`pip check`应无依赖冲突，人脸接口应为`True`。GPU路径的CUDA应为`True`；CPU路径的CUDA为`False`正常。

## 4. 准备本地配置和模型

首次创建配置；已有`.env`时不会覆盖：

```powershell
if (-not (Test-Path -LiteralPath .env)) {
    Copy-Item -LiteralPath .env.example -Destination .env
}
```

CPU路径打开`.env`，把`DET_DEVICE=0`改成`DET_DEVICE=cpu`；GPU路径保留`0`。不要把文件保存为`.env.txt`。

联合跟踪使用下列模型，已随当前Git分支提供：

```text
weights/
├─ yolo11n.pt                           人物检测
├─ osnet_x0_25_msmt17.onnx               身体特征
├─ face_detection_yunet_2023mar.onnx     人脸检测
└─ face_recognition_sface_2021dec.onnx   人脸特征
```

appearance兼容后端另用`mobilenet_v3_small-047dcff4.pth`；`yolo11s.pt`只用于可选检测器对比。

需要校验或补齐模型时运行：

```powershell
powershell.exe -NoProfile -File .\scripts\fetch_weights.ps1
.\envs\vitrack\python.exe -X utf8 scripts/fetch_identity_models.py
```

已有正确模型会直接复用。网络失败或摘要不符时先处理报错，模型来源、SHA256和许可见[第三方资源](third_party.md)。应用不会在推理过程中隐式下载模型。

## 5. 连接手机与电脑

在Windows“设置 → 网络和Internet → 移动热点”开启热点，让手机连接该热点。需要有可供Windows共享的网络连接；热点能否开启取决于本机网卡和系统设置。

手机提示“此Wi-Fi无法访问互联网”时，选择保持连接，避免自动切回其他网络。程序需要的是手机与电脑局域网互通。

默认电脑热点地址为`192.168.137.1`。这是**电脑的地址**，不是手机自己的IP。可以用`ipconfig`查看热点虚拟网卡IPv4，或在手机Wi-Fi详情查看网关。

`run.py`顶部默认配置为：

```python
PHONE_IP = "192.168.137.1"
PORT = 8450
CERTIFICATE_DIR = ROOT / "certs" / "hotspot"
```

如果实际电脑地址不同，把`PHONE_IP`改成实际地址，下文签证书和手机访问时也使用同一地址。修改端口需要同步修改手机网址。

## 6. 配置手机信任的HTTPS证书

手机浏览器的摄像头API需要HTTPS安全环境。仅生成一个自签证书、在浏览器警告页点“继续”，并不能保证摄像头API可用。推荐使用mkcert创建本地CA，再让电脑和手机信任这个CA。

### 6.1 安装mkcert并生成证书

在支持winget的Windows终端执行：

```powershell
winget install --id FiloSottile.mkcert --exact --source winget
```

没有winget时，从[mkcert官方发布页](https://github.com/FiloSottile/mkcert/releases)下载Windows对应程序，命名为`mkcert.exe`，放到PATH中的目录。安装后重新打开PowerShell，`mkcert -version`应能输出版本。

首次准备项目证书时，在项目根目录执行：

```powershell
mkcert -install
New-Item -ItemType Directory -Path .\certs\hotspot -Force | Out-Null
mkcert -cert-file .\certs\hotspot\cert.pem -key-file .\certs\hotspot\key.pem 192.168.137.1 localhost 127.0.0.1 ::1
Copy-Item -LiteralPath (Join-Path (mkcert -CAROOT) 'rootCA.pem') -Destination .\certs\hotspot\rootCA.crt
```

`mkcert -install`会在本机安装它的开发CA信任，可能出现系统确认。以上签发命令按首次目录为空的情况给出；已有可用证书应复用。需要换地址或重新签发时，先使用新的证书目录，并同步修改`run.py`中的`CERTIFICATE_DIR`，避免无意覆盖原配置。

实际热点地址不是192.168.137.1时，替换签发命令中的地址。必须保留`localhost`与`127.0.0.1`，启动检查会核对这些地址。

### 6.2 Android导入CA证书

1. 将`certs/hotspot/rootCA.crt`通过USB等方式复制到手机。
2. 在手机设置中搜索“安装证书”，选择安装**CA证书**。常见位置为“安全/隐私 → 更多安全设置 → 加密与凭据 → 安装证书 → CA证书”，不同系统菜单可能不同。
3. 选择刚复制的`rootCA.crt`，确认安装。它会让手机信任由这台电脑的mkcert CA签发的证书。
4. 完全关闭再打开Chrome/Edge，之后用第7节地址访问。

传到手机的是CA的**公开证书**`rootCA.crt`。`key.pem`和mkcert目录里的`rootCA-key.pem`是私钥，留在电脑，不上传到GitHub或发给其他人。证书不随仓库分发，每台新电脑需要生成自己的证书并让手机重新信任。

项目自带的`scripts/gen_cert.py`也能生成和检查自签证书，但不会替手机完成信任。只有已经处理好对应证书信任的环境才使用这条路径；不要将“证书文件存在”等同于“手机相机可以使用”。

## 7. 启动与验证

### 7.1 先检查，不开摄像头

```powershell
.\envs\vitrack\python.exe -X utf8 run.py --check
```

应输出项目Python路径、手机HTTPS地址和“启动检查通过”。这一步检查环境位置、热点地址、证书、模型文件和端口，不加载推理模型或访问摄像头。

### 7.2 启动服务

```powershell
.\envs\vitrack\python.exe -X utf8 run.py
```

也可用编辑器打开根目录`run.py`，点击“运行Python文件”。若编辑器选的是其他Python，入口会转交项目环境；仍需先完成第3节的环境安装。

等待终端出现`Application startup complete`，保持这个终端运行。模型第一次加载需要时间，以实际就绪信息为准。

电脑浏览器可打开`https://localhost:8450/api/health`，确认：

- `ok`为`true`。
- `version`为`0.3.6-distance-reentry`。
- `source`为`ws`，`identity.mode`为`hybrid`。
- `recording.allowed`为`false`。

本入口固定启用BoT-SORT、OSNet和人脸辅助，覆盖`.env`中的旧appearance模式、证书路径和媒体保存开关。它保留`.env`中的`DET_DEVICE`等检测设置。不要直接运行`app/main.py`或`app/config.py`来代替启动入口。

### 7.3 手机操作

手机打开`https://192.168.137.1:8450`，地址按实际配置替换。确认顶部版本一致，并在“摄像头访问环境”看到“安全环境已就绪，开启前仍需授权”。

1. 点击“开始检测”，按浏览器提示允许摄像头；无需麦克风权限。
2. 人物入镜出现白框，按住目标框约0.6秒锁定，绿框表示已绑定。短按只选中。
3. 再次长按绿框取消；锁定另一个人会替换原目标。同一会话只锁定一个身份。
4. 也可在检测开始后上传清晰单人JPEG/PNG登记照片。文件小于6MiB，宽高不超过4096；照片登记同样替换原目标。
5. 远处锁定后缓慢走近、让正脸清晰停留，可为原连续目标补充人脸依据。极小、模糊、遮挡或变化过快时可能无法完成，不保证任意距离下重识别成功。

绿色虚线“识别中”表示候选确认；绿色实线“跟踪中”表示仍保持目标，当前依靠连续性。多人交叉、相似衣着等场景存在误认和丢失风险，不用于身份认证。

停止时先在手机点击“停止检测”，确认预览和摄像头使用提示结束，再在电脑终端按Ctrl+C。再次运行需要重新登记身份。

浏览器模式的画面显示在手机上，电脑另开页面不会自动观看同一手机会话；需要投影时另行准备手机投屏。

## 8. 常见问题

### 找不到Conda或项目Python

确认已安装Miniconda，给`setup_env.ps1`传入实际`-CondaPath`。克隆仓库不会复制作者的`envs/`；`run.py`自动选择环境不等于自动安装环境。

### 导入报DLL错误，或torchvision的NMS不可用

确认使用项目Python 3.11、已安装x64 VC++运行库，并运行`pip check`。PyTorch和torchvision必须按上述对应版本、同一CPU/CUDA来源安装。OpenCV需要`FaceDetectorYN`和`FaceRecognizerSF`接口；避免在同一环境混装多个OpenCV包覆盖模块。

### 提示无法使用GPU

用第3节命令检查`torch.cuda.is_available()`。为`False`时先检查驱动与PyTorch构建；也可以走CPU安装路径并设置`DET_DEVICE=cpu`。一键入口不会静默将GPU检测改为CPU。

### 手机提示地址不可达

先确认电脑服务已就绪、手机仍连接电脑热点，并核对实际地址与端口。若电脑可访问而手机不可访问，检查VPN、代理、Wi-Fi设备隔离及Windows防火墙。

需要开放端口时，可在管理员PowerShell为本地子网增加入站规则：

```powershell
New-NetFirewallRule -DisplayName 'ViTrack HTTPS 8450' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8450 -RemoteAddress LocalSubnet
```

端口改变时规则也要同步。此规则只放行指定端口的本地子网访问。

### 页面能打开，但不能调用摄像头

确认网址为HTTPS、访问IP在证书地址清单中、Android已安装正确的CA证书，以及浏览器对该站点的摄像头权限。优先使用独立Chrome/Edge；应用内置浏览器可能不支持。更换电脑或重新生成CA后，手机原来信任的证书不会自动更新。

### 端口已占用

回到原服务终端按Ctrl+C，或修改`run.py`的`PORT`，然后访问新端口。不要反复点击运行同时开启多份服务。

### 没有手机也想先检查程序

可用电脑摄像头的本地HTTP入口启动联合模式：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_identity.ps1 -Mode pc -Port 8000
```

电脑打开`http://localhost:8000/pc`。localhost可作为安全环境；仍需在页面手动开始并允许相机。这个方式使用的是电脑摄像头。

不使用任何摄像头时，可运行[测试说明](testing.md)中的公开样例与状态检查。

## 9. 可选：IP摄像头接入

手机安装能提供HTTP/MJPEG或RTSP流的相机App，由使用者手动启动，关闭App的云广播、录制和音频。取得实际视频地址后，在一个新的PowerShell终端执行：

```powershell
$env:SOURCE = 'ipcam'
$env:IPCAM_URL = 'http://手机实际地址:8080/video'
$env:IDENTITY_MODE = 'hybrid'
$env:IDENTITY_DEVICE = 'cpu'
$env:REID_MODEL = 'osnet_x0_25'
$env:TRACKER = 'botsort.yaml'
$env:ALLOW_MEDIA_SAVE = 'false'
powershell.exe -NoProfile -File .\scripts\run.ps1 -Mode pc -Port 8000
```

打开电脑终端显示的`/pc`页面，勾选同意后开始读取。CPU检测设置仍从`.env`读取。这里使用`run.ps1`；`run.py`固定是浏览器推帧模式，不启动IP源。

HTTP视频流在局域网一段不加密。停止电脑读取后，还需在手机App停止摄像头服务。环境变量仅在本终端及其子进程生效，结束后关闭该终端即可。

## 10. 目录、更新与验证边界

```text
run.py                 手机联合模式启动入口
requirements.txt       直接依赖及版本范围
.env.example           配置样例，复制为本机.env使用
app/                   服务、检测、跟踪与身份逻辑
web/                   浏览器页面，无前端构建步骤
scripts/               环境、模型、证书和检查工具
weights/               本地模型
docs/                  使用、架构、策略与测试说明
envs/、certs/           本机环境和证书，不进入Git
outputs/、work/         本机结果和临时文件，不进入Git
```

更新代码前先停止服务，保留自己的修改，再执行`git pull --ff-only`。依赖清单变化后重新安装对应依赖；不要覆盖已配置的`.env`和证书。所有图片、照片及身份特征默认仅在会话内存处理，停止后清除；录制默认关闭。

上述步骤按现有脚本与已运行的Windows环境核对。项目有GPU环境、模型、公开样例、手机连接及人工使用记录，但不声称在所有新电脑、CPU机器、Android品牌和证书组合上都已完成安装测试。遇到失败时，提供失败步骤、命令和不含个人画面的文字错误，便于定位。

2026-10-22已在现有环境中将检测、身体编码器与人脸编码器均设为CPU，用公开样例推进6帧并完成会话清理；这验证了CPU执行路径，不等同于全新CPU机器的依赖安装验证。文档中的依赖清单已逐项对照`requirements.txt`，PowerShell示例已做语法检查。
