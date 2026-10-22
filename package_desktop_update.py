"""Seller-only signed installer packager. Never ship the private signing key."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def load_key(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return Ed25519PrivateKey.from_private_bytes(path.read_bytes())
    key = Ed25519PrivateKey.generate()
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as stream:
        stream.write(key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()))
    return key


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--key', default='private-license-batches/update-signing-private.key')
    parser.add_argument('--public', default='windows-installer-kit/source/update-public.key')
    parser.add_argument('--init', action='store_true')
    parser.add_argument('--platform', choices=['windows-x64', 'windows-x86'], default='windows-x64')
    parser.add_argument('--installer')
    parser.add_argument('--version')
    parser.add_argument('--minimum-version', default='1.0.0')
    parser.add_argument('--output')
    args = parser.parse_args()
    key = load_key(args.key)
    public = base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    Path(args.public).write_text(public + '\n')
    if args.init:
        return
    if not all([args.installer, args.version, args.output]):
        parser.error('--installer, --version and --output are required')
    import re
    if not all(re.fullmatch(r'\d{1,6}\.\d{1,6}\.\d{1,6}', v) for v in [args.version, args.minimum_version]):
        parser.error('Versions must be x.y.z')
    installer = Path(args.installer).read_bytes()
    if not installer.startswith(b'MZ'):
        parser.error('Expected a Windows EXE installer')
    manifest = json.dumps(dict(kind='hesab-ghadim-windows-update-v1', platform=args.platform,
                              version=args.version, minimum_version=args.minimum_version,
                              size=len(installer), sha256=hashlib.sha256(installer).hexdigest()),
                          sort_keys=True, separators=(',', ':')).encode()
    with ZipFile(args.output, 'x', ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json', manifest)
        archive.writestr('signature.txt', base64.b64encode(key.sign(manifest)))
        archive.writestr('installer.exe', installer)
    print(args.output)


if __name__ == '__main__':
    main()
