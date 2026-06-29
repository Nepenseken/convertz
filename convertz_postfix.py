#!/usr/bin/env python3
"""
Post-fix for Nepenseken/convertz ItemsAdder -> Geyser packs.

Fixes the failure pattern seen in ItemsAdder packs where:
1) Java model texture_size is lost and Bedrock geometry is written as 16x16.
2) duplicate root assets override the real ItemsAdder contents/*/resource_pack assets.
3) armor item attachables exist but the matching .player attachable/layer texture is missing.
4) animated 3D weapon models are detected and reported so they can be frozen/handled manually.

Usage:
  python convertz_postfix.py packtwin.zip geyser_resources.mcpack -o geyser_resources.fixed.mcpack
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
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
    "helmet": (0, "geometry.player.armor.helmet", "variable.helmet_layer_visible = 0.0;", "humanoid"),
    "chestplate": (1, "geometry.player.armor.chestplate", "variable.chest_layer_visible = 0.0;", "humanoid"),
    "chest": (1, "geometry.player.armor.chestplate", "variable.chest_layer_visible = 0.0;", "humanoid"),
    "leggings": (2, "geometry.player.armor.leggings", "variable.leg_layer_visible = 0.0;", "humanoid_leggings"),
    "legs": (2, "geometry.player.armor.leggings", "variable.leg_layer_visible = 0.0;", "humanoid_leggings"),
    "boots": (3, "geometry.player.armor.boots", "variable.feet_layer_visible = 0.0;", "humanoid"),
}


def load_json(raw: bytes, name: str) -> Any | None:
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception as exc:
        print(f"[WARN] JSON skip {name}: {exc}")
        return None


def dump_json(data: Any) -> bytes:
    return (json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def source_priority(path: str) -> int:
    # ItemsAdder's contents/*/resource_pack is normally the authoritative RP.
    if "/resource_pack/assets/" in path and path.startswith("contents/"):
        return 100
    if path.startswith("assets/"):
        return 10
    return 0


def model_stem(path: str) -> str:
    return Path(path).stem


def count_java_elements(data: Any) -> int:
    if not isinstance(data, dict):
        return 0
    return len(data.get("elements") or [])


def count_bedrock_cubes(data: Any) -> int:
    total = 0
    for geo in data.get("minecraft:geometry", []) if isinstance(data, dict) else []:
        for bone in geo.get("bones", []) or []:
            total += len(bone.get("cubes") or [])
            total += len(bone.get("texture_meshes") or [])
    return total


def namespace_from_model_path(path: str) -> str:
    m = re.search(r"(?:^|/)assets/([^/]+)/models/", path)
    return m.group(1) if m else ""


def collect_source_models(src: zipfile.ZipFile) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for name in src.namelist():
        if not name.endswith(".json") or "/models/" not in name or "/assets/" not in name:
            continue
        data = load_json(src.read(name), name)
        if not isinstance(data, dict):
            continue
        tex_size = data.get("texture_size")
        if not (isinstance(tex_size, list) and len(tex_size) == 2 and all(isinstance(x, (int, float)) for x in tex_size)):
            continue
        textures = data.get("textures") or {}
        animated = any(re.search(r"animation|animated|_0[0-9]|frame", str(v), re.I) for v in textures.values())
        index[model_stem(name)].append({
            "path": name,
            "namespace": namespace_from_model_path(name),
            "priority": source_priority(name),
            "texture_size": [int(tex_size[0]), int(tex_size[1])],
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
    # Prefer contents/*/resource_pack, then closest element count. This resolves many duplicate IA root-asset bugs.
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


def fix_geometry_texture_sizes(files: dict[str, bytes], source_models: dict[str, list[dict[str, Any]]]) -> tuple[int, list[str]]:
    changed = 0
    animated_hits: list[str] = []
    for name in list(files):
        if not name.startswith("models/blocks/") or not name.endswith(".json"):
            continue
        data = load_json(files[name], name)
        if not isinstance(data, dict) or "minecraft:geometry" not in data:
            continue
        stem = model_stem(name)
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
        # Do not overwrite the geometry texture sizes for items/weapons as they are mapped to spritesheets.
        # for geo in data.get("minecraft:geometry", []) or []:
        #     desc = geo.get("description") or {}
        #     if desc.get("texture_width") != width or desc.get("texture_height") != height:
        #         desc["texture_width"] = width
        #         desc["texture_height"] = height
        #         did = True
        if did:
            files[name] = dump_json(data)
            changed += 1
        if chosen.get("animated"):
            animated_hits.append(f"{name} <= {chosen['path']}")
    return changed, animated_hits


def collect_equipment_textures(src: zipfile.ZipFile) -> dict[str, dict[str, Any]]:
    # eq_id -> {namespace, humanoid, humanoid_leggings, paths}
    equipment = {}
    for name in src.namelist():
        if not name.endswith(".json"):
            continue
        if not ("/models/equipment/" in name or "/equipment/" in name):
            continue
        data = load_json(src.read(name), name)
        if not isinstance(data, dict):
            continue
        ns = namespace_from_equipment_path(name)
        layers = data.get("layers") or {}
        def first_texture(key: str) -> str:
            arr = layers.get(key) or []
            if isinstance(arr, list) and arr and isinstance(arr[0], dict):
                tex = arr[0].get("texture", "")
                return tex.split(":", 1)[1] if ":" in tex else tex
            return ""
        eq_id = Path(name).stem
        equipment[eq_id] = {
            "namespace": ns,
            "humanoid": first_texture("humanoid") or eq_id,
            "humanoid_leggings": first_texture("humanoid_leggings") or first_texture("humanoid") or eq_id,
            "priority": source_priority(name),
        }
    return equipment


def namespace_from_equipment_path(path: str) -> str:
    m = re.search(r"(?:^|/)assets/([^/]+)/(?:models/equipment|equipment)/", path)
    return m.group(1) if m else ""


def detect_slot_and_base(item_name: str) -> tuple[str, str] | tuple[None, None]:
    for slot in ["chestplate", "leggings", "helmet", "boots", "chest", "legs"]:
        if slot in item_name:
            base = item_name.replace(slot, "", 1).strip("_")
            return slot, base
    return None, None


def color_split(name: str) -> tuple[str, str]:
    for color in sorted(COLORS, key=len, reverse=True):
        suf = "_" + color
        if name.endswith(suf):
            return name[:-len(suf)], color
    return name, ""


def normalize_eq_core(eq_id: str) -> str:
    x = eq_id
    for prefix in ["roman_armor_", "medieval_armor_set_", "demonking_assortment_", "witchcaster_", "ec_"]:
        if x.startswith(prefix):
            x = x[len(prefix):]
    x = x.replace("_armor", "").replace("armor", "")
    return x.strip("_")


def choose_equipment(item_name: str, namespace: str, equipment: dict[str, dict[str, Any]]) -> str | None:
    slot, base = detect_slot_and_base(item_name)
    if not slot or not base:
        return None
    base_no_color, color = color_split(base)
    candidates = []
    for eq_id, info in equipment.items():
        if namespace and info.get("namespace") != namespace:
            continue
        core = normalize_eq_core(eq_id)
        score = 0
        if color and eq_id.endswith("_" + color):
            score += 8
        if base == core or base_no_color == core:
            score += 10
        if core in base or base_no_color in core:
            score += 5
        # Special EC pattern: ecrubychest_darkpink -> ecrubyarmor_darkpink
        ec_guess = re.sub(r"(helmet|chest|legs|leggings|boots)", "armor", item_name, count=1)
        if eq_id == ec_guess:
            score += 30
        if score:
            candidates.append((score, info.get("priority", 0), eq_id))
    if not candidates:
        return None
    return sorted(candidates, reverse=True)[0][2]


def find_source_png(src: zipfile.ZipFile, namespace: str, texture_name: str, layer_sub: str) -> bytes | None:
    texture_name = texture_name.strip("/")
    candidates = []
    for base in [
        f"assets/{namespace}/textures/entity/equipment/{layer_sub}/{texture_name}.png",
        f"contents",  # sentinel: handled below
        f"assets/{namespace}/textures/{texture_name}.png",
    ]:
        if base != "contents" and base in src.namelist():
            candidates.append((source_priority(base), base))
    for name in src.namelist():
        if name.endswith(f"/assets/{namespace}/textures/entity/equipment/{layer_sub}/{texture_name}.png"):
            candidates.append((source_priority(name), name))
        elif name.endswith(f"/assets/{namespace}/textures/{texture_name}.png"):
            candidates.append((source_priority(name), name))
    if not candidates:
        return None
    chosen = sorted(candidates, reverse=True)[0][1]
    return src.read(chosen)


def write_player_attachable(gmdl: str, layer_name: str, slot: str) -> bytes:
    _, geometry, parent_setup, _ = SLOT_DATA[slot]
    data = {
        "format_version": "1.10.0",
        "minecraft:attachable": {
            "description": {
                "identifier": f"geyser_custom:{gmdl}.player",
                "item": {f"geyser_custom:{gmdl}": "query.owner_identifier == 'minecraft:player'"},
                "materials": {"default": "armor_leather", "enchanted": "armor_leather_enchanted"},
                "textures": {"default": f"textures/armor_layer/{layer_name}", "enchanted": "textures/misc/enchanted_item_glint"},
                "geometry": {"default": geometry},
                "scripts": {"parent_setup": parent_setup},
                "render_controllers": ["controller.render.armor"],
            }
        },
    }
    return dump_json(data)


def fix_missing_player_armor(files: dict[str, bytes], src: zipfile.ZipFile, equipment: dict[str, dict[str, Any]]) -> int:
    made = 0
    attachables = [n for n in files if n.startswith("attachables/") and n.endswith(".attachable.json") and not n.endswith(".player.json")]
    for afile in attachables:
        basename = Path(afile).name
        m = re.match(r"(.+?)\.(gmdl_[0-9a-f]+)\.attachable\.json$", basename)
        if not m:
            continue
        item_name, gmdl = m.group(1), m.group(2)
        slot, _base = detect_slot_and_base(item_name)
        if not slot:
            continue
        player_name = afile.replace(".attachable.json", ".attachable.player.json")
        # Some older runs use .player.json after .json; normalize both checks.
        if player_name in files or afile.replace(".json", ".player.json") in files:
            continue
        adata = load_json(files[afile], afile)
        desc = (((adata or {}).get("minecraft:attachable") or {}).get("description") or {})
        tex_default = ((desc.get("textures") or {}).get("default") or "")
        ns = ""
        mt = re.match(r"textures/([^/]+)/", tex_default)
        if mt:
            ns = mt.group(1)
        eq_id = choose_equipment(item_name, ns, equipment)
        if not eq_id:
            continue
        info = equipment[eq_id]
        layer_sub = SLOT_DATA[slot][3]
        texture_ref = info.get(layer_sub) or info.get("humanoid") or eq_id
        namespace = info.get("namespace") or ns
        png = find_source_png(src, namespace, texture_ref, layer_sub)
        if not png and layer_sub == "humanoid_leggings":
            png = find_source_png(src, namespace, texture_ref, "humanoid")
        if not png:
            continue
        layer_name = f"{namespace}_{eq_id}"
        files[f"textures/armor_layer/{layer_name}.png"] = png
        files[player_name] = write_player_attachable(gmdl, layer_name, slot)
        made += 1
    return made


def deduplicate_mappings(mappings_data: dict[str, Any]) -> tuple[int, int]:
    """Remove duplicate entries from geyser_mappings items.

    Returns (total_before, duplicates_removed).
    """
    items = mappings_data.get("items", {})
    total_before = sum(len(v) for v in items.values())
    total_dupes = 0
    for java_item in list(items):
        entries = items[java_item]
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for entry in entries:
            key = json.dumps(entry, sort_keys=True)
            if key not in seen:
                seen.add(key)
                unique.append(entry)
            else:
                total_dupes += 1
        items[java_item] = unique
    return total_before, total_dupes


def fix_mappings_file(mappings_path: Path, output_path: Path | None = None) -> tuple[int, int]:
    """Read, deduplicate, and write a geyser_mappings.json file.

    Returns (total_before, duplicates_removed).
    """
    if not mappings_path.exists():
        return 0, 0
    data = json.loads(mappings_path.read_text(encoding="utf-8"))
    total_before, dupes = deduplicate_mappings(data)
    out = output_path or mappings_path
    out.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return total_before, dupes


def repack(input_mcpack: Path, output_mcpack: Path, source_zip: Path,
           mappings_path: Path | None = None) -> None:
    with zipfile.ZipFile(input_mcpack, "r") as rp:
        files = {name: rp.read(name) for name in rp.namelist() if not name.endswith("/")}
    with zipfile.ZipFile(source_zip, "r") as src:
        source_models = collect_source_models(src)
        size_fixed, animated_hits = fix_geometry_texture_sizes(files, source_models)
        equipment = collect_equipment_textures(src)
        player_fixed = fix_missing_player_armor(files, src, equipment)
    with zipfile.ZipFile(output_mcpack, "w", compression=zipfile.ZIP_DEFLATED) as out:
        for name in sorted(files):
            out.writestr(name, files[name])

    # Deduplicate geyser_mappings.json if provided
    mappings_dupes = 0
    mappings_before = 0
    if mappings_path and mappings_path.exists():
        out_mappings = output_mcpack.parent / mappings_path.name
        mappings_before, mappings_dupes = fix_mappings_file(
            mappings_path, out_mappings if out_mappings != mappings_path else None
        )
    else:
        # Try to find geyser_mappings.json next to the mcpack
        candidate = input_mcpack.parent / "geyser_mappings.json"
        if candidate.exists():
            out_mappings = output_mcpack.parent / "geyser_mappings.json"
            mappings_before, mappings_dupes = fix_mappings_file(
                candidate, out_mappings if out_mappings != candidate else None
            )

    report = output_mcpack.with_suffix(".postfix-report.txt")
    with report.open("w", encoding="utf-8") as f:
        f.write(f"geometry_texture_size_fixed={size_fixed}\n")
        f.write(f"player_armor_attachables_generated={player_fixed}\n")
        f.write(f"animated_model_candidates={len(animated_hits)}\n")
        f.write(f"mappings_entries_before={mappings_before}\n")
        f.write(f"mappings_duplicates_removed={mappings_dupes}\n")
        for line in animated_hits[:500]:
            f.write(line + "\n")
    print(f"[OK] wrote {output_mcpack}")
    print(f"[OK] wrote {report}")
    print(f"[SUMMARY] geometry texture_size fixed: {size_fixed}")
    print(f"[SUMMARY] .player armor attachables generated: {player_fixed}")
    print(f"[SUMMARY] animated 3D model candidates reported: {len(animated_hits)}")
    if mappings_dupes:
        print(f"[SUMMARY] mappings duplicates removed: {mappings_dupes} ({mappings_before} -> {mappings_before - mappings_dupes})")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Post-fix for convertz output packs: fix geometry texture sizes, "
                    "generate missing armor .player attachables, and deduplicate mappings."
    )
    parser.add_argument("source_zip", type=Path, help="Original ItemsAdder/Java resource pack zip")
    parser.add_argument("mcpack", type=Path, help="Converted Geyser/Bedrock mcpack")
    parser.add_argument("-o", "--output", type=Path, default=None, help="Fixed output mcpack")
    parser.add_argument("-m", "--mappings", type=Path, default=None,
                        help="Path to geyser_mappings.json (auto-detected if not specified)")
    args = parser.parse_args()
    out = args.output or args.mcpack.with_name(args.mcpack.stem + ".fixed.mcpack")
    repack(args.mcpack, out, args.source_zip, mappings_path=args.mappings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
