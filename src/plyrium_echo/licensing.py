"""Licensing + trial — fully offline, never phones home.

A license key is a signed token: ``base64url(payload) . base64url(signature)``,
signed with an Ed25519 private key that only the vendor holds. The app embeds
the matching PUBLIC key and verifies the signature locally — so activation works
with no internet and no server, keeping the offline promise intact.

Trial: 14 days from first run. The start time is stored in the data dir AND
mirrored to HKCU; we take the earliest of the two, so deleting one doesn't reset
the clock. (A determined user can still reset a local trial — for a low-cost
indie app that's an acceptable trade vs. a heavy DRM/online scheme.)
"""

from __future__ import annotations

import base64
import json
import math
import time

from . import paths

# Ed25519 public key (base64, raw 32 bytes). Private key is kept off-repo by the
# vendor and used only by tools/license_keygen.py to mint keys.
_PUBLIC_KEY_B64 = "KItU9CxNc/OZXSd4Nqjn2lY0tEaCs5q6vO1/tTh0VDg="
_PRODUCT = "echo"
TRIAL_DAYS = 14


def _b64d(s: str) -> bytes:
    s = s.strip()
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def verify_key(key_str: str) -> dict | None:
    """Return the payload dict if the key signature is valid, else None."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        msg_b64, sig_b64 = (key_str or "").strip().split(".")
        msg, sig = _b64d(msg_b64), _b64d(sig_b64)
        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(_PUBLIC_KEY_B64))
        pub.verify(sig, msg)                       # raises if invalid
        payload = json.loads(msg.decode("utf-8"))
        if payload.get("p") != _PRODUCT:
            return None
        return payload
    except Exception:
        return None


class License:
    def __init__(self):
        self._key_path = paths.data_dir() / "license.key"
        self._trial_path = paths.data_dir() / ".trial"
        self._payload = None
        if self._key_path.exists():
            try:
                self._payload = verify_key(self._key_path.read_text(encoding="utf-8"))
            except Exception:
                self._payload = None

    # ── trial ──
    def _reg_get(self):
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Plyrium Echo") as k:
                v, _ = winreg.QueryValueEx(k, "t")
                return float(v)
        except Exception:
            return None

    def _reg_set(self, ts: float):
        try:
            import winreg
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Plyrium Echo") as k:
                winreg.SetValueEx(k, "t", 0, winreg.REG_SZ, str(ts))
        except Exception:
            pass

    def _trial_start(self) -> float:
        cands = []
        try:
            if self._trial_path.exists():
                cands.append(float(self._trial_path.read_text(encoding="utf-8").strip()))
        except Exception:
            pass
        reg = self._reg_get()
        if reg:
            cands.append(reg)
        if cands:
            return min(cands)
        now = time.time()                          # first run — stamp it
        try:
            self._trial_path.write_text(str(now), encoding="utf-8")
        except Exception:
            pass
        self._reg_set(now)
        return now

    def trial_days_left(self) -> int:
        left = TRIAL_DAYS - (time.time() - self._trial_start()) / 86400.0
        return max(0, math.ceil(left))

    # ── status / activation ──
    def licensed(self) -> bool:
        return self._payload is not None

    def licensed_to(self) -> str | None:
        return (self._payload or {}).get("n")

    def active(self) -> bool:
        """True if the app is usable (licensed or still in trial)."""
        return self.licensed() or self.trial_days_left() > 0

    def status(self) -> tuple[str, object]:
        if self.licensed():
            return ("licensed", self.licensed_to())
        d = self.trial_days_left()
        return ("trial", d) if d > 0 else ("expired", 0)

    def status_text(self) -> str:
        kind, info = self.status()
        if kind == "licensed":
            return f"Licensed to {info}"
        if kind == "trial":
            return f"Trial — {info} day{'s' if info != 1 else ''} left"
        return "Trial ended"

    def activate(self, key_str: str) -> tuple[bool, str]:
        payload = verify_key(key_str or "")
        if not payload:
            return (False, "That license key isn't valid. Check for a typo or "
                           "paste it again.")
        try:
            self._key_path.write_text((key_str or "").strip(), encoding="utf-8")
        except Exception as exc:
            return (False, f"Couldn't save the license: {exc}")
        self._payload = payload
        return (True, f"Activated — licensed to {payload.get('n', 'you')}. Thank you!")
