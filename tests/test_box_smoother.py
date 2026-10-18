"""在隔离 Edge 中验证框显示平滑，仅输入合成坐标，不访问物理摄像头或实拍画面。

入口为 pytest；复用样例页面夹具，导入真实 box_smoother.js 检查稳定性与清理边界。
测试只返回数值和布尔结论，不截图、不读取手机视频源。
"""

import pytest

from scripts.verify_stream import DEFAULT_BROWSER
from tests.test_ipcamera import sample_stream
from tests.test_ipcam_page import viewer


@pytest.mark.skipif(not DEFAULT_BROWSER.is_file(), reason="local Edge browser is not installed")
def test_box_smoother_boundaries(viewer):
    """输入合成框序列，检查抑制小抖动、快速跟随、无框清理、类别/轨迹隔离和分数真实性。"""
    session, _ = viewer
    result = session.evaluate("""(async()=>{
      const {BoxSmoother}=await import('/static/box_smoother.js');
      const box=(xyxy,score=.6,extra={})=>({cls:0,name:'person',xyxy,score,...extra});
      const base=[.2,.2,.6,.8], smoother=new BoxSmoother();
      const first=box([...base]);
      smoother.update([first],640,480,0);
      let rawTravel=0,displayTravel=0,rawBefore=base[0],displayBefore=base[0],time=0;
      // 中心保持不动、边缘交替扩张/收缩，模拟用户说的框大小频繁抖动。
      for(let index=0;index<30;index++){
        const delta=index%2===0?.008:-.008;
        const current=box([base[0]+delta,base[1]+delta,base[2]-delta,base[3]-delta],.51);
        const output=smoother.update([current],640,480,time+=33)[0];
        rawTravel+=Math.abs(current.xyxy[0]-rawBefore);
        displayTravel+=Math.abs(output.xyxy[0]-displayBefore);
        rawBefore=current.xyxy[0];displayBefore=output.xyxy[0];
        if(output.score!==.51)throw new Error('confidence was changed');
      }
      const retainedFirst=JSON.stringify(first)===JSON.stringify(box([...base]));
      const moved=box([.35,.2,.75,.8],.93);
      const fast=smoother.update([moved],640,480,time+=33)[0];
      const fastFollows=JSON.stringify(fast.xyxy)===JSON.stringify(moved.xyxy);
      const empty=smoother.update([],640,480,time+=33);
      const clearsMissing=empty.length===0&&smoother.previous.length===0;
      const fresh=smoother.update([first],640,480,time+=33)[0];
      const freshOriginal=JSON.stringify(fresh.xyxy)===JSON.stringify(base);
      const changed=box([.21,.21,.59,.79],.7);
      const dimensions=smoother.update([changed],480,640,time+=33)[0];
      const resizeResets=JSON.stringify(dimensions.xyxy)===JSON.stringify(changed.xyxy);
      const delayed=smoother.update([first],480,640,time+=600)[0];
      const gapResets=JSON.stringify(delayed.xyxy)===JSON.stringify(base);
      smoother.reset();
      smoother.update([first],640,480,0);
      const otherClass=box([.21,.21,.59,.79],.88,{cls:2,name:'car'});
      const category=smoother.update([otherClass],640,480,33)[0];
      const classSeparated=JSON.stringify(category.xyxy)===JSON.stringify(otherClass.xyxy);
      smoother.reset();
      smoother.update([box([...base],.6,{track_id:1})],640,480,0);
      const otherTrack=box([.21,.21,.59,.79],.88,{track_id:2});
      const track=smoother.update([otherTrack],640,480,33)[0];
      const trackSeparated=JSON.stringify(track.xyxy)===JSON.stringify(otherTrack.xyxy);
      smoother.reset();
      smoother.update([first],640,480,0);
      const pair=[box([.201,.2,.601,.8]),box([.21,.2,.61,.8])];
      const outputs=smoother.update(pair,640,480,33);
      const unchangedCount=outputs.filter((item,index)=>JSON.stringify(item.xyxy)===JSON.stringify(pair[index].xyxy)).length;
      const noDuplicateReuse=unchangedCount===1;
      smoother.reset();
      const resets=smoother.previous.length===0&&smoother.sizeKey===null;
      return {rawTravel,displayTravel,retainedFirst,fastFollows,clearsMissing,freshOriginal,
              resizeResets,gapResets,classSeparated,trackSeparated,noDuplicateReuse,resets,
              deviceCalls,readRequests:ui.sourceRequested};
    })()""")
    assert result["displayTravel"] < result["rawTravel"] * 0.4
    for check in (
        "retainedFirst", "fastFollows", "clearsMissing", "freshOriginal", "resizeResets",
        "gapResets", "classSeparated", "trackSeparated", "noDuplicateReuse", "resets",
    ):
        assert result[check], check
    assert result["deviceCalls"] == 0
    assert result["readRequests"] is False
