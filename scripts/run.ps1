# ViTrack 启动入口：读取已有配置，检查端口/证书，再启动 FastAPI；属于 P2 手机接入。
# 输入：-Mode pc/phone、可选端口/绑定地址/手机连接的局域网 IP；输出：访问地址或检查计划。
# 调用 app.config 读取 .env，调用 gen_cert.py 检查证书；不自动打开浏览器或访问摄像头。
[CmdletBinding()]
param(
    [ValidateSet('pc', 'phone')][string]$Mode = 'pc',
    [ValidateRange(0, 65535)][int]$Port = 0,
    [string]$BindAddress = '',
    [string]$LanIP = '',
    [switch]$CheckOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot 'envs\vitrack\python.exe'

function New-LaunchPlan {
    <#
    用途：将启动选项交给项目 Python 检查，返回可用于启动的计划对象。
    输入为脚本参数；输出包含地址、端口、证书公开信息和 Uvicorn 参数，不加载检测模型。
    Python 复用 app.config，避免 PowerShell 用另一套规则重复解析 .env。
    #>
    param([string]$LaunchMode, [int]$LaunchPort, [string]$Address, [string]$PhoneIP)

    $options = @{ mode = $LaunchMode; port = $LaunchPort; bind_address = $Address; lan_ip = $PhoneIP }
    # Base64 这里只编码参数 JSON，不是摄像头内容；用于避免 Windows 丢失引号或空字符串。
    $optionsJson = ConvertTo-Json -InputObject $options -Compress
    $encodedOptions = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($optionsJson))
    $planCode = @'
import base64
import ipaddress
import json
import socket
import sys
from app.config import load_config
from scripts.gen_cert import check_certificate, local_ips

try:
    options = json.loads(base64.b64decode(sys.argv[1]))
    settings = load_config()
    mode = options['mode']
    if settings.source == 'ipcam' and mode != 'pc':
        raise ValueError('IP camera fallback is viewed on the PC; use -Mode pc')
    port = options['port'] or (8000 if mode == 'pc' else settings.app_port)
    address = options['bind_address'] or ('127.0.0.1' if mode == 'pc' else settings.app_host)
    # IPv4 绑定与手机候选地址分开：0.0.0.0 是监听所有网卡，不是手机访问网址。
    bind_ip = ipaddress.IPv4Address(address)
    addresses = local_ips() if mode == 'phone' else []
    selected_ip = options['lan_ip']
    certificate = None
    if mode == 'phone':
        if selected_ip:
            selected_ip = str(ipaddress.IPv4Address(selected_ip))
            if selected_ip not in addresses:
                raise ValueError('LanIP must be a current local adapter address: ' + ', '.join(addresses))
        elif len(addresses) == 1:
            selected_ip = addresses[0]
        else:
            raise ValueError('Choose the adapter shared with your phone using -LanIP; candidates: ' + ', '.join(addresses))
        if str(bind_ip) not in ('0.0.0.0', selected_ip):
            raise ValueError('Phone mode must bind 0.0.0.0 or the selected LanIP')
        certificate = check_certificate(settings.https_cert, settings.https_key, [selected_ip, '127.0.0.1'])
        if 'localhost' not in certificate['dns_names']:
            raise ValueError('Certificate must also include localhost for the printed PC URL')
    # 先试绑定再释放：端口占用时退出，不停止已有服务。启动瞬间的竞争仍由 Uvicorn 报错。
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((address, port))
    launch_args = ['-X', 'utf8', '-m', 'uvicorn', 'app.main:app',
                   '--host', address, '--port', str(port), '--workers', '1']
    if certificate is not None:
        launch_args.extend(['--ssl-certfile', str(settings.https_cert),
                            '--ssl-keyfile', str(settings.https_key)])
    scheme = 'https' if mode == 'phone' else 'http'
    pc_host = 'localhost' if address in ('0.0.0.0', '127.0.0.1') else address
    plan = {'ok':True, 'mode':mode, 'bind_address':address, 'port':port, 'source':settings.source,
            'pc_url':scheme + '://' + pc_host + ':' + str(port) + '/pc',
            'phone_url':None if mode == 'pc' else 'https://' + selected_ip + ':' + str(port),
            'certificate':certificate, 'launch_args':launch_args}
except Exception as error:
    print(json.dumps({'ok':False, 'error':str(error)}))
    sys.exit(1)
# 默认 ASCII 转义保证 Windows PowerShell 5.1 也能可靠解析中文路径和错误。
print(json.dumps(plan))
'@
    $planOutput = & $pythonPath -X utf8 -c $planCode $encodedOptions
    $planExit = $LASTEXITCODE
    $plan = ($planOutput -join [Environment]::NewLine) | ConvertFrom-Json
    if ($planExit -ne 0 -or -not $plan.ok) {
        throw ("启动检查失败：{0}" -f $plan.error)
    }
    return $plan
}

function Show-AccessUrls {
    <#
    用途：把启动计划转换成初学者可复制的地址；输入计划，输出三行终端提示。
    不伪造尚未实现的 IP 摄像头入口；PC 模式也不会把普通 HTTP 当成手机安全上下文。
    #>
    param([Parameter(Mandatory = $true)]$Plan)

    if ($Plan.source -eq 'ipcam') {
        Write-Host ("PC IP 视频源页面：{0}（勾选同意后可开始读取）" -f $Plan.pc_url)
    } else {
        Write-Host ("PC 页面：{0}" -f $Plan.pc_url)
    }
    if ($Plan.mode -eq 'phone') {
        Write-Host ("手机 HTTPS：{0}" -f $Plan.phone_url)
    } else {
        Write-Host '手机 HTTPS：请使用 -Mode phone 启动，并在多网卡时指定 -LanIP。'
    }
    if ($Plan.source -eq 'ipcam') {
        Write-Host 'IP 摄像头模式：接口已启用；明确确认启动后才读取，默认不连接。'
    } else {
        Write-Host 'IP 摄像头模式：需配置 SOURCE=ipcam 与 IPCAM_URL，并使用 -Mode pc。'
    }
}

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw '找不到项目 Python，请先运行 scripts/setup_env.ps1。'
}

# 临时切到项目根目录保证 app 的导入位置正确；退出或报错均恢复用户原来的目录。
Push-Location -LiteralPath $projectRoot
try {
    $plan = New-LaunchPlan -LaunchMode $Mode -LaunchPort $Port -Address $BindAddress -PhoneIP $LanIP
    Show-AccessUrls -Plan $plan
    if ($Mode -eq 'phone' -and $plan.certificate.self_signed) {
        Write-Host '当前为自签证书：手机可能仍拒绝摄像头；信任与实机验证尚未完成。'
    }
    if ($CheckOnly) {
        # 只返回经过检查的计划，不启动服务、不加载模型，也不打开摄像头。
        return $plan
    }
    Write-Host '服务启动中；按 Ctrl+C 停止。隐私视频源需明确确认后才会开启。'
    $launchArgs = @($plan.launch_args)
    & $pythonPath @launchArgs
    if ($LASTEXITCODE -ne 0) {
        throw ("服务退出，退出码：{0}" -f $LASTEXITCODE)
    }
} finally {
    Pop-Location
}
