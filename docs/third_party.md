# 第三方代码、权重与公开样例来源

- YOLO11n/YOLO11s：Ultralytics官方模型，来源为 `ultralytics/assets` 的v8.3.0发布资源。项目使用Ultralytics包；许可信息见 https://github.com/ultralytics/ultralytics/blob/main/LICENSE 与 https://www.ultralytics.com/license 。s模型只用于基准，生产默认n模型。
- ByteTrack：通过已安装Ultralytics包内实现调用，不另行下载跟踪模型；配置来自包内bytetrack.yaml。
- MobileNetV3-Small：torchvision官方 `mobilenet_v3_small-047dcff4.pth`，下载自 https://download.pytorch.org/models/mobilenet_v3_small-047dcff4.pth ，已验证SHA256前缀047dcff4。torchvision代码许可见 https://github.com/pytorch/vision/blob/main/LICENSE 。
- `data/samples/test.jpg`：Ultralytics公开bus示例图，来源 https://ultralytics.com/images/bus.jpg ，用于公开样例检查，不是用户照片，也不声称为本项目自有作品。来源未单独标注图片作者和独立许可。
- 三张衣物诊断图：作者、来源、CC许可、下载与摘要记录见 `data/samples/clothing/README.md` 和 `data/samples/detection_cases.json`，分发时保留这些记录。
- PWA图标由 `scripts/create_icons.py` 绘制几何形状生成，不使用用户图片或外部图标素材。

项目保留依赖自身的许可证。实际安装版本见requirements.lock.txt；源码包只携带必要模型和指定公开样例，不携带整个第三方Python环境。
