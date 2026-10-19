"""用独立 Edge 验证 IP 观看页面，只读取本机官方样例流，始终拒绝摄像头和麦克风权限。

运行入口：项目 Python -m pytest tests/test_ipcam_page.py；不操作用户日常浏览器。
复用 test_ipcamera 的 MJPEG 样例服务，用真实 FastAPI/YOLO 检查页面、取消和错误状态。
"""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx
import pytest

from scripts.verify_stream import BrowserSession, DEFAULT_BROWSER, sample_source
from tests.test_ipcamera import sample_stream


PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 页面中只保留控制消息的类型和数量，绝不把返回的图像写入报告。
GUARD = r"""
window.deviceCalls=0;window.maximumPending=0;window.sentTypes=[];
navigator.mediaDevices.getUserMedia=async()=>{deviceCalls++;throw new Error("test forbids devices")};
const NativeSocket=window.WebSocket;
window.WebSocket=class extends NativeSocket{
  constructor(...args){super(...args);this.testPending=0;
    this.addEventListener("message",()=>this.testPending=Math.max(0,this.testPending-1));}
  send(text){const body=JSON.parse(text);this.testPending++;
    maximumPending=Math.max(maximumPending,this.testPending);sentTypes.push(body.type);
    if(sentTypes.length>300)sentTypes.shift();return super.send(text);}
};
"""


@pytest.fixture
def viewer(sample_stream, tmp_path, request):
    """启动隔离服务/浏览器；默认IP样例，间接参数ws改用公开图合成轨道，始终拒绝设备。"""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    base_url = "http://127.0.0.1:" + str(port)
    environment = os.environ.copy()
    source = getattr(request, "param", "ipcam")
    environment.update(SOURCE=source, IPCAM_URL=sample_stream["url"] + "/video")
    server = browser = session = None
    with (tmp_path / "service.txt").open("w", encoding="utf-8") as output:
        try:
            server = subprocess.Popen(
                [sys.executable, "-X", "utf8", "-m", "uvicorn", "app.main:app",
                 "--host", "127.0.0.1", "--port", str(port), "--workers", "1"],
                cwd=PROJECT_ROOT, env=environment, stdout=output, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            with httpx.Client(base_url=base_url, trust_env=False, timeout=5) as client:
                deadline = time.monotonic() + 40
                while True:
                    if server.poll() is not None:
                        raise RuntimeError("test service exited")
                    try:
                        if client.get("/api/health").status_code == 200:
                            break
                    except httpx.ConnectError:
                        pass
                    if time.monotonic() > deadline:
                        raise TimeoutError("test service not ready")
                    time.sleep(0.1)
            profile_dir = tmp_path / "edge_profile"
            browser = subprocess.Popen(
                [str(DEFAULT_BROWSER), "--headless=new", "--disable-gpu", "--no-first-run",
                 "--no-default-browser-check", "--disable-background-networking", "--disable-sync",
                 "--disable-extensions", "--disable-component-update", "--disable-background-mode",
                 "--window-size=1365,1000", "--remote-debugging-port=0",
                 "--user-data-dir=" + str(profile_dir), "about:blank"],
                stdout=output, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW,
            )
            port_file = profile_dir / "DevToolsActivePort"
            deadline = time.monotonic() + 20
            while not port_file.is_file():
                if browser.poll() is not None or time.monotonic() > deadline:
                    raise TimeoutError("test browser not ready")
                time.sleep(0.1)
            debug_port = port_file.read_text().splitlines()[0]
            targets = httpx.get("http://127.0.0.1:" + debug_port + "/json/list", trust_env=False).json()
            page = next(item for item in targets if item["type"] == "page")
            session = BrowserSession(page["webSocketDebuggerUrl"])
            session.call("Page.enable")
            session.call("Runtime.enable")
            for permission in ("camera", "microphone"):
                session.call("Browser.setPermission", {
                    "permission": {"name": permission}, "setting": "denied", "origin": base_url,
                })
            # 浏览器推帧测试只使用公开图生成的canvas轨道；原生设备权限仍为denied。
            guard = GUARD if source == "ipcam" else "window.deviceCalls=0;" + sample_source(PROJECT_ROOT / "data/samples/test.jpg")
            session.call("Page.addScriptToEvaluateOnNewDocument", {"source": guard})
            session.call("Page.navigate", {"url": base_url + "/pc"})
            start_label = "开始读取" if source == "ipcam" else "开始检测"
            ready = 'document.getElementById("start-detection")?.textContent===' + json.dumps(start_label)
            if source == "ws":
                ready += ' && !document.getElementById("start-detection").disabled'
            session.wait(ready)
            session.evaluate('(async()=>{window.ui=(await import("/static/start.js")).client})()')
            yield session, base_url
        finally:
            # 即使页面断言失败，也只停止本次样例读取；不使用任何真实设备地址。
            if source == "ipcam" and server is not None and server.poll() is None:
                try:
                    httpx.post(base_url + "/api/ipcam/stop", timeout=8, trust_env=False)
                except httpx.HTTPError:
                    pass
            if session is not None:
                session.close()
            if browser is not None:
                try:
                    browser.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    browser.terminate()
                    browser.wait(timeout=8)
            if server is not None and server.poll() is None:
                subprocess.run(["taskkill", "/PID", str(server.pid), "/T", "/F"],
                               capture_output=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
                server.wait(timeout=15)
            # Windows 句柄释放稍晚，短暂等待后再让 pytest 处理自己的临时文件。
            time.sleep(0.5)


def start_sample(session, frames=3):
    """经页面明确勾选并点击启动，等待实际绘制指定帧数；仅用于本机样例。"""
    session.evaluate("""(()=>{
      const consent=document.getElementById("ipcam-consent");
      consent.checked=true;consent.dispatchEvent(new Event("change"));
      document.getElementById("start-detection").click();
    })()""")
    session.wait("ui.received >= " + str(frames), timeout=25)


@pytest.mark.skipif(not DEFAULT_BROWSER.is_file(), reason="local Edge browser is not installed")
def test_ipcam_page_lifecycle(viewer, sample_stream):
    """覆盖模式分派、明确确认、镜像、布局、迟到启动、停止失败和坏包，保持隐私权限 denied。"""
    session, base_url = viewer
    initial = session.evaluate("""({
      calls:deviceCalls,disabled:document.getElementById("start-detection").disabled,
      checked:document.getElementById("ipcam-consent").checked,
      localModules:performance.getEntriesByType("resource").some(item=>/\/(camera|app)\.js$/.test(item.name)),
      facing:document.getElementById("camera-facing").disabled,
      mirrored:ui.mirrored,mirrorChecked:document.getElementById("mirror-preview").checked
    })""")
    assert initial == {"calls": 0, "disabled": True, "checked": False, "localModules": False,
                       "facing": True, "mirrored": True, "mirrorChecked": True}
    assert sample_stream["requests"] == 0
    start_sample(session)
    summary = session.evaluate("""({
      boxes:ui.boxes.length,received:ui.received,pending:maximumPending,
      types:[...new Set(sentTypes)],videoHidden:document.getElementById("camera-video").hidden,
      calls:deviceCalls,visible:!ui.preview.hidden,historyCount:ui.smoother.previous.length,
      trackIds:ui.boxes.map(box=>box.track_id)
    })""")
    assert summary["boxes"] == 4 and summary["received"] >= 3
    assert summary["pending"] == 1 and summary["types"] == ["next"]
    assert summary["videoHidden"] and summary["visible"] and summary["calls"] == 0
    assert summary["historyCount"] == summary["boxes"]
    assert all(isinstance(track_id, int) and track_id > 0 for track_id in summary["trackIds"])
    assert len(set(summary["trackIds"])) == len(summary["trackIds"])
    assert session.evaluate("""(()=>{
      const context=ui.overlayContext,original=context.fillText,labels=[];
      try {context.fillText=(text,...args)=>{labels.push(text);return original.call(context,text,...args)};
        ui.render();return ui.boxes.every(box=>labels.some(text=>text.includes('#'+box.track_id+' ')));
      } finally {context.fillText=original}
    })()""")

    mirror = session.evaluate("""(()=>{
      const control=document.getElementById("mirror-preview"),ctx=ui.overlayContext;
      // 默认已镜像；先切回原方向，再检查左右翻转前后的像素和框坐标。
      control.checked=false;control.dispatchEvent(new Event("change"));
      const width=ui.preview.width,height=ui.preview.height;
      const before=ui.context.getImageData(0,0,width,height).data;
      const original=ctx.strokeRect,strokes=[];
      let result;
      try {
        ctx.strokeRect=(...args)=>{strokes.push(args);return original.apply(ctx,args)};
        control.checked=true;control.dispatchEvent(new Event("change"));
        const after=ui.context.getImageData(0,0,width,height).data;
        let flipped=true;
        for(let y=0;y<height;y+=31)for(let x=0;x<width;x+=29)for(let c=0;c<4;c++)
          flipped &&= before[(y*width+x)*4+c]===after[(y*width+width-1-x)*4+c];
        result=flipped && ui.mirrored && strokes.length===ui.boxes.length &&
          ui.boxes.every((box,index)=>Math.abs(strokes[index][0]-(1-box.xyxy[2])*width)<0.01) &&
          ctx.getTransform().a===1;
      } finally {ctx.strokeRect=original;control.checked=false;control.dispatchEvent(new Event("change"))}
      return result;
    })()""")
    assert mirror
    for width in (1365, 390, 320):
        session.call("Emulation.setDeviceMetricsOverride",
                     {"width": width, "height": 900, "deviceScaleFactor": 1, "mobile": False})
        layout = session.evaluate("""(async()=>{
          await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
          const a=ui.preview.getBoundingClientRect(),b=ui.overlay.getBoundingClientRect();
          return {overflow:document.documentElement.scrollWidth>innerWidth,
                  aligned:Math.abs(a.x-b.x)<=1&&Math.abs(a.y-b.y)<=1&&Math.abs(a.width-b.width)<=1&&Math.abs(a.height-b.height)<=1};
        })()""")
        assert not layout["overflow"] and layout["aligned"]
    session.evaluate("ui.stop()")
    assert session.evaluate("!ui.sourceRequested && ui.lastImage===null && ui.preview.hidden && ui.state==='idle' && ui.smoother.previous.length===0")
    assert httpx.get(base_url + "/api/ipcam/status", trust_env=False).json()["state"] == "idle"

    # 故意延迟启动请求，再立即停止；晚到的启动响应不能让画面恢复。
    session.evaluate("""(()=>{
      window.realFetch=window.fetch.bind(window);
      window.fetch=(path,options)=>String(path)==="/api/ipcam/start"
        ?new Promise((resolve,reject)=>setTimeout(()=>realFetch(path,options).then(resolve,reject),300))
        :realFetch(path,options);
      const box=document.getElementById("ipcam-consent");
      box.checked=true;box.dispatchEvent(new Event("change"));
      document.getElementById("start-detection").click();
      window.lateStop=ui.stop();
    })()""")
    session.evaluate("lateStop")
    assert session.evaluate("ui.state==='idle' && !ui.sourceRequested && ui.lastImage===null && ui.received===0")
    session.evaluate("window.fetch=realFetch")

    # 停止失败时不能显示已停止；保留停止按钮，恢复网络后可重试。
    start_sample(session)
    session.evaluate("""window.fetch=(path,options)=>String(path)==="/api/ipcam/stop"
      ?Promise.resolve(new Response(JSON.stringify({ok:false,message:"测试停止失败"}),{status:500}))
      :realFetch(path,options)""")
    session.evaluate("ui.stop()")
    assert session.evaluate("ui.state==='error'&&ui.sourceRequested&&!ui.nodes.stop.disabled&&ui.nodes.start.disabled&&ui.lastImage===null")
    session.evaluate("window.fetch=realFetch;ui.stop()")
    assert session.evaluate("!ui.sourceRequested&&ui.state==='idle'")

    start_sample(session)
    session.evaluate('ui.nodes.consent.checked=false;ui.nodes.consent.dispatchEvent(new Event("change"))')
    session.wait("!ui.sourceRequested && ui.state==='idle'")

    # 用结构上合法但无法解码的测试 JPEG 触发故障，不能让旧画面继续显示。
    start_sample(session)
    session.evaluate("""(async()=>{
      ui.pending=true;ui.decoding=false;
      await ui.receive(JSON.stringify({type:"ipcam_frame",seq:ui.lastSeq+1,w:10,h:10,img:"/9j/AAAA",
        result:{type:"result",seq:ui.lastSeq+1,fps:1,latency_ms:1,boxes:[]}}),ui.generation);
    })()""")
    session.wait("!ui.sourceRequested && ui.state==='error'")
    assert session.evaluate("ui.lastImage===null && ui.preview.hidden && deviceCalls===0")

    validation = session.evaluate("""(async()=>{
      const {checkIpPacket}=await import("/static/ipcam.js");
      const packet={type:"ipcam_frame",seq:1,w:10,h:10,img:"/9j/AAAA",
        result:{type:"result",seq:1,fps:1,latency_ms:1,boxes:[]}};
      checkIpPacket(packet);
      let rejected=0;
      for(const change of [
        value=>value.result.seq=2, value=>value.w=0, value=>value.img="https://external.invalid/picture",
        value=>value.result.boxes=[{cls:0,name:"person",score:.9,xyxy:[.8,.2,.3,.9]}],
        value=>value.result.boxes=[{cls:0,name:"person",score:.9,xyxy:[.1,.2,.3,.9],track_id:"bad"}]
      ]){
        const value=structuredClone(packet);change(value);
        try{checkIpPacket(value)}catch{rejected++}
      }
      return rejected;
    })()""")
    assert validation == 5

    # 健康接口返回未知模式时，页面应保持禁用，不能猜测改开本机摄像头。
    session.call("Page.addScriptToEvaluateOnNewDocument", {"source": """
      const actualFetch=window.fetch.bind(window);
      window.fetch=(path,options)=>String(path)==="/api/health"
        ?Promise.resolve(new Response(JSON.stringify({ok:true,source:"unknown"}),{status:200}))
        :actualFetch(path,options);
    """})
    session.call("Page.reload")
    session.wait('document.getElementById("health-status").textContent==="初始化失败"')
    assert session.evaluate("""deviceCalls===0 && document.getElementById("start-detection").disabled &&
      !performance.getEntriesByType("resource").some(item=>/\/(camera|app|ipcam)\.js$/.test(item.name))""")
