#!/usr/bin/env python3
"""
ItemsAdder `ia:<id>` texture resolver for java2bedrock.sh converter.

Two-pass approach:
1. Read all models, build ia_id -> models mapping
2. For each model with ia:, try to find matching PNG
3. If found, use the resolved path for ALL models with same ia: id
4. Write back only after all mappings are resolved

Usage: python ia_fix.py <pack_directory>
"""

import json, os, sys, re
from pathlib import Path
from collections import defaultdict

def build_texture_index(assets_dir: Path) -> dict:
    index = defaultdict(list)
    for png in assets_dir.rglob("*.png"):
        png_str = str(png)
        if "/textures/" in png_str or "\\textures\\" in png_str:
            index[png.stem.lower()].append(png)
    return index

def find_texture_png_by_name(model_name: str, texture_index: dict) -> Path | None:
    """Find matching PNG by model filename only (no ia: id context)."""
    name = model_name.lower()

    if name in texture_index:
        return texture_index[name][0]

    for k in texture_index:
        if k.endswith(f"_{name}"):
            return texture_index[k][0]

    for k in texture_index:
        if name in k:
            return texture_index[k][0]

    for k in texture_index:
        if len(k) >= 4 and k in name:
            return texture_index[k][0]

    # Strip trailing _<number>
    base = re.sub(r'_\d+$', '', name)
    if base and base != name and len(base) > 2:
        r = find_texture_png_by_name(base, texture_index)
        if r: return r

    # Color suffix stripping
    colors = ["_red", "_black", "_white", "_blue", "_green", "_yellow",
              "_lightred", "_darkred", "_pink", "_darkpink", "_orange",
              "_darkorange", "_brown", "_darkbrown", "_lightgreen", 
              "_darkgreen", "_cyan", "_teal", "_lightblue", "_darkblue",
              "_lightpurple", "_purple", "_darkpurple", "_lightgray",
              "_gray", "_darkyellow"]
    for c in sorted(colors, key=len, reverse=True):
        if name.endswith(c):
            base2 = name[:-len(c)]
            if len(base2) > 2:
                r = find_texture_png_by_name(base2, texture_index)
                if r:
                    tex_stem = r.stem
                    colored = tex_stem + c
                    if colored.lower() in texture_index:
                        return texture_index[colored.lower()][0]
                    return r

    # Suffix swaps
    swaps = [("legs", "leggings"), ("leggings", "legs"),
             ("legs", "leggins"), ("leggins", "legs"),
             ("boots", "boot"), ("boot", "boots"),
             ("helmet", "helm"), ("helm", "helmet"),
             ("chestplate", "chest"), ("chest", "chestplate")]
    for a, b in swaps:
        if name.endswith(a):
            r = find_texture_png_by_name(name[:-len(a)] + b, texture_index)
            if r: return r

    # Strip prefix patterns
    for prefix in ["ecbluemech", "eclavabeast", "eclightknight", "ecruby", "ec"]:
        if name.startswith(prefix) and len(name) > len(prefix) + 2:
            stripped = name[len(prefix):].lstrip("_")
            if stripped and len(stripped) > 2:
                r = find_texture_png_by_name(stripped, texture_index)
                if r: return r

    return None


def process_pack(pack_dir: str):
    pack = Path(pack_dir)
    assets = pack / "assets"
    if not assets.exists():
        print(f"[ERROR] assets/ not found")
        sys.exit(1)

    texture_index = build_texture_index(assets)
    print(f"[INFO] {len(texture_index)} unique texture names indexed")

    # --- PASS 1: Collect all models with ia: references ---
    # {ia_id: [(model_path, model_name, textures_dict, namespace)]}
    ia_groups = defaultdict(list)

    for ns_dir in assets.iterdir():
        if not ns_dir.is_dir() or ns_dir.name in ("minecraft", "_iainternal"):
            continue
        models_dir = ns_dir / "models"
        if not models_dir.exists():
            continue

        for model_file in models_dir.rglob("*.json"):
            try:
                data = json.loads(model_file.read_text(encoding='utf-8'))
            except Exception:
                continue

            textures = data.get("textures")
            if not textures:
                continue

            # Collect all ia: ids in this model
            ia_ids = {v for v in textures.values() if isinstance(v, str) and v.startswith("ia:")}
            if not ia_ids:
                continue

            for ia_id in ia_ids:
                ia_groups[ia_id].append({
                    "path": model_file,
                    "name": model_file.stem,
                    "namespace": ns_dir.name,
                    "textures": textures,
                    "data": data,
                })

    print(f"[INFO] {len(ia_groups)} unique ia: IDs across models")

    if not ia_groups:
        print("No ia: references found. Pack is already clean!")
        return

    # --- PASS 2: Try to resolve each ia: group ---
    resolved_map = {}  # {ia_id: (tex_namespace, rel_path, png_name)}

    for ia_id, models in ia_groups.items():
        # Try to find texture by any model name in the group
        best_png = None
        for m in sorted(models, key=lambda m: len(m["name"]), reverse=True):
            png = find_texture_png_by_name(m["name"], texture_index)
            if png:
                best_png = png
                break

        if not best_png:
            # Last resort: find any texture in the model's namespace
            ns = models[0]["namespace"]
            ns_textures_dir = assets / ns / "textures"
            if ns_textures_dir.exists():
                pngs = list(ns_textures_dir.rglob("*.png"))
                if pngs:
                    # Try to find closest to model dir structure
                    model_dir = models[0]["path"].parent.relative_to(assets / ns / "models")
                    closest_dir = ns_textures_dir / str(model_dir)
                    if closest_dir.exists():
                        pngs = list(closest_dir.rglob("*.png"))
                        if not pngs:
                            pngs = list(ns_textures_dir.rglob("*.png"))
                    best_png = pngs[0]

        if not best_png:
            print(f"  [SKIP] ia:{ia_id} ({len(models)} models) - no texture found")
            continue

        # Build path
        ns = models[0]["namespace"]
        try:
            rel = best_png.relative_to(assets / ns / "textures")
            tex_ns = ns
        except ValueError:
            rel = best_png.relative_to(assets)
            tex_ns = rel.parts[0]
            rel = Path(*rel.parts[2:])

        rel_path = str(rel.with_suffix('')).replace('\\', '/')
        resolved_map[ia_id] = (tex_ns, rel_path, best_png.name)
        print(f"  [OK]   {ia_id} ({len(models)} models) -> {tex_ns}:{rel_path} ({best_png.name})")

    # --- PASS 3: Apply resolutions ---
    fixed = 0
    for ia_id, resolution in resolved_map.items():
        tex_ns, rel_path, png_name = resolution
        for m in ia_groups[ia_id]:
            new_textures = {}
            for key, val in m["textures"].items():
                if isinstance(val, str) and val.startswith("ia:"):
                    new_textures[key] = f"{tex_ns}:{rel_path}"
                else:
                    new_textures[key] = val
            m["data"]["textures"] = new_textures
            m["path"].write_text(json.dumps(m["data"], separators=(',', ':')), encoding='utf-8')
            fixed += 1

    print(f"\n{'='*50}")
    print(f"Fixed {fixed} model files across {len(resolved_map)} ia: groups.")

    remaining = 0
    for ns_dir in [d for d in assets.iterdir() if d.is_dir() and d.name != "minecraft"]:
        md = ns_dir / "models"
        if md.exists():
            for f in md.rglob("*.json"):
                try:
                    if 'ia:' in f.read_text(encoding='utf-8'):
                        remaining += 1
                except:
                    pass
    if remaining:
        print(f"Still has ia: references: {remaining} models")
    else:
        print("ALL ia: references resolved!")
    print(f"\nNow run: ./converter.sh <pack_zip>")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python ia_fix.py <pack_directory>")
        sys.exit(1)
    process_pack(sys.argv[1])
