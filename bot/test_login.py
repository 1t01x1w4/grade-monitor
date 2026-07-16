"""Test CAS password login with RSA encryption and captcha flow."""
import asyncio
import importlib.util
import os
import sys
import types as _types

# Load .env
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# Bypass plugin __init__.py (depends on nonebot), load scraper modules directly
_PLUGIN_DIR = os.path.join(os.path.dirname(__file__), "src", "plugins", "grade_monitor")

# Register fake parent package for relative imports
_pkg = _types.ModuleType("grade_monitor")
_pkg.__path__ = [_PLUGIN_DIR]
_pkg.__package__ = "grade_monitor"
sys.modules["grade_monitor"] = _pkg


def _load_module(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_cfg = _load_module("grade_monitor.config_manager", os.path.join(_PLUGIN_DIR, "config_manager.py"))
_scraper = _load_module("grade_monitor.scraper", os.path.join(_PLUGIN_DIR, "scraper.py"))

_rsa_encrypt = _scraper._rsa_encrypt
_get_chunk_size = _scraper._get_chunk_size
_generate_login_token = _scraper._generate_login_token
_login_with_password = _scraper._login_with_password
_get_captcha = _scraper._get_captcha
_solve_arithmetic_captcha = _scraper._solve_arithmetic_captcha
login = _scraper.login
fetch_grades = _scraper.fetch_grades
invalidate_tgt = _scraper.invalidate_tgt

# RSA private exponent for round-trip verification (从 debug_app.js 提取)
_RSA_PRIVATE_EXP = int(
    "413798867d69babed22e0dd3d4031c635f3e9dbca0fa50a32974a0e230787b7f"
    "7ba78caefbee828a051c690357a8cc31dba8efc738b4db22e887571ef1ec5a5a"
    "55b6d866f6a67527f6a7d78a127c9f687008bb540228b50aa2d1ca5a4ff71107"
    "234f936b611ac46432a26da9c302eaa7180820df70593353b3f8c0247fe97a45",
    16,
)
_RSA_MODULUS = _scraper._RSA_MODULUS


async def main():
    username = os.getenv("JW_USERNAME", "").strip()
    password = os.getenv("JW_PASSWORD", "").strip()

    if not username or username == "your_student_id":
        print("[ERROR] Please set valid JW_USERNAME and JW_PASSWORD in bot/.env")
        return

    print(f"Username: {username}")
    print(f"Password length: {len(password)}")

    # --- Round-trip verification ---
    print("\n--- Round-trip Verification ---")
    chunk_size = _get_chunk_size()
    print(f"Chunk size: {chunk_size} bytes")

    # Test with a known plaintext
    test_plaintext = password
    encrypted_hex = _rsa_encrypt(test_plaintext)
    print(f"RSA encrypted: {len(encrypted_hex)} hex chars")

    # Decrypt: c^d mod n
    c = int(encrypted_hex, 16)
    decrypted_int = pow(c, _RSA_PRIVATE_EXP, _RSA_MODULUS)
    decrypted_bytes = decrypted_int.to_bytes(
        (decrypted_int.bit_length() + 7) // 8, 'little'
    )

    # The decrypted bytes should start with the password followed by zero padding
    password_bytes = test_plaintext.encode("utf-8")
    if decrypted_bytes[:len(password_bytes)] == password_bytes:
        # Check that trailing bytes are all zeros
        trailing = decrypted_bytes[len(password_bytes):]
        all_zeros = all(b == 0 for b in trailing)
        zero_count = len(trailing)
        print(f"[PASS] Round-trip verified: decrypted data starts with password, "
              f"{zero_count} trailing bytes ({'all zeros' if all_zeros else 'NON-ZERO!'})")
    else:
        print(f"[FAIL] Round-trip mismatch!")
        print(f"  Expected prefix: {password_bytes.hex()}")
        print(f"  Got prefix:      {decrypted_bytes[:len(password_bytes)].hex()}")
        print(f"  Full decrypted ({len(decrypted_bytes)} bytes): {decrypted_bytes.hex()}")
        return

    # --- RSA encryption and Loginusertoken ---
    print("\n--- RSA Encryption Tests ---")
    encrypted = _rsa_encrypt(password)
    print(f"Password encrypted: {len(encrypted)} hex chars (expected 256)")
    assert len(encrypted) == 256, f"RSA encryption length mismatch: {len(encrypted)}"

    token = _generate_login_token()
    print(f"Loginusertoken: {len(token)} hex chars (expected 256)")
    assert len(token) == 256, f"Loginusertoken length mismatch: {len(token)}"
    print("[PASS] RSA encryption and Loginusertoken generation work correctly")

    # Test captcha fetch
    print("\nFetching captcha...")
    captcha_uid, captcha_answer = await _get_captcha()
    if captcha_uid and captcha_answer:
        print(f"Captcha uid: {captcha_uid}")
        print(f"Captcha answer: {captcha_answer}")
    else:
        print("[INFO] Captcha OCR not available (expected — set JW_CAPTCHA_CODE/JW_CAPTCHA_UID to test)")

    # Test full login flow (requires captcha)
    print("\nAttempting CAS login (requires captcha)...")
    tgt = await _login_with_password(username, password)

    if tgt:
        print(f"[SUCCESS] TGT: {tgt}")

        # --- Full SSO flow: TGT → ST → JSESSIONID ---
        print("\n--- Full SSO Login (TGT → ST → JSESSIONID) ---")
        # Invalidate any cached state so login() uses our fresh TGT
        invalidate_tgt()
        try:
            client = await login()
            # Find the main app JSESSIONID (path=/jwglxt), not the SSO one (path=/sso)
            jsessionid = ""
            for c in client.cookies.jar:
                if c.name == "JSESSIONID" and "jwglxt" in c.domain and c.path == "/jwglxt":
                    jsessionid = c.value
                    break
            print(f"[SUCCESS] JSESSIONID obtained: {jsessionid[:20]}..." if jsessionid else "[FAIL] No JSESSIONID in cookies")

            # --- Fetch Grades ---
            print("\n--- Fetching Grades ---")
            grades = await fetch_grades()
            print(f"[SUCCESS] Retrieved {len(grades)} grade entries:")
            for g in grades[:10]:  # Show first 10
                name = g.get("kcmc", g.get("course", "?"))
                score = g.get("cj", g.get("score", "?"))
                term = g.get("xnm", g.get("term", "?"))
                print(f"  {term} | {name}: {score}")
            if len(grades) > 10:
                print(f"  ... and {len(grades) - 10} more entries")
        except Exception as e:
            print(f"[FAIL] Full flow failed: {e}")
    else:
        print("[FAILED] Login failed — captcha may be required")
        print("To test with captcha, set JW_CAPTCHA_UID and JW_CAPTCHA_CODE in .env")


if __name__ == "__main__":
    asyncio.run(main())
