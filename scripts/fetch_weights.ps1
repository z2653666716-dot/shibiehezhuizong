# 本文件按最多三个来源下载 YOLO11n，属于 P0 模型准备。
# 输入：check_mirrors.ps1 中的地址；输出：weights\yolo11n.pt。
# 下载中间文件放 work\downloads，完成后才移入 weights；实际推理由 P0 验收执行。
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$modelPath = Join-Path $projectRoot 'weights\yolo11n.pt'
$downloadPath = Join-Path $projectRoot 'work\downloads\yolo11n.pt.download'
$sources = & (Join-Path $PSScriptRoot 'check_mirrors.ps1') -GetSources

function Test-ModelFile {
    <#
    检查下载文件是否像一个完整的 YOLO11n 包。
    输入：文件路径；输出：布尔值。主流程据此决定复用或保存下载。
    文件大小和 ZIP 文件头只能排除空文件、网页等明显错误，不能代替实际模型加载。
    #>
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    $file = Get-Item -LiteralPath $Path
    if ($file.Length -lt 1MB -or $file.Length -gt 20MB) { return $false }
    $stream = [IO.File]::OpenRead($Path)
    try {
        return ($stream.ReadByte() -eq 80 -and $stream.ReadByte() -eq 75)
    } finally {
        $stream.Dispose()
    }
}

if (Test-Path -LiteralPath $modelPath) {
    if (-not (Test-ModelFile -Path $modelPath)) {
        throw "已有模型文件不完整，请先检查：$modelPath"
    }
    Write-Host "复用已有模型：$modelPath"
    return
}
if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) {
    throw '找不到 Windows curl.exe，无法执行下载。'
}
New-Item -ItemType Directory -Path (Split-Path -Parent $modelPath) -Force | Out-Null
New-Item -ItemType Directory -Path (Split-Path -Parent $downloadPath) -Force | Out-Null

if (Test-ModelFile -Path $downloadPath) {
    Move-Item -LiteralPath $downloadPath -Destination $modelPath
    Write-Host "复用已下载的完整文件：$modelPath"
    return
}

# 按固定优先级逐个尝试，避免反复请求同一个失败的镜像。
foreach ($source in $sources.Yolo) {
    Write-Host "下载来源：$source"
    & curl.exe --fail --location --connect-timeout 10 --max-time 90 --retry 0 --silent --show-error --output $downloadPath $source
    if ($LASTEXITCODE -eq 0 -and (Test-ModelFile -Path $downloadPath)) {
        Move-Item -LiteralPath $downloadPath -Destination $modelPath
        Write-Host "模型已保存：$modelPath"
        return
    }
    Write-Warning '当前来源未得到完整模型，尝试下一个来源。'
}
throw '三个模型来源均未成功。请保留输出，改用离线模型，不再重复请求失败来源。'
