"""创建本地ONNX执行器，复用项目PyTorch已有的CUDA/cuDNN库，不安装系统DLL或隐式联网。

两个身份编码器共用此入口；输入模型路径与检测设备，输出会话和实际执行后端。
GPU不可用时明确记录CPU回退，健康接口也展示实际设备，不能只凭RTX型号宣称全部在GPU运行。
"""
import logging
from pathlib import Path


def prepare_model(path, dynamic_batch=False):
    """规范旧导出元信息：冻结参数输入，行人图只把输入/输出批大小改为动态；不改权重和算子。"""
    import onnx
    model = onnx.load(str(path))
    frozen = {tensor.name for tensor in model.graph.initializer}
    data_inputs = [item for item in model.graph.input if item.name not in frozen]
    del model.graph.input[:]
    model.graph.input.extend(data_inputs)
    if dynamic_batch:
        # 已核实OSNet内部Reshape使用Shape/Gather取得实际batch，所以仅需修正输入/输出声明。
        for item in [*model.graph.input, *model.graph.output]:
            dimension = item.type.tensor_type.shape.dim[0]
            dimension.ClearField("dim_value")
            dimension.dim_param = "batch"
    onnx.checker.check_model(model)
    return model.SerializeToString()


def create_session(path, device="cpu", dynamic_batch=False):
    """选择本机可用CUDA或CPU，限制线程与显存池；失败时在本机CPU运行同一模型。"""
    import onnxruntime as runtime
    # 旧导出图会重复打印数百条常量提示；应用保留错误，实际后端/回退由下方统一记录。
    runtime.set_default_logger_severity(3)
    options = runtime.SessionOptions()
    options.log_severity_level = 3
    model_bytes = prepare_model(path, dynamic_batch)
    options.intra_op_num_threads, options.inter_op_num_threads = 2, 1
    providers = ["CPUExecutionProvider"]
    if device != "cpu" and "CUDAExecutionProvider" in runtime.get_available_providers():
        import torch
        if torch.cuda.is_available():
            # 项目环境已安装匹配的CUDA PyTorch；只在当前进程加载其DLL，不改PATH或全局配置。
            runtime.preload_dlls(directory=str(Path(torch.__file__).parent / "lib"))
            providers.insert(0, ("CUDAExecutionProvider", {
                "device_id": int(device), "arena_extend_strategy": "kSameAsRequested",
                "cudnn_conv_algo_search": "DEFAULT", "gpu_mem_limit": 768 * 1024 * 1024}))
    try:
        session = runtime.InferenceSession(model_bytes, sess_options=options, providers=providers)
    except RuntimeError:
        if len(providers) == 1:
            raise
        logging.getLogger(__name__).exception("身份模型CUDA初始化失败，改用本机CPU执行同一权重")
        session = runtime.InferenceSession(model_bytes, sess_options=options, providers=["CPUExecutionProvider"])
    actual = f"cuda:{device}" if "CUDAExecutionProvider" in session.get_providers() else "cpu"
    logging.getLogger(__name__).info("身份执行器 model=%s backend=%s", path.name, actual)
    return session, actual
