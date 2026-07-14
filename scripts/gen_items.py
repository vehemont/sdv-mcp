"""Regenerate sdv_items.py from the community-maintained unpacked-asset mirror.

Source: https://github.com/MateusAquino/stardewids  (dist/*.json), which compiles
Stardew Valley's unpacked Data/Objects + Data/BigCraftables into per-type JSON,
tracked in git and updated per game patch. We keep only id -> English name so the
generated module stays small and ships inside the wheel (offline at runtime).

Run this when a new game version adds items:
    python scripts/gen_items.py
"""
import json, sys, urllib.request, datetime

BASE = "https://raw.githubusercontent.com/MateusAquino/stardewids/main/dist"
OUT = "sdv_items.py"
EN = "data-en-US"


def fetch(name):
    with urllib.request.urlopen(f"{BASE}/{name}", timeout=60) as r:
        return json.load(r)


def id_names(entries):
    out = {}
    for e in entries:
        iid = str(e.get("id", "")).strip()
        name = (e.get("names") or {}).get(EN, "").strip()
        if iid and name and iid not in out:
            out[iid] = name
    return out


def dump(d):
    # deterministic ordering: numeric ids first (sorted numerically), then the rest
    def key(k):
        return (0, int(k)) if k.isdigit() else (1, k)
    lines = [f"    {k!r}: {d[k]!r}," for k in sorted(d, key=key)]
    return "{\n" + "\n".join(lines) + "\n}"


def main():
    objects = id_names(fetch("objects.json"))
    big = id_names(fetch("big-craftables.json"))
    header = (
        '"""Auto-generated item catalog (id -> English name). DO NOT EDIT BY HAND.\n'
        f"Generated {datetime.date.today().isoformat()} by scripts/gen_items.py from\n"
        'the MateusAquino/stardewids unpacked-asset mirror.\n'
        'OBJECTS keys are unqualified object ids; BIG_CRAFTABLES keys are unqualified\n'
        'big-craftable ids (note: object/big-craftable numeric ids can collide).\n"""\n'
    )
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(header)
        f.write(f"\nOBJECTS = {dump(objects)}\n")
        f.write(f"\nBIG_CRAFTABLES = {dump(big)}\n")
    print(f"wrote {OUT}: {len(objects)} objects, {len(big)} big craftables")


if __name__ == "__main__":
    sys.exit(main())
