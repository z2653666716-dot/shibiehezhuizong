"""模拟安卓系统相册让网页隐藏再返回，验证照片上传仍属于原会话；仅使用公开图合成轨道。

复用隔离Edge和真实HTTP/WS接口，不读取用户相册，不开启物理摄像头或麦克风。
"""
from pathlib import Path

import pytest

from scripts.verify_stream import DEFAULT_BROWSER
from tests.test_ipcamera import sample_stream
from tests.test_ipcam_page import viewer


@pytest.mark.skipif(not DEFAULT_BROWSER.is_file(), reason="Edge is unavailable")
@pytest.mark.parametrize("viewer", ["ws"], indirect=True)
@pytest.mark.parametrize("return_before_selection", [True, False])
def test_picker_background_preserves_session_and_upload(viewer, return_before_selection):
    """相册隐藏期间暂停视频轨道，返回后同一会话登记公开照片；普通切后台仍应断开。"""
    browser, _ = viewer
    browser.evaluate("document.getElementById('start-detection').click()")
    browser.wait("ui.received>=8")
    browser.evaluate("window.originalPhotoSession=ui.interaction.session")
    browser.call("Page.setInterceptFileChooserDialog", {"enabled": True})
    browser.evaluate("document.getElementById('upload-photo').click()")
    # 仅覆盖document.hidden模拟原生相册的生命周期，不授予任何设备权限。
    browser.evaluate("""(()=>{
      Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});
      document.dispatchEvent(new Event('visibilitychange'));
    })()""")
    assert browser.evaluate("ui.interaction.session===originalPhotoSession")
    assert browser.evaluate("ui.camera.stream.getVideoTracks().every(track=>!track.enabled)")
    browser.evaluate("window.hiddenFrames=ui.received")
    browser.evaluate("new Promise(resolve=>setTimeout(resolve,400))")
    assert browser.evaluate("ui.received<=hiddenFrames+1")
    show_page = """(()=>{
      Object.defineProperty(document,'hidden',{configurable:true,get:()=>false});
      document.dispatchEvent(new Event('visibilitychange'));
    })()"""
    if return_before_selection:
        browser.evaluate(show_page)
    document = browser.call("DOM.getDocument")
    node = browser.call("DOM.querySelector", {"nodeId": document["root"]["nodeId"], "selector": "#photo-file"})
    browser.call("DOM.setFileInputFiles", {"nodeId": node["nodeId"],
        "files": [str(Path(__file__).resolve().parents[1] / "data/samples/test.jpg")]})
    browser.wait("document.getElementById('photo-status').dataset.state==='registered'", timeout=25)
    assert browser.evaluate("ui.interaction.session===originalPhotoSession")
    if not return_before_selection:
        # 安卓可能先发送选照结果，稍后才通知网页可见；成功登记不能因此被清空。
        assert browser.evaluate("ui.camera.stream.getVideoTracks().every(track=>!track.enabled)")
        browser.evaluate(show_page)
    browser.wait("ui.boxes.some(box=>box.state==='locked')", timeout=20)
    assert browser.evaluate("ui.camera.stream.getVideoTracks().every(track=>track.enabled)")
    assert browser.evaluate("deviceCalls") == 0
    # 相册流程结束后，不把一般的切后台误当成选照，也不能永久保留旧会话。
    browser.evaluate("""(()=>{
      Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});
      document.dispatchEvent(new Event('visibilitychange'));
    })()""")
    assert browser.evaluate("ui.interaction.session===null && ui.socket===null")
    browser.evaluate("document.getElementById('stop-detection').click()")
    assert browser.evaluate("ui.camera.state==='idle'")


@pytest.mark.skipif(not DEFAULT_BROWSER.is_file(), reason="Edge is unavailable")
@pytest.mark.parametrize("viewer", ["ws"], indirect=True)
def test_picker_cancel_network_error_and_stop_abort(viewer):
    """取消相册不破坏会话；断网上传给出中文原因；停止能取消在途上传，旧结果不覆盖界面。"""
    browser, _ = viewer
    browser.evaluate("document.getElementById('start-detection').click()")
    browser.wait("ui.received>=5")
    browser.call("Page.setInterceptFileChooserDialog", {"enabled": True})
    browser.evaluate("""(()=>{
      window.originalPhotoSession=ui.interaction.session;
      document.getElementById('upload-photo').click();
      Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});
      document.dispatchEvent(new Event('visibilitychange'));
      document.getElementById('photo-file').dispatchEvent(new Event('cancel'));
    })()""")
    assert browser.evaluate("ui.interaction.session===originalPhotoSession && !ui.interaction.photoSelecting")
    browser.evaluate("""(()=>{
      Object.defineProperty(document,'hidden',{configurable:true,get:()=>false});
      document.dispatchEvent(new Event('visibilitychange'));
      const originalFetch=window.fetch;
      window.photoTestMode='network';window.photoSignalAborted=false;
      window.fetch=(path,options)=>{
        if(String(path).startsWith('/api/identities/photo')){
          if(photoTestMode==='network') return Promise.reject(new TypeError('test offline'));
          return new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>{
            photoSignalAborted=true;reject(new DOMException('test stopped','AbortError'));
          },{once:true}));
        }
        return originalFetch(path,options);
      };
    })()""")
    document = browser.call("DOM.getDocument")
    node = browser.call("DOM.querySelector", {"nodeId": document["root"]["nodeId"], "selector": "#photo-file"})
    file_selection = {"nodeId": node["nodeId"],
                      "files": [str(Path(__file__).resolve().parents[1] / "data/samples/test.jpg")]}
    browser.call("DOM.setFileInputFiles", file_selection)
    browser.wait("document.getElementById('photo-status').dataset.state==='error'")
    assert "未能连接电脑" in browser.evaluate("document.getElementById('photo-status').textContent")
    assert browser.evaluate("!document.getElementById('upload-photo').disabled && !ui.interaction.photoUploading")
    browser.evaluate("window.photoTestMode='wait'")
    browser.call("DOM.setFileInputFiles", file_selection)
    browser.wait("ui.interaction.photoUploading")
    browser.evaluate("document.getElementById('stop-detection').click()")
    browser.wait("photoSignalAborted")
    assert browser.evaluate("ui.camera.state==='idle' && ui.interaction.session===null")
    assert browser.evaluate("document.getElementById('photo-status').dataset.state") == "idle"
    assert browser.evaluate("document.getElementById('photo-file').value") == ""
    assert browser.evaluate("deviceCalls") == 0


@pytest.mark.skipif(not DEFAULT_BROWSER.is_file(), reason="Edge is unavailable")
@pytest.mark.parametrize("viewer", ["ws"], indirect=True)
def test_expired_picker_cannot_resume_camera(viewer):
    """模拟后台计时器延迟，返回时已过期限必须结束合成轨道，不能自动恢复视频。"""
    browser, _ = viewer
    browser.evaluate("document.getElementById('start-detection').click()")
    browser.wait("ui.received>=5")
    browser.call("Page.setInterceptFileChooserDialog", {"enabled": True})
    browser.evaluate("""(()=>{
      document.getElementById('upload-photo').click();
      Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});
      document.dispatchEvent(new Event('visibilitychange'));
      ui.photoPauseDeadline=Date.now()-1;
      Object.defineProperty(document,'hidden',{configurable:true,get:()=>false});
      document.dispatchEvent(new Event('visibilitychange'));
    })()""")
    assert browser.evaluate("ui.camera.state==='idle' && ui.socket===null && ui.interaction.session===null")
    assert browser.evaluate("syntheticTracks.every(track=>track.readyState==='ended')")
    assert "超时" in browser.evaluate("document.getElementById('photo-status').textContent")
