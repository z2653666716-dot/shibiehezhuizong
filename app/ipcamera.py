"""读取网络摄像头，属于 P2 的 IP 视频源；不做检测、不保存画面。

输入为明确配置的 http/https/rtsp 地址；start 后子进程才连接，read 返回最新 BGR 帧。
main.py 在用户确认启动后调用本类，再把图像交给 Pipeline.process_frame。
独立进程让停止操作可以中断原生库卡住的网络读取，避免设备一直被占用。
"""

from dataclasses import dataclass
import multiprocessing
import os
from queue import Empty
import threading
import time
from urllib.parse import urlsplit

import numpy as np


OPEN_TIMEOUT_MS = 5000
READ_TIMEOUT_MS = 2000
MAX_FRAME_SIDE = 4096
DEFAULT_MAX_SIDE = 640


@dataclass(frozen=True)
class CapturedFrame:
    """read 的返回值：seq 是采集序号，image 是 BGR 像素；不含文件路径或身份信息。"""

    seq: int
    image: np.ndarray


def _read_stream(url, pixels, metadata, frame_lock, events, stop_event,
                 open_timeout_ms, read_timeout_ms, max_side):
    """子进程执行：连接网络流、持续取帧；共享内存返回图像，小队列返回状态。

    URL 只传给 OpenCV，不记录到输出；固定像素槽只保留一帧，events 只发送小型状态。
    原生读取可能卡住，因此父进程还会在 stop 时终止未及时退出的子进程。
    """
    # 避免第三方库把带账号密码的完整流地址写到标准错误；可定位的错误码经 events 返回。
    with open(os.devnull, "w") as quiet:
        os.dup2(quiet.fileno(), 2)
        os.environ["OPENCV_LOG_LEVEL"] = "SILENT"
        capture = None
        try:
            # 某些 OpenCV 构建没有 setLogLevel；环境变量和标准错误隔离已足够。
            import cv2
            capture = cv2.VideoCapture(url, cv2.CAP_FFMPEG, [
                cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, open_timeout_ms,
                cv2.CAP_PROP_READ_TIMEOUT_MSEC, read_timeout_ms,
            ])
            if not capture.isOpened():
                events.put(("error", "IPCAM_OPEN_FAILED"))
                return
            events.put(("running", None))
            sequence = 0
            while not stop_event.is_set():
                ok, image = capture.read()
                if not ok:
                    if not stop_event.is_set():
                        events.put(("error", "IPCAM_DISCONNECTED"))
                    break
                if (image is None or image.dtype != np.uint8 or image.ndim != 3 or
                        image.shape[2] != 3 or min(image.shape[:2]) <= 0 or
                        max(image.shape[:2]) > MAX_FRAME_SIDE):
                    events.put(("error", "IPCAM_BAD_FRAME"))
                    break
                height, width = image.shape[:2]
                scale = min(1.0, max_side / max(height, width))
                if scale < 1:
                    image = cv2.resize(image, (max(1, round(width * scale)), max(1, round(height * scale))))
                sequence += 1
                # 共享内存只留一个图像槽。先写像素再写尺寸/序号，读者不会拿到半张新图。
                # 不通过 Queue 传大图，避免进程中断后消费者卡在半个序列化消息中。
                with frame_lock:
                    np.frombuffer(pixels, dtype=np.uint8)[:image.size] = image.reshape(-1)
                    metadata[:] = [sequence, image.shape[0], image.shape[1]]
        except Exception:
            events.put(("error", "IPCAM_READ_FAILED"))
        finally:
            if capture is not None:
                capture.release()


class IpCamera:
    """管理网络读取子进程；输入 URL/超时，输出最新帧和不含 URL 的状态。

    构造函数不连接网络。main.py 调用 start/read/stop，并在后台线程等待 read。
    读写锁保护生命周期；read 等待新帧时不持生命周期锁，使 stop 可以及时执行。
    """

    def __init__(self, url: str, open_timeout_ms: int = OPEN_TIMEOUT_MS,
                 read_timeout_ms: int = READ_TIMEOUT_MS, max_side: int = DEFAULT_MAX_SIDE):
        """校验网络 URL、超时和帧槽大小；不支持数字设备编号或本地文件。"""
        address = urlsplit(url)
        if address.scheme not in {"http", "https", "rtsp"} or not address.hostname:
            raise ValueError("IP 视频源只接受 http/https/rtsp 网络地址")
        address.port
        if any(isinstance(value, bool) or not isinstance(value, int) or not 100 <= value <= 30000
               for value in (open_timeout_ms, read_timeout_ms)):
            raise ValueError("视频源超时应为 100～30000 毫秒")
        if isinstance(max_side, bool) or not isinstance(max_side, int) or not 32 <= max_side <= 2048:
            raise ValueError("图像最长边应为 32～2048 像素")
        self.url = url
        self.open_timeout_ms = open_timeout_ms
        self.read_timeout_ms = read_timeout_ms
        self.max_side = max_side
        self._context = multiprocessing.get_context("spawn")
        self._lock = threading.RLock()
        self._process = None
        self._pixels = self._metadata = self._frame_lock = self._events = self._stop_event = None
        self.state = "idle"
        self.error_code = None
        self.last_seq = 0

    def start(self) -> None:
        """用户确认后调用，无额外输入；创建一次读取进程，重复 start 不重复连接。"""
        with self._lock:
            if self._process is not None:
                return
            self._pixels = self._context.RawArray("B", self.max_side * self.max_side * 3)
            self._metadata = self._context.RawArray("q", 3)
            self._frame_lock = self._context.Lock()
            self._events = self._context.Queue(maxsize=4)
            self._stop_event = self._context.Event()
            process = self._context.Process(
                target=_read_stream,
                args=(self.url, self._pixels, self._metadata, self._frame_lock, self._events, self._stop_event,
                      self.open_timeout_ms, self.read_timeout_ms, self.max_side),
                daemon=True,
            )
            # 先成功启动，再发布进程引用，避免状态显示成已开启但实际上没有进程。
            try:
                process.start()
            except Exception:
                self._events.close()
                raise
            self._process = process
            self.state = "opening"
            self.error_code = None
            self.last_seq = 0

    def read(self, timeout: float = 0.2) -> CapturedFrame | None:
        """在限时内读取一帧；输入等待秒数，输出 CapturedFrame 或 None。

        生命周期事件优先更新状态；seq 跳号意味着主动丢弃旧帧，不代表传错顺序。
        共享锁限时获取，停止中的旧进程即使没释放锁，也不能让 read 永久等待。
        main.py 需循环调用，并在 state=error 时停止本次读取，等待用户决定是否重试。
        """
        if not 0 <= timeout <= 2:
            raise ValueError("read 等待时间应在 0～2 秒")
        with self._lock:
            process, events = self._process, self._events
            pixels, metadata, frame_lock = self._pixels, self._metadata, self._frame_lock
        if process is None:
            return None
        try:
            updates = []
            while True:
                try:
                    updates.append(events.get_nowait())
                except Empty:
                    break
            with self._lock:
                if process is not self._process:
                    return None
                for state, code in updates:
                    self.state, self.error_code = state, code
                if self.state == "error":
                    return None
            deadline = time.monotonic() + timeout
            while True:
                with self._lock:
                    if process is not self._process:
                        return None
                if frame_lock.acquire(timeout=min(0.02, max(0, deadline - time.monotonic()))):
                    try:
                        sequence, height, width = metadata[:]
                        with self._lock:
                            if process is not self._process:
                                return None
                            if sequence > self.last_seq:
                                # 必须在锁内复制；返回后生产者可以覆盖共享槽，不能让推理读到变化中的像素。
                                image = np.frombuffer(pixels, dtype=np.uint8, count=height * width * 3)
                                image = image.reshape(height, width, 3).copy()
                                self.last_seq = sequence
                                self.state = "running"
                                return CapturedFrame(sequence, image)
                    finally:
                        frame_lock.release()
                if not process.is_alive():
                    with self._lock:
                        if process is self._process:
                            self.state, self.error_code = "error", "IPCAM_DISCONNECTED"
                    return None
                if time.monotonic() >= deadline:
                    return None
                # 这里只是等新帧，不持有共享锁；5ms 的间隔避免空转占满 CPU。
                time.sleep(min(0.005, max(0, deadline - time.monotonic())))
        except (OSError, ValueError):
            # stop 可以在另一线程释放资源；过期 read 不得让已停止的流恢复运行。
            with self._lock:
                if process is self._process:
                    self.state, self.error_code = "error", "IPCAM_READ_FAILED"
            return None

    def status(self) -> dict:
        """无输入，输出当前状态和最后采集序号；不公开 URL、密码或图像。"""
        with self._lock:
            return {"state": self.state, "error_code": self.error_code, "last_seq": self.last_seq}

    def stop(self) -> None:
        """无输入，先请求退出，再限时终止阻塞进程，释放共享资源；重复调用安全。"""
        with self._lock:
            process = self._process
            if process is None:
                return
            self._process = None
            events = self._events
            self._stop_event.set()
            self._pixels = self._metadata = self._frame_lock = self._events = self._stop_event = None
            self.state, self.error_code = "idle", None
        process.join(timeout=0.3)
        if process.is_alive():
            process.terminate()
            process.join(timeout=2)
        if process.is_alive():
            process.kill()
            process.join(timeout=2)
        if process.is_alive():
            raise RuntimeError("网络视频读取进程未退出")
        process.close()
        events.close()
        events.cancel_join_thread()
