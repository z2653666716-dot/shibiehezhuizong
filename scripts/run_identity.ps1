# 实验分支启动入口：临时启用BoT-SORT、OSNet和人脸辅助，不修改用户.env或系统环境变量。
# 输入模式、端口及可选热点地址/证书目录；调用已有run.ps1，只启动服务，不打开摄像头。
[CmdletBinding()]
param(
    [ValidateSet('pc', 'phone')][string]$Mode = 'pc',
    [ValidateRange(1, 65535)][int]$Port = 8445,
    [string]$LanIP = '',
    [string]$CertificateDir = 'certs/hotspot',
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
$options = @{
    SOURCE = 'ws'; IDENTITY_MODE = 'hybrid'; IDENTITY_DEVICE = 'cpu'; REID_MODEL = 'osnet_x0_25';
    TRACKER = 'botsort.yaml'; ALLOW_MEDIA_SAVE = 'false';
    HTTPS_CERT = (Join-Path $CertificateDir 'cert.pem');
    HTTPS_KEY = (Join-Path $CertificateDir 'key.pem')
}
$previous = @{}
try {
    # 只改本脚本进程的环境，子服务继承；服务退出时恢复，避免影响下次启动稳定版。
    foreach ($name in $options.Keys) {
        $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
        [Environment]::SetEnvironmentVariable($name, $options[$name], 'Process')
    }
    & (Join-Path $PSScriptRoot 'run.ps1') -Mode $Mode -Port $Port -LanIP $LanIP -CheckOnly:$CheckOnly
} finally {
    foreach ($name in $previous.Keys) {
        [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process')
    }
}
