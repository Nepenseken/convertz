#!/usr/bin/env python3
"""
Postprocess fixer for Nepenseken/convertz output packs.

Run after target/rp has been generated and before zipping.

Fixes:
- Bedrock geometry texture_width/texture_height using Java model texture_size.
- Missing armor .player attachables and armor_layer textures.
- Reports animated model candidates that need manual Bedrock animation support.

The script is intentionally tolerant: it logs skips but does not break conversion.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

COLORS = {
    "black", "blue", "brown", "cyan", "gray", "green", "orange", "pink", "purple", "red", "teal", "white", "yellow",
    "darkblue", "darkbrown", "darkgreen", "darkorange", "darkpink", "darkpurple", "darkred", "darkyellow",
    "lightblue", "lightgray", "lightgreen", "lightpurple", "lightred",
}
SLOTS = {
    "helmet": ("geometry.player.armor.helmet", "variable.helmet_layer_visible = 0.0;", "humanoid"),
    "helm": ("geometry.player.armor.helmet", "variable.helmet_layer_visible = 0.0;", "humanoid"),
    "chestplate": ("geometry.player.armor.chestplate", "variable.chest_layer_visible = 0.0;", "humanoid"),
    "chest": ("geometry.player.armor.chestplate", "variable.chest_layer_visible = 0.0;", "humanoid"),
    "leggings": ("geometry.player.armor.leggings", "variable.leg_layer_visible = 0.0;", "humanoid_leggings"),
    "legs": ("geometry.player.armor.leggings", "variable.leg_layer_visible = 0.0;", "humanoid_leggings"),
    "leggins": ("geometry.player.armor.leggings", "variable.leg_layer_visible = 0.0;", "humanoid_leggings"),
    "boots": ("geometry.player.armor.boots", "variable.feet_layer_visible = 0.0;", "humanoid"),
    "boot": ("geometry.player.armor.boots", "variable.feet_layer_visible = 0.0;", "humanoid"),
}


def load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def norm(value: str) -> str:
    value = value.lower().replace("-", "_")
    value = re.sub(r"[^a-z0-9_]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value


def source_priority(path: str) -> int:
    p = path.replace("\\", "/")
    if p.startswith("contents/") and "/resource_pack/assets/" in p:
        return 100
    if p.startswith("assets/"):
        return 50
    return 0


def namespace_from_asset_path(path: str) -> str:
    p = path.replace("\\", "/")
    m = re.search(r"(?:^|/)assets/([^/]+)/", p)
    return m.group(1) if m else ""


def model_stem_candidates(path: Path) -> Iterable[str]:
    stem = path.stem
    yield stem
    # converter often emits name.hash.json or name.gmdl_xxx.json
    if "." in stem:
        yield stem.split(".", 1)[0]
    m = re.match(r"(.+?)\.gmdl_[a-f0-9]+$", stem)
    if m:
        yield m.group(1)
    # Some files are gmdl hashes only; cannot infer original name.


def count_java_elements(data: Any) -> int:
    if isinstance(data, dict) and isinstance(data.get("elements"), list):
        return len(data["elements"])
    return 0


def count_bedrock_cubes(data: Any) -> int:
    if not isinstance(data, dict):
        return 0
    total = 0
    for geo in data.get("minecraft:geometry", []) or []:
        for bone in geo.get("bones", []) or []:
            total += len(bone.get("cubes") or [])
            total += len(bone.get("texture_meshes") or [])
    return total


def iter_zip_json(zip_path: Path):
    with zipfile.ZipFile(zip_path, "r") as zf:
        for name in zf.namelist():
            if not name.endswith(".json"):
                continue
            try:
                data = json.loads(zf.read(name).decode("utf-8"))
            except Exception:
                continue
            yield name, data


def collect_source_models_from_zip(zip_path: Path) -> Dict[str, List[Dict[str, Any]]]:
    index: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    if not zip_path.exists():
        return index
    try:
        for name, data in iter_zip_json(zip_path):
            p = name.replace("\\", "/")
            if "/models/" not in p or "/assets/" not in p:
                continue
            if not isinstance(data, dict):
                continue
            tex_size = data.get("texture_size")
            if not (isinstance(tex_size, list) and len(tex_size) == 2):
                continue
            try:
                width, height = int(tex_size[0]), int(tex_size[1])
            except Exception:
                continue
            textures = data.get("textures") or {}
            animated = any(re.search(r"animated|animation|frame|_0[0-9]", str(v), re.I) for v in textures.values())
            stem = Path(p).stem
            index[stem].append({
                "path": p,
                "namespace": namespace_from_asset_path(p),
                "priority": source_priority(p),
                "texture_size": [width, height],
                "elements": count_java_elements(data),
                "animated": animated,
            })
    except Exception as exc:
        print(f"[POST] could not read source zip {zip_path}: {exc}")
    for values in index.values():
        values.sort(key=lambda x: (x["priority"], x["elements"]), reverse=True)
    return index


def collect_source_models_from_dir(root: Path) -> Dict[str, List[Dict[str, Any]]]:
    index: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    if not root.exists():
        return index
    for model_file in sorted(root.glob("**/assets/*/models/**/*.json")):
        data = load_json(model_file)
        if not isinstance(data, dict):
            continue
        tex_size = data.get("texture_size")
        if not (isinstance(tex_size, list) and len(tex_size) == 2):
            continue
        try:
            width, height = int(tex_size[0]), int(tex_size[1])
        except Exception:
            continue
        p = str(model_file).replace("\\", "/")
        textures = data.get("textures") or {}
        animated = any(re.search(r"animated|animation|frame|_0[0-9]", str(v), re.I) for v in textures.values())
        index[model_file.stem].append({
            "path": p,
            "namespace": namespace_from_asset_path(p),
            "priority": source_priority(p),
            "texture_size": [width, height],
            "elements": count_java_elements(data),
            "animated": animated,
        })
    for values in index.values():
        values.sort(key=lambda x: (x["priority"], x["elements"]), reverse=True)
    return index


def merge_model_indices(*indices: Dict[str, List[Dict[str, Any]]]) -> Dict[str, List[Dict[str, Any]]]:
    merged: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for idx in indices:
        for stem, values in idx.items():
            merged[stem].extend(values)
    for values in merged.values():
        values.sort(key=lambda x: (x["priority"], x["elements"]), reverse=True)
    return merged


def choose_source_model(stems: Iterable[str], bedrock_data: Any, source_models: Dict[str, List[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    cube_count = count_bedrock_cubes(bedrock_data)
    candidates: List[Dict[str, Any]] = []
    for stem in stems:
        candidates.extend(source_models.get(stem, []))
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c.get("priority", 0), -abs((c.get("elements") or 0) - cube_count)), reverse=True)
    return candidates[0]


def fix_geometry_texture_sizes(rp_dir: Path, source_models: Dict[str, List[Dict[str, Any]]]) -> Tuple[int, List[str]]:
    models_dir = rp_dir / "models" / "blocks"
    changed = 0
    animated: List[str] = []
    if not models_dir.exists():
        return changed, animated
    for model_file in sorted(models_dir.rglob("*.json")):
        data = load_json(model_file)
        if not isinstance(data, dict) or "minecraft:geometry" not in data:
            continue
        chosen = choose_source_model(model_stem_candidates(model_file), data, source_models)
        if not chosen:
            continue
        width, height = chosen["texture_size"]
        did = False
        for geo in data.get("minecraft:geometry", []) or []:
            desc = geo.setdefault("description", {})
            if desc.get("texture_width") != width or desc.get("texture_height") != height:
                desc["texture_width"] = width
                desc["texture_height"] = height
                did = True
        if did:
            write_json(model_file, data)
            changed += 1
        if chosen.get("animated"):
            try:
                rel = model_file.relative_to(rp_dir)
            except Exception:
                rel = model_file
            animated.append(f"{rel} <= {chosen['path']}")
    return changed, animated


def infer_slot(item_name: str) -> Optional[str]:
    n = norm(item_name)
    for key in sorted(SLOTS, key=len, reverse=True):
        if n.endswith(key) or f"_{key}_" in n or f"_{key}" in n:
            return key
    # Compact EliteCreatures-style names: ecrubychest_black, ecbluemechhelmet
    for key in ["helmet", "chest", "legs", "boots"]:
        if key in n:
            return key
    return None


def strip_slot_and_color(item_name: str, slot: str) -> str:
    n = norm(item_name)
    for color in sorted(COLORS, key=len, reverse=True):
        suffix = "_" + color
        if n.endswith(suffix):
            n = n[:-len(suffix)]
            break
    aliases = {
        "helmet": ["helmet", "helm"],
        "helm": ["helmet", "helm"],
        "chestplate": ["chestplate", "chest"],
        "chest": ["chestplate", "chest"],
        "leggings": ["leggings", "leggins", "legs"],
        "legs": ["leggings", "leggins", "legs"],
        "leggins": ["leggings", "leggins", "legs"],
        "boots": ["boots", "boot"],
        "boot": ["boots", "boot"],
    }
    for alias in aliases.get(slot, [slot]):
        n = n.replace("_" + alias, "_")
        n = n.replace(alias + "_", "")
        if n.endswith(alias):
            n = n[:-len(alias)]
    return norm(n)


def collect_equipment_textures_from_zip(zip_path: Path) -> Dict[str, Dict[str, str]]:
    out: Dict[str, Dict[str, str]] = {}
    if not zip_path.exists():
        return out
    try:
        for name, data in iter_zip_json(zip_path):
            p = name.replace("\\", "/")
            if not ("/equipment/" in p or "/models/equipment/" in p):
                continue
            if "/assets/" not in p or not isinstance(data, dict):
                continue
            ns = namespace_from_asset_path(p)
            eq_id = Path(p).stem
            layers = data.get("layers") or {}
            rec: Dict[str, str] = {}
            for bedrock_layer in ["humanoid", "humanoid_leggings"]:
                value = layers.get(bedrock_layer)
                texture = ""
                if isinstance(value, list) and value:
                    texture = value[0].get("texture", "") if isinstance(value[0], dict) else ""
                elif isinstance(value, dict):
                    texture = value.get("texture", "")
                if texture:
                    rec[bedrock_layer] = texture.split(":", 1)[-1]
            if rec:
                out[f"{ns}:{eq_id}"] = rec
    except Exception:
        pass
    return out


def collect_pngs_from_zip(zip_path: Path) -> List[Tuple[str, bytes]]:
    out: List[Tuple[str, bytes]] = []
    if not zip_path.exists():
        return out
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for name in zf.namelist():
                p = name.replace("\\", "/")
                if p.endswith(".png") and "/assets/" in p and "/textures/" in p:
                    try:
                        out.append((p, zf.read(name)))
                    except Exception:
                        pass
    except Exception:
        pass
    return out


def collect_pngs_from_dir(root: Path) -> List[Tuple[str, bytes]]:
    out: List[Tuple[str, bytes]] = []
    if not root.exists():
        return out
    for png in sorted(root.glob("**/assets/*/textures/**/*.png")):
        try:
            out.append((str(png).replace("\\", "/"), png.read_bytes()))
        except Exception:
            pass
    return out


def unique_pngs(*lists: List[Tuple[str, bytes]]) -> List[Tuple[str, bytes]]:
    seen = set()
    out: List[Tuple[str, bytes]] = []
    # Later priority first: contents resource_pack before root assets.
    all_items: List[Tuple[str, bytes]] = []
    for lst in lists:
        all_items.extend(lst)
    all_items.sort(key=lambda x: source_priority(x[0]), reverse=True)
    for path, data in all_items:
        key = path
        if key in seen:
            continue
        seen.add(key)
        out.append((path, data))
    return out


def score_armor_png(item_name: str, slot: str, png_path: str) -> int:
    p = png_path.lower().replace("\\", "/")
    stem = norm(Path(p).stem)
    item = norm(item_name)
    base = strip_slot_and_color(item, slot)
    expected_sub = SLOTS[slot][2]
    score = 0
    if "/entity/equipment/" in p:
        score += 500
    if expected_sub in p:
        score += 300
    if stem == base:
        score += 400
    if base and (stem.endswith(base) or base in stem or stem in base):
        score += 200
    # Preserve color when item has color suffix.
    for color in COLORS:
        if item.endswith("_" + color):
            if stem.endswith("_" + color) or ("_" + color) in stem:
                score += 180
            else:
                score -= 50
            break
    # Leggings should prefer humanoid_leggings over humanoid.
    if expected_sub == "humanoid_leggings" and "humanoid_leggings" not in p:
        score -= 250
    if expected_sub == "humanoid" and "humanoid_leggings" in p:
        score -= 250
    return score


def find_best_armor_png(item_name: str, slot: str, pngs: List[Tuple[str, bytes]]) -> Optional[Tuple[str, bytes]]:
    scored: List[Tuple[int, str, bytes]] = []
    for path, data in pngs:
        s = score_armor_png(item_name, slot, path)
        if s > 0:
            scored.append((s, path, data))
    if not scored:
        return None
    scored.sort(key=lambda x: (x[0], source_priority(x[1])), reverse=True)
    return scored[0][1], scored[0][2]


def get_attachable_identifier(data: Any) -> Optional[str]:
    try:
        return data["minecraft:attachable"]["description"]["identifier"].split(":", 1)[1]
    except Exception:
        return None


def write_player_attachable(path: Path, identifier: str, layer_name: str, slot: str) -> None:
    geometry, parent_setup, _ = SLOTS[slot]
    data = {
        "format_version": "1.10.0",
        "minecraft:attachable": {
            "description": {
                "identifier": f"geyser_custom:{identifier}.player",
                "item": {f"geyser_custom:{identifier}": "query.owner_identifier == 'minecraft:player'"},
                "materials": {
                    "default": "armor_leather",
                    "enchanted": "armor_leather_enchanted",
                },
                "textures": {
                    "default": f"textures/armor_layer/{layer_name}",
                    "enchanted": "textures/misc/enchanted_item_glint",
                },
                "geometry": {"default": geometry},
                "scripts": {"parent_setup": parent_setup},
                "render_controllers": ["controller.render.armor"],
            }
        },
    }
    write_json(path, data)


def fix_missing_armor_player_layers(rp_dir: Path, source_pngs: List[Tuple[str, bytes]]) -> int:
    attach_dir = rp_dir / "attachables"
    if not attach_dir.exists():
        return 0
    armor_layer_dir = rp_dir / "textures" / "armor_layer"
    armor_layer_dir.mkdir(parents=True, exist_ok=True)
    fixed = 0

    for attach_file in sorted(attach_dir.rglob("*.attachable.json")):
        if attach_file.name.endswith(".player.json"):
            continue
        if attach_file.with_name(attach_file.name.replace(".attachable.json", ".attachable.player.json")).exists():
            continue
        if attach_file.with_suffix(".player.json").exists():
            continue

        # Name format is normally modelname.hash.attachable.json.
        item_name = attach_file.name.split(".", 1)[0]
        slot = infer_slot(item_name)
        if not slot:
            continue
        data = load_json(attach_file)
        identifier = get_attachable_identifier(data)
        if not identifier:
            continue
        best = find_best_armor_png(item_name, slot, source_pngs)
        if not best:
            continue
        src_path, blob = best
        ns = namespace_from_asset_path(src_path) or "itemsadder"
        layer_name = norm(f"{ns}_{Path(src_path).stem}")
        layer_path = armor_layer_dir / f"{layer_name}.png"
        if not layer_path.exists():
            layer_path.write_bytes(blob)

        player_path = attach_file.with_name(attach_file.name.replace(".attachable.json", ".attachable.player.json"))
        write_player_attachable(player_path, identifier, layer_name, slot)
        fixed += 1
    return fixed


def resolve_existing_path(path_arg: str) -> Optional[Path]:
    raw = Path(path_arg)
    candidates = [raw, Path("..") / raw, Path.cwd() / raw, Path.cwd().parent / raw]
    for p in candidates:
        if p.exists():
            return p.resolve()
    return None


def main(argv: List[str]) -> None:
    source_arg = argv[1] if len(argv) > 1 else ""
    rp_arg = argv[2] if len(argv) > 2 else "./target/rp"
    rp_dir = Path(rp_arg)
    if not rp_dir.exists():
        print(f"[POST] target rp dir not found: {rp_dir}")
        return

    source_zip = resolve_existing_path(source_arg) if source_arg else None
    dir_candidates = [Path("."), Path(".."), Path("pack"), Path("../pack")]

    source_indices: List[Dict[str, List[Dict[str, Any]]]] = []
    source_png_lists: List[List[Tuple[str, bytes]]] = []
    if source_zip and source_zip.is_file():
        source_indices.append(collect_source_models_from_zip(source_zip))
        source_png_lists.append(collect_pngs_from_zip(source_zip))
    for d in dir_candidates:
        if d.exists():
            source_indices.append(collect_source_models_from_dir(d))
            source_png_lists.append(collect_pngs_from_dir(d))

    source_models = merge_model_indices(*source_indices)
    source_pngs = unique_pngs(*source_png_lists)
    print(f"[POST] source models indexed: {len(source_models)}; source PNGs indexed: {len(source_pngs)}")

    geo_fixed, animated = fix_geometry_texture_sizes(rp_dir, source_models)
    armor_fixed = fix_missing_armor_player_layers(rp_dir, source_pngs)

    report = rp_dir.parent / "itemsadder_fix_report.txt"
    report.write_text(
        "ItemsAdder/Geyser postprocess report\n"
        f"geometry_texture_size_fixed={geo_fixed}\n"
        f"armor_player_attachables_fixed={armor_fixed}\n"
        f"animated_model_candidates={len(animated)}\n"
        + ("\nAnimated candidates:\n" + "\n".join(animated[:500]) + "\n" if animated else ""),
        encoding="utf-8",
    )

    print(f"[POST] geometry texture size fixed: {geo_fixed}")
    print(f"[POST] missing armor .player attachables fixed: {armor_fixed}")
    print(f"[POST] animated model candidates reported: {len(animated)}")
    print(f"[POST] report: {report}")


if __name__ == "__main__":
    main(sys.argv)
