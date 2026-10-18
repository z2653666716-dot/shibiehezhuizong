"""集中读取 ViTrack 的配置，不加载模型，也不启动服务。

属于应用的基础配置模块：后续 main.py 调用 load_config，再把结果传给检测等模块。
输入是项目 .env 和进程环境变量，输出是经过类型、范围检查的 AppConfig 对象。
"""

import math
import os
from pathlib import Path
from typing import Literal, Self

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


# __file__ 指向本文件；向上两级就是项目根目录，不依赖终端当前所在位置。
PROJECT_ROOT = Path(__file__).resolve().parents[1]


class AppConfig(BaseModel):
    """保存经过检查的配置，由 load_config 创建，供后续各模块读取。

    字符串数字会转换为 int/float；frozen=True 防止某个模块意外修改共享配置。
    此类只检查设置本身，不要求后续阶段的证书、网页或模型文件已经存在。
    """

    model_config = ConfigDict(frozen=True, validate_default=True, extra="forbid")

    # 服务连接设置。证书是否可用，由后续 HTTPS 启动流程检查。
    app_host: str = Field(default="0.0.0.0", min_length=1)
    app_port: int = Field(default=8443, ge=1, le=65535)
    https_cert: Path = Path("certs/cert.pem")
    https_key: Path = Path("certs/key.pem")
    source: Literal["ws", "ipcam"] = "ws"
    ipcam_url: str = ""

    # 检测设置：设备 0 表示第一张 GPU；target_classes 为 None 时检测全部类别。
    det_model: Path = Path("weights/yolo11n.pt")
    det_imgsz: int = Field(default=640, ge=32, le=2048)
    det_conf: float = Field(default=0.35, ge=0, le=1)
    det_iou: float = Field(default=0.5, ge=0, le=1)
    det_device: int | Literal["cpu"] = 0
    target_classes: tuple[int, ...] | None = (0,)

    # tracker 是 Ultralytics 内置资源名，不能当成项目文件路径拼接。
    tracker: str = Field(default="bytetrack.yaml", min_length=1)
    track_max_age: int = Field(default=30, ge=1)

    # 外观匹配、身份数量、传输和可选录制参数；默认禁止媒体保存。
    reid_model: Literal["mobilenet_v3_small", "color_histogram", "osnet_x0_25"] = "mobilenet_v3_small"
    reid_ema: float = Field(default=0.9, ge=0, lt=1)
    reid_tau_high: float = Field(default=0.80, ge=0, le=1)
    reid_tau_low: float = Field(default=0.45, ge=0, le=1)
    reid_margin: float = Field(default=0.05, ge=0, le=1)
    reid_confirm_frames: int = Field(default=3, ge=1)
    reid_max_templates: int = Field(default=5, ge=1)
    reid_w_appear: float = Field(default=0.85, ge=0, le=1)
    reid_w_color: float = Field(default=0.15, ge=0, le=1)
    reid_weights: Path = Path("weights/mobilenet_v3_small-047dcff4.pth")
    reid_calibrated: bool = False
    identity_limit: int = Field(default=20, ge=1, le=100)
    allow_media_save: bool = False
    jpeg_quality: float = Field(default=0.65, ge=0, le=1)
    max_side: int = Field(default=640, ge=32, le=2048)
    record_fps: int = Field(default=15, ge=1, le=60)

    @field_validator("https_cert", "https_key", "det_model", "reid_weights", mode="before")
    @classmethod
    def resolve_project_path(cls, value: object) -> Path:
        """输入文件路径，输出绝对路径；由 Pydantic 在字段转换前自动调用。

        相对路径从 PROJECT_ROOT 开始查找。这里只计算路径，不创建或读取目标文件。
        """
        if not isinstance(value, (str, Path)) or not str(value).strip():
            raise ValueError("文件路径不能为空")
        path = Path(str(value).strip()).expanduser()
        return (path if path.is_absolute() else PROJECT_ROOT / path).resolve()

    @field_validator("det_device", mode="before")
    @classmethod
    def parse_device(cls, value: object) -> int | str:
        """把环境中的 cpu 或非负整数编号转换为检测器可接收的设备设置。"""
        text = str(value).strip().lower()
        if text == "cpu":
            return "cpu"
        if text.isdecimal():
            return int(text)
        raise ValueError("DET_DEVICE 应填写 cpu 或非负 GPU 编号，例如 0")

    @field_validator("target_classes", mode="before")
    @classmethod
    def parse_classes(cls, value: object) -> object:
        """输入逗号分隔的类别文本，输出待转换的类别元组；空文本表示全部类别。

        例如 0,2 会拆成两个元素，再由 Pydantic 把字符串转换为整数。
        非字符串输入留给字段类型检查，便于直接构造 AppConfig 时同样使用元组。
        """
        if isinstance(value, str):
            if not value.strip():
                return None
            return tuple(part.strip() for part in value.split(","))
        return value

    @model_validator(mode="after")
    def check_relationships(self) -> Self:
        """全部字段转换完成后，检查多个参数之间的关系；成功返回当前配置。

        由 Pydantic 自动调用；这里不能只检查每个数字的范围，还要检查组合是否合理。
        """
        if self.det_imgsz % 32 != 0:
            raise ValueError("DET_IMGSZ 应为 32 的倍数，例如 480、640 或 800")
        if self.reid_tau_low >= self.reid_tau_high:
            raise ValueError("REID_TAU_LOW 必须小于 REID_TAU_HIGH")
        if not math.isclose(self.reid_w_appear + self.reid_w_color, 1.0, abs_tol=1e-6):
            raise ValueError("REID_W_APPEAR 与 REID_W_COLOR 相加必须为 1")
        if self.target_classes is not None:
            if not self.target_classes:
                raise ValueError("类别元组不能没有元素；使用 None 表示全部类别")
            if any(class_id < 0 or class_id > 79 for class_id in self.target_classes):
                raise ValueError("TARGET_CLASSES 的 COCO 类别编号应在 0～79 之间")
            if len(set(self.target_classes)) != len(self.target_classes):
                raise ValueError("TARGET_CLASSES 中的类别编号不能重复")
        if self.source == "ipcam":
            # 手机地址因设备而异，切到该模式后必须显式填写，避免误用示例 IP。
            from urllib.parse import urlsplit

            try:
                address = urlsplit(self.ipcam_url)
                valid_address = address.scheme in {"http", "https", "rtsp"} and address.hostname
                address.port  # 读取属性也会检查端口是否为有效数字及有效范围。
            except ValueError as error:
                raise ValueError("IPCAM_URL 不是有效的视频流地址") from error
            if not valid_address:
                raise ValueError("SOURCE=ipcam 时请填写 http、https 或 rtsp 格式的 IPCAM_URL")
        return self


def load_config(env_file: str | Path | None = None) -> AppConfig:
    """读取配置并返回 AppConfig，供未来的应用入口调用。

    输入：可选 .env 路径，默认读取项目根目录 .env；默认文件不存在时使用内置值。
    顺序：默认值 < .env 文件 < 进程环境变量；不会把 .env 内容写入 os.environ。
    输出：只读配置对象；参数不合法时抛出包含参数名的 ValueError。
    """
    path = PROJECT_ROOT / ".env" if env_file is None else Path(env_file)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if env_file is not None and not path.is_file():
        raise FileNotFoundError(f"找不到指定的配置文件：{path}")

    # utf-8-sig 兼容 Windows 编辑器保存的 BOM；关闭插值使实际文本与填写内容一致。
    file_values = dotenv_values(path, encoding="utf-8-sig", interpolate=False) if path.is_file() else {}
    field_names = {name.upper(): name for name in AppConfig.model_fields}
    unknown = sorted(set(file_values) - set(field_names))
    if unknown:
        raise ValueError(f"未知配置项：{', '.join(unknown)}，请对照 .env.example 检查拼写")

    values = {}
    for env_name, field_name in field_names.items():
        # 环境变量优先；用是否存在判断，保留 TARGET_CLASSES= 这样的有意义空值。
        if env_name in os.environ:
            value = os.environ[env_name]
        elif env_name in file_values:
            value = file_values[env_name]
        else:
            continue  # 未填写的参数交给 AppConfig 中的默认值处理。
        if value is None:
            raise ValueError(f"{env_name} 缺少等号，请使用 参数名=值 的格式")
        values[field_name] = value.strip()

    try:
        return AppConfig(**values)
    except ValidationError as error:
        # 保留具体字段与原因，同时将常见的 Pydantic 数值错误转换为中文提示。
        messages = []
        bounds = {
            "greater_than": ("gt", "大于"), "greater_than_equal": ("ge", "大于或等于"),
            "less_than": ("lt", "小于"), "less_than_equal": ("le", "小于或等于"),
        }
        for item in error.errors(include_url=False):
            location = ".".join(str(part).upper() for part in item["loc"]) or "参数组合"
            reason = item["msg"].removeprefix("Value error, ")
            if item["type"] in bounds:
                key, relation = bounds[item["type"]]
                reason = f"应{relation} {item['ctx'][key]}"
            elif item["type"] in {"int_parsing", "int_from_float", "float_parsing", "finite_number"}:
                reason = "请填写有效的整数或小数，整数参数不能填写小数"
            elif item["type"] == "literal_error":
                reason = f"允许的值：{item['ctx']['expected']}"
            messages.append(f"{location}：{reason}")
        raise ValueError("配置错误；" + "；".join(messages)) from error
