"""隔离浏览器检查镜像触点、短按、长按和取消；只使用已有公开样例。"""
import pytest

from scripts.verify_stream import DEFAULT_BROWSER
from tests.test_ipcamera import sample_stream
from tests.test_ipcam_page import viewer, start_sample


@pytest.mark.skipif(not DEFAULT_BROWSER.is_file(), reason="Edge is unavailable")
def test_pointer_lock_and_cancel(viewer):
    """前置镜像时在显示框中心按下，短按黄框、长按绿框；取消不触发锁定。"""
    session, _ = viewer
    start_sample(session, frames=8)
    session.evaluate("""(()=>{
      const canvas=ui.overlay, box=ui.boxes.find(box=>box.track_id!=null);
      const rect=canvas.getBoundingClientRect();
      const x=(box.xyxy[0]+box.xyxy[2])/2;
      window.testPoint={clientX:rect.left+(ui.mirrored?1-x:x)*rect.width,
        clientY:rect.top+(box.xyxy[1]+box.xyxy[3])/2*rect.height,
        pointerId:1,pointerType:'touch',button:0,bubbles:true};
      window.lockActions=[];
      const request=ui.interaction.request.bind(ui.interaction);
      ui.interaction.request=(path,options)=>{
        if(path==='/api/lock')lockActions.push(JSON.parse(options.body).action);
        return request(path,options);
      };
      // 合成 PointerEvent 不会产生原生 pointer capture，测试只替换捕获调用。
      canvas.setPointerCapture=()=>{};
      canvas.dispatchEvent(new PointerEvent('pointerdown',testPoint));
      canvas.dispatchEvent(new PointerEvent('pointerup',testPoint));
      window.chosen=box.track_id;
    })()""")
    assert session.evaluate("ui.interaction.selected===chosen")
    assert session.evaluate("ui.interaction.style(ui.boxes.find(b=>b.track_id===chosen)).color") == "#ffe166"
    session.evaluate("ui.overlay.dispatchEvent(new PointerEvent('pointerdown',testPoint))")
    # 安卓长按会在计时器之前或之后补发菜单；两种顺序都不能重复发送锁定/取消。
    session.evaluate("ui.overlay.dispatchEvent(new MouseEvent('contextmenu',{...testPoint,button:2}))")
    session.wait("ui.boxes.some(b=>b.track_id===chosen&&b.state==='locked')")
    session.evaluate("""(()=>{
      ui.overlay.dispatchEvent(new PointerEvent('pointerup',testPoint));
      ui.overlay.dispatchEvent(new MouseEvent('contextmenu',{...testPoint,button:2}));
      window.afterLockFrames=ui.received;
    })()""")
    session.wait("ui.received>=afterLockFrames+5")
    assert session.evaluate("lockActions") == ["lock"]
    assert session.evaluate("ui.boxes.find(b=>b.track_id===chosen).identity_id") == "ID-01"
    assert session.evaluate("document.querySelectorAll('.identity-card').length") == 1
    session.evaluate("""(()=>{
      ui.overlay.dispatchEvent(new PointerEvent('pointerdown',testPoint));
      ui.overlay.dispatchEvent(new PointerEvent('pointercancel',testPoint));
    })()""")
    assert session.evaluate("ui.interaction.press===null")
    # 再次完整长按绿框应取消，而不是重复登记或显示“null已锁定”。
    session.evaluate("ui.overlay.dispatchEvent(new PointerEvent('pointerdown',testPoint))")
    session.evaluate("ui.overlay.dispatchEvent(new MouseEvent('contextmenu',{...testPoint,button:2}))")
    session.wait("ui.boxes.every(b=>b.state==='none') && document.querySelectorAll('.identity-card').length===0")
    assert session.evaluate("document.getElementById('toast').textContent") == "已取消锁定"
    assert session.evaluate("ui.interaction.selected===null")
    assert session.evaluate("lockActions") == ["lock", "unlock"]
    # 真正的电脑鼠标右键仍然可用：等待触摸菜单屏蔽期结束，再发送一次明确右键。
    session.evaluate("new Promise(resolve=>setTimeout(resolve,1600))")
    session.evaluate("""(()=>{
      const event=new MouseEvent('contextmenu',{...testPoint,button:2});
      // 慢速完整回归中会触发640到480的自适应调整，轨迹号按设计重建；应锁定当前点击处的框。
      window.rightClicked=ui.interaction.hit(event)?.track_id;
      if(rightClicked==null)throw new Error('public sample no longer under test pointer');
      ui.overlay.dispatchEvent(event);
    })()""")
    session.wait("ui.boxes.some(b=>b.track_id===rightClicked&&b.state==='locked')")
    assert session.evaluate("lockActions") == ["lock", "unlock", "lock"]
    session.evaluate("document.getElementById('stop-detection').click()")
    session.wait("ui.state==='idle'")
    assert session.evaluate("ui.interaction.session===null && ui.interaction.selected===null")
    assert session.evaluate("deviceCalls") == 0
