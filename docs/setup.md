# 安装与使用

完整步骤已整理到[使用说明：从克隆到手机运行](usage.md)。首次使用请从该文档开始，依次完成环境、依赖、模型、网络和证书配置。

- 有NVIDIA显卡：选择GPU安装路径，实际检查PyTorch与torchvision的GPU运算。
- 无NVIDIA显卡：选择CPU路径，单独安装CPU版PyTorch，并设置`DET_DEVICE=cpu`。
- 手机浏览器接入：配置手机信任的HTTPS证书，再运行根目录`run.py`。
- IP摄像头接入、本地电脑使用和常见错误：见同一文档的后半部分。

依赖的版本范围以根目录`requirements.txt`为准。模型来源与许可见[第三方资源](third_party.md)，程序结构见[代码结构](code_guide.md)。
