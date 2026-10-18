"""用官方公开bus照片验证真实模型的照片注册页面；隐私权限拒绝，不接触实拍内容。"""
from pathlib import Path

import pytest

from scripts.verify_stream import DEFAULT_BROWSER
from tests.test_ipcamera import sample_stream
from tests.test_ipcam_page import viewer, start_sample


@pytest.mark.skipif(not DEFAULT_BROWSER.is_file(), reason="Edge is unavailable")
def test_public_photo_upload_matches_live_sample(viewer):
    """手动选择的等价操作只指向公开文件，检查照片提示、缩略图、匹配与删除。"""
    session, _ = viewer
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
    session.evaluate("document.querySelector('.identity-card button:last-child').click()")
    session.wait("document.querySelectorAll('.identity-card').length===0 && ui.boxes.every(box=>box.state==='none')")
