# 安装与使用

## 环境

启动工具按Windows环境编写，需要Python 3.11和Conda。YOLO默认使用第一张CUDA显卡，身份编码器默认使用CPU；无CUDA时可在`.env`中设置`DET_DEVICE=cpu`，处理速度会降低。其他操作系统的安装和启动流程尚未验证。

```powershell
git clone https://github.com/z2653666716-dot/shibiehezhuizong.git
cd shibiehezhuizong
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup_env.ps1 -InstallDependencies
```

环境放在`envs/vitrack`，不需要手动激活。脚本默认查找用户目录下的Miniconda；路径不同时，通过`-CondaPath`指定实际`conda.exe`位置。

## 模型

仓库已包含所需权重，以下命令用于校验或补齐：

```powershell
powershell.exe -NoProfile -File .\scripts\fetch_weights.ps1
.\envs\vitrack\python.exe -X utf8 scripts/fetch_identity_models.py
```

联合跟踪使用YOLO11n、OSNet、YuNet和SFace。模型保存在`weights/`，下载失败会报错，运行时不会自动换成随机权重。来源与摘要见[第三方资源](third_party.md)。

原有appearance后端另外使用MobileNetV3，需要时执行：

```powershell
.\envs\vitrack\python.exe -X utf8 scripts/fetch_reid_weights.py
```

## 热点与证书

开启电脑移动热点，让手机连接。Windows常用热点地址为`192.168.137.1`，但应以本机网卡实际地址为准。

```powershell
.\envs\vitrack\python.exe -X utf8 scripts/gen_cert.py --ip 192.168.137.1 --output-dir certs/hotspot
```

手机浏览器访问摄像头需要HTTPS安全环境。这里生成的是自签证书，手机仍需完成本地证书信任；浏览器不接受时，需要使用受信任的本地证书方案。已有证书不会被脚本覆盖；地址变化时在新目录生成，并更新启动参数中的证书目录。私钥留在电脑，不发给手机。

校园或公共Wi-Fi可能隔离设备。出现地址不可达时，优先让手机连接电脑热点，而不是反复更换网页端口。

## 启动与停止

打开根目录`run.py`，点击编辑器运行按钮。入口即使由其他Python启动，也会转交`envs/vitrack/python.exe`执行。

入口默认启用`hybrid`模式，监听`192.168.137.1:8450`，使用`certs/hotspot`。修改顶部`PHONE_IP`、`PORT`、`CERTIFICATE_DIR`可适配其他网络。只检查启动条件可运行：

```powershell
.\envs\vitrack\python.exe run.py --check
```

也可以显式启动：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_identity.ps1 -Mode phone -Port 8450 -LanIP 192.168.137.1
```

等待`Application startup complete`后，手机访问终端显示的地址。点击开始并授权相机后才采集；停止时先结束页面检测，再在服务终端按Ctrl+C。重复启动时端口占用会报错，不会结束原服务。

同一会话只登记一个身份。长按白框锁定，长按绿框取消；上传照片会替换原目标。照片须为单人JPEG/PNG，小于6MiB、宽高不超过4096。停止会话后需要重新登记。

## IP摄像头模式

支持HTTP/MJPEG与RTSP地址。由手机端相机App提供视频流，电脑页面负责读取、检测和显示；此模式不调用电脑浏览器摄像头。

```powershell
$env:SOURCE = 'ipcam'
$env:IPCAM_URL = 'http://手机实际地址:8080/video'
powershell.exe -NoProfile -File .\scripts\run.ps1 -Mode pc
```

打开终端给出的电脑页面，勾选同意后开始读取。该命令按当前配置选择后端，默认是appearance模式；`run.py`固定使用浏览器推帧，不能用它启动IP源。停止电脑读取后，还需停止手机App的相机服务。HTTP视频流在局域网内不加密，手机App的录制、云广播和音频应保持关闭。

## 配置

配置优先级为进程环境变量、项目`.env`、`app/config.py`默认值。`.env.example`给出完整字段；`run.py`和`run_identity.ps1`会为本次进程覆盖身份模式等启动参数。

- `DET_CONF`：人物检测门槛，默认0.35。
- `DET_IMGSZ`、`MAX_SIDE`：模型输入尺寸与传输最长边，默认640。
- `FACE_MATCH_THRESHOLD`：人脸匹配门槛，默认0.45。
- `BODY_MATCH_THRESHOLD`、`BODY_HOLD_THRESHOLD`：身体重新确认与连续维持门槛，默认0.75、0.55。
- `REID_CONFIRM_FRAMES`、`REID_MAX_TEMPLATES`：确认次数与每类模板上限，默认6、5。

这些参数尚未经过正式数据集标定。调整时分别观察漏认和误认，不能只以绿框出现次数衡量效果。
