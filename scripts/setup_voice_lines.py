# -*- coding: utf-8 -*-
"""Sao chép voice lines vào runtime/voice_lines và ghi danh mục phân loại."""
import json
import shutil
from pathlib import Path

SOURCE = Path(r"D:\Tris voice")
PROJECT = Path(r"D:\Ai building\2026-08-30\sau-x20\outputs\english-ai-tutor")
TARGET = PROJECT / "runtime" / "voice_lines"

# Phân loại theo ngữ nghĩa câu thoại của nhân vật.
CATEGORY_BY_FILE = {
    # ===== CHIẾN ĐẤU (battle / combat) =====
    "bring-on-the-bad-guys": "chien_dau",
    "eyes-on-the-enemy-rumble": "chien_dau",
    "i-don-t-take-cover-i-take-cover-out": "chien_dau",
    "let-s-get-in-range": "chien_dau",
    "let-s-snares-vines-meet-your-worst-nightmare": "chien_dau",
    "light-em-up": "chien_dau",
    "lookout-below": "chien_dau",
    "nothing-a-little-gunpowder-won-t-fix": "chien_dau",
    "it-won-t-be-so-much-a-whisper-as-a-deafening-explosion": "chien_dau",
    "if-it-s-worth-shooting-once-it-s-probably-worth-shooting-a-lot": "chien_dau",
    "if-there-s-a-sword-for-making-things-explode-this-is-it": "chien_dau",
    "check-the-kick-on-this-sucker": "chien_dau",
    "let-him-come-by-land-by-sea-or-air-center-on-in-home-when-the-battle-got-his-blair": "chien_dau",
    "abandoned-gunner-never-turns-tail-unless-it-s-to-taunt-you": "chien_dau",
    "i-dare-you-to-dare-me": "chien_dau",
    # ===== HƯNG PHẤN (excited / hype) =====
    "bringing-down-the-house": "hung_phan",
    "let-s-get-this-party-started": "hung_phan",
    "infinity-anything-is-pretty-awesome": "hung_phan",
    "all-the-risk-and-none-of-the-consequences-i-m-sold": "hung_phan",
    "i-bravely-volunteered-to-charge-in-recklessly": "hung_phan",
    "more-where-that-came-from": "hung_phan",
    "keep-em-coming": "hung_phan",
    "does-this-make-me-royalty": "hung_phan",
    "is-that-a-rocket-in-your-pocket": "hung_phan",
    # ===== VUI (happy / playful) =====
    "a-cannon-ball-is-the-best-ice-breaker": "vui",
    "anyone-ever-tell-you-you-re-a-little-clingy": "vui",
    "can-t-wait-to-tell-the-recruits-about-that-one": "vui",
    "ha-ha-ha-that-was-scary": "vui",
    "i-can-eyeball-it": "vui",
    "i-got-this-one": "vui",
    "i-just-need-a-point-in-the-right-direction": "vui",
    "just-passing-through": "vui",
    "leave-it-to-me": "vui",
    "let-me-get-in-there": "vui",
    "maybe-i-cut-that-a-little-close-maybe": "vui",
    "once-a-bandel-gunner-always-a-bandel-gunner": "vui",
    "any-landing-you-can-walk-away-from": "vui",
    "oh-veigar-tell-me-all-about-your-diabolical-plan": "vui",
    "blunstone-pie-intense-time-so-bad-oh-god-oh-shoarma": "vui",
    # ===== BUỒN (sad / calm / tired) =====
    "need-a-breather": "buon",
}

TARGET.mkdir(parents=True, exist_ok=True)
catalog = {"vui": [], "chien_dau": [], "hung_phan": [], "buon": []}
missing = []
for name, category in CATEGORY_BY_FILE.items():
    src = SOURCE / f"{name}.mp3"
    if not src.is_file():
        missing.append(name)
        continue
    shutil.copy2(src, TARGET / src.name)
    catalog[category].append(src.name)

(TARGET / "catalog.json").write_text(
    json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8"
)
total = sum(len(v) for v in catalog.values())
print(f"Copied {total} clips -> {TARGET}")
for cat, items in catalog.items():
    print(f"  {cat}: {len(items)} clips")
if missing:
    print("MISSING:", missing)
