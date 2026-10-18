"""用官方公开bus照片验证真实模型的照片注册页面；隐私权限拒绝，不接触实拍内容。"""
from pathlib import Path

import cv2
import numpy as np
import pytest

from scripts.verify_stream import DEFAULT_BROWSER
from tests.test_ipcamera import sample_stream
from tests.test_ipcam_page import viewer, start_sample


@pytest.mark.skipif(not DEFAULT_BROWSER.is_file(), reason="Edge is unavailable")
def test_public_photo_upload_matches_live_sample(viewer, tmp_path):
    """手动选择的等价操作只指向公开文件，检查照片提示、缩略图、匹配与删除。"""
    session, _ = viewer
    session.call("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844,
        "deviceScaleFactor": 1, "mobile": True})
    start_sample(session, frames=8)
    assert session.evaluate("document.getElementById('upload-photo').disabled") is False
    document = session.call("DOM.getDocument")
    node = session.call("DOM.querySelector", {"nodeId": document["root"]["nodeId"], "selector": "#photo-file"})
    session.evaluate("window.photoStartedAt=performance.now()")
    session.call("DOM.setFileInputFiles", {"nodeId": node["nodeId"],
        "files": [str(Path(__file__).resolve().parents[1] / "data/samples/test.jpg")]})
    session.wait("ui.boxes.some(box=>box.state==='locked'&&box.identity_id==='ID-01')", timeout=15)
    result = session.evaluate("""({
      locked:ui.boxes.filter(box=>box.state==='locked').length,
      candidates:ui.boxes.filter(box=>box.state==='candidate').length,
      elapsedMs:performance.now()-photoStartedAt,
      thumbs:document.querySelectorAll('.identity-card img').length,
      photoCleared:document.getElementById('photo-file').value==='',calls:deviceCalls,
      message:document.getElementById('toast').textContent
    })""")
    assert result["locked"] == 1 and result["thumbs"] == 1 and result["photoCleared"]
    assert result["calls"] == 0
    assert session.evaluate("document.getElementById('photo-status').dataset.state") == "registered"
    assert "登记成功" in session.evaluate("document.getElementById('photo-status').textContent")
    assert "匹配成功" in session.evaluate("document.getElementById('photo-match-status').textContent")
    session.wait("document.getElementById('photo-preview').naturalWidth>0")
    assert session.evaluate("document.getElementById('photo-section').getBoundingClientRect().top < document.getElementById('camera-section').getBoundingClientRect().top")
    assert session.evaluate("document.documentElement.scrollWidth<=window.innerWidth")
    # 模拟即时提示过期；登记状态应常驻，不随toast隐藏。
    session.evaluate("document.getElementById('toast').hidden=true")
    assert "登记成功" in session.evaluate("document.getElementById('photo-status').textContent")
    session.evaluate("document.querySelector('.identity-card button:last-child').click()")
    session.wait("document.querySelectorAll('.identity-card').length===0 && ui.boxes.every(box=>box.state==='none')")
    session.wait("document.getElementById('photo-preview').hidden")
    # 合成黑图在真实照片接口应报无人，失败原因也必须常驻显示。
    empty = tmp_path / "empty_photo.png"
    empty.write_bytes(cv2.imencode(".png", np.zeros((64, 64, 3), np.uint8))[1].tobytes())
    session.call("DOM.setFileInputFiles", {"nodeId": node["nodeId"], "files": [str(empty)]})
    session.wait("document.getElementById('photo-status').dataset.state==='error'")
    assert "照片中没有检测到人物" in session.evaluate("document.getElementById('photo-status').textContent")
    assert "脸部特写" in session.evaluate("document.getElementById('photo-status').textContent")
    # 停止时清空状态，旧成功图片地址不能继续留在页面中。
    session.evaluate("document.getElementById('stop-detection').click()")
    session.wait("ui.state==='idle'")
    assert session.evaluate("document.getElementById('photo-status').dataset.state") == "idle"
    assert session.evaluate("document.getElementById('photo-preview').getAttribute('src')") is None
