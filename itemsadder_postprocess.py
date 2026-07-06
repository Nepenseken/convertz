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
    if p.startswith("contents/") and ("/resource_pack/assets/" in p or "/resourcepack/assets/" in p):
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

    search_dirs = []
    if (root / "assets").exists():
        search_dirs.append(root / "assets")
    if (root / "contents").exists():
        search_dirs.append(root / "contents")
    if (root / "pack" / "assets").exists():
        search_dirs.append(root / "pack" / "assets")

    for s_dir in search_dirs:
        for model_file in sorted(s_dir.rglob("*.json")):
            ps = str(model_file).replace("\\", "/")
            if "/models/" not in ps:
                continue
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
    # Disabled to prevent overwriting geometry texture size of 16x16 with Java texture size.
    # Standard Bedrock 3D custom items use 16x16 geometry width/height for UV precision.
    return 0, []


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


def collect_pngs_from_zip(zip_path: Path) -> List[Tuple[str, Any]]:
    out: List[Tuple[str, Any]] = []
    if not zip_path.exists():
        return out
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for name in zf.namelist():
                p = name.replace("\\", "/")
                if p.endswith(".png") and "/assets/" in p and "/textures/" in p:
                    out.append((p, (zip_path, name)))
    except Exception:
        pass
    return out


def collect_pngs_from_dir(root: Path) -> List[Tuple[str, Any]]:
    out: List[Tuple[str, Any]] = []
    if not root.exists():
        return out

    search_dirs = []
    if (root / "assets").exists():
        search_dirs.append(root / "assets")
    if (root / "contents").exists():
        search_dirs.append(root / "contents")
    if (root / "pack" / "assets").exists():
        search_dirs.append(root / "pack" / "assets")

    for s_dir in search_dirs:
        for png in s_dir.rglob("*.png"):
            ps = str(png).replace("\\", "/")
            if "/textures/" in ps:
                out.append((ps, png))
    return out


def unique_pngs(*lists: List[Tuple[str, Any]]) -> List[Tuple[str, Any]]:
    seen = set()
    out: List[Tuple[str, Any]] = []
    # Later priority first: contents resource_pack before root assets.
    all_items: List[Tuple[str, Any]] = []
    for lst in lists:
        all_items.extend(lst)
    all_items.sort(key=lambda x: source_priority(x[0]), reverse=True)
    for path, source_info in all_items:
        key = path
        if key in seen:
            continue
        seen.add(key)
        out.append((path, source_info))
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


def find_best_armor_png(item_name: str, slot: str, pngs: List[Tuple[str, Any]]) -> Optional[Tuple[str, Any]]:
    scored: List[Tuple[int, str, Any]] = []
    for path, source_info in pngs:
        s = score_armor_png(item_name, slot, path)
        if s > 0:
            scored.append((s, path, source_info))
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


def fix_missing_armor_player_layers(rp_dir: Path, source_pngs: List[Tuple[str, Any]]) -> int:
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
            if isinstance(blob, Path):
                png_bytes = blob.read_bytes()
            else:
                zpath, member = blob
                with zipfile.ZipFile(zpath, "r") as zf:
                    png_bytes = zf.read(member)
            layer_path.write_bytes(png_bytes)

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


def deduplicate_mappings(target_dir: Path) -> int:
    """Remove duplicate entries from geyser_mappings.json in target_dir.

    Returns the number of duplicates removed.
    """
    mappings_path = target_dir / "geyser_mappings.json"
    if not mappings_path.exists():
        return 0
    try:
        data = json.loads(mappings_path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    items = data.get("items", {})
    total_dupes = 0
    for java_item in list(items):
        entries = items[java_item]
        seen: set = set()
        unique: list = []
        for entry in entries:
            key = json.dumps(entry, sort_keys=True)
            if key not in seen:
                seen.add(key)
                unique.append(entry)
            else:
                total_dupes += 1
        items[java_item] = unique
    if total_dupes > 0:
        write_json(mappings_path, data)
    return total_dupes


def convert_pngs_to_rgba(rp_dir: Path) -> int:
    return 0


def fix_animated_texture_geometries(rp_dir: Path) -> int:
    try:
        from PIL import Image
    except ImportError:
        print("[POST] PIL/Pillow not installed, skipping animated texture aspect ratio fix")
        return 0

    geom_to_tex = {}
    attachables_dir = rp_dir / "attachables"
    if attachables_dir.exists():
        for filepath in attachables_dir.rglob("*.json"):
            try:
                data = json.loads(filepath.read_text(encoding="utf-8"))
                desc = data.get("minecraft:attachable", {}).get("description", {})
                geom_id = desc.get("geometry", {}).get("default")
                tex_path = desc.get("textures", {}).get("default")
                if geom_id and tex_path:
                    geom_to_tex[geom_id.lower()] = tex_path
            except Exception:
                pass

    models_dir = rp_dir / "models" / "blocks"
    updated_count = 0
    if models_dir.exists():
        for filepath in list(models_dir.rglob("*.json")):
            try:
                data = json.loads(filepath.read_text(encoding="utf-8"))
                geoms = data.get("minecraft:geometry", [])
                modified = False
                for g in geoms:
                    ident = g.get("description", {}).get("identifier")
                    if not ident:
                        continue
                    tex_path = geom_to_tex.get(ident.lower())
                    if not tex_path:
                        continue
                    png_path = rp_dir / f"{tex_path}.png"
                    if png_path.exists():
                        try:
                            with Image.open(png_path) as img:
                                w, h = img.size
                            if h > w:
                                ratio = h / w
                                g["description"]["texture_width"] = 16.0
                                g["description"]["texture_height"] = 16.0 * ratio
                                modified = True
                                updated_count += 1
                        except Exception as img_err:
                            print(f"[POST] Error opening image {png_path}: {img_err}")
                if modified:
                    write_json(filepath, data)
            except Exception:
                pass
    return updated_count



_java_textures_cache = {}

def resolve_java_textures(model_path: Path, workspace_root: Path) -> Dict[str, str]:
    """Recursively resolves all texture definitions in a Java model JSON file,
    including parent models.
    """
    cache_key = (model_path, workspace_root)
    if cache_key in _java_textures_cache:
        return dict(_java_textures_cache[cache_key])

    textures = {}
    if not model_path.exists():
        return textures
    try:
        model_data = json.loads(model_path.read_text(encoding="utf-8"))
    except Exception:
        return textures

    parent = model_data.get("parent")
    if parent and isinstance(parent, str):
        if ":" in parent:
            p_ns, p_path = parent.split(":", 1)
        else:
            p_ns, p_path = "minecraft", parent
        parent_model_paths = [
            workspace_root / "assets" / p_ns / "models" / f"{p_path}.json",
            workspace_root / "pack" / "assets" / p_ns / "models" / f"{p_path}.json",
        ]
        parent_resolved = {}
        for p_model_path in parent_model_paths:
            if p_model_path.exists():
                parent_resolved = resolve_java_textures(p_model_path, workspace_root)
                break
        textures.update(parent_resolved)

    model_textures = model_data.get("textures", {})
    if isinstance(model_textures, dict):
        textures.update(model_textures)

    for _ in range(5):
        changed = False
        for key, val in list(textures.items()):
            if isinstance(val, str) and val.startswith("#"):
                ref_key = val[1:]
                if ref_key in textures:
                    textures[key] = textures[ref_key]
                    changed = True
        if not changed:
            break
    _java_textures_cache[cache_key] = textures
    return dict(textures)

def locate_texture_png(texture_ref: str, workspace_root: Path) -> Optional[Path]:
    if not isinstance(texture_ref, str) or texture_ref.startswith("#"):
        return None
    if ":" in texture_ref:
        ns, path = texture_ref.split(":", 1)
    else:
        ns, path = "minecraft", texture_ref
    candidates = [
        workspace_root / "assets" / ns / "textures" / f"{path}.png",
        workspace_root / "pack" / "assets" / ns / "textures" / f"{path}.png",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None

def find_matching_element(cube, java_elements):
    origin = cube.get("origin", [0, 0, 0])
    size = cube.get("size", [0, 0, 0])
    to_x = 8.0 - origin[0]
    from_x = to_x - size[0]
    from_y = origin[1]
    to_y = from_y + size[1]
    from_z = origin[2] + 8.0
    to_z = from_z + size[2]

    for elem in java_elements:
        e_from = elem.get("from", [0, 0, 0])
        e_to = elem.get("to", [0, 0, 0])
        if (abs(from_x - e_from[0]) < 0.02 and
            abs(to_x - e_to[0]) < 0.02 and
            abs(from_y - e_from[1]) < 0.02 and
            abs(to_y - e_to[1]) < 0.02 and
            abs(from_z - e_from[2]) < 0.02 and
            abs(to_z - e_to[2]) < 0.02):
            return elem
    return None

def get_original_uv(bedrock_face, java_face):
    if java_face and "uv" in java_face:
        return java_face["uv"]
    if bedrock_face and isinstance(bedrock_face, dict):
        uv = bedrock_face.get("uv", [0, 0])
        uv_size = bedrock_face.get("uv_size", [16, 16])
        return [uv[0], uv[1], uv[0] + uv_size[0], uv[1] + uv_size[1]]
    return [0, 0, 16, 16]

def get_uv_face(u0, v0, u1, v1, face_name, X_offset, Y_offset, W_tex, H_tex, total_width, max_height):
    u0_s = (u0 * W_tex / 16.0 + X_offset) * (16.0 / total_width)
    v0_s = (v0 * H_tex / 16.0 + Y_offset) * (16.0 / max_height)
    u1_s = (u1 * W_tex / 16.0 + X_offset) * (16.0 / total_width)
    v1_s = (v1 * H_tex / 16.0 + Y_offset) * (16.0 / max_height)

    x_sign = 1 if (u1_s - u0_s) >= 0 else -1
    y_sign = 1 if (v1_s - v0_s) >= 0 else -1

    if face_name in ("up", "down"):
        uv_u = u1_s - 0.016 * x_sign
        uv_v = v1_s - 0.016 * y_sign
        uv_w = (u0_s - u1_s) + 0.016 * x_sign
        uv_h = (v0_s - v1_s) + 0.016 * y_sign
    else:
        uv_u = u0_s + 0.016 * x_sign
        uv_v = v0_s + 0.016 * y_sign
        uv_w = (u1_s - u0_s) - 0.016 * x_sign
        uv_h = (v1_s - v0_s) - 0.016 * y_sign

    return [round(uv_u, 4), round(uv_v, 4)], [round(uv_w, 4), round(uv_h, 4)]

def parse_mcmeta_ticks(mcmeta_path: Path) -> int:
    try:
        data = json.loads(mcmeta_path.read_text(encoding="utf-8"))
        anim = data.get("animation", {})
        return anim.get("frametime", 1)
    except Exception:
        return 1

def find_atlas_tile_for_texture(texture_path: str, rp_dir: Path) -> Optional[str]:
    item_tex_path = rp_dir / "textures" / "item_texture.json"
    if item_tex_path.exists():
        try:
            data = json.loads(item_tex_path.read_text(encoding="utf-8"))
            for key, val in data.get("texture_data", {}).items():
                tex_val = val.get("textures")
                if isinstance(tex_val, str) and (tex_val == texture_path or tex_val.replace("\\", "/") == texture_path):
                    return key
                elif isinstance(tex_val, list):
                    for t in tex_val:
                        if t == texture_path or t.replace("\\", "/") == texture_path:
                            return key
        except Exception:
            pass

    terrain_tex_path = rp_dir / "textures" / "terrain_texture.json"
    if terrain_tex_path.exists():
        try:
            data = json.loads(terrain_tex_path.read_text(encoding="utf-8"))
            for key, val in data.get("texture_data", {}).items():
                tex_val = val.get("textures")
                if isinstance(tex_val, str) and (tex_val == texture_path or tex_val.replace("\\", "/") == texture_path):
                    return key
                elif isinstance(tex_val, list):
                    for t in tex_val:
                        if t == texture_path or t.replace("\\", "/") == texture_path:
                            return key
        except Exception:
            pass
    return None

import math

def rotate_point(x, y, z, origin, axis, angle_deg):
    ox, oy, oz = origin
    rad = math.radians(angle_deg)
    cos_a = math.cos(rad)
    sin_a = math.sin(rad)
    
    px = x - ox
    py = y - oy
    pz = z - oz
    
    if axis == 'x':
        ry = py * cos_a - pz * sin_a
        rz = py * sin_a + pz * cos_a
        rx = px
    elif axis == 'y':
        rx = px * cos_a + pz * sin_a
        rz = -px * sin_a + pz * cos_a
        ry = py
    elif axis == 'z':
        rx = px * cos_a - py * sin_a
        ry = px * sin_a + py * cos_a
        rz = pz
    else:
        rx, ry, rz = px, py, pz
        
    return rx + ox, ry + oy, rz + oz

def rotate_gui(x, y, z, rx, ry, rz):
    rad_x = math.radians(rx)
    rad_y = math.radians(ry)
    rad_z = math.radians(rz)
    
    cx, sx = math.cos(rad_x), math.sin(rad_x)
    cy, sy = math.cos(rad_y), math.sin(rad_y)
    cz, sz = math.cos(rad_z), math.sin(rad_z)
    
    x1 = x * cz - y * sz
    y1 = x * sz + y * cz
    z1 = z
    
    x2 = x1 * cy + z1 * sy
    y2 = y1
    z2 = -x1 * sy + z1 * cy
    
    x3 = x2
    y3 = y2 * cx - z2 * sx
    z3 = y2 * sx + z2 * cx
    
    return x3, y3, z3

def solve_affine(p0, p1, p3, w, h):
    x0, y0 = p0
    x1, y1 = p1
    x3, y3 = p3
    
    det = x0*(y1 - y3) - y0*(x1 - x3) + (x1*y3 - x3*y1)
    if abs(det) < 1e-6:
        return None
        
    a = w * (y3 - y0) / det
    b = w * (x0 - x3) / det
    c = w * (x3*y0 - x0*y3) / det
    d = h * (y0 - y1) / det
    e = h * (x1 - x0) / det
    f = h * (x0*y1 - x1*y0) / det
    
    return (a, b, c, d, e, f)

def locate_model_json(ref, workspace_root):
    ns, path = ref.split(":", 1) if ":" in ref else ("minecraft", ref)
    cand1 = Path(workspace_root) / "assets" / ns / "models" / f"{path}.json"
    if cand1.exists():
        return cand1
    for rp_name in ["resource_pack", "resourcepack"]:
        cand2 = Path(workspace_root) / "contents" / ns / rp_name / "assets" / ns / "models" / f"{path}.json"
        if cand2.exists():
            return cand2
    cands = list(Path(workspace_root).glob(f"**/models/{path}.json"))
    if cands:
        return cands[0]
    return None

def resolve_display_settings(model_path, workspace_root):
    try:
        with open(model_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        display = data.get("display", {})
        if "gui" in display:
            return display["gui"]
        
        parent = data.get("parent")
        if parent:
            parent_path = locate_model_json(parent, workspace_root)
            if parent_path and parent_path.exists():
                return resolve_display_settings(parent_path, workspace_root)
    except Exception:
        pass
    return None

def render_3d_icon(java_model_path: Path, workspace_root: Path, output_path: Path) -> bool:
    from PIL import Image
    try:
        with open(java_model_path, "r", encoding="utf-8") as f:
            model = json.load(f)
    except Exception as e:
        print(f"[POST] Error loading model for rendering: {e}")
        return False
        
    gui_settings = resolve_display_settings(java_model_path, workspace_root) or {}
    
    rx, ry, rz = gui_settings.get("rotation", [-90, -135, -90])
    tx, ty, tz = gui_settings.get("translation", [-1.5, 1, -1.5])
    sx, sy, sz = gui_settings.get("scale", [0.45, 0.45, 0.45])
    
    resolved_textures = resolve_java_textures(java_model_path, workspace_root)
    texture_paths = {}
    for tex_key, tex_val in resolved_textures.items():
        png_path = locate_texture_png(tex_val, workspace_root)
        if png_path and png_path.exists():
            try:
                texture_paths[tex_key] = Image.open(png_path).convert("RGBA")
            except Exception:
                pass
                
    elements = model.get("elements", [])
    if not elements:
        return False
        
    faces_to_render = []
    
    for el in elements:
        fx1, fy1, fz1 = el.get("from", [0, 0, 0])
        fx2, fy2, fz2 = el.get("to", [16, 16, 16])
        
        x1, x2 = min(fx1, fx2), max(fx1, fx2)
        y1, y2 = min(fy1, fy2), max(fy1, fy2)
        z1, z2 = min(fz1, fz2), max(fz1, fz2)
        
        local_vertices = [
            (x1, y1, z1), (x2, y1, z1), (x2, y2, z1), (x1, y2, z1),
            (x1, y1, z2), (x2, y1, z2), (x2, y2, z2), (x1, y2, z2)
        ]
        
        rot = el.get("rotation")
        if rot:
            angle = rot.get("angle", 0)
            axis = rot.get("axis", "y")
            origin = rot.get("origin", [8, 8, 8])
            for i, (vx, vy, vz) in enumerate(local_vertices):
                local_vertices[i] = rotate_point(vx, vy, vz, origin, axis, angle)
                
        faces_def = {
            "north": {"indices": [3, 2, 1, 0]},
            "south": {"indices": [6, 7, 4, 5]},
            "west":  {"indices": [7, 3, 0, 4]},
            "east":  {"indices": [2, 6, 5, 1]},
            "up":    {"indices": [3, 2, 6, 7]},
            "down":  {"indices": [4, 5, 1, 0]},
        }
        
        for face_name, face_info in faces_def.items():
            face_el = el.get("faces", {}).get(face_name)
            if not face_el:
                continue
                
            tex_key = face_el.get("texture", "").replace("#", "")
            tex_img = texture_paths.get(tex_key)
            if not tex_img:
                continue
                
            uv = face_el.get("uv", [0, 0, 16, 16])
            u1, v1, u2, v2 = uv
            
            tw, th = tex_img.size
            left = min(u1, u2) / 16.0 * tw
            right = max(u1, u2) / 16.0 * tw
            top = min(v1, v2) / 16.0 * th
            bottom = max(v1, v2) / 16.0 * th
            
            if left >= right or top >= bottom:
                continue
                
            face_tex = tex_img.crop((left, top, right, bottom))
            
            if face_el.get("rotation"):
                rot_ang = face_el.get("rotation")
                face_tex = face_tex.rotate(-rot_ang, expand=True)
                
            v_indices = face_info["indices"]
            f_v = [local_vertices[idx] for idx in v_indices]
            
            transformed_vertices = []
            for (vx, vy, vz) in f_v:
                vx_s = (vx - 8.0) * sx
                vy_s = (vy - 8.0) * sy
                vz_s = (vz - 8.0) * sz
                
                vx_r, vy_r, vz_r = rotate_gui(vx_s, vy_s, vz_s, rx, ry, rz)
                
                vx_t = vx_r + tx + 8.0
                vy_t = vy_r + ty + 8.0
                vz_t = vz_r + tz + 8.0
                
                transformed_vertices.append((vx_t, vy_t, vz_t))
                
            pts_2d = []
            for (vx, vy, vz) in transformed_vertices:
                sc_x = 128 + (vx - 8.0) * 12
                sc_y = 128 - (vy - 8.0) * 12
                pts_2d.append((sc_x, sc_y))
                
            avg_z = sum(v[2] for v in transformed_vertices) / 4.0
            
            faces_to_render.append({
                "depth": avg_z,
                "pts_2d": pts_2d,
                "texture": face_tex
            })
            
    if not faces_to_render:
        return False
        
    faces_to_render.sort(key=lambda x: x["depth"])
    
    canvas = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    for face in faces_to_render:
        pts = face["pts_2d"]
        tex = face["texture"]
        tw, th = tex.size
        
        p0 = pts[0]
        p1 = pts[1]
        p3 = pts[3]
        
        coeffs = solve_affine(p0, p1, p3, tw, th)
        if not coeffs:
            continue
            
        warped = tex.transform((256, 256), Image.AFFINE, coeffs, Image.BILINEAR)
        canvas.alpha_composite(warped)
        
    bbox = canvas.getbbox()
    if bbox:
        cropped = canvas.crop(bbox)
        cw, ch = cropped.size
        scale = min(220 / cw, 220 / ch)
        nw = int(cw * scale)
        nh = int(ch * scale)
        if nw > 0 and nh > 0:
            resized = cropped.resize((nw, nh), Image.Resampling.LANCZOS)
            final_canvas = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
            final_canvas.paste(resized, ((256 - nw) // 2, (256 - nh) // 2))
            canvas = final_canvas
            
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, "PNG")
    return True

_image_cache = {}

def fix_3d_items_textures_and_geometry(rp_dir: Path, workspace_root: Path) -> int:
    from PIL import Image
    config_path = workspace_root / "config.json"
    if not config_path.exists():
        print("[POST] config.json not found; skipping 3D items fix")
        return 0

    try:
        config_data = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[POST] Error loading config.json: {e}")
        return 0

    model_paths_map = {}
    for entry in config_data.values():
        geom = entry.get("geometry")
        path = entry.get("path")
        if geom and path:
            model_paths_map[f"geometry.geyser_custom.{geom}".lower()] = Path(path)

    geometry_file_map = {}
    for json_file in rp_dir.rglob("models/blocks/**/*.json"):
        try:
            geom_data = json.loads(json_file.read_text(encoding="utf-8"))
            geoms = geom_data.get("minecraft:geometry", [])
            for g in geoms:
                ident = g.get("description", {}).get("identifier")
                if ident:
                    geometry_file_map[ident.lower()] = json_file
        except Exception:
            pass

    fixed_count = 0
    for entry in config_data.values():
        if entry.get("generated") is not False:
            continue

        geom_name = entry.get("geometry")
        if not geom_name:
            continue

        geom_id = f"geometry.geyser_custom.{geom_name}".lower()
        if geom_id not in geometry_file_map:
            continue

        geom_file = geometry_file_map[geom_id]
        java_model_rel = model_paths_map.get(geom_id)
        if not java_model_rel:
            continue
        java_model_path = workspace_root / java_model_rel
        if not java_model_path.exists():
            continue

        try:
            java_model_data = json.loads(java_model_path.read_text(encoding="utf-8"))
            java_elements = java_model_data.get("elements", [])
        except Exception:
            continue

        if not java_elements:
            continue

        resolved_textures = resolve_java_textures(java_model_path, workspace_root)
        unique_texture_refs = []
        for elem in java_elements:
            faces = elem.get("faces", {})
            for face_name, face_data in faces.items():
                tex_var = face_data.get("texture", "")
                if tex_var.startswith("#"):
                    real_ref = resolved_textures.get(tex_var[1:])
                    if real_ref and real_ref not in unique_texture_refs:
                        unique_texture_refs.append(real_ref)
                elif tex_var and tex_var not in unique_texture_refs:
                    unique_texture_refs.append(tex_var)

        if not unique_texture_refs:
            continue

        texture_pngs = []
        png_paths = []
        for ref in unique_texture_refs:
            png_path = locate_texture_png(ref, workspace_root)
            if png_path:
                texture_pngs.append(png_path)
                png_paths.append(ref)

        if not texture_pngs:
            continue

        images = []
        valid_png_paths = []
        for ref, p in zip(png_paths, texture_pngs):
            try:
                if p not in _image_cache:
                    with Image.open(p) as img:
                        _image_cache[p] = img.convert("RGBA")
                images.append(_image_cache[p].copy())
                valid_png_paths.append(ref)
            except Exception as e:
                print(f"[POST] Failed to load texture {p.name}: {e}")

        if not images:
            continue

        widths = [img.size[0] for img in images]
        heights = [img.size[1] for img in images]
        total_width = sum(widths)
        max_height = max(heights)

        stitched_img = Image.new("RGBA", (total_width, max_height))
        x_offset = 0
        offsets = {}
        for ref, img in zip(valid_png_paths, images):
            stitched_img.paste(img, (x_offset, 0))
            offsets[ref] = (x_offset, 0, img.size[0], img.size[1])
            x_offset += img.size[0]

        ns = entry.get("namespace", "minecraft")
        model_path = entry.get("model_path", "")
        model_name = entry.get("model_name", "")

        target_texture_path = rp_dir / "textures" / ns / model_path / f"{model_name}.png"
        target_texture_path.parent.mkdir(parents=True, exist_ok=True)
        stitched_img.save(target_texture_path, "PNG")

        # Generate 3D isometric inventory icon
        icon_texture_path = rp_dir / "textures" / ns / model_path / f"{model_name}_icon.png"
        try:
            if render_3d_icon(java_model_path, workspace_root, icon_texture_path):
                # Update item_texture.json
                item_tex_path = rp_dir / "textures" / "item_texture.json"
                if item_tex_path.exists():
                    item_tex = json.loads(item_tex_path.read_text(encoding="utf-8"))
                    path_hash = entry.get("path_hash")
                    if path_hash and "texture_data" in item_tex:
                        if path_hash in item_tex["texture_data"]:
                            item_tex["texture_data"][path_hash]["textures"] = f"textures/{ns}/{model_path}/{model_name}_icon".replace("//", "/")
                            write_json(item_tex_path, item_tex)
        except Exception as e:
            print(f"[POST] Failed to generate 3D icon for {model_name}: {e}")

        try:
            geom_data = json.loads(geom_file.read_text(encoding="utf-8"))
            geoms = geom_data.get("minecraft:geometry", [])
            for g in geoms:
                if g.get("description", {}).get("identifier", "").lower() != geom_id:
                    continue
                g["description"]["texture_width"] = 16.0
                g["description"]["texture_height"] = 16.0

                bones = g.get("bones", [])
                for bone in bones:
                    cubes = bone.get("cubes", [])
                    for cube in cubes:
                        match_elem = find_matching_element(cube, java_elements)
                        if not match_elem:
                            continue

                        cube_uvs = cube.get("uv", {})
                        if not isinstance(cube_uvs, dict):
                            continue

                        java_faces = match_elem.get("faces", {})
                        for face_name, bedrock_face in list(cube_uvs.items()):
                            java_face = java_faces.get(face_name)
                            tex_var = ""
                            if java_face:
                                tex_var = java_face.get("texture", "")
                            if not tex_var and bedrock_face:
                                for f in java_faces.values():
                                    if f.get("texture"):
                                        tex_var = f.get("texture")
                                        break
                            real_ref = ""
                            if tex_var.startswith("#"):
                                real_ref = resolved_textures.get(tex_var[1:], "")
                            elif tex_var:
                                real_ref = tex_var

                            if real_ref not in offsets:
                                if valid_png_paths:
                                    real_ref = valid_png_paths[0]
                                else:
                                    continue

                            X_off, Y_off, W_tex, H_tex = offsets[real_ref]
                            u0, v0, u1, v1 = get_original_uv(bedrock_face, java_face)
                            uv_pos, uv_size = get_uv_face(u0, v0, u1, v1, face_name, X_off, Y_off, W_tex, H_tex, total_width, max_height)
                            cube_uvs[face_name] = {
                                "uv": uv_pos,
                                "uv_size": uv_size
                            }
            write_json(geom_file, geom_data)
            fixed_count += 1
        except Exception as e:
            print(f"[POST] Failed to update geometry for {geom_id}: {e}")
    return fixed_count

def generate_flipbook_animations(rp_dir: Path, workspace_root: Path) -> int:
    flipbook_entries = []
    mcmeta_files = []
    for base_dir in [workspace_root / "assets", workspace_root / "pack" / "assets", workspace_root / "contents"]:
        if base_dir.exists():
            mcmeta_files.extend(list(base_dir.rglob("*.png.mcmeta")))

    seen_refs = set()
    for mcmeta_path in mcmeta_files:
        path_str = mcmeta_path.as_posix()
        if "/assets/" not in path_str:
            continue
        parts = mcmeta_path.parts
        try:
            idx = parts.index("assets")
            if parts[idx + 2] != "textures":
                continue
            ns = parts[idx + 1]
            subpath_parts = list(parts[idx + 3:-1])
            stem_name = mcmeta_path.stem
            if stem_name.endswith(".png"):
                stem_name = stem_name[:-4]
            subpath_parts.append(stem_name)
            subpath = "/".join(subpath_parts)
        except Exception:
            continue

        texture_ref = f"{ns}:{subpath}".replace("\\", "/")
        if texture_ref in seen_refs:
            continue
        seen_refs.add(texture_ref)

        target_tex_path = f"textures/{ns}/{subpath}".replace("\\", "/")
        target_png_file = rp_dir / f"{target_tex_path}.png"
        
        # If target file does not exist, copy the uncropped vertical strip PNG from source
        if not target_png_file.exists():
            src_png = mcmeta_path.parent / mcmeta_path.stem
            if src_png.exists():
                target_png_file.parent.mkdir(parents=True, exist_ok=True)
                import shutil
                shutil.copy2(src_png, target_png_file)

        if not target_png_file.exists():
            continue

        ticks = parse_mcmeta_ticks(mcmeta_path)
        atlas_tile = find_atlas_tile_for_texture(target_tex_path, rp_dir)

        entry = {
            "flipbook_texture": target_tex_path,
            "ticks_per_frame": ticks
        }
        if atlas_tile:
            entry["atlas_tile"] = atlas_tile
        flipbook_entries.append(entry)

    if flipbook_entries:
        flipbook_json_path = rp_dir / "textures" / "flipbook_textures.json"
        try:
            existing_data = []
            if flipbook_json_path.exists():
                try:
                    existing_data = json.loads(flipbook_json_path.read_text(encoding="utf-8"))
                    if not isinstance(existing_data, list):
                        existing_data = []
                except Exception:
                    pass
            merged = {e["flipbook_texture"]: e for e in existing_data + flipbook_entries}
            write_json(flipbook_json_path, list(merged.values()))
            return len(flipbook_entries)
        except Exception as e:
            print(f"[POST] Failed to write flipbook_textures.json: {e}")
    return 0


def consolidate_animations(rp_dir: Path) -> None:
    import os
    animations_dir = rp_dir / "animations"
    if not animations_dir.exists():
        return

    merged_animations = {}
    json_files_to_delete = []

    try:
        for json_path in list(animations_dir.rglob("*.json")):
            if json_path.name == "animations.json":
                try:
                    with open(json_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, dict) and "animations" in data:
                            merged_animations.update(data["animations"])
                except Exception:
                    pass
                json_files_to_delete.append(json_path)
                continue

            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and "animations" in data:
                    merged_animations.update(data["animations"])
                    json_files_to_delete.append(json_path)
            except Exception as e:
                print(f"[POST] Error reading animation file {json_path}: {e}")

        if merged_animations:
            target_file = animations_dir / "animations.json"
            animations_dir.mkdir(parents=True, exist_ok=True)
            output_data = {
                "format_version": "1.8.0",
                "animations": merged_animations
            }
            with open(target_file, "w", encoding="utf-8") as f:
                json.dump(output_data, f, indent=2)
            print(f"[POST] Consolidated {len(merged_animations)} animations into {target_file}")

            for p in json_files_to_delete:
                if p.exists() and p != target_file:
                    try:
                        p.unlink()
                    except Exception:
                        pass

            for root, dirs, files in os.walk(str(animations_dir), topdown=False):
                for d in dirs:
                    dir_path = Path(root) / d
                    try:
                        if not os.listdir(dir_path):
                            os.rmdir(dir_path)
                    except Exception:
                        pass
    except Exception as e:
        print(f"[POST] Error consolidating animations: {e}")


def main(argv: List[str]) -> None:
    source_arg = argv[1] if len(argv) > 1 else ""
    rp_arg = argv[2] if len(argv) > 2 else "./target/rp"
    rp_dir = Path(rp_arg)
    
    # Convert all textures to RGBA mode
    target_rp = Path("./target/rp")
    if len(argv) > 1 and Path(argv[1]).exists() and (Path(argv[1]) / "textures").exists():
        target_rp = Path(argv[1])
    rgba_converted = convert_pngs_to_rgba(target_rp)
    print(f"[POST] converted non-RGBA textures to RGBA: {rgba_converted}")

    if not rp_dir.exists():
        print(f"[POST] target rp dir not found: {rp_dir}")
        return

    source_zip = resolve_existing_path(source_arg) if source_arg else None
    dir_candidates = [Path("."), Path(".."), Path("pack"), Path("../pack")]

    source_indices: List[Dict[str, List[Dict[str, Any]]]] = []
    source_png_lists: List[List[Tuple[str, Any]]] = []
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
    anim_geoms_fixed = fix_animated_texture_geometries(rp_dir)

    # Deduplicate geyser_mappings.json (removes duplicates introduced by armor fix)
    mappings_dupes = deduplicate_mappings(rp_dir.parent)

    # Resolve workspace root (contains config.json and original unpacked assets)
    workspace_root = None
    for p in [rp_dir.parent.parent.parent, rp_dir.parent.parent, Path.cwd(), Path.cwd().parent]:
        if (p / "config.json").exists():
            workspace_root = p.resolve()
            break

    fixed_3d_items = 0
    flipbooks_generated = 0
    if workspace_root:
        fixed_3d_items = fix_3d_items_textures_and_geometry(rp_dir, workspace_root)
        flipbooks_generated = generate_flipbook_animations(rp_dir, workspace_root)
        consolidate_animations(rp_dir)
    else:
        print("[POST] Could not resolve workspace root (config.json not found); skipping 3D items fix and flipbook generation")

    report = rp_dir.parent / "itemsadder_fix_report.txt"
    report.write_text(
        "ItemsAdder/Geyser postprocess report\n"
        f"geometry_texture_size_fixed={geo_fixed}\n"
        f"armor_player_attachables_fixed={armor_fixed}\n"
        f"animated_model_candidates={len(animated)}\n"
        f"animated_texture_geometries_fixed={anim_geoms_fixed}\n"
        f"mappings_duplicates_removed={mappings_dupes}\n"
        f"fixed_3d_items_textures_and_geometry={fixed_3d_items}\n"
        f"flipbook_animations_generated={flipbooks_generated}\n"
        + ("\nAnimated candidates:\n" + "\n".join(animated[:500]) + "\n" if animated else ""),
        encoding="utf-8",
    )

    print(f"[POST] geometry texture size fixed: {geo_fixed}")
    print(f"[POST] missing armor .player attachables fixed: {armor_fixed}")
    print(f"[POST] animated weapon texture geometries fixed: {anim_geoms_fixed}")
    print(f"[POST] animated model candidates reported: {len(animated)}")
    print(f"[POST] fixed 3D item textures and geometries: {fixed_3d_items}")
    print(f"[POST] flipbook animations generated: {flipbooks_generated}")
    if mappings_dupes:
        print(f"[POST] mappings duplicates removed: {mappings_dupes}")
    print(f"[POST] report: {report}")


if __name__ == "__main__":
    main(sys.argv)

