import sys
from pathlib import Path
from dotenv import load_dotenv

root = Path(r"d:\sliit\Y4S1\rp\vinuka\Technology-Enabled-Employee-Tracking-and-Performance-Management-System\R26-IT-042")
sys.path.append(str(root))

from common.encryption import AESEncryptor
load_dotenv(root / ".env")

def manual_decrypt(path):
    print(f"Decrypting {path}...")
    enc = AESEncryptor()
    data = Path(path).read_bytes()
    print(f"File size: {len(data)}")
    print(f"Data starts with: {data[:20]}")
    try:
        dec = enc.decrypt_bytes(data)
        print(f"Success! Decrypted size: {len(dec)}")
    except Exception as exc:
        print(f"Failed! Error: {exc}")

if __name__ == "__main__":
    manual_decrypt(root / "screenshots" / "test_admin_20260328T081425.enc")
