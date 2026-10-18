"""串联一帧图像的解码、检测、坐标转换和结果组装，属于 ViTrack 的帧处理流水线。

未来 WebSocket 接口调用 process_message；直接图像入口 process_frame 供后续摄像头读取流程使用。
本模块调用 Detector 和 schemas，不打开网络端点或摄像头，P1 尚不进行跟踪或重识别。
"""

import asyncio
import base64
import binascii
from collections import deque
from io import BytesIO
import logging
import threading
from time import perf_counter

import cv2
import numpy as np
from PIL.JpegImagePlugin import JpegImageFile

from .detector import Detector
from .schemas import Box, ErrorResponse, FrameMessage, FrameResult


logger = logging.getLogger(__name__)

# 接收上限与前端的 MAX_SIDE 不同：前者限制输入，后者是计划发送尺寸。
MAX_JPEG_BYTES = 4 * 1024 * 1024
MAX_FRAME_SIDE = 4096
FPS_WINDOW = 30


class PipelineError(ValueError):
    """表示可以向客户端解释的帧处理错误，供未来接口统一捕获。"""

    def __init__(self, code: str, message: str) -> None:
        """输入错误码与中文提示，输出异常对象；由下方流水线抛出。"""
        super().__init__(message)
        self.code = code
        self.message = message

    def to_response(self) -> ErrorResponse:
        """把当前异常转为统一错误数据；未来接口调用后再选择 HTTP 或 WS 发送。"""
        return ErrorResponse(code=self.code, message=self.message)


class Pipeline:
    """持有一个检测器，按顺序处理共享模型上的任务。

    输入：已初始化的 Detector；输出：提供两个异步帧处理入口的流水线实例。
    线程锁保护实际工作，调用方取消等待也不会提前释放仍在推理的模型。
    """

    def __init__(self, detector: Detector) -> None:
        """保存检测器并初始化处理锁、有限长度统计窗口和最新结果。

        不重新加载模型；未来应用启动流程创建本对象，健康接口可读取最新统计。
        """
        self.detector = detector
        self._process_lock = threading.Lock()
        self._completion_times: deque[float] = deque(maxlen=FPS_WINDOW)
        self.latest_result: FrameResult | None = None
        self.processed_frames = 0

    async def process_message(self, message: FrameMessage) -> FrameResult:
        """处理浏览器的一帧消息，由未来 WebSocket 接口 await 调用。

        输入：已经过 schemas 检查的 FrameMessage；输出：保留原 seq 的 FrameResult。
        to_thread 将解码和推理交给后台线程，等待期间不占住事件循环。
        """
        if not isinstance(message, FrameMessage):
            raise PipelineError("BAD_FRAME", "请先将帧消息解析为 FrameMessage")
        return await asyncio.to_thread(self._run, message, message.seq)

    async def process_frame(self, frame_bgr: np.ndarray, seq: int) -> FrameResult:
        """处理直接提供的图像，为后续 IP 摄像头路径保留共同入口。

        输入：BGR 数组和非负整数帧号；输出：与浏览器路径相同格式的 FrameResult。
        本方法不读取摄像头，调用方等待处理期间应保留该帧内容。
        """
        if isinstance(seq, bool) or not isinstance(seq, int) or seq < 0:
            raise PipelineError("BAD_FRAME", "帧序号 seq 必须是非负整数")
        return await asyncio.to_thread(self._run, frame_bgr, seq)

    def _run(self, source: FrameMessage | np.ndarray, seq: int) -> FrameResult:
        """后台线程共用的同步流程，供两个异步入口调用。

        输入：消息或图像，以及帧号；输出：检测结果与统计。发生错误时抛出 PipelineError。
        锁覆盖解码、推理、组装与统计，保证同一个模型及统计状态不会被交叉修改。
        """
        with self._process_lock:
            started = perf_counter()
            frame = self._decode_message(source) if isinstance(source, FrameMessage) else source
            self._check_frame(frame)
            height, width = frame.shape[:2]
            try:
                detections = self.detector.detect(frame)
                # 每个像素框除以原图尺寸，得到手机画布可使用的 0～1 坐标。
                boxes = [Box.from_detection(item, width, height) for item in detections]
                result = FrameResult(seq=seq, boxes=boxes)
            except Exception as error:
                logger.exception("检测或结果转换失败")
                raise PipelineError("INFERENCE_FAILED", "目标检测失败，请检查服务日志") from error

            finished = perf_counter()
            result.latency_ms = round((finished - started) * 1000, 2)
            self._completion_times.append(finished)
            if len(self._completion_times) > 1:
                elapsed = self._completion_times[-1] - self._completion_times[0]
                if elapsed > 0:
                    result.fps = round((len(self._completion_times) - 1) / elapsed, 2)
            # FPS 来自实际处理完成的时间间隔，第一帧没有间隔，保持默认 0。
            self.processed_frames += 1
            self.latest_result = result
            return result

    @staticmethod
    def _decode_message(message: FrameMessage) -> np.ndarray:
        """输入 Base64 帧消息，输出 OpenCV BGR 图像，由 _run 在线程内调用。

        顺序：限制文本长度 → Base64 解码 → 检查 JPEG 头信息及尺寸 → OpenCV 解码。
        Pillow 只读取头部元信息，先拦截超大尺寸，实际像素仍由 cv2.imdecode 解码。
        """
        max_encoded_length = 4 * ((MAX_JPEG_BYTES + 2) // 3)
        size_message = f"JPEG 超过 {MAX_JPEG_BYTES / (1024 * 1024):g} MiB，请降低发送尺寸或图片质量"
        if len(message.img) > max_encoded_length:
            raise PipelineError("FRAME_TOO_LARGE", size_message)
        try:
            jpeg_bytes = base64.b64decode(message.img, validate=True)
        except (binascii.Error, ValueError) as error:
            raise PipelineError("BAD_FRAME", "图片必须是纯 Base64 文本，不含 data:image 前缀") from error
        if not jpeg_bytes:
            raise PipelineError("BAD_FRAME", "图片内容为空")
        if len(jpeg_bytes) > MAX_JPEG_BYTES:
            raise PipelineError("FRAME_TOO_LARGE", size_message)

        try:
            # 直接使用 JPEG 头解析器，避免第三方接管通用 Image.open 后自动尝试其他格式。
            with JpegImageFile(BytesIO(jpeg_bytes)) as image:
                width, height = image.size
        except (OSError, ValueError, SyntaxError) as error:
            raise PipelineError("BAD_FRAME", "图片内容损坏或不是可识别的 JPEG") from error
        if width > MAX_FRAME_SIDE or height > MAX_FRAME_SIDE:
            raise PipelineError("FRAME_TOO_LARGE", f"图片宽高不能超过 {MAX_FRAME_SIDE} 像素")
        if (width, height) != (message.w, message.h):
            raise PipelineError(
                "BAD_FRAME",
                f"图片实际尺寸为 {width}×{height}，与消息声明的 {message.w}×{message.h} 不一致",
            )
        try:
            # 以编码后的像素尺寸为准，避免 EXIF 自动旋转改变宽高和坐标对应关系。
            flags = cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION
            frame = cv2.imdecode(np.frombuffer(jpeg_bytes, dtype=np.uint8), flags)
        except cv2.error as error:
            raise PipelineError("BAD_FRAME", "JPEG 像素解码失败") from error
        if frame is None or frame.shape[:2] != (height, width):
            raise PipelineError("BAD_FRAME", "JPEG 无法完整解码为声明尺寸的图像")
        return frame

    @staticmethod
    def _check_frame(frame: np.ndarray) -> None:
        """检查两个入口共用的图像要求；输入 BGR 数组，成功不返回数据，失败抛出异常。"""
        if not isinstance(frame, np.ndarray):
            raise PipelineError("BAD_FRAME", "帧必须是 OpenCV/NumPy 图像数组")
        if (frame.dtype != np.uint8 or frame.ndim != 3 or frame.shape[2] != 3
                or frame.shape[0] == 0 or frame.shape[1] == 0):
            raise PipelineError("BAD_FRAME", "帧必须是非空的 uint8 三通道 BGR 图像")
        if max(frame.shape[:2]) > MAX_FRAME_SIDE:
            raise PipelineError("FRAME_TOO_LARGE", f"图片宽高不能超过 {MAX_FRAME_SIDE} 像素")
