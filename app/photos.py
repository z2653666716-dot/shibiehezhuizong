"""在内存中解析有大小上限的照片上传，不使用会把大文件暂存磁盘的 UploadFile。

HTTP 接口先限流读取请求，本模块检查 JPEG/PNG 头部、尺寸和 EXIF 方向，供 Pipeline 注册。
"""
from email.parser import BytesParser
from email.policy import default
from io import BytesIO

import cv2
import numpy as np
from PIL import Image, ImageOps
from PIL.JpegImagePlugin import JpegImageFile
from PIL.PngImagePlugin import PngImageFile

from .session import SessionError

MAX_PHOTO_BYTES = 6 * 1024 * 1024
MAX_PHOTO_SIDE = 4096


def decode_photo(content, content_type):
    """输入最多6MiB的请求体及类型，输出BGR图片；文件名只当元信息，不用于路径。"""
    if not content or len(content) > MAX_PHOTO_BYTES:
        raise SessionError("PHOTO_TOO_LARGE", "请选择不超过 6 MiB 的照片")
    if content_type.lower().startswith("multipart/form-data"):
        if len(content_type) > 512:
            raise SessionError("BAD_PHOTO", "照片上传格式不正确")
        message = BytesParser(policy=default).parsebytes(
            ("Content-Type: " + content_type + "\r\nMIME-Version: 1.0\r\n\r\n").encode("ascii") + content)
        parts = [part for part in message.iter_parts()
                 if part.get_param("name", header="content-disposition") in {"photo", "file"}]
        if len(parts) != 1:
            raise SessionError("BAD_PHOTO", "请一次选择一张照片")
        content = parts[0].get_payload(decode=True)
    # 明确选格式，避免第三方接管通用 Image.open 后尝试安装 HEIF 等无关依赖。
    if content and content.startswith(b"\xff\xd8\xff"):
        opener = JpegImageFile
    elif content and content.startswith(b"\x89PNG\r\n\x1a\n"):
        opener = PngImageFile
    else:
        raise SessionError("BAD_PHOTO", "请选择有效的 JPEG 或 PNG 照片")
    try:
        with opener(BytesIO(content)) as image:
            if image.format not in {"JPEG", "PNG"}:
                raise SessionError("BAD_PHOTO", "请选择 JPEG 或 PNG 照片")
            if max(image.size) > MAX_PHOTO_SIDE or min(image.size) < 16:
                raise SessionError("PHOTO_SIZE", "照片宽高应在 16～4096 像素之间，请先缩小超大照片")
            # EXIF 旋转在检测前统一完成，避免手机竖拍照片的坐标方向错误。
            rgb = np.asarray(ImageOps.exif_transpose(image).convert("RGB"))
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    except SessionError:
        raise
    except (OSError, ValueError, TypeError, SyntaxError, Image.DecompressionBombError) as error:
        raise SessionError("BAD_PHOTO", "照片损坏或不是有效的 JPEG/PNG 图片") from error
