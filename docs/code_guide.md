# 代码结构

## 入口与请求链路

`run.py`负责选择项目解释器和检查启动条件，再启动`app.main:app`。`app/main.py`中的`create_app()`注册HTTP/WebSocket接口，`lifespan()`在启动时加载模型、创建`Pipeline`，在退出时释放后台任务。

浏览器向`/ws/stream`发送带帧号的JPEG。`Pipeline.process_message()`解码后进入同一处理锁，依次完成检测、轨迹关联、身份核验，组装`FrameResult`返回。模型计算通过`asyncio.to_thread()`执行，避免阻塞网络事件循环；共享锁保证同一模型不会被多条连接同时推进。

## 模块

```text
run.py                      启动入口
app/
  main.py                   HTTP/WebSocket路由、生命周期
  config.py / schemas.py    配置与消息约束
  pipeline.py               单帧处理与模型调度
  detector.py               YOLO人物检测
  tracker.py                ByteTrack / BoT-SORT轨迹适配
  session.py                会话、手动锁定与appearance后端
  hybrid_session.py         人脸与身体联合身份状态机
  faces.py                  YuNet/SFace、人脸质量与归属
  person_features.py        OSNet行人特征
  gallery.py                有限模板库
  photos.py / ipcamera.py   照片解析、IP源生命周期
web/
  start.js                  按服务模式初始化页面
  app.js / camera.js        浏览器采集与推帧
  ipcam.js                  IP源预览
  interaction.js            手势、照片登记、身份操作
  box_smoother.js            显示框平滑
tests/                      状态规则、模型、接口与浏览器检查
```

`schemas.py`区分像素坐标的`Detection`和归一化坐标的`Box`。`FrameResult`带帧号、框、身份状态和会话凭据，前端据此关联画面与操作。

## 轨迹与身份

`Tracker`负责相邻帧关联，轨迹编号仅在视频会话内有意义。`HybridSession`负责判断当前轨迹是否仍属于登记目标。目标离开后可能换一个轨迹编号，身份库中的ID保持不变，重新匹配后才绑定到新轨迹。

`Gallery`保留最初登记模板，限制后续模板数量。人脸与身体模板分别管理，只有头部的观测不会作为全身外观输入。联合策略及模板更新条件见[身份跟踪策略](tracking_upgrade.md)。

appearance后端保留MobileNetV3和颜色直方图方案，用于兼容和对比；其阈值含义与OSNet后端不同。

## 会话隔离与清理

每条浏览器视频连接拥有独立的轨迹、身份库与随机会话凭据。锁定接口同时检查会话、轨迹和帧号，防止过期画面上的操作落到新目标上。

`Pipeline.reset_tracker()`先撤销会话凭据，再等待已在执行的线程离开处理锁，最后清空画面、模板和缓存。取消异步等待不会自动结束底层推理线程，因此清理必须等待在途计算，避免迟到结果写回已结束的会话。

IP源使用独立采集任务，多位观看者共用同一帧结果，不重复更新轨迹。

## 前端

浏览器一次只发送一帧，上一帧未返回时跳过当前发送机会。IP源页面每显示完一帧再请求下一帧，避免慢客户端积压。

`TargetInteraction`将触点转换为归一化坐标，镜像时还原横坐标，按住600ms后发出明确的lock/unlock请求。抬手、移动、取消或停止视频会终止手势计时；接口响应也会重新核对会话，避免旧请求覆盖新状态。

`box_smoother.js`只平滑显示坐标，不修改检测分数和身份状态。`sw.js`只缓存界面资源，离线时禁用需要电脑服务的检测功能。

## 数据处理

照片请求体限量读入内存，JPEG/PNG解码后检查尺寸并校正EXIF。联合模式要求单人照片，有清晰人脸时建立人脸模板；缩略图经带会话凭据的no-store接口提供。删除身份或停止会话会清除相关内存。

录制模块需要保存配置与页面确认同时允许，默认关闭。诊断只记录匿名编号、状态、原因和标量，不记录图片、Base64或特征向量。

阅读顺序：`run.py` → `main.py` → `pipeline.py` → `hybrid_session.py` → 编码器与对应测试。
