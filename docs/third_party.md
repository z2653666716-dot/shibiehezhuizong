# 第三方代码、权重与公开样例来源

- YOLO11n/YOLO11s：Ultralytics官方模型，来源为 `ultralytics/assets` 的v8.3.0发布资源。项目使用Ultralytics包；许可信息见 https://github.com/ultralytics/ultralytics/blob/main/LICENSE 与 https://www.ultralytics.com/license 。s模型只用于基准，生产默认n模型。
- ByteTrack：通过已安装Ultralytics包内实现调用，不另行下载跟踪模型；配置来自包内bytetrack.yaml。
- MobileNetV3-Small：torchvision官方 `mobilenet_v3_small-047dcff4.pth`，下载自 https://download.pytorch.org/models/mobilenet_v3_small-047dcff4.pth ，已验证SHA256前缀047dcff4。torchvision代码许可见 https://github.com/pytorch/vision/blob/main/LICENSE 。
- `data/samples/test.jpg`：Ultralytics公开bus示例图，来源 https://ultralytics.com/images/bus.jpg ，用于公开样例检查，不是用户照片，也不声称为本项目自有作品。来源未单独标注图片作者和独立许可。
- 三张衣物诊断图：作者、来源、CC许可、下载与摘要记录见 `data/samples/clothing/README.md` 和 `data/samples/detection_cases.json`，分发时保留这些记录。
- PWA图标由 `scripts/create_icons.py` 绘制几何形状生成，不使用用户图片或外部图标素材。

项目保留依赖自身的许可证。实际安装版本见requirements.lock.txt；源码包只携带必要模型和指定公开样例，不携带整个第三方Python环境。

## 身份保持实验分支

- BoT-SORT：使用已有Ultralytics实现，显式挂接本地OSNet编码器，禁止第三方自动下载；相机运动估计只保留必要灰度内存，停止时清除。
- OSNet ONNX：发布者 `anriha/osnet_x0_25_msmt17`，固定提交 `1e22b925c70caa5591e9fab3f5540af8484bcad8`，模型卡仅标注MIT，缺少训练与导出记录。来源 https://huggingface.co/anriha/osnet_x0_25_msmt17 ，SHA256 `e78604f4ccda49b8f41cd0f8f7303800ce75d2361895ebb0729513c1bf53d277`。只作为实验候选，不将MSMT17文件名当作已核验的训练成绩。原输入声明16×3×256×128、输出16×512；内部Reshape实际支持动态批。运行前只规范输入/输出batch元信息，在内存执行，不修改权重原文件；原16人输出与新3人输出已做数值一致性检查。
- YuNet：OpenCV Zoo官方 `face_detection_yunet_2023mar.onnx`，MIT，完整许可见 `docs/licenses/yunet_license.txt`。SHA256 `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`，来源 https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet 。
- SFace：OpenCV Zoo官方 `face_recognition_sface_2021dec.onnx`，Apache-2.0，完整许可见 `docs/licenses/sface_license.txt`。SHA256 `0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79`，来源 https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface 。
- ONNX/ONNX Runtime：规范旧导出图和执行同一模型；默认身份编码器选择本机实测更快的CPU，YOLO检测仍在CUDA。`IDENTITY_DEVICE=cuda`保留显式CUDA实验路径与CPU回退，健康接口分别给出两个编码器实际设备。SFace CUDA输入已与OpenCV官方特征对齐，公开图余弦为1.0；不把设备名称当作速度或准确率证明。
