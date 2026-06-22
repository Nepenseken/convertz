#!/usr/bin/env python3
"""
ItemsAdder armor converter for java2bedrock.sh.
Reads ItemsAdder armors.yml configs directly instead of OptiFine .properties files.
Generates proper .player attachables so armor renders as 3D layer textures on the player model,
not the item icon.

Usage: python armor.py <contents_dir>
  contents_dir: path to ItemsAdder contents/ directory containing armors.yml configs
"""

import os, json, shutil, glob, sys, hashlib
from pathlib import Path

# Try to load yaml, if not available, provide clear error
try:
    import yaml
except ImportError:
    print("[ERROR] PyYAML is required. Install with: pip install pyyaml")
    sys.exit(1)

ARMOR_SLOTS = ["leather_helmet", "leather_chestplate", "leather_leggings", "leather_boots"]
SLOT_GEOMETRY = {
    0: "geometry.player.armor.helmet",
    1: "geometry.player.armor.chestplate",
    2: "geometry.player.armor.leggings",
    3: "geometry.player.armor.boots",
}
SLOT_NAMES = ["helmet", "chestplate", "leggings", "boots"]
SLOT_VISIBLE_VARIABLE = {
    0: "variable.helmet_layer_visible = 0.0;",
    1: "variable.chest_layer_visible = 0.0;",
    2: "variable.leg_layer_visible = 0.0;",
    3: "variable.feet_layer_visible = 0.0;",
}
SLOT_MAP = {
    "HEAD": 0,
    "CHEST": 1,
    "LEGS": 2,
    "FEET": 3,
}


def load_armor_configs(contents_dir: str) -> dict:
    """Load all armors*.yml files and build item -> equipment -> layer texture maps."""
    contents = Path(contents_dir)
    if not contents.exists():
        print(f"[WARN] Contents dir not found: {contents_dir}")
        return {}

    configs = {}

    for armors_file in sorted(contents.rglob("armors*.yml")):
        try:
            with open(armors_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if not data:
                continue

            namespace = data.get("info", {}).get("namespace", "")
            if not namespace:
                continue

            equipments = data.get("equipments", {})
            items = data.get("items", {})

            ns_eq = {}
            for eq_id, eq_data in equipments.items():
                ns_eq[eq_id] = {
                    "layer_1": eq_data.get("layer_1", ""),
                    "layer_2": eq_data.get("layer_2", ""),
                }

            ns_items = {}
            for item_name, item_data in items.items():
                eq_info = item_data.get("equipment", {})
                eq_id = eq_info.get("id", "")
                slot = eq_info.get("slot", "")
                entry = {}
                if eq_id and slot:
                    entry["equipment_id"] = eq_id
                    entry["slot"] = slot
                # Also store resource model_path for direct item scan
                resource = item_data.get("resource", {})
                if "model_path" in resource:
                    entry["model_path"] = resource["model_path"]
                if entry:
                    ns_items[item_name] = entry

            if ns_items:
                if namespace in configs:
                    # Merge with existing equipments and items (don't overwrite)
                    configs[namespace]["equipments"].update(ns_eq)
                    configs[namespace]["items"].update(ns_items)
                else:
                    configs[namespace] = {"equipments": ns_eq, "items": ns_items}
                print(f"  [OK] {armors_file.name} ({namespace}): {len(ns_items)} items")

        except Exception as e:
            print(f"  [ERR] {armors_file.name}: {e}")

    return configs


def write_player_attachable(file_path: str, gmdl: str, layer_name: str, slot_index: int):
    """Write a .player attachable JSON for armor rendering on the player model."""
    geometry = SLOT_GEOMETRY.get(slot_index, "geometry.player.armor.helmet")
    parent_script = SLOT_VISIBLE_VARIABLE.get(slot_index, "variable.helmet_layer_visible = 0.0;")
    ajson = {
        "format_version": "1.10.0",
        "minecraft:attachable": {
            "description": {
                "identifier": f"geyser_custom:{gmdl}.player",
                "item": {f"geyser_custom:{gmdl}": "query.owner_identifier == 'minecraft:player'"},
                "materials": {
                    "default": "armor_leather",
                    "enchanted": "armor_leather_enchanted",
                },
                "textures": {
                    "default": f"textures/armor_layer/{layer_name}",
                    "enchanted": "textures/misc/enchanted_item_glint",
                },
                "geometry": {"default": geometry},
                "scripts": {"parent_setup": parent_script},
                "render_controllers": ["controller.render.armor"],
            }
        },
    }
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "w") as f:
        json.dump(ajson, f)


def generate_gmdl(model_ref: str) -> str:
    """Generate deterministic 8-char gmdl hash from a model reference (namespace:model_path)."""
    return "gmdl_" + hashlib.md5(model_ref.encode()).hexdigest()[:8]


def find_armor_texture(pack_dir: str, namespace: str, eq_id: str, layer_path: str, layer_key: str) -> (Path | None):
    """Find the armor layer PNG in the Java pack, searching overlay dirs with fallbacks."""
    texture_dirs = [Path(pack_dir)]
    for tex_base in texture_dirs:
        # Try old format: assets/{ns}/textures/{layer_path}.png
        p = tex_base / "assets" / namespace / "textures" / f"{layer_path}.png"
        if p.exists():
            return p
        # Try overlay format: ia_overlay_*/assets/{ns}/textures/entity/equipment/humanoid/
        layer_sub = "humanoid_leggings" if layer_key == "layer_2" else "humanoid"
        for overlay_dir in sorted(tex_base.glob("ia_overlay_*/")):
            # Try equipment ID name first (most common in modern ItemsAdder)
            p = overlay_dir / "assets" / namespace / "textures" / "entity" / "equipment" / layer_sub / f"{eq_id}.png"
            if p.exists():
                return p
            # Try basename of layer_path
            layer_base = Path(layer_path).name
            p = overlay_dir / "assets" / namespace / "textures" / "entity" / "equipment" / layer_sub / f"{layer_base}.png"
            if p.exists():
                return p
            # Try old path inside overlay
            p = overlay_dir / "assets" / namespace / "textures" / f"{layer_path}.png"
            if p.exists():
                return p
    return None


def find_attachable(staging_dir: str, namespace: str, model_path: str) -> (str | None):
    """Find an existing attachable JSON (non-.player) for the given namespace/model_path."""
    item_filename = Path(model_path).name
    attachable_dirs = [
        f"{staging_dir}/target/rp/attachables",
        "./target/rp/attachables",
        "target/rp/attachables",
    ]
    for base_dir in attachable_dirs:
        # Try nested format: {base_dir}/{namespace}/{model_path}/*.json
        afiles = glob.glob(f"{base_dir}/{namespace}/{model_path}/*.json")
        afile = next((f for f in afiles if not f.endswith(".player.json")), None)
        if afile:
            return afile
        # Try flat format: {base_dir}/{item_filename}*.json
        afiles = glob.glob(f"{base_dir}/{item_filename}*.json")
        afile = next((f for f in afiles if not f.endswith(".player.json")), None)
        if afile:
            return afile
        # Try old hybrid: {base_dir}/{namespace}/{model_path}*.json
        afiles = glob.glob(f"{base_dir}/{namespace}/{model_path}*.json")
        afile = next((f for f in afiles if not f.endswith(".player.json")), None)
        if afile:
            return afile
    return None


def generate_item_attachable(afile_path: str, gmdl: str, namespace: str,
                              model_path: str, model_name: str):
    """Generate a minimal item attachable for 2D sprite items (matches converter.sh format)."""
    attachable = {
        "format_version": "1.10.0",
        "minecraft:attachable": {
            "description": {
                "identifier": f"geyser_custom:{gmdl}",
                "materials": {
                    "default": "entity_alphatest_one_sided",
                    "enchanted": "entity_alphatest_one_sided",
                },
                "textures": {
                    "default": f"textures/{namespace}/{model_path}",
                    "enchanted": "textures/misc/enchanted_item_glint",
                },
                "geometry": {
                    "default": f"geometry.geyser_custom.{gmdl}",
                },
                "scripts": {
                    "pre_animation": [
                        "v.main_hand = c.item_slot == 'main_hand';",
                        "v.off_hand = c.item_slot == 'off_hand';",
                        "v.head = c.item_slot == 'head';",
                    ],
                    "animate": [
                        {"thirdperson_main_hand": "v.main_hand && !c.is_first_person"},
                        {"thirdperson_off_hand": "v.off_hand && !c.is_first_person"},
                        {"thirdperson_head": "v.head && !c.is_first_person"},
                        {"firstperson_main_hand": "v.main_hand && c.is_first_person"},
                        {"firstperson_off_hand": "v.off_hand && c.is_first_person"},
                        {"firstperson_head": "c.is_first_person && v.head"},
                    ],
                },
                "animations": {
                    "thirdperson_main_hand": f"animation.geyser_custom.{gmdl}.thirdperson_main_hand",
                    "thirdperson_off_hand": f"animation.geyser_custom.{gmdl}.thirdperson_off_hand",
                    "thirdperson_head": f"animation.geyser_custom.{gmdl}.head",
                    "firstperson_main_hand": f"animation.geyser_custom.{gmdl}.firstperson_main_hand",
                    "firstperson_off_hand": f"animation.geyser_custom.{gmdl}.firstperson_off_hand",
                    "firstperson_head": "animation.geyser_custom.disable",
                },
                "render_controllers": ["controller.render.item_default"],
            }
        },
    }
    os.makedirs(os.path.dirname(afile_path), exist_ok=True)
    with open(afile_path, "w") as f:
        json.dump(attachable, f)


def copy_item_texture(pack_dir: str, staging_dir: str, namespace: str,
                       model_path: str) -> bool:
    """Copy item icon PNG from Java pack to target RP textures (converter.sh style path)."""
    # The item model's texture might be at various locations; try the model_path first
    model_name = Path(model_path).name
    candidates = [
        # Same path as model: textures/{namespace}/{model_path}.png
        Path(pack_dir) / "assets" / namespace / "textures" / f"{model_path}.png",
        # Common ItemsAdder pattern: textures/{namespace}/item/{model_path}.png
        Path(pack_dir) / "assets" / namespace / "textures" / "item" / f"{model_path}.png",
    ]
    src = None
    for c in candidates:
        if c.exists():
            src = c
            break
    if not src:
        return False

    # Destination matches converter.sh's 2D generated item path
    dst = Path(staging_dir) / "target" / "rp" / "textures" / namespace / model_path / f"{model_name}.png"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        shutil.copy2(src, dst)
    return True


def process_armor_item(namespace: str, model_path: str, item_name: str, eq_id: str, eq_data: dict,
                       slot_idx: int, pack_dir: str, staging_dir: str, armor_layer_dir: Path,
                       processed: set) -> bool:
    """Process one armor item: find texture, copy to armor_layer, generate .player attachable.
    
    If no existing attachable is found, generates a minimal one with a deterministic gmdl.
    Returns True on success, False on skip/error.
    """
    # Deduplicate: skip if (namespace, eq_id, slot_idx) already processed successfully
    dedup_key = (namespace, eq_id, slot_idx)
    if dedup_key in processed:
        return False

    # Determine which layer to use
    layer_key = "layer_2" if slot_idx == 2 else "layer_1"
    layer_path = eq_data.get(layer_key, "")
    if not layer_path:
        return False

    # Find the armor layer PNG
    found_png = find_armor_texture(pack_dir, namespace, eq_id, layer_path, layer_key)
    if not found_png:
        print(f"  [SKIP] {item_name}: layer PNG not found for eq={eq_id} ({layer_path})")
        return False

    # Copy to armor_layer directory
    layer_name = f"{namespace}_{eq_id}"
    layer_dest = armor_layer_dir / f"{layer_name}.png"
    if not layer_dest.exists():
        shutil.copy2(found_png, layer_dest)

    # Find existing attachable or generate one
    afile = find_attachable(staging_dir, namespace, model_path)
    if afile:
        with open(afile, "r") as f:
            attach_data = json.load(f)
        gmdl = attach_data["minecraft:attachable"]["description"]["identifier"].split(":")[1]
    else:
        # No existing attachable — generate a minimal one with deterministic gmdl
        gmdl = generate_gmdl(f"{namespace}:{model_path}")
        # Copy item icon texture (if available) for inventory rendering
        copy_item_texture(pack_dir, staging_dir, namespace, model_path)
        # Generate item attachable
        model_name = Path(model_path).name
        afile = f"{staging_dir}/target/rp/attachables/{model_name}.{gmdl}.attachable.json"
        generate_item_attachable(afile, gmdl, namespace, model_path, model_name)
        print(f"  [GEN]  {item_name}: generated attachable (gmdl={gmdl})")

    # Generate .player attachable
    pfile = afile.replace(".json", ".player.json")
    write_player_attachable(pfile, gmdl, layer_name, slot_idx)
    print(f"  [OK]   {item_name} -> {layer_name} (gmdl={gmdl})")
    
    # Only mark as processed on SUCCESS
    processed.add(dedup_key)
    return True


def main():
    if len(sys.argv) < 2:
        print("Usage: python armor.py <contents_dir>")
        sys.exit(1)

    contents_dir = sys.argv[1]
    pack_dir = "pack"
    staging_dir = "staging"

    print("[ARMOR] Loading ItemsAdder armor configs...")
    configs = load_armor_configs(contents_dir)

    if not configs:
        print("[WARN] No ItemsAdder armor configs found. Nothing to convert.")
        return

    armor_layer_dir = Path(staging_dir) / "target" / "rp" / "textures" / "armor_layer"
    armor_layer_dir.mkdir(parents=True, exist_ok=True)

    total_processed = 0
    total_errors = 0
    processed = set()  # Track (namespace, eq_id, slot_idx) to avoid duplicates

    # --- PASS 1: Process items found via vanilla leather armor overrides ---
    for slot_idx, (item_type, slot_name) in enumerate(zip(ARMOR_SLOTS, SLOT_NAMES)):
        item_file = Path(pack_dir) / "assets" / "minecraft" / "models" / "item" / f"{item_type}.json"
        if not item_file.exists():
            continue

        with open(item_file, "r") as f:
            data = json.load(f)

        overrides = data.get("overrides", [])
        print(f"\n[{slot_name.upper()}] {len(overrides)} overrides (leather override pass)")

        for override in overrides:
            try:
                model = override.get("model", "")
                if not model:
                    continue

                namespace = model.split(":")[0]
                model_path = model.split(":")[1]
                item_name = model_path.split("/")[-1]

                if item_name in ARMOR_SLOTS:
                    continue

                # Look up this item in configs
                ns_config = configs.get(namespace)
                if not ns_config:
                    continue

                items = ns_config.get("items", {})
                equipments = ns_config.get("equipments", {})

                # Find matching item (try exact, then prefix match for color variants)
                matched_item = items.get(item_name)
                if not matched_item:
                    for cfg_name, cfg_item in items.items():
                        if cfg_name.startswith(item_name):
                            matched_item = cfg_item
                            break

                if not matched_item:
                    # Try the other direction: item_name might be longer (color variant)
                    for cfg_name, cfg_item in items.items():
                        if item_name.startswith(cfg_name):
                            matched_item = cfg_item
                            break

                if not matched_item:
                    # Try suffix match: cfg key ends with model name (roman_armor_* items)
                    for cfg_name, cfg_item in items.items():
                        if cfg_name.endswith(item_name):
                            matched_item = cfg_item
                            break

                if not matched_item:
                    continue

                eq_id = matched_item["equipment_id"]
                eq_data = equipments.get(eq_id)
                if not eq_data:
                    continue

                ok = process_armor_item(namespace, model_path, item_name, eq_id, eq_data,
                                        slot_idx, pack_dir, staging_dir, armor_layer_dir, processed)
                if ok:
                    total_processed += 1
                else:
                    total_errors += 1

            except Exception as e:
                print(f"  [ERR]  {override.get('model', '?')}: {e}")
                total_errors += 1

    # --- PASS 2: Process items directly from YAML configs (ItemsAdder modern format) ---
    print(f"\n{'='*50}")
    print("[DIRECT SCAN] Scanning YAML items for armor equipment entries...")
    direct_count = 0

    for namespace, ns_config in configs.items():
        items = ns_config.get("items", {})
        equipments = ns_config.get("equipments", {})

        for item_name, item_data in items.items():
            try:
                eq_id = item_data.get("equipment_id", "")
                slot = item_data.get("slot", "")
                model_path = item_data.get("model_path", "")

                if not eq_id or not slot or not model_path:
                    continue

                slot_idx = SLOT_MAP.get(slot)
                if slot_idx is None:
                    continue

                eq_data = equipments.get(eq_id)
                if not eq_data:
                    continue

                # Skip if already processed via leather override
                dedup_key = (namespace, eq_id, slot_idx)
                if dedup_key in processed:
                    continue

                ok = process_armor_item(namespace, model_path, item_name, eq_id, eq_data,
                                        slot_idx, pack_dir, staging_dir, armor_layer_dir, processed)
                if ok:
                    total_processed += 1
                    direct_count += 1
                else:
                    total_errors += 1

            except Exception as e:
                print(f"  [ERR]  {namespace}:{item_name}: {e}")
                total_errors += 1

    if direct_count:
        print(f"\n[DIRECT SCAN] {direct_count} additional items processed from YAML configs")

    print(f"\n{'='*50}")
    print(f"Armor conversion: {total_processed} OK, {total_errors} errors")


if __name__ == "__main__":
    main()
