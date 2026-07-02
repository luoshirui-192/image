"""Generate Django-compatible password hash for seed scripts (deterministic salt)."""
import hashlib
import base64
import sys

# Fixed salt keeps seed SQL reproducible across environments.
DEFAULT_SALTS = {
    "admin123": "seedadmin001",
    "user123": "seeduser001",
}


def make_pbkdf2_password(password: str, salt: str | None = None, iterations: int = 600000) -> str:
    salt = salt or DEFAULT_SALTS.get(password, "seeddefault01")
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    )
    hash_b64 = base64.b64encode(digest).decode("ascii").strip()
    return f"pbkdf2_sha256${iterations}${salt}${hash_b64}"


if __name__ == "__main__":
    password = sys.argv[1] if len(sys.argv) > 1 else "admin123"
    print(make_pbkdf2_password(password))
