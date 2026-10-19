"""ViTrack 的 FastAPI 服务入口，接通帧流水线并保存可定位错误的日志。

Uvicorn 通过 app.main:app 加载本模块；lifespan 初始化配置、模型和 Pipeline。
浏览器推帧与 IP 视频源共用 Pipeline；后者必须明确确认启动，不随服务启动自动读取。
"""

import asyncio
import base64

import cv2
from contextlib import asynccontextmanager, suppress
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.websockets import WebSocketState

from .config import AppConfig, PROJECT_ROOT, load_config
from .detector import Detector
from .ipcamera import IpCamera
from .pipeline import MAX_JPEG_BYTES, Pipeline, PipelineError
from .schemas import ErrorResponse, FrameMessage, IpCameraPull, IpCameraStart, LockRequest, SelectRequest, RecordRequest, InteractionEvent
from .session import SessionError
from .photos import MAX_PHOTO_BYTES


LOG_DIR = PROJECT_ROOT / "outputs" / "logs"
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 3
LOG_LEVEL = logging.INFO
LOG_TIMEZONE = timezone(timedelta(hours=8))
MAX_MESSAGE_BYTES = 4 * ((MAX_JPEG_BYTES + 2) // 3) + 64 * 1024

# ContextVar 为每个异步请求保存自己的值；to_thread 会把它们带进后台线程。
# 元组中依次是请求/连接编号与帧号，"-" 表示当前没有这项信息。
log_context: ContextVar[tuple[str, str]] = ContextVar("vitrack_log_context", default=("-", "-"))
logger = logging.getLogger(__name__)


class LogContextFilter(logging.Filter):
    """由日志处理器调用，将当前请求编号和帧号附加到每条日志。"""

    def filter(self, record: logging.LogRecord) -> bool:
        """输入日志记录，补充上下文字段，返回 True 表示保留这条记录。"""
        record.request_id, record.frame_seq = log_context.get()
        return True


def configure_logging() -> None:
    """创建日志目录、轮换文件和终端输出，由服务生命周期开始时调用。

    输出：安装到 app 日志层级的处理器；不修改全局 Python 日志配置。
    重复启动时只替换本应用管理的处理器，避免一条消息被重复写入。
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    app_logger = logging.getLogger("app")
    server_logger = logging.getLogger("uvicorn.error")
    old_handlers = set()
    for parent in (app_logger, server_logger):
        for handler in list(parent.handlers):
            if (handler.name or "").startswith("vitrack."):
                parent.removeHandler(handler)
                old_handlers.add(handler)
    for handler in old_handlers:
        handler.close()

    formatter = logging.Formatter(
        "%(asctime)s+08:00 %(levelname)s %(name)s:%(lineno)d "
        "request=%(request_id)s seq=%(frame_seq)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # 日志统一用北京时间显示，不依赖部署机器的时区。
    formatter.converter = lambda stamp: datetime.fromtimestamp(stamp, LOG_TIMEZONE).timetuple()
    context_filter = LogContextFilter()
    file_handlers = []
    for filename, level in (("app.log", logging.DEBUG), ("errors.log", logging.ERROR)):
        handler = RotatingFileHandler(
            LOG_DIR / filename, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.set_name(f"vitrack.{filename}")
        handler.setLevel(level)
        handler.setFormatter(formatter)
        handler.addFilter(context_filter)
        app_logger.addHandler(handler)
        file_handlers.append(handler)

    console = logging.StreamHandler()
    console.set_name("vitrack.console")
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)
    console.addFilter(context_filter)
    app_logger.addHandler(console)
    app_logger.setLevel(LOG_LEVEL)
    app_logger.propagate = False
    # 本应用的HTTP中间件只记录path；关闭Uvicorn重复访问行，避免缩略图URL的会话查询凭据落入终端。
    logging.getLogger("uvicorn.access").disabled = True
    # Uvicorn 保留原来的终端输出，同时将启动/网络层错误写入相同文件。
    for handler in file_handlers:
        server_logger.addHandler(handler)


def log_files() -> dict[str, Path]:
    """返回当前存在的日志和有限数量备份，供列表与下载接口共用。

    仅按已知文件名生成路径，不使用客户端输入拼接任意文件路径。
    """
    names = []
    for base in ("app.log", "errors.log"):
        names.append(base)
        names.extend(f"{base}.{number}" for number in range(1, LOG_BACKUP_COUNT + 1))
    return {name: LOG_DIR / name for name in names if (LOG_DIR / name).is_file()}


def read_log_snapshot(name: str) -> bytes:
    """读取一份固定的日志副本，供下载接口在线程中调用。

    输入：允许的日志文件名；输出：本次下载的完整字节内容。
    与对应文件处理器共用锁，复制期间暂停该日志的写入和轮换。
    不在这里记录日志，以免持有文件锁时再次触发其他日志处理器。
    """
    # 先找到所属日志组；具体文件仍须通过 log_files 的白名单检查。
    base = next(
        (base for base in ("app.log", "errors.log")
         if name == base or name.startswith(f"{base}.")),
        None,
    )
    if base is None:
        raise HTTPException(404, "日志文件不存在")
    handler = next(
        (handler for handler in logging.getLogger("app").handlers
         if handler.name == f"vitrack.{base}"),
        None,
    )
    if not isinstance(handler, RotatingFileHandler):
        raise HTTPException(503, "日志服务尚未就绪")

    # logging 写文件和轮换时也持有这把锁；把查找与读取放在一起，
    # 防止查到 app.log.1 后，它在真正读取前已经被轮换或删除。
    with handler.lock:
        path = log_files().get(name)
        if path is None:
            raise HTTPException(404, "日志文件不存在")
        try:
            return path.read_bytes()
        except FileNotFoundError as error:
            # 外部手动删除日志等少见情况，仍返回可理解的中文提示。
            raise HTTPException(404, "日志文件不存在") from error


def error_body(code: str, message: str) -> dict:
    """把错误码与中文提示转换成响应字典，附加可搜索的日志编号和帧号。

    HTTP/WS 错误处理调用本函数；不包含收到的整帧文本或 Base64 图片。
    """
    request_id, seq = log_context.get()
    if request_id != "-":
        reference = f"日志编号：{request_id}"
        if seq != "-":
            reference += f"，帧号：{seq}"
        message = f"{message}（{reference}）"
    return ErrorResponse(code=code, message=message).model_dump(mode="json")


def create_app(config: AppConfig | None = None) -> FastAPI:
    """创建服务及路由，供模块入口和检查流程调用。

    输入：可选配置；默认在启动时读取 .env。输出：FastAPI 应用。
    创建应用本身不会加载模型或创建日志文件，真正初始化在 lifespan 中进行。
    """

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        """FastAPI 启停入口，输入应用对象，输出服务运行期间的异步上下文。

        框架先执行 yield 前的初始化，之后处理请求；停止服务时执行 finally 记录结束状态。
        """
        configure_logging()
        pipeline = None
        try:
            settings = config if config is not None else load_config()
            application.state.settings = settings
            application.state.ipcam_reader = (
                IpCamera(settings.ipcam_url, max_side=settings.max_side) if settings.source == "ipcam" else None
            )
            logger.info("服务启动 source=%s model=%s", settings.source, settings.det_model)
            # 权重加载也可能耗时，启动阶段交给后台线程执行。
            detector = await asyncio.to_thread(Detector, settings)
            pipeline = Pipeline(detector, settings)
            application.state.pipeline = pipeline
            application.state.ready = True
            logger.info("服务就绪 device=%s", detector.device_name)
        except Exception:
            logger.exception("服务启动失败")
            raise
        try:
            yield
        finally:
            async with application.state.ipcam_lock:
                await stop_ipcam_task()
            application.state.ready = False
            application.state.pipeline = None
            logger.info("服务结束 processed_frames=%s", pipeline.processed_frames)
            # 文件处理器留至进程退出时由 logging 关闭，保留尚在收尾的后台错误。

    application = FastAPI(title="ViTrack", version="0.3.1-experimental", lifespan=lifespan)
    application.state.ready = False
    application.state.pipeline = None
    application.state.settings = None
    application.state.ipcam_reader = None
    application.state.ipcam_task = None
    application.state.ipcam_packet = None
    application.state.ipcam_error = None
    application.state.ipcam_sequence = 0
    application.state.ipcam_lock = asyncio.Lock()
    application.state.ipcam_condition = asyncio.Condition()

    def require_ipcam() -> IpCamera:
        """HTTP 入口共用检查：无输入，返回读取器；配置不符直接拒绝，不尝试连接。"""
        if not application.state.ready:
            raise HTTPException(503, "检测服务尚未就绪")
        if application.state.ipcam_reader is None:
            raise HTTPException(409, "当前为浏览器推帧模式，请先配置 SOURCE=ipcam 和 IPCAM_URL")
        return application.state.ipcam_reader

    def ipcam_status() -> dict:
        """输出读取和处理状态；健康/控制接口共用，不包含地址密码或图像。"""
        reader = application.state.ipcam_reader
        status = reader.status() if reader is not None else {"state": "idle", "last_seq": 0, "error_code": None}
        if application.state.ipcam_error:
            status["state"] = "error"
            status["error_code"] = application.state.ipcam_error["code"]
        return {"configured": reader is not None, **status, "result_seq": application.state.ipcam_sequence,
                "has_frame": application.state.ipcam_packet is not None}

    def prepare_ipcam_frame(image, max_side: int, quality: float):
        """接收 BGR 图像、最长边和质量，输出缩放图像及同一图像的 JPEG/Base64。

        后台任务调用；按比例缩放，检测与预览使用同一张图，保证框的坐标对应正确。
        全部转换在内存完成，不写照片或视频。
        """
        height, width = image.shape[:2]
        scale = min(1.0, max_side / max(width, height))
        if scale < 1:
            image = cv2.resize(image, (max(1, round(width * scale)), max(1, round(height * scale))))
        ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, round(quality * 100)])
        if not ok:
            raise PipelineError("IPCAM_ENCODE_FAILED", "IP 视频源预览编码失败")
        return image, base64.b64encode(encoded).decode("ascii")

    async def run_ipcam() -> None:
        """确认启动后的唯一后台任务：循环取最新帧、共用 Pipeline 检测、发布一个结果包。

        输出保存在应用内存并唤醒 WebSocket；读取和编码在线程内等待。
        每张图只推理一次，所有观看者共用结果，不为慢观看者累积画面。
        """
        reader = application.state.ipcam_reader
        pipeline = application.state.pipeline
        tracker = None
        token = log_context.set((uuid4().hex[:12], "-"))
        messages = {
            "IPCAM_OPEN_FAILED": "无法打开 IP 视频源，请检查手机 App、地址和网络",
            "IPCAM_DISCONNECTED": "IP 视频源已断开，请检查网络后手动重新启动",
            "IPCAM_BAD_FRAME": "IP 视频源返回的图像尺寸或格式不符合要求",
            "IPCAM_READ_FAILED": "读取 IP 视频源失败，请检查连接后重试",
        }
        try:
            # 一次 IP 采集共用一个轨迹上下文，多位观看者只看结果，不重复更新轨迹。
            tracker = pipeline.create_tracker()
            while True:
                captured = await asyncio.to_thread(reader.read)
                if captured is None:
                    status = reader.status()
                    if status["state"] == "error":
                        code = status["error_code"] or "IPCAM_READ_FAILED"
                        raise PipelineError(code, messages.get(code, "IP 视频源读取失败"))
                    continue
                settings = application.state.settings
                image, jpeg = await asyncio.to_thread(
                    prepare_ipcam_frame, captured.image, pipeline.recommended_max_side, settings.jpeg_quality,
                )
                # 结果序号跨多次开始/停止递增，旧会话的 after 不会挡住新会话。
                application.state.ipcam_sequence += 1
                sequence = application.state.ipcam_sequence
                log_context.set((log_context.get()[0], str(sequence)))
                result = await pipeline.process_frame(image, sequence, tracker=tracker)
                height, width = image.shape[:2]
                async with application.state.ipcam_condition:
                    application.state.ipcam_packet = {
                        "type": "ipcam_frame", "seq": sequence, "w": width, "h": height,
                        "img": jpeg, "result": result.model_dump(mode="json"),
                    }
                    application.state.ipcam_condition.notify_all()
                # 主动让出事件循环，让停止请求也有机会及时执行。
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            raise
        except PipelineError as error:
            application.state.ipcam_error = error_body(error.code, error.message)
            logger.warning("IP 视频源停止 code=%s", error.code)
        except Exception:
            application.state.ipcam_error = error_body("IPCAM_FAILED", "IP 视频源处理失败，请检查服务状态")
            logger.exception("IP 视频源处理失败")
        finally:
            try:
                await asyncio.to_thread(reader.stop)
            finally:
                try:
                    await pipeline.reset_tracker(tracker)
                finally:
                    async with application.state.ipcam_condition:
                        application.state.ipcam_packet = None
                        application.state.ipcam_condition.notify_all()
                    log_context.reset(token)

    async def stop_ipcam_task() -> None:
        """取消处理任务、等待读取进程关闭并清除预览，由控制接口和服务退出调用。

        调用方持有 ipcam_lock，使同时到来的开始/停止操作按顺序执行。
        """
        task = application.state.ipcam_task
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        reader = application.state.ipcam_reader
        if reader is not None:
            await asyncio.to_thread(reader.stop)
        application.state.ipcam_task = None
        application.state.ipcam_packet = None
        application.state.ipcam_error = None
        async with application.state.ipcam_condition:
            application.state.ipcam_condition.notify_all()

    async def next_ipcam_packet(after: int) -> dict:
        """输入已显示序号，等待更新的结果包；停止或失败时退出，不返回过期画面。"""
        async with application.state.ipcam_condition:
            while True:
                if application.state.ipcam_error:
                    raise PipelineError("IPCAM_STOPPED", "IP 视频源已发生错误，请查看状态后重试")
                packet = application.state.ipcam_packet
                if packet is not None and packet["seq"] > after:
                    return packet
                reader = application.state.ipcam_reader
                if reader is None or reader.status()["state"] == "idle":
                    raise PipelineError("IPCAM_NOT_STARTED", "IP 视频源尚未启动，请先明确确认启动")
                await application.state.ipcam_condition.wait()


    @application.middleware("http")
    async def request_log(request: Request, call_next):
        """框架传入 HTTP 请求和 call_next，输出带日志编号的响应。

        调用 call_next 进入路由；意外错误转为中文响应，并在 finally 恢复原上下文。
        """
        request_id = uuid4().hex[:12]
        token = log_context.set((request_id, "-"))
        started = perf_counter()
        try:
            try:
                response = await call_next(request)
            except Exception:
                logger.exception("HTTP 未预期异常 method=%s path=%r", request.method, request.url.path)
                response = JSONResponse(error_body("INTERNAL_ERROR", "服务处理失败，请检查错误日志"), 500)
            response.headers["X-Request-ID"] = request_id
            level = logging.ERROR if response.status_code >= 500 else (
                logging.WARNING if response.status_code >= 400 else logging.INFO
            )
            logger.log(level, "HTTP %s %r status=%s response_ms=%.2f",
                       request.method, request.url.path, response.status_code,
                       (perf_counter() - started) * 1000)
            return response
        finally:
            log_context.reset(token)

    @application.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, error: StarletteHTTPException) -> JSONResponse:
        """输入请求与 HTTP 异常，输出统一 JSON 错误，由框架自动调用。"""
        message = error.detail if isinstance(error.detail, str) else "请求无法处理"
        if error.status_code == 404 and message == "Not Found":
            message = "请求的地址不存在"
        if error.status_code == 405:
            message = "这个地址不支持当前请求方法"
        return JSONResponse(error_body("HTTP_ERROR", message), error.status_code, headers=error.headers)

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        """输入请求与参数检查异常，输出 422 JSON；框架在 HTTP 参数无效时调用。

        日志只记字段位置和错误类型，不写请求正文。
        """
        fields = [(item["loc"], item["type"]) for item in error.errors()]
        logger.warning("HTTP 参数无效 fields=%s", fields)
        return JSONResponse(error_body("BAD_REQUEST", "请求参数格式不正确"), 422)

    @application.exception_handler(SessionError)
    async def session_error(request: Request, error: SessionError):
        """把锁定/身份操作失败转换为中文业务错误，页面可直接显示。"""
        logger.warning("操作拒绝 path=%r code=%s message=%s", request.url.path, error.code, error.message)
        return JSONResponse(error_body(error.code, error.message), 409)

    @application.post("/api/lock")
    async def lock_target(action: LockRequest):
        """当前会话内锁定指定轨迹；不会访问其他连接的相同轨迹号。"""
        return await application.state.pipeline.session_action(action.session_id, "lock", action.track_id, action.seq, action.action)

    @application.post("/api/interaction-events")
    async def interaction_event(event: InteractionEvent):
        """接收受限的数字/枚举事件，关联当前会话；不读取设备，不接受媒体或任意文本。"""
        return await application.state.pipeline.session_action(event.session_id, "record_interaction",
                                                              event.model_dump(exclude={"session_id"}))

    @application.post("/api/select")
    async def select_target(action: SelectRequest):
        """按触点兜底锁定，坐标以原始画面为准。"""
        return await application.state.pipeline.session_action(action.session_id, "select", action.x, action.y, action.seq)

    @application.get("/api/identities")
    async def list_identities(session_id: str):
        """返回指定会话身份摘要；不暴露其他会话或内部特征。"""
        items = await application.state.pipeline.session_action(session_id, "summaries")
        return {"ok": True, "identities": [item.model_dump() for item in items]}

    @application.delete("/api/identities/{identity_id}")
    async def delete_identity(identity_id: str, session_id: str):
        """删除会话内身份；不存在的会话或身份返回业务错误。"""
        await application.state.pipeline.session_action(session_id, "delete", identity_id)
        return {"ok": True}

    @application.post("/api/identities/photo")
    async def upload_photo(request: Request, session_id: str):
        """限量流式读入照片，全程内存解析；multipart 不经过自动磁盘暂存。"""
        content = bytearray()
        async for chunk in request.stream():
            if len(content) + len(chunk) > MAX_PHOTO_BYTES:
                raise SessionError("PHOTO_TOO_LARGE", "请选择不超过 6 MiB 的照片")
            content.extend(chunk)
        return await application.state.pipeline.register_photo(session_id, bytes(content), request.headers.get("content-type", ""))

    @application.get("/api/identities/{identity_id}/thumbnail")
    async def identity_thumbnail(identity_id: str, session_id: str):
        """返回内存缩略图，禁止浏览器持久缓存；停止会话后立即不可访问。"""
        content = await application.state.pipeline.session_action(session_id, "thumbnail", identity_id)
        return Response(content, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @application.post("/api/record/start")
    async def start_record(action: RecordRequest):
        """显式确认录制，仍受服务的禁止保存配置限制，默认拒绝。"""
        return await application.state.pipeline.session_action(action.session_id, "start_record", action.confirm)

    @application.post("/api/record/stop")
    async def stop_record(action: RecordRequest):
        """停止当前会话录制，不影响检测；停止视频同样会关闭写入器。"""
        return await application.state.pipeline.session_action(action.session_id, "stop_record")

    @application.get("/api/record/file/{filename}")
    async def record_file(filename: str, session_id: str):
        """只返回本会话明确录制过的文件，禁止遍历或下载任意本机文件。"""
        path = await application.state.pipeline.session_action(session_id, "record_file", filename)
        return FileResponse(path, media_type="video/mp4", filename=path.name, headers={"Cache-Control": "no-store"})

    @application.get("/api/health")
    async def health(request: Request) -> JSONResponse:
        """框架在 GET /api/health 时传入请求，输出设备、模型和统计 JSON。

        供前端和人工排查使用；读取现有状态，不重新执行检测。
        """
        if not application.state.ready:
            return JSONResponse(error_body("SERVICE_NOT_READY", "检测服务尚未就绪"), 503)
        settings = application.state.settings
        pipeline = application.state.pipeline
        latest = pipeline.latest_result
        return JSONResponse({
            "ok": True, "version": application.version, "source": settings.source, "ipcam": ipcam_status(),
            "locking": {"mode": "single", "repeat_long_press": "unlock", "fresh_frame_verification": True},
            "diagnostics": {"interaction_events": True, "identity_rejection_reasons": True},
            "device": settings.det_device, "device_name": pipeline.detector.device_name,
            "cuda_available": pipeline.detector.cuda_available, "model": settings.det_model.name,
            "fps": latest.fps if latest else 0.0,
            "latency_ms": latest.latency_ms if latest else 0.0,
            "processed_frames": pipeline.processed_frames,
            "https": {"cert_file_present": settings.https_cert.is_file(),
                      "key_file_present": settings.https_key.is_file()},
            "mirror_config_present": (PROJECT_ROOT / "scripts/check_mirrors.ps1").is_file(),
            "logs_url": "/api/logs", "stage": "P7",
            "tracking": {"method": "BoT-SORT" if settings.tracker == "botsort.yaml" else "ByteTrack", "scope": "per_video_session"},
            "identity": {"mode": settings.identity_mode, "experimental": settings.identity_mode == "hybrid",
                         "face_method": "YuNet+SFace" if settings.identity_mode == "hybrid" else None,
                         "body_method": settings.reid_model, "face_threshold": settings.face_match_threshold,
                         "continuity_grace_seconds": settings.identity_hold_seconds,
                         "confirmation": {"required_positive_frames": settings.reid_confirm_frames,
                                          "max_consecutive_gaps": 2 if settings.identity_mode == "hybrid" else 0,
                                          "bounded_evidence_window": settings.identity_mode == "hybrid"},
                         "encoder_device": {
                             "body": getattr(getattr(pipeline.extractor, "person_encoder", None), "execution_device", None),
                             "face": getattr(pipeline.face_encoder, "execution_device", None)}},
            "reid": {"model": settings.reid_model, "high_threshold": settings.reid_tau_high,
                     "local_weights_present": (settings.person_weights if settings.reid_model == "osnet_x0_25" else settings.reid_weights).is_file(), "calibrated": settings.reid_calibrated,
                     "experimental_body_match_threshold": settings.body_match_threshold if settings.identity_mode == "hybrid" else None},
            "field_acceptance": {"live_reid": "pending", "android_install": "pending"},
            "recording": {"allowed": settings.allow_media_save},
            "capture": {"max_side": settings.max_side, "jpeg_quality": settings.jpeg_quality},
        })

    @application.get("/sw.js")
    async def service_worker():
        """根路径提供Worker，作用域覆盖主页面；不缓存检测API或用户媒体。"""
        return FileResponse(PROJECT_ROOT / "web/sw.js", media_type="application/javascript",
                            headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})

    @application.get("/api/ipcam/status")
    async def camera_status() -> JSONResponse:
        """无输入，输出状态；查询不会启动设备或暴露配置地址。"""
        require_ipcam()
        return JSONResponse({"ok": True, **ipcam_status()})

    @application.post("/api/ipcam/start")
    async def start_ipcam(action: IpCameraStart) -> JSONResponse:
        """接收 JSON confirm=true，启动配置的视频源；没有明确确认则拒绝。"""
        reader = require_ipcam()
        if not action.confirm:
            raise HTTPException(400, "请明确确认后再启动 IP 视频源")
        async with application.state.ipcam_lock:
            task = application.state.ipcam_task
            if task is not None and not task.done():
                return JSONResponse({"ok": True, **ipcam_status()})
            await stop_ipcam_task()
            await asyncio.to_thread(reader.start)
            application.state.ipcam_task = asyncio.create_task(run_ipcam())
            return JSONResponse({"ok": True, **ipcam_status()})

    @application.post("/api/ipcam/stop")
    async def stop_ipcam() -> JSONResponse:
        """无额外输入，停止网络读取并释放当前预览；重复操作安全。"""
        require_ipcam()
        async with application.state.ipcam_lock:
            await stop_ipcam_task()
            return JSONResponse({"ok": True, **ipcam_status()})

    @application.websocket("/ws/ipcam")
    async def ipcam_stream(websocket: WebSocket) -> None:
        """接收 next/after，返回更新的图像和框；连接本身不会启动读取。

        一问一答避免慢客户端积压，每个 img/result 来自同一帧；
        后续 IP 视频源页面调用本接口，浏览器摄像头仍走 /ws/stream。
        """
        token = log_context.set((uuid4().hex[:12], "-"))
        try:
            await websocket.accept()
            if application.state.ipcam_reader is None:
                await websocket.send_json(error_body("SOURCE_MISMATCH", "当前不是 IP 视频源模式"))
                await websocket.close(code=1008)
                return
            while True:
                event = await websocket.receive()
                if event["type"] == "websocket.disconnect":
                    break
                text = event.get("text")
                if text is None or len(text.encode("utf-8")) > 1024:
                    await websocket.send_json(error_body("BAD_REQUEST", "请发送小于 1024 字节的 next 请求"))
                    continue
                try:
                    pull = IpCameraPull.model_validate(json.loads(text))
                except (ValidationError, json.JSONDecodeError):
                    await websocket.send_json(error_body("BAD_REQUEST", "next 请求格式不正确"))
                    continue
                try:
                    packet = await asyncio.wait_for(next_ipcam_packet(pull.after), timeout=15)
                    await websocket.send_json(packet)
                except PipelineError as error:
                    await websocket.send_json(error_body(error.code, error.message))
                except asyncio.TimeoutError:
                    await websocket.send_json(error_body("IPCAM_WAIT_TIMEOUT", "等待新画面超时，请检查视频源状态"))
        except WebSocketDisconnect:
            pass
        except Exception:
            logger.exception("IP 视频源观看连接异常")
        finally:
            log_context.reset(token)

    @application.get("/api/logs")
    async def logs() -> JSONResponse:
        """GET /api/logs 入口，无额外输入，输出日志元信息 JSON，供诊断面板展示。"""
        files = []
        for name, path in log_files().items():
            info = path.stat()
            files.append({
                "name": name, "size_bytes": info.st_size,
                "modified_at": datetime.fromtimestamp(info.st_mtime, LOG_TIMEZONE).isoformat(),
                "download_url": f"/api/logs/{name}",
            })
        return JSONResponse({"ok": True, "files": files,
                             "max_file_bytes": LOG_MAX_BYTES, "backup_count": LOG_BACKUP_COUNT})

    @application.get("/api/logs/{name}")
    async def download_log(name: str) -> Response:
        """GET 下载入口，输入日志名，输出固定内容的附件，由诊断页面调用。

        日志始终在增长；不能用先取大小、稍后再读文件的方式发送。
        先在线程中复制内容，再由 Response 按副本的实际长度发送。
        """
        content = await asyncio.to_thread(read_log_snapshot, name)
        logger.info("日志下载 name=%s snapshot_bytes=%s", name, len(content))
        return Response(
            content=content,
            media_type="text/plain; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{name}"',
                "Cache-Control": "no-store",
            },
        )

    @application.get("/")
    @application.get("/pc")
    async def page() -> FileResponse:
        """GET / 和 /pc 入口，无额外输入，输出 HTML 文件；页面未创建时返回明确提示。"""
        index = PROJECT_ROOT / "web/index.html"
        if not index.is_file():
            raise HTTPException(503, "摄像头页面将在下一里程碑接入，当前可查看 /api/health 和 /api/logs")
        return FileResponse(index)

    web_dir = PROJECT_ROOT / "web"
    if web_dir.is_dir():
        application.mount("/static", StaticFiles(directory=web_dir), name="static")

    @application.websocket("/ws/stream")
    async def stream(websocket: WebSocket) -> None:
        """处理一条浏览器连接：循环接收消息，检查后交给 Pipeline，再返回 JSON。

        每条连接生成日志编号，每一帧记录自己的 seq；不记录 JPEG/Base64 正文。
        一帧返回后再读取下一帧，共享模型的最终串行控制仍由 Pipeline 负责。
        """
        connection_id = uuid4().hex[:12]
        token = log_context.set((connection_id, "-"))
        sent_frames = 0
        pipeline = tracker = None
        try:
            await websocket.accept(headers=[(b"x-request-id", connection_id.encode("ascii"))])
            logger.info("WS 连接建立")
            if not application.state.ready:
                await websocket.send_json(error_body("SERVICE_NOT_READY", "检测服务尚未就绪"))
                await websocket.close(code=1013)
                return
            if application.state.settings.source != "ws":
                await websocket.send_json(error_body("SOURCE_MISMATCH", "当前为 IP 视频源模式，请使用对应观看接口"))
                await websocket.close(code=1008)
                return
            pipeline = application.state.pipeline
            # 每条推帧连接独立保存轨迹，不能用同一个跟踪器处理不同手机的画面。
            tracker = pipeline.create_tracker()
            while True:
                log_context.set((connection_id, "-"))
                event = await websocket.receive()
                if event["type"] == "websocket.disconnect":
                    logger.info("WS 客户端断开 code=%s", event.get("code"))
                    break
                text = event.get("text")
                if text is None:
                    logger.warning("WS 拒绝二进制消息")
                    await websocket.send_json(error_body("BAD_FRAME", "请发送 JSON 文本帧消息"))
                    continue
                if len(text.encode("utf-8")) > MAX_MESSAGE_BYTES:
                    logger.warning("WS 消息超出大小上限")
                    await websocket.send_json(error_body("FRAME_TOO_LARGE", "帧消息过大，请降低发送尺寸"))
                    await websocket.close(code=1009)
                    break
                try:
                    payload = json.loads(text)
                    if isinstance(payload, dict):
                        seq = payload.get("seq")
                        if isinstance(seq, int) and not isinstance(seq, bool) and seq >= 0:
                            log_context.set((connection_id, str(seq)))
                    message = FrameMessage.model_validate(payload)
                except (json.JSONDecodeError, ValidationError) as error:
                    logger.warning("WS 帧格式错误 error_type=%s", type(error).__name__)
                    await websocket.send_json(error_body("BAD_FRAME", "帧消息 JSON 或必填字段不正确"))
                    continue
                try:
                    result = await pipeline.process_message(message, tracker=tracker)
                except PipelineError as error:
                    level = logging.ERROR if error.code == "INFERENCE_FAILED" else logging.WARNING
                    logger.log(level, "帧处理失败 code=%s message=%s", error.code, error.message)
                    await websocket.send_json(error_body(error.code, error.message))
                    continue
                except Exception:
                    logger.exception("未预期的帧处理异常")
                    await websocket.send_json(error_body("INTERNAL_ERROR", "帧处理失败，请检查错误日志"))
                    continue
                await websocket.send_json(result.model_dump(mode="json"))
                sent_frames += 1
                # 常态只记首帧和每 30 帧摘要；DEBUG 模式可记录每帧，避免 INFO 日志增长过快。
                level = logging.INFO if sent_frames == 1 or sent_frames % 30 == 0 else logging.DEBUG
                logger.log(level, "帧完成 boxes=%s fps=%.2f latency_ms=%.2f",
                           len(result.boxes), result.fps, result.latency_ms)
        except WebSocketDisconnect as error:
            logger.info("WS 连接断开 code=%s", error.code)
        except Exception:
            logger.exception("WS 连接异常")
            if websocket.application_state == WebSocketState.CONNECTED:
                try:
                    await websocket.close(code=1011)
                except (RuntimeError, WebSocketDisconnect):
                    pass
        finally:
            try:
                if pipeline is not None:
                    await pipeline.reset_tracker(tracker)
            finally:
                logger.info("WS 连接结束 sent_frames=%s", sent_frames)
                log_context.reset(token)

    return application


# ASGI 入口：python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
app = create_app()
