# 本文件集中保存下载地址，并检查 P0 所需镜像是否可访问。
# 输入：-GetSources 表示只读取地址，不发网络请求；输出：地址字典或终端检查表。
# setup_env.ps1、fetch_weights.ps1 通过 -GetSources 复用同一份地址。
[CmdletBinding()]
param([switch]$GetSources)

$ErrorActionPreference = 'Stop'

# 镜像失效时优先修改这里，避免到多个脚本中分别更改。
$githubProxies = @('https://ghfast.top/', 'https://gh-proxy.com/')
$releasePath = 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n.pt'
$sources = @{
    Conda = @('https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main/',
              'https://repo.anaconda.com/pkgs/main/')
    Pip = @('https://pypi.tuna.tsinghua.edu.cn/simple',
            'https://mirrors.aliyun.com/pypi/simple/')
    TorchCuda = 'https://download.pytorch.org/whl/cu128'
    Yolo = @(($githubProxies[0] + $releasePath),
             ($githubProxies[1] + $releasePath),
             'https://hf-mirror.com/Ultralytics/YOLO11/resolve/main/yolo11n.pt')
}

if ($GetSources) { return $sources }

# 每个检查项只发一个 HEAD 请求，不下载模型或安装软件。
$targets = @(
    @{ Name = 'Conda Tsinghua'; Url = ($sources.Conda[0] + 'win-64/repodata.json') }
    @{ Name = 'PyPI Tsinghua'; Url = ($sources.Pip[0] + '/fastapi/') }
    @{ Name = 'PyPI Aliyun'; Url = ($sources.Pip[1] + 'fastapi/') }
    @{ Name = 'PyTorch CUDA'; Url = ($sources.TorchCuda + '/torch/') }
    @{ Name = 'YOLO GitHub proxy'; Url = $sources.Yolo[0] }
    @{ Name = 'YOLO HF mirror'; Url = $sources.Yolo[2] }
)
$results = foreach ($target in $targets) {
    try {
        $response = Invoke-WebRequest -Uri $target.Url -Method Head -UseBasicParsing -TimeoutSec 8
        [PSCustomObject]@{ Name = $target.Name; Available = $true; Status = [int]$response.StatusCode }
    } catch {
        # 一个地址不可访问不应中断整张检查表，后续仍需知道其他源的状态。
        $status = 'unreachable'
        if ($_.Exception.Response) { $status = [int]$_.Exception.Response.StatusCode }
        [PSCustomObject]@{ Name = $target.Name; Available = $false; Status = $status }
    }
}
$results | Format-Table -AutoSize
Write-Host '说明：HEAD 请求成功只代表地址可访问，实际安装或下载仍以运行结果为准。'
