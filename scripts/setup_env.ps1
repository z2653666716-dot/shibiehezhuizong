# 本文件为 ViTrack 准备独立的 Python 3.11 环境，属于 P0 环境搭建。
# 默认准备 Python 和 pip；添加 -InstallDependencies 可安装依赖并验证 GPU。
# 输入：可选的 CondaPath（conda.exe 路径）；输出：envs\vitrack 环境和控制台说明。
# 本脚本不需要激活环境，后续脚本可直接调用该环境中的 python.exe。
[CmdletBinding()]
param(
    [string]$CondaPath = (Join-Path $env:USERPROFILE 'miniconda3\Scripts\conda.exe'),
    [switch]$InstallDependencies
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# 从脚本自身的位置找到项目，而不是依赖终端当前在哪个文件夹。
$projectRoot = Split-Path -Parent $PSScriptRoot
$environmentRoot = Join-Path $projectRoot 'envs\vitrack'
$pythonPath = Join-Path $environmentRoot 'python.exe'
$workRoot = Join-Path $projectRoot 'work'
$downloadSources = & (Join-Path $PSScriptRoot 'check_mirrors.ps1') -GetSources

function Assert-ProjectEnvironment {
    <#
    用途：确认指定环境确实使用 Python 3.11，并且 pip 可以运行。
    输入：EnvironmentPath 是环境目录；输出：成功时返回，失败时抛出中文错误。
    调用关系：主流程在复用环境或新建环境后调用本函数。
    #>
    param([Parameter(Mandatory = $true)][string]$EnvironmentPath)

    $environmentPython = Join-Path $EnvironmentPath 'python.exe'
    if (-not (Test-Path -LiteralPath $environmentPython -PathType Leaf)) {
        throw "环境中没有 python.exe：$EnvironmentPath"
    }

    # -I 忽略用户级 Python 包和 PYTHONPATH，避免其他项目影响此次检查。
    # Python 的退出码为 0 表示版本和实际环境位置都正确；非 0 表示检查失败。
    $checkCode = 'import os, sys; print(sys.version.split()[0]); print(sys.prefix); sys.exit(0 if sys.version_info[:2] == (3, 11) and os.path.realpath(sys.prefix) == os.path.realpath(sys.argv[1]) else 1)'
    $checkOutput = & $environmentPython -I -c $checkCode $EnvironmentPath
    if ($LASTEXITCODE -ne 0) {
        throw "目标环境不是预期的 Python 3.11 独立环境，请先检查，不会自动覆盖。实际输出：$checkOutput"
    }
    Write-Host ("Python 版本与环境位置检查通过：{0}" -f ($checkOutput -join ' | '))

    & $environmentPython -I -m pip --version
    if ($LASTEXITCODE -ne 0) {
        throw '环境中的 pip 无法运行，请检查环境完整性。'
    }
}

if (-not (Test-Path -LiteralPath $CondaPath -PathType Leaf)) {
    throw "找不到 Conda：$CondaPath。请使用 -CondaPath 指定实际的 conda.exe 路径。"
}

# 防止环境目录通过文件链接指向项目外；本脚本不会删除或替换已有目录。
foreach ($localPath in @((Join-Path $projectRoot 'envs'), $environmentRoot, $workRoot)) {
    if (Test-Path -LiteralPath $localPath) {
        $localItem = Get-Item -LiteralPath $localPath -Force
        if (-not $localItem.PSIsContainer -or
            (($localItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0)) {
            throw "预期为项目内的普通目录，请检查该位置：$localPath"
        }
    }
}

if (Test-Path -LiteralPath $environmentRoot) {
    # 重复运行时只检查并复用，不重新安装；不完整的旧目录也不会被悄悄清空。
    Assert-ProjectEnvironment -EnvironmentPath $environmentRoot
    Write-Host '已有环境可用，本次无需创建。'
} else {
    # 仅临时改变本进程的配置，不执行 conda config 或 pip config。
    # finally 会在成功或失败后恢复这些变量，避免影响当前终端后续操作。
    $processSettings = @{
        CONDA_PKGS_DIRS = (Join-Path $workRoot 'conda\packages')
        CONDA_ENVS_PATH = (Join-Path $projectRoot 'envs')
        CONDA_AUTO_UPDATE_CONDA = 'false'
        CONDA_NOTIFY_OUTDATED_CONDA = 'false'
        CONDA_NUMBER_CHANNEL_NOTICES = '0'
        CONDA_REMOTE_CONNECT_TIMEOUT_SECS = '10'
        CONDA_REMOTE_READ_TIMEOUT_SECS = '30'
        CONDA_REMOTE_MAX_RETRIES = '0'
        TEMP = (Join-Path $workRoot 'temp')
        TMP = (Join-Path $workRoot 'temp')
    }
    $savedSettings = @{}

    try {
        foreach ($settingName in $processSettings.Keys) {
            $savedSettings[$settingName] = [Environment]::GetEnvironmentVariable($settingName, 'Process')
            [Environment]::SetEnvironmentVariable($settingName, $processSettings[$settingName], 'Process')
        }

        # 缓存与临时文件按用途分开放；不预先创建目标环境，让 Conda 管理其内容。
        foreach ($folderPath in @($processSettings.CONDA_PKGS_DIRS, $processSettings.TEMP)) {
            New-Item -ItemType Directory -Path $folderPath -Force | Out-Null
        }

        # 先用方案指定的清华镜像，再尝试官方源；每个源仅尝试一次，不无限重试。
        $channels = $downloadSources.Conda
        $created = $false
        foreach ($channel in $channels) {
            Write-Host "正在创建 Python 3.11 环境，下载源：$channel"
            # 参数数组确保带空格的路径仍作为一个参数；& 表示运行指定的可执行文件。
            # --prefix 指定安装位置；--override-channels 防止混入全局配置的软件源。
            $createArguments = @(
                'create', '--prefix', $environmentRoot,
                '--override-channels', '--channel', $channel,
                '--no-default-packages', '--no-shortcuts', '--yes',
                'python=3.11', 'pip'
            )
            & $CondaPath @createArguments
            if ($LASTEXITCODE -eq 0) {
                $created = $true
                break
            }
            Write-Warning "该源创建失败，退出码为 $LASTEXITCODE。"

            # 如果已经写出环境内容，先停下供排查，避免在部分完成的环境上盲目重试。
            if (Test-Path -LiteralPath $pythonPath) {
                throw "检测到部分环境：$environmentRoot。请检查上方错误，本脚本不会自动删除它。"
            }
        }
        if (-not $created) {
            throw '两个下载源均未成功。本次停止，请保留错误输出用于排查或离线安装。'
        }

        Assert-ProjectEnvironment -EnvironmentPath $environmentRoot
    } finally {
        foreach ($settingName in $savedSettings.Keys) {
            [Environment]::SetEnvironmentVariable($settingName, $savedSettings[$settingName], 'Process')
        }
    }
}

Write-Host "环境位置：$environmentRoot"
Write-Host "后续可直接运行：& '$pythonPath' --version"

if ($InstallDependencies) {
    # 本流程读取 requirements.txt，调用 pip，再由 verify_env.py 输出真实验收报告。
    # 安装进程的缓存、临时文件和库搜索路径只在 try 内生效，finally 负责恢复。
    $requirementsPath = Join-Path $projectRoot 'requirements.txt'
    if (-not (Test-Path -LiteralPath $requirementsPath -PathType Leaf)) {
        throw "找不到依赖清单：$requirementsPath"
    }
    $installSettings = @{
        PIP_CONFIG_FILE = 'NUL'
        PIP_CACHE_DIR = (Join-Path $workRoot 'pip')
        TEMP = (Join-Path $workRoot 'temp')
        TMP = (Join-Path $workRoot 'temp')
        PATH = ($environmentRoot + ';' + (Join-Path $environmentRoot 'Library\bin') + ';' +
                (Join-Path $environmentRoot 'Scripts') + ';' + $env:PATH)
    }
    $savedInstallSettings = @{}
    try {
        foreach ($settingName in $installSettings.Keys) {
            $savedInstallSettings[$settingName] = [Environment]::GetEnvironmentVariable($settingName, 'Process')
            [Environment]::SetEnvironmentVariable($settingName, $installSettings[$settingName], 'Process')
        }
        foreach ($folderPath in @($installSettings.PIP_CACHE_DIR, $installSettings.TEMP)) {
            New-Item -ItemType Directory -Path $folderPath -Force | Out-Null
        }

        # 参数数组记录通用网络选项；软件源按顺序切换，不修改用户全局 pip 设置。
        $pipOptions = @('--timeout', '30', '--retries', '0', '--disable-pip-version-check',
                        '--progress-bar', 'off', '--no-warn-script-location')
        $pipSources = $downloadSources.Pip
        $installed = $false
        foreach ($pipSource in $pipSources) {
            & $pythonPath -I -m pip install -r $requirementsPath --index-url $pipSource @pipOptions
            if ($LASTEXITCODE -eq 0) {
                $installed = $true
                break
            }
            Write-Warning "依赖安装源失败：$pipSource"
        }
        if (-not $installed) { throw '依赖镜像均安装失败，请检查错误输出或准备离线安装包。' }

        # 普通 PyPI 的 Windows 包可能不带 CUDA；先实际检测，再按需更换官方 GPU 构建。
        & $pythonPath -I -c 'import torch; raise SystemExit(0 if torch.cuda.is_available() else 1)'
        if ($LASTEXITCODE -ne 0) {
            Write-Host '当前 PyTorch 无法使用 GPU，正在安装对应的官方 CUDA 12.8 构建。'
            & $pythonPath -I -m pip install 'torch==2.9.1+cu128' 'torchvision==0.24.1+cu128' --no-deps --index-url $downloadSources.TorchCuda @pipOptions
            if ($LASTEXITCODE -ne 0) { throw '官方 CUDA 构建安装失败，请保留错误输出用于排查。' }
        }

        & $pythonPath -I -m pip check
        if ($LASTEXITCODE -ne 0) { throw '依赖版本存在冲突，请检查 pip check 输出。' }
        & $pythonPath -I (Join-Path $PSScriptRoot 'verify_env.py')
        if ($LASTEXITCODE -ne 0) { throw '环境实测失败，不能视为 GPU 环境验收通过。' }

        # 锁文件记录本次真正安装的版本；主清单记录兼容范围，两者职责不同。
        $lockedPackages = & $pythonPath -I -m pip freeze
        if ($LASTEXITCODE -ne 0) { throw '无法生成依赖锁文件。' }
        $lockText = "# CUDA builds require the official PyTorch index.`n" +
                    "--extra-index-url " + $downloadSources.TorchCuda + "`n" +
                    ($lockedPackages -join "`n") + "`n"
        [IO.File]::WriteAllText((Join-Path $projectRoot 'requirements.lock.txt'), $lockText,
                               (New-Object System.Text.UTF8Encoding($false)))
        Write-Host '依赖安装、GPU 运算检查和版本锁定均已完成。'
    } finally {
        foreach ($settingName in $savedInstallSettings.Keys) {
            [Environment]::SetEnvironmentVariable($settingName, $savedInstallSettings[$settingName], 'Process')
        }
    }
} else {
    Write-Host '本次仅准备 Python 和 pip；添加 -InstallDependencies 可安装依赖并验证 GPU。'
}
