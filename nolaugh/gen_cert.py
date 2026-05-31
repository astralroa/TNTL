"""
Run this once to generate cert.pem and key.pem for HTTPS.
Requires: pip install cryptography

Usage: py gen_cert.py [your-radmin-ip]
Example: py gen_cert.py 26.24.146.35
"""
import sys, datetime, ipaddress
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

extra_ips = sys.argv[1:] if len(sys.argv) > 1 else []

key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, u'nolaugh-local')])

san_entries = [
    x509.DNSName(u'localhost'),
    x509.IPAddress(ipaddress.IPv4Address('127.0.0.1')),
]
for ip in extra_ips:
    try:
        san_entries.append(x509.IPAddress(ipaddress.IPv4Address(ip)))
        print(f"Added IP: {ip}")
    except Exception:
        print(f"Skipped invalid IP: {ip}")

cert = (
    x509.CertificateBuilder()
    .subject_name(subject)
    .issuer_name(issuer)
    .public_key(key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(datetime.datetime.now(datetime.UTC))
    .not_valid_after(datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=825))
    .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
    .sign(key, hashes.SHA256())
)

open('cert.pem', 'wb').write(cert.public_bytes(serialization.Encoding.PEM))
open('key.pem', 'wb').write(key.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.TraditionalOpenSSL,
    serialization.NoEncryption(),
))
print("cert.pem and key.pem generated. Valid for 825 days.")
print("Run server with:")
print("  py -m daphne -b 0.0.0.0 -p 8443 --certfile cert.pem --keyfile key.pem nolaugh.asgi:application")
