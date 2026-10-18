"""为 ViTrack 生成和检查局域网 HTTPS 证书，属于 P2 手机接入功能。

命令行输入：可选 --ip、--days、--output-dir；输出：cert.pem、key.pem 和公开的检查摘要。
run.ps1 复用 local_ips/check_certificate，先检查地址与证书，再启动已有 app.main:app。
只实现方案 B 的自签证书；不联网、不安装系统信任、不访问摄像头、不覆盖已有文件。
"""

import argparse
from datetime import datetime, timedelta, timezone
import ipaddress
import json
from pathlib import Path
import socket
import ssl
import psutil

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def local_ips() -> list[str]:
    """查询本机网卡的 IPv4 地址，返回去重列表，供生成证书和启动脚本选择地址。

    这里只枚举本机网卡地址，不连接外部服务或访问定位；多网卡时保留全部候选，不猜手机使用哪张网卡。
    """
    addresses = set()
    # 只按电脑名称查DNS会漏掉Windows移动热点网卡；直接枚举本机已分配地址，不访问定位/WLAN权限。
    candidates = [item.address for items in psutil.net_if_addrs().values() for item in items
                  if item.family == socket.AF_INET]
    for candidate in candidates:
        address = ipaddress.ip_address(candidate)
        if not address.is_loopback and not address.is_link_local and not address.is_unspecified:
            addresses.add(str(address))
    return sorted(addresses, key=ipaddress.ip_address)


def check_certificate(cert_path: Path, key_path: Path, addresses: list[str]) -> dict:
    """检查证书文件、有效期、私钥配对及 SAN 地址，输出不含私钥的摘要。

    输入为证书路径、私钥路径、需要访问的 IP；由 create_certificate 和 run.ps1 调用。
    SAN 是证书允许使用的地址清单；只修改网址而不更新 SAN，会造成证书地址不匹配。
    """
    if not cert_path.is_file() or not key_path.is_file():
        raise ValueError("缺少证书或私钥，请先运行 scripts/gen_cert.py")
    certificate = x509.load_pem_x509_certificate(cert_path.read_bytes())
    # SSLContext 会检查证书能否加载以及私钥是否与其配对，不会把证书加入系统信任。
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert_path), str(key_path))
    now = datetime.now(timezone.utc)
    if not certificate.not_valid_before_utc <= now < certificate.not_valid_after_utc:
        raise ValueError("证书尚未生效或已经过期，请在新目录生成证书并更新 .env 路径")
    try:
        names = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound as error:
        raise ValueError("证书缺少 SAN 地址清单") from error
    ip_names = [str(address) for address in names.get_values_for_type(x509.IPAddress)]
    missing = [address for address in addresses if str(ipaddress.ip_address(address)) not in ip_names]
    if missing:
        raise ValueError("证书不包含这些 IP：" + ", ".join(missing) + "；请在新目录生成并更新配置")
    return {
        "cert_path": str(cert_path), "key_path": str(key_path),
        "ip_addresses": ip_names, "dns_names": names.get_values_for_type(x509.DNSName),
        "expires_at": certificate.not_valid_after_utc.isoformat(),
        "fingerprint_sha256": certificate.fingerprint(hashes.SHA256()).hex(),
        "self_signed": certificate.subject == certificate.issuer,
    }


def create_certificate(output_dir: Path, addresses: list[str], days: int) -> dict:
    """接收目标目录、IP 和有效天数，返回生成或复用后的公开摘要。

    主流程调用本函数；先整理地址，再复用完整证书或生成 RSA 私钥和带 SAN 的证书。
    已有文件不会被覆盖，避免一次重跑让已经配置好的手机失去原证书。
    """
    if not 1 <= days <= 825:
        raise ValueError("days 应在 1～825 天")
    # localhost 和回环地址用于本机验证；set 去重，IPAddress 区分 IPv4 与 IPv6。
    requested = {str(ipaddress.ip_address(value)) for value in addresses}
    requested.update(("127.0.0.1", "::1"))
    ip_names = sorted(requested, key=lambda value: (ipaddress.ip_address(value).version, value))
    cert_path = output_dir / "cert.pem"
    key_path = output_dir / "key.pem"
    if cert_path.exists() or key_path.exists() or cert_path.is_symlink() or key_path.is_symlink():
        result = check_certificate(cert_path, key_path, ip_names)
        if "localhost" not in result["dns_names"]:
            raise ValueError("已有证书不包含 localhost，请使用新目录，旧文件不会覆盖")
        result["action"] = "reused"
        return result

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ViTrack local development")])
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject).issuer_name(subject).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=days))
        .add_extension(x509.SubjectAlternativeName(
            [x509.DNSName("localhost")] +
            [x509.IPAddress(ipaddress.ip_address(value)) for value in ip_names]
        ), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(key, hashes.SHA256())
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    # xb 表示“只能新建”，即使并发运行，也不能覆盖另一进程刚生成的文件。
    # 只有两份写入均完成，才返回成功；出错只移除本次刚创建的文件。
    created = []
    try:
        for path, content in (
            (key_path, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption())),
            (cert_path, certificate.public_bytes(serialization.Encoding.PEM)),
        ):
            with path.open("xb") as target:
                created.append(path)
                target.write(content)
        result = check_certificate(cert_path, key_path, ip_names)
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    result["action"] = "created"
    return result


def main() -> int:
    """命令行入口：校验参数、生成/复用证书并打印摘要；成功返回 0，失败返回 1。"""
    parser = argparse.ArgumentParser(description="生成项目内的局域网自签证书，不安装系统信任")
    parser.add_argument("--ip", action="append", default=[], help="需包含的 IP，可重复；省略则包含本机网卡")
    parser.add_argument("--days", type=int, default=365, help="有效天数，默认 365")
    parser.add_argument("--output-dir", type=Path, default=Path("certs"), help="证书目录，默认项目 certs")
    args = parser.parse_args()
    try:
        output_dir = args.output_dir
        if not output_dir.is_absolute():
            output_dir = PROJECT_ROOT / output_dir
        result = create_certificate(output_dir.resolve(), args.ip or local_ips(), args.days)
    except (ValueError, OSError, ssl.SSLError) as error:
        print("证书准备失败：" + str(error))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("自签证书不等于手机已信任；手机验证失败时按方案转用 mkcert。私钥 key.pem 不发给手机。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
