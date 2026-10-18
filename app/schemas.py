"""定义 ViTrack 内部检测数据和前后端通信格式，不执行模型推理或网络请求。

检测器返回 Detection，流水线转换成 Box 并组装 FrameResult，后续服务器再发送 JSON。
FrameMessage 描述浏览器输入，IdentitySummary 和 ErrorResponse 描述公开身份与错误信息。
"""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# Annotated 为数字附加范围要求；这些类型别名让多个字段使用相同的检查规则。
# strict=True 拒绝把字符串数字当作坐标；JSON 中的整数仍可用作浮点数。
UnitValue = Annotated[float, Field(ge=0, le=1, strict=True)]
PixelValue = Annotated[float, Field(ge=0, strict=True)]
SimilarityValue = Annotated[float, Field(ge=-1, le=1, strict=True)]
NormalizedCoordinates = tuple[UnitValue, UnitValue, UnitValue, UnitValue]
PixelCoordinates = tuple[PixelValue, PixelValue, PixelValue, PixelValue]


class DataModel(BaseModel):
    """所有数据格式的共同基础，由下方具体模型继承。

    输入是字段数据；Pydantic 检查字段类型并支持转换为 JSON。
    拒绝未知字段、NaN 和无穷大；构造与字段赋值时均检查，减少错误数据流向前端。
    """

    model_config = ConfigDict(
        extra="forbid", allow_inf_nan=False, str_strip_whitespace=True, validate_assignment=True
    )


class Detection(DataModel):
    """一条内部检测结果，由 Detector.detect 创建。

    输入：COCO 类别编号、名称、置信度、像素坐标；输出：可供裁剪和跟踪使用的数据对象。
    此处不保存身份或轨迹，因为仅凭单帧检测还不能确认目标身份。
    """

    cls: int = Field(ge=0, le=79, strict=True)
    name: str = Field(min_length=1)
    score: UnitValue
    xyxy: PixelCoordinates

    # 类方法参数 cls 表示类本身；上面的数据字段 cls 表示类别编号，含义不同。
    @field_validator("xyxy")
    @classmethod
    def check_coordinates(cls, value: PixelCoordinates) -> PixelCoordinates:
        """由 Pydantic 调用：检查四个像素坐标的顺序，成功返回原坐标。"""
        left, top, right, bottom = value
        if right <= left or bottom <= top:
            raise ValueError("像素框必须满足左 < 右、上 < 下，不能只有一条线或一个点")
        return value


class Box(DataModel):
    """发送给前端的目标框，字段对应实施方案的 boxes 数组。

    输入：归一化坐标和检测信息，可附加后续阶段的轨迹及身份结果。
    输出：能转换成 JSON 的目标框；P1 默认没有轨迹、身份，state 为 none。
    """

    cls: int = Field(ge=0, le=79, strict=True)
    name: str = Field(min_length=1)
    score: UnitValue
    xyxy: NormalizedCoordinates
    track_id: int | None = Field(default=None, ge=0, strict=True)
    identity_id: Annotated[str, Field(min_length=1)] | None = None
    state: Literal["none", "candidate", "locked"] = "none"
    sim: SimilarityValue | None = None
    verification: Literal["none", "face", "body", "continuity"] = "none"

    @field_validator("xyxy")
    @classmethod
    def check_coordinates(cls, value: NormalizedCoordinates) -> NormalizedCoordinates:
        """由 Pydantic 调用：除 0～1 范围外，还要求归一化框有正的宽度与高度。"""
        left, top, right, bottom = value
        if right <= left or bottom <= top:
            raise ValueError("归一化框必须满足左 < 右、上 < 下")
        return value

    @model_validator(mode="after")
    def check_state(self) -> Self:
        """由 Pydantic 在字段转换后调用，检查身份编号与显示状态是否一致。

        这里只检查数据关系，不进行识别：候选尚未绑定身份，锁定后才有 identity_id。
        selected 是前端短按的本地状态，不属于服务器发回的三种身份状态。
        """
        if self.state == "locked" and self.identity_id is None:
            raise ValueError("locked 状态必须提供 identity_id")
        if self.state != "locked" and self.identity_id is not None:
            raise ValueError("只有 locked 状态可以携带已绑定的 identity_id")
        if self.state != "none" and self.track_id is None:
            raise ValueError("candidate 或 locked 状态必须提供 track_id")
        return self

    @classmethod
    def from_detection(cls, detection: Detection, width: int, height: int) -> Self:
        """把像素检测框转成前端框，由流水线调用。

        输入：Detection 和原图宽、高；输出：没有绑定身份的 Box。
        横坐标除以宽，纵坐标除以高，再限制在画面范围内；完全位于画面外的框会被拒绝。
        """
        if any(isinstance(size, bool) or not isinstance(size, int) or size <= 0
               for size in (width, height)):
            raise ValueError("图像宽、高必须是正整数")
        left, top, right, bottom = detection.xyxy
        scaled = (left / width, top / height, right / width, bottom / height)
        # 依次把四个坐标截到 0～1，防止边缘框因为轻微越界画到画布外面。
        clipped = tuple(max(0.0, min(1.0, coordinate)) for coordinate in scaled)
        return cls(cls=detection.cls, name=detection.name, score=detection.score, xyxy=clipped)


class IdentitySummary(DataModel):
    """前端身份条使用的简要信息，由会话内的身份库提供。

    输入：身份编号、名字、可选缩略图地址与在线状态；输出：可公开发送的身份摘要。
    不放外观特征或模板，thumb只指向当前会话的内存缩略图接口。
    """

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    thumb: Annotated[str, Field(min_length=1)] | None = None
    online: bool = Field(default=False, strict=True)


class FrameMessage(DataModel):
    """浏览器发送到 /ws/stream 的一帧消息，由未来的 WebSocket 接口解析。

    输入：JSON 字段；输出：类型检查后的帧信息。seq 是帧序号，ts 是客户端毫秒时间戳。
    w/h 是发送图片的像素尺寸；img 是纯 Base64 文本，不含 data:image 前缀。
    本模型不解码图片，JPEG 内容及实际尺寸由后续流水线检查。
    """

    type: Literal["frame"] = "frame"
    seq: int = Field(ge=0, strict=True)
    ts: int = Field(ge=0, strict=True)
    w: int = Field(gt=0, strict=True)
    h: int = Field(gt=0, strict=True)
    img: str = Field(min_length=1)


class FrameResult(DataModel):
    """供服务器返回的一帧结果，由流水线组装。

    输入：原帧序号、服务端 FPS、处理耗时和数据列表；输出：result JSON。
    latency_ms 表示服务端处理耗时，不包含手机采集、网络和绘制的全部时间。
    """

    type: Literal["result"] = "result"
    seq: int = Field(ge=0, strict=True)
    fps: Annotated[float, Field(ge=0, strict=True)] = 0.0
    latency_ms: Annotated[float, Field(ge=0, strict=True)] = 0.0
    # default_factory 每次创建一份新列表，防止两帧意外共用同一个可变列表。
    boxes: list[Box] = Field(default_factory=list)
    identities: list[IdentitySummary] = Field(default_factory=list)
    session_id: str | None = None
    events: list[dict] = Field(default_factory=list)
    capture_max_side: int | None = Field(default=None, ge=32, le=2048)


class LockRequest(DataModel):
    """锁定请求：会话随机凭据、目标轨迹号和用户看到的帧号。"""

    session_id: str = Field(min_length=20, max_length=100)
    track_id: int = Field(ge=0, strict=True)
    seq: int = Field(ge=0, strict=True)
    # 页面明确发送lock/unlock使重试幂等；旧客户端省略时保留长按切换语义。
    action: Literal["lock", "unlock", "toggle"] = "toggle"


class SelectRequest(DataModel):
    """触点锁定请求：x/y 是还原镜像后的归一化坐标。"""

    session_id: str = Field(min_length=20, max_length=100)
    x: UnitValue
    y: UnitValue
    seq: int = Field(ge=0, strict=True)


class InteractionEvent(DataModel):
    """仅允许有限的手势诊断字段；不接受任意消息、照片、文件名或向量。"""
    session_id: str = Field(min_length=20, max_length=100)
    seq: int = Field(ge=0, strict=True)
    track_id: int | None = Field(default=None, ge=0, strict=True)
    event: Literal["press_start", "press_commit", "press_cancel", "menu_suppressed", "photo_too_large"]
    reason: Literal["hold_complete", "released_early", "pointer_cancel", "capture_lost", "moved", "stopped", "duplicate_menu", "size_limit"] | None = None
    pointer: Literal["touch", "mouse", "pen", "unknown"] = "unknown"


class RecordRequest(DataModel):
    """录制操作始终指定视频会话；开始另需confirm=true且服务允许保存。"""
    session_id: str = Field(min_length=20, max_length=100)
    confirm: bool = Field(default=False, strict=True)


class IpCameraStart(DataModel):
    """IP 视频源启动请求：只接受 JSON 布尔 confirm，由启动接口检查是否明确同意。"""

    confirm: bool = Field(strict=True)


class IpCameraPull(DataModel):
    """观看请求：after 表示已显示序号；服务端只返回更新的一帧，避免慢客户端排队。"""

    type: Literal["next"] = "next"
    after: int = Field(default=0, ge=0, strict=True)


class ErrorResponse(DataModel):
    """统一中文错误格式，由未来的 HTTP/WS 错误处理流程构造。

    输入：错误码和中文提示；输出：ok=false、code、message，供前端直接显示 message。
    本类只规定格式，不决定 HTTP 状态码，也不发送响应。
    """

    ok: Literal[False] = False
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
