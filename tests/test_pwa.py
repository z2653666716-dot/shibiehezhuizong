"""检查PWA安装资源、只缓存界面和默认禁用录制，浏览器隐私权限始终拒绝。"""
import pytest

from scripts.verify_stream import DEFAULT_BROWSER
from tests.test_ipcamera import sample_stream
from tests.test_ipcam_page import viewer


@pytest.mark.skipif(not DEFAULT_BROWSER.is_file(), reason="Edge is unavailable")
def test_shell_cache_does_not_cache_media(viewer):
    """真实Worker安装、核对manifest/PNG和缓存清单；不开始任何视频源。"""
    session, _ = viewer
    result = session.evaluate("""(async()=>{
      const registration=await navigator.serviceWorker.ready;
      const manifest=await (await fetch('/static/manifest.webmanifest')).json();
      const names=await caches.keys();
      const urls=[];
      for(const name of names) for(const request of await (await caches.open(name)).keys()) urls.push(new URL(request.url).pathname);
      return {active:!!registration.active,display:manifest.display,icons:manifest.icons.map(x=>x.sizes),
        urls,recordDisabled:document.getElementById('record-video').disabled,
        calls:deviceCalls,session:ui.interaction.session};
    })()""")
    assert result["active"] and result["display"] == "standalone"
    assert result["icons"] == ["192x192", "512x512"]
    assert "/static/icons/icon-512.png" in result["urls"]
    assert not any(path.startswith(("/api/", "/outputs/", "/ws/")) for path in result["urls"])
    assert result["recordDisabled"] and result["session"] is None and result["calls"] == 0
    # 模拟断网后重新导航，验证真正从Worker得到界面，而不是只检查文件存在。
    session.call("Network.enable")
    session.call("Network.emulateNetworkConditions", {"offline": True, "latency": 0,
                 "downloadThroughput": 0, "uploadThroughput": 0})
    session.call("Page.navigate", {"url": _ + "/pc"})
    session.wait("document.getElementById('page-status')?.textContent.includes('无法连接电脑')", timeout=15)
    assert session.evaluate("document.title.startsWith('ViTrack') && document.getElementById('start-detection').disabled")
    session.call("Network.emulateNetworkConditions", {"offline": False, "latency": 0,
                 "downloadThroughput": -1, "uploadThroughput": -1})
