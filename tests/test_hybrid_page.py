"""用公开示例的人脸临时裁剪验证实验版真实照片页面；拒绝全部物理设备权限。"""
from pathlib import Path

import cv2
import pytest

from app.config import AppConfig, PROJECT_ROOT
from app.faces import FaceEncoder
from scripts.verify_stream import DEFAULT_BROWSER
from tests.test_ipcamera import sample_stream
from tests.test_ipcam_page import viewer, start_sample
from tests.test_hybrid_identity import MODELS_READY


@pytest.fixture
def hybrid_viewer(monkeypatch, request):
    """复用隔离Edge与本机公开MJPEG，只在本测试进程明确启用实验设置。"""
    for name, value in {"IDENTITY_MODE": "hybrid", "IDENTITY_DEVICE": "cpu", "REID_MODEL": "osnet_x0_25",
                        "TRACKER": "botsort.yaml", "MAX_SIDE": "960"}.items():
        monkeypatch.setenv(name, value)
    return request.getfixturevalue("viewer")


@pytest.mark.skipif(not MODELS_READY or not DEFAULT_BROWSER.is_file(), reason="experimental models or Edge missing")
def test_real_photo_page_can_register_face_portrait(hybrid_viewer, tmp_path):
    """真实API登记脸部特写→缩略图→同一公开人物变绿；960只让公开图脸像素充足，不改生产默认640。"""
    browser, _ = hybrid_viewer
    assert browser.evaluate("""(async()=>{
      const health=await(await fetch('/api/health')).json();
      return document.getElementById('app-version').textContent.includes(health.version);
    })()""")
    assert "支持清晰单人人脸照" in browser.evaluate("document.querySelector('.photo-hint').textContent")
    image = cv2.imread(str(PROJECT_ROOT / "data/samples/test.jpg"))
    faces = [face for face in FaceEncoder(AppConfig(det_device="cpu")).read(image) if face.feature is not None]
    face = max(faces, key=lambda item: (item.xyxy[2] - item.xyxy[0]) * (item.xyxy[3] - item.xyxy[1]))
    left, top, right, bottom = face.xyxy
    dx, dy = int((right - left) * .3), int((bottom - top) * .3)
    photo = image[max(0, top - dy):bottom + dy, max(0, left - dx):right + dx]
    path = tmp_path / "public_face.jpg"
    path.write_bytes(cv2.imencode(".jpg", photo)[1].tobytes())
    start_sample(browser, frames=8)
    document = browser.call("DOM.getDocument")
    node = browser.call("DOM.querySelector", {"nodeId": document["root"]["nodeId"], "selector": "#photo-file"})
    browser.call("DOM.setFileInputFiles", {"nodeId": node["nodeId"], "files": [str(path)]})
    browser.wait("document.getElementById('photo-status').dataset.state==='registered'", timeout=20)
    browser.wait("ui.boxes.some(box=>box.state==='locked'&&box.identity_id==='ID-01')", timeout=20)
    assert "人脸身份" in browser.evaluate("document.getElementById('photo-status').textContent")
    assert browser.evaluate("document.querySelectorAll('.identity-card').length") == 1
    assert browser.evaluate("deviceCalls") == 0
    browser.evaluate("document.getElementById('stop-detection').click()")
    browser.wait("ui.state==='idle'")
    assert browser.evaluate("document.getElementById('photo-preview').getAttribute('src')") is None
