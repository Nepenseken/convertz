#!/usr/bin/env python3
"""
ItemsAdder pre-conversion fixer for Nepenseken/convertz.

Run immediately after the Java resource pack is decompressed and before converter.sh
builds config.json.

Fixes:
1. Merges ItemsAdder contents/*/resource_pack/assets into root assets/ with priority.
2. Resolves model texture references that still use ia:<id> to real namespace:path textures.
3. Keeps output vanilla-compatible for the original converter logic.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

COLORS = [
    "red", "black", "white", "blue", "green", "yellow", "lightred", "darkred",
    "pink", "darkpink", "orange", "darkorange", "brown", "darkbrown",
    "lightgreen", "darkgreen", "cyan", "teal", "lightblue", "darkblue",
    "lightpurple", "purple", "darkpurple", "lightgray", "gray", "darkyellow",
]
SLOT_WORDS = [
    ("chestplate", "chest"), ("chest", "chestplate"),
    ("leggings", "legs"), ("legs", "leggings"), ("legs", "leggins"),
    ("leggins", "legs"), ("boots", "boot"), ("boot", "boots"),
    ("helmet", "helm"), ("helm", "helmet"),
    ("sword", "blade"), ("blade", "sword"),
]


def load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def merge_itemsadder_resource_pack(pack_dir: Path) -> int:
    """Copy contents/*/resource_pack/assets over root assets with priority."""
    copied = 0
    root_assets = pack_dir / "assets"
    root_assets.mkdir(parents=True, exist_ok=True)

    content_roots = sorted((pack_dir / "contents").glob("*/resource_pack/assets")) if (pack_dir / "contents").exists() else []
    for assets_dir in content_roots:
        for src in assets_dir.rglob("*"):
            if not src.is_file():
                continue
            rel = src.relative_to(assets_dir)
            dst = root_assets / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            # Contents resource_pack should win over duplicate root assets.
            shutil.copy2(src, dst)
            copied += 1
    if copied:
        print(f"[IA] merged {copied} files from contents/*/resource_pack/assets into assets/")
    return copied


def build_texture_index(assets_dir: Path) -> Dict[str, List[Path]]:
    index: Dict[str, List[Path]] = defaultdict(list)
    for png in sorted(assets_dir.rglob("*.png")):
        ps = str(png).replace("\\", "/")
        if "/textures/" not in ps:
            continue
        index[png.stem.lower()].append(png)
    return index


def normalize_name(name: str) -> str:
    name = name.lower().replace("-", "_")
    name = re.sub(r"[^a-z0-9_]+", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name


def remove_color_suffix(name: str) -> str:
    for color in sorted(COLORS, key=len, reverse=True):
        suffix = "_" + color
        if name.endswith(suffix):
            return name[:-len(suffix)]
    return name


def candidate_names(model_name: str) -> Iterable[str]:
    seen = set()

    def add(value: str):
        value = normalize_name(value)
        if value and value not in seen:
            seen.add(value)
            yield value

    base = normalize_name(model_name)
    for v in add(base): yield v

    no_number = re.sub(r"_\d+$", "", base)
    for v in add(no_number): yield v

    no_color = remove_color_suffix(base)
    for v in add(no_color): yield v

    # Common ItemsAdder / EliteCreatures prefix stripping.
    for prefix in ["ecbluemech", "eclavabeast", "eclightknight", "ecruby", "elite_", "ec_"]:
        if base.startswith(prefix):
            for v in add(base[len(prefix):]): yield v

    # Slot aliases.
    for a, b in SLOT_WORDS:
        if base.endswith(a):
            for v in add(base[:-len(a)] + b): yield v
        if no_color.endswith(a):
            for v in add(no_color[:-len(a)] + b): yield v

    # Weapon pack variants: broadsword_orange -> broadsword, orange_broadsword.
    parts = base.split("_")
    if parts:
        for p in parts:
            if len(p) > 3:
                for v in add(p): yield v
        if parts[-1] in COLORS and len(parts) > 1:
            for v in add("_".join(parts[:-1])): yield v


def score_texture(model_name: str, png: Path) -> int:
    stem = normalize_name(png.stem)
    model = normalize_name(model_name)
    score = 0
    if stem == model:
        score += 1000
    if stem in set(candidate_names(model)):
        score += 700
    if model in stem:
        score += 300
    if remove_color_suffix(model) in stem:
        score += 150
    ps = str(png).replace("\\", "/").lower()
    if "/item/" in ps or "/items/" in ps:
        score += 60
    if "/entity/equipment/" in ps:
        score -= 120
    return score


def find_texture_png(model_name: str, texture_index: Dict[str, List[Path]]) -> Optional[Path]:
    names = list(candidate_names(model_name))
    for name in names:
        if name in texture_index:
            return texture_index[name][0]

    candidates: List[Tuple[int, Path]] = []
    for paths in texture_index.values():
        for png in paths:
            s = score_texture(model_name, png)
            if s > 0:
                candidates.append((s, png))
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[0], len(str(x[1]))), reverse=True)
    return candidates[0][1]


def texture_reference_from_png(assets_dir: Path, png: Path) -> Optional[str]:
    try:
        rel = png.relative_to(assets_dir)
    except ValueError:
        return None
    parts = rel.parts
    if len(parts) < 3 or parts[1] != "textures":
        return None
    ns = parts[0]
    path = Path(*parts[2:]).with_suffix("")
    return f"{ns}:{str(path).replace('\\\\', '/')}"


def resolve_ia_references(pack_dir: Path) -> int:
    assets = pack_dir / "assets"
    if not assets.exists():
        print("[IA] assets/ not found; skipping ia: resolver")
        return 0

    texture_index = build_texture_index(assets)
    print(f"[IA] indexed {len(texture_index)} unique texture names")

    changed = 0
    unresolved = 0
    for model_file in sorted(assets.glob("*/models/**/*.json")):
        data = load_json(model_file)
        if not data:
            continue
        textures = data.get("textures")
        if not isinstance(textures, dict):
            continue
        ia_values = [v for v in textures.values() if isinstance(v, str) and v.startswith("ia:")]
        if not ia_values:
            continue

        best = find_texture_png(model_file.stem, texture_index)
        if not best:
            unresolved += 1
            continue
        ref = texture_reference_from_png(assets, best)
        if not ref:
            unresolved += 1
            continue
        for key, value in list(textures.items()):
            if isinstance(value, str) and value.startswith("ia:"):
                textures[key] = ref
        data["textures"] = textures
        write_json(model_file, data)
        changed += 1

    print(f"[IA] resolved ia: references in {changed} model files; unresolved={unresolved}")
    return changed


def main(argv: List[str]) -> None:
    pack_dir = Path(argv[1] if len(argv) > 1 else ".").resolve()
    if not pack_dir.exists():
        print(f"[IA] pack dir not found: {pack_dir}")
        return
    merge_itemsadder_resource_pack(pack_dir)
    resolve_ia_references(pack_dir)


if __name__ == "__main__":
    main(sys.argv)
