#!/usr/bin/env python3
"""
Integrated ItemsAdder fix for Nepenseken/convertz.

Run after convertz has generated target/rp and before final mcpack zipping:
  python3 convertz_integrated_fix.py <original_java_pack.zip> ./target/rp

It fixes:
- Bedrock geometry texture_width/texture_height from Java texture_size.
- Missing armor .player attachables/layer textures.
- Reports animated 3D model candidates that cannot be safely auto-animated on Bedrock/Geyser.
"""
from __future__ import annotations

import argparse
import json
import re
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any

COLORS = {
    "black","blue","brown","cyan","gray","green","orange","pink","purple","red","teal","white","yellow",
    "darkblue","darkbrown","darkgreen","darkorange","darkpink","darkpurple","darkred","darkyellow",
    "lightblue","lightgray","lightgreen","lightpurple","lightred",
}
SLOT_DATA = {
    "helmet": ("geometry.player.armor.helmet", "variable.helmet_layer_visible = 0.0;", "humanoid"),
    "chestplate": ("geometry.player.armor.chestplate", "variable.chest_layer_visible = 0.0;", "humanoid"),
    "chest": ("geometry.player.armor.chestplate", "variable.chest_layer_visible = 0.0;", "humanoid"),
    "leggings": ("geometry.player.armor.leggings", "variable.leg_layer_visible = 0.0;", "humanoid_leggings"),
    "legs": ("geometry.player.armor.leggings", "variable.leg_layer_visible = 0.0;", "humanoid_leggings"),
    "boots": ("geometry.player.armor.boots", "variable.feet_layer_visible = 0.0;", "humanoid"),
}


def load_json_file(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_json_zip(zf: zipfile.ZipFile, name: str) -> Any | None:
    try:
        return json.loads(zf.read(name).decode("utf-8"))
    except Exception:
        return None


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def source_priority(path: str) -> int:
    p = path.replace("\\", "/")
    if p.startswith("contents/") and "/resource_pack/assets/" in p:
        return 100
    if p.startswith("assets/"):
        return 10
    return 0


def model_stem(path: str | Path) -> str:
    return Path(path).stem


def namespace_from_model_path(path: str) -> str:
    m = re.search(r"(?:^|/)assets/([^/]+)/models/", path.replace("\\", "/"))
    return m.group(1) if m else ""


def namespace_from_equipment_path(path: str) -> str:
    m = re.search(r"(?:^|/)assets/([^/]+)/(?:models/equipment|equipment)/", path.replace("\\", "/"))
    return m.group(1) if m else ""


def count_java_elements(data: Any) -> int:
    return len(data.get("elements") or []) if isinstance(data, dict) else 0


def count_bedrock_cubes(data: Any) -> int:
    total = 0
    if not isinstance(data, dict):
        return 0
    for geo in data.get("minecraft:geometry", []) or []:
        for bone in geo.get("bones", []) or []:
            total += len(bone.get("cubes") or [])
            total += len(bone.get("texture_meshes") or [])
    return total


def collect_source_models(source_zip: Path) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with zipfile.ZipFile(source_zip, "r") as zf:
        for name in zf.namelist():
            if not name.endswith(".json") or "/models/" not in name or "/assets/" not in name:
                continue
            data = load_json_zip(zf, name)
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
            animated = any(re.search(r"animation|animated|_0[0-9]|frame", str(v), re.I) for v in textures.values())
            index[model_stem(name)].append({
                "path": name,
                "namespace": namespace_from_model_path(name),
                "priority": source_priority(name),
                "texture_size": [width, height],
                "elements": count_java_elements(data),
                "animated": animated,
            })
    for candidates in index.values():
        candidates.sort(key=lambda c: (c["priority"], c["elements"]), reverse=True)
    return index


def choose_source_model(stem: str, bedrock_data: Any, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not candidates:
        return None
    cube_count = count_bedrock_cubes(bedrock_data)
    return sorted(candidates, key=lambda c: (c["priority"], -abs((c.get("elements") or 0) - cube_count)), reverse=True)[0]


def clean_bedrock_stem(stem: str) -> str:
    # Remove geyser hash suffix (e.g. .gmdl_ca5d6b7)
    stem = re.sub(r"\.gmdl_[0-9a-fA-F]+$", "", stem)
    return stem


def get_base_stems(stem: str) -> list[str]:
    stem = clean_bedrock_stem(stem)
    stems = [stem]
    stem_no_num = re.sub(r"_\d+$", "", stem)
    if stem_no_num != stem:
        stems.append(stem_no_num)
        
    extra = []
    for s in stems:
        for color in sorted(COLORS, key=len, reverse=True):
            suffix = "_" + color
            if s.endswith(suffix):
                base = s[:-len(suffix)]
                extra.append(base)
                base_no_num = re.sub(r"_\d+$", "", base)
                if base_no_num != base:
                    extra.append(base_no_num)
                    
    res = []
    for s in stems + extra:
        if s and s not in res:
            res.append(s)
    return res


def fix_geometry_texture_sizes(rp_dir: Path, source_models: dict[str, list[dict[str, Any]]]) -> tuple[int, list[str]]:
    changed = 0
    animated_hits: list[str] = []
    models_dir = rp_dir / "models" / "blocks"
    if not models_dir.exists():
        return 0, []
    for path in models_dir.rglob("*.json"):
        data = load_json_file(path)
        if not isinstance(data, dict) or "minecraft:geometry" not in data:
            continue
        stem = path.stem
        candidates = []
        for base_stem in get_base_stems(stem):
            if base_stem in source_models:
                candidates = source_models[base_stem]
                break
        chosen = choose_source_model(stem, data, candidates)
        if not chosen:
            continue
        width, height = chosen["texture_size"]
        did = False
        for geo in data.get("minecraft:geometry", []) or []:
            desc = geo.get("description") or {}
            if desc.get("texture_width") != width or desc.get("texture_height") != height:
                desc["texture_width"] = width
                desc["texture_height"] = height
                geo["description"] = desc
                did = True
        if did:
            write_json(path, data)
            changed += 1
        if chosen.get("animated"):
            animated_hits.append(f"{path.relative_to(rp_dir)} <= {chosen['path']}")
    return changed, animated_hits


def collect_equipment_textures(source_zip: Path) -> dict[str, dict[str, Any]]:
    equipment: dict[str, dict[str, Any]] = {}
    with zipfile.ZipFile(source_zip, "r") as zf:
        for name in zf.namelist():
            if not name.endswith(".json"):
                continue
            if not ("/models/equipment/" in name or "/equipment/" in name):
                continue
            data = load_json_zip(zf, name)
            if not isinstance(data, dict):
                continue
            layers = data.get("layers") or {}
            def first_texture(key: str) -> str:
                arr = layers.get(key) or []
                if isinstance(arr, list) and arr and isinstance(arr[0], dict):
                    tex = arr[0].get("texture", "")
                    return tex.split(":", 1)[1] if ":" in tex else tex
                return ""
            eq_id = Path(name).stem
            equipment[eq_id] = {
                "namespace": namespace_from_equipment_path(name),
                "humanoid": first_texture("humanoid") or eq_id,
                "humanoid_leggings": first_texture("humanoid_leggings") or first_texture("humanoid") or eq_id,
                "priority": source_priority(name),
            }
    return equipment


def detect_slot_and_base(item_name: str) -> tuple[str | None, str | None]:
    for slot in ["chestplate", "leggings", "helmet", "boots", "chest", "legs"]:
        if slot in item_name:
            return slot, item_name.replace(slot, "", 1).strip("_")
    return None, None


def color_split(name: str) -> tuple[str, str]:
    for color in sorted(COLORS, key=len, reverse=True):
        suffix = "_" + color
        if name.endswith(suffix):
            return name[:-len(suffix)], color
    return name, ""


def normalize_eq_core(eq_id: str) -> str:
    x = eq_id
    for prefix in ["roman_armor_", "medieval_armor_set_", "demonking_assortment_", "witchcaster_", "ec_"]:
        if x.startswith(prefix):
            x = x[len(prefix):]
    return x.replace("_armor", "").replace("armor", "").strip("_")


def choose_equipment(item_name: str, namespace: str, equipment: dict[str, dict[str, Any]]) -> str | None:
    slot, base = detect_slot_and_base(item_name)
    if not slot or not base:
        return None
    base_no_color, color = color_split(base)
    candidates: list[tuple[int, int, str]] = []
    for eq_id, info in equipment.items():
        if namespace and info.get("namespace") and info.get("namespace") != namespace:
            continue
        core = normalize_eq_core(eq_id)
        score = 0
        if color and eq_id.endswith("_" + color):
            score += 8
        if base == core or base_no_color == core:
            score += 10
        if core and (core in base or base_no_color in core):
            score += 5
        ec_guess = re.sub(r"(helmet|chest|legs|leggings|boots)", "armor", item_name, count=1)
        if eq_id == ec_guess:
            score += 30
        if score:
            candidates.append((score, int(info.get("priority", 0)), eq_id))
    return sorted(candidates, reverse=True)[0][2] if candidates else None


def find_source_png(source_zip: Path, namespace: str, texture_name: str, layer_sub: str) -> bytes | None:
    texture_name = texture_name.strip("/")
    with zipfile.ZipFile(source_zip, "r") as zf:
        candidates: list[tuple[int, str]] = []
        direct = [
            f"assets/{namespace}/textures/entity/equipment/{layer_sub}/{texture_name}.png",
            f"assets/{namespace}/textures/{texture_name}.png",
        ]
        names = set(zf.namelist())
        for d in direct:
            if d in names:
                candidates.append((source_priority(d), d))
        for name in names:
            if name.endswith(f"/assets/{namespace}/textures/entity/equipment/{layer_sub}/{texture_name}.png"):
                candidates.append((source_priority(name), name))
            elif name.endswith(f"/assets/{namespace}/textures/{texture_name}.png"):
                candidates.append((source_priority(name), name))
        if not candidates:
            return None
        return zf.read(sorted(candidates, reverse=True)[0][1])


def write_player_attachable(identifier_hash: str, layer_name: str, slot: str) -> dict[str, Any]:
    geometry, parent_setup, _layer_sub = SLOT_DATA[slot]
    return {
        "format_version": "1.10.0",
        "minecraft:attachable": {
            "description": {
                "identifier": f"geyser_custom:{identifier_hash}.player",
                "item": {f"geyser_custom:{identifier_hash}": "query.owner_identifier == 'minecraft:player'"},
                "materials": {"default": "armor_leather", "enchanted": "armor_leather_enchanted"},
                "textures": {"default": f"textures/armor_layer/{layer_name}", "enchanted": "textures/misc/enchanted_item_glint"},
                "geometry": {"default": geometry},
                "scripts": {"parent_setup": parent_setup},
                "render_controllers": ["controller.render.armor"],
            }
        },
    }


def fix_missing_player_armor(rp_dir: Path, source_zip: Path, equipment: dict[str, dict[str, Any]]) -> int:
    made = 0
    attachables_dir = rp_dir / "attachables"
    if not attachables_dir.exists():
        return 0
    for path in attachables_dir.rglob("*.attachable.json"):
        if path.name.endswith(".player.json"):
            continue
        m = re.match(r"(.+?)\.(gmdl_[0-9a-f]+)\.attachable\.json$", path.name)
        if not m:
            continue
        item_name, identifier_hash = m.group(1), m.group(2)
        slot, _base = detect_slot_and_base(item_name)
        if not slot:
            continue
        player_path = path.with_name(path.name.replace(".attachable.json", ".attachable.player.json"))
        alt_player_path = path.with_name(path.name.replace(".json", ".player.json"))
        if player_path.exists() or alt_player_path.exists():
            continue
        adata = load_json_file(path)
        desc = (((adata or {}).get("minecraft:attachable") or {}).get("description") or {})
        tex_default = ((desc.get("textures") or {}).get("default") or "")
        mt = re.match(r"textures/([^/]+)/", tex_default)
        namespace = mt.group(1) if mt else ""
        eq_id = choose_equipment(item_name, namespace, equipment)
        if not eq_id:
            continue
        info = equipment[eq_id]
        layer_sub = SLOT_DATA[slot][2]
        texture_ref = info.get(layer_sub) or info.get("humanoid") or eq_id
        tex_namespace = info.get("namespace") or namespace
        png = find_source_png(source_zip, tex_namespace, texture_ref, layer_sub)
        if not png and layer_sub == "humanoid_leggings":
            png = find_source_png(source_zip, tex_namespace, texture_ref, "humanoid")
        if not png:
            continue
        layer_name = f"{tex_namespace}_{eq_id}"
        layer_path = rp_dir / "textures" / "armor_layer" / f"{layer_name}.png"
        layer_path.parent.mkdir(parents=True, exist_ok=True)
        layer_path.write_bytes(png)
        write_json(player_path, write_player_attachable(identifier_hash, layer_name, slot))
        made += 1
    return made


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_zip", type=Path, help="Original Java/ItemsAdder resource pack zip")
    parser.add_argument("rp_dir", type=Path, help="convertz target/rp directory")
    args = parser.parse_args()
    if not args.source_zip.exists():
        print(f"[convertz-fix] source zip not found: {args.source_zip}")
        return 0
    if not args.rp_dir.exists():
        print(f"[convertz-fix] target rp dir not found: {args.rp_dir}")
        return 0
    source_models = collect_source_models(args.source_zip)
    size_fixed, animated_hits = fix_geometry_texture_sizes(args.rp_dir, source_models)
    equipment = collect_equipment_textures(args.source_zip)
    player_fixed = fix_missing_player_armor(args.rp_dir, args.source_zip, equipment)
    report = args.rp_dir.parent / "convertz_integrated_fix_report.txt"
    report.write_text(
        "geometry_texture_size_fixed=%s\nplayer_armor_attachables_generated=%s\nanimated_model_candidates=%s\n%s\n" % (
            size_fixed, player_fixed, len(animated_hits), "\n".join(animated_hits[:500])
        ),
        encoding="utf-8",
    )
    print(f"[convertz-fix] geometry texture_size fixed: {size_fixed}")
    print(f"[convertz-fix] armor .player attachables generated: {player_fixed}")
    print(f"[convertz-fix] animated 3D candidates reported: {len(animated_hits)}")
    print(f"[convertz-fix] report: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
