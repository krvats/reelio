"""Secrets file: AES-256-GCM, key from PBKDF2(passphrase). Same format the browser UI writes with WebCrypto."""
import os, json, base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

ITER = 200_000


def _key(passphrase, salt, iters):
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iters).derive(passphrase.encode())


def encrypt(obj, passphrase, iters=ITER):
    salt, iv = os.urandom(16), os.urandom(12)
    ct = AESGCM(_key(passphrase, salt, iters)).encrypt(iv, json.dumps(obj).encode(), None)
    b = lambda x: base64.b64encode(x).decode()
    return {"v": 1, "kdf": "pbkdf2-sha256", "iter": iters, "salt": b(salt), "iv": b(iv), "ct": b(ct)}


def decrypt(blob, passphrase):
    d = lambda k: base64.b64decode(blob[k])
    try:
        pt = AESGCM(_key(passphrase, d("salt"), int(blob.get("iter", ITER)))).decrypt(d("iv"), d("ct"), None)
    except Exception:
        raise ValueError("could not unlock secrets: the REELIO_KEY secret in GitHub does not match the passphrase set in the app")
    return json.loads(pt)
