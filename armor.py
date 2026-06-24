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

# Namespace aliases — when a YAML config uses one namespace but
# the actual texture/models live under a different namespace.
NAMESPACE_ALIASES = {
    "witchcasterspellsassortment": ["elitecreatures"],
}


def load_armor_configs(contents_dir: str) -> dict:
    """Load all armors*.yml files and build item -> equipment -> layer texture maps."""
    contents = Path(contents_dir)
    if not contents.exists():
        print(f"[WARN] Contents dir not found: {contents_dir}")
        return {}

    configs = {}

    yml_files = []
    for pat in ("armors*.yml", "armor*.yml"):
        yml_files.extend(sorted(contents.rglob(pat)))
    for armors_file in yml_files:
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
                    # Merge equipments (different keys so no conflict)
                    configs[namespace]["equipments"].update(ns_eq)
                    # Items may share names across YAML files (e.g. elitecreatures namespace
                    # from both witchcaster/ and demonking/); track ALL per-source items
                    configs[namespace]["items"].update(ns_items)  # last-file-wins for PASS 1
                    if "sources" not in configs[namespace]:
                        configs[namespace]["sources"] = []
                    configs[namespace]["sources"].append(ns_items)
                else:
                    configs[namespace] = {"equipments": ns_eq, "items": ns_items, "sources": [ns_items]}
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


def find_armor_texture(pack_dir: str, namespace: str, eq_id: str, layer_path: str, layer_key: str,
                      slot_idx: int = -1) -> (Path | None):
    """Find the armor layer PNG in the Java pack, searching overlay dirs with fallbacks."""
    # If namespace not found directly, try aliases (e.g. witchcasterspellsassortment -> elitecreatures)
    namespaces_to_try = [namespace] + NAMESPACE_ALIASES.get(namespace, [])
    
    layer_sub = "humanoid_leggings" if layer_key == "layer_2" else "humanoid"
    
    # Build a set of unique base dirs to search:
    # pack/, root (.), all ia_overlay_* dirs, and contents/*/resource_pack/
    search_bases = set()
    for base in [Path(pack_dir), Path(".")]:
        search_bases.add(base)
        for od in sorted(base.glob("ia_overlay_*/")):
            search_bases.add(od)
        # Also search inside contents/*/resource_pack/ for legacy textures
        for rp in sorted(base.glob("contents/*/resource_pack/")):
            search_bases.add(rp)
    
    # If layer_key is layer_2 and we can't find it, also try falling back to layer_1 texture
    # (some ItemsAdder packs only define layer_1 textures)
    fallback_subs = [layer_sub]
    if layer_key == "layer_2":
        fallback_subs.append("humanoid")  # fallback: leggings use humanoid texture
    
    for base in sorted(search_bases, key=str):
        for ns in namespaces_to_try:
            for sub in fallback_subs:
                # Try overlay texture path (modern ItemsAdder): assets/{ns}/textures/entity/equipment/{sub}/{eq_id}.png
                p = base / "assets" / ns / "textures" / "entity" / "equipment" / sub / f"{eq_id}.png"
                if p.exists():
                    return p
                # Try overlay with layer_path basename instead of eq_id
                layer_base = Path(layer_path).name
                p = base / "assets" / ns / "textures" / "entity" / "equipment" / sub / f"{layer_base}.png"
                if p.exists():
                    return p
            # Try old format: assets/{ns}/textures/{layer_path}.png
            p = base / "assets" / ns / "textures" / f"{layer_path}.png"
            if p.exists():
                return p
            # Fallback: some YAML configs have wrong layer paths (e.g. armors_rendering
            # uses "armor_1"/"armor_2" but actual textures use slot names like 
            # "chestplate"/"leggings"/"boots"). Try mapping via split on "_armor_".
            if slot_idx >= 0:
                layer_part = Path(layer_path).stem  # e.g. "witchcasteranimated_armor_black_1"
                if "_armor_" in layer_part:
                    prefix, suffix = layer_part.split("_armor_", 1)
                    # suffix is like "1", "black_1", "blue_2" etc.
                    # Strip trailing _1 or _2 to get optional color
                    color = ""
                    slot_num = suffix
                    if suffix.endswith("_1") or suffix.endswith("_2"):
                        slot_num = suffix[-1]  # "1" or "2"
                        color = suffix[:-2]    # e.g. "black", "blue", or ""  
                    if color:
                        color = f"_{color}"
                    slot_name_map = {1: "chestplate", 2: "leggings", 3: "boots", 0: "helmet"}
                    slot_name = slot_name_map.get(slot_idx, "")
                    if slot_name:
                        alt_name = f"{prefix}_{slot_name}{color}"
                        alt_path = Path(layer_path).parent / alt_name
                        p = base / "assets" / ns / "textures" / f"{alt_path}.png"
                        if p.exists():
                            return p
    return None


def find_attachable(staging_dir: str, namespace: str, model_path: str) -> (str | None):
    """Find an existing converter.sh attachable via recursive search.
    
    converter.sh generates: {base}/{namespace}/{dir_only}/{model_name}.{hash}.attachable.json
    We search:              {base}/{namespace}/**/{model_name}*.json  (recursive)
    """
    model_name = Path(model_path).name  # extracts filename regardless of directory depth
    attachable_dirs = [
        f"{staging_dir}/target/rp/attachables",
        "./target/rp/attachables",
        "target/rp/attachables",
    ]
    for base_dir in attachable_dirs:
        # ** matches any intervening directory structure
        for afile in sorted(glob.glob(f"{base_dir}/{namespace}/**/{model_name}*.json", recursive=True)):
            if not afile.endswith(".player.json"):
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
    model_name = Path(model_path).name
    # Search in pack_dir AND root (converter.sh extracts to root)
    search_dirs = [Path(pack_dir), Path(".")]
    src = None
    for base in search_dirs:
        candidates = [
            base / "assets" / namespace / "textures" / f"{model_path}.png",
            base / "assets" / namespace / "textures" / "item" / f"{model_path}.png",
        ]
        for c in candidates:
            if c.exists():
                src = c
                break
        if src:
            break
    if not src:
        return False

    # Destination matches converter.sh's 2D generated item path
    dst = Path(staging_dir) / "target" / "rp" / "textures" / namespace / model_path / f"{model_name}.png"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        shutil.copy2(src, dst)
    return True


def load_overlay_equipment(pack_dir: str) -> dict:
    """Load equipment definitions from ia_overlay_* dirs (modern ItemsAdder format).
    
    Returns {eq_id: texture_name} e.g. {"roman_armor_legionnaire_red": "roman_armor_legionnaire_red"}
    """
    equipment_map = {}
    search_bases = [Path(pack_dir), Path(".")]
    
    for base in search_bases:
        for overlay_dir in sorted(base.glob("ia_overlay_*/")):
            assets_dir = overlay_dir / "assets"
            if not assets_dir.exists():
                continue
            for ns_dir in sorted(assets_dir.iterdir()):
                if not ns_dir.is_dir():
                    continue
                # Two possible equipment dir locations:
                # 1) assets/{ns}/models/equipment/{eq_id}.json (1.21.2 format)
                # 2) assets/{ns}/equipment/{eq_id}.json (1.21.4+ format)
                for eq_dir in [ns_dir / "models" / "equipment", ns_dir / "equipment"]:
                    if not eq_dir.exists():
                        continue
                    for eq_file in sorted(eq_dir.glob("*.json")):
                        try:
                            with open(eq_file) as f:
                                data = json.load(f)
                            eq_id = eq_file.stem
                            layers = data.get("layers", {})
                            humanoid = layers.get("humanoid", [{}])[0].get("texture", "")
                            if ":" in humanoid:
                                humanoid = humanoid.split(":")[1]
                            if humanoid:
                                equipment_map[eq_id] = humanoid
                        except:
                            pass
    return equipment_map


def scan_armor_models(pack_dir: str, overlay_eq: dict = None) -> list:
    """Scan auto_generated model dirs for potential armor items (by naming convention).
    
    overlay_eq: dict of eq_id → texture_name from overlay equipment JSONs
    Uses overlay_eq to match model names to equipment IDs.
    
    Returns list of (namespace, model_path, item_name, slot_idx, eq_id)
    """
    SLOT_KEYWORDS = [
        ("_helmet", 0), ("_chestplate", 1), ("_leggings", 2), ("_boots", 3),
    ]
    items = []
    search_bases = [Path(pack_dir), Path(".")]
    seen = set()
    
    # Pre-compute: for each eq_id, extract shorter keys for matching
    # e.g. "roman_armor_veles_darkpurple" → "veles_darkpurple"
    eq_lookup = {}
    if overlay_eq:
        for eq_id in overlay_eq:
            # Try to find a meaningful "short name" — the part after all known prefixes
            # ItemsAdder prefix example: "roman_armor_", "medieval_armor_set_", etc.
            # Strip common prefixes to get the core name
            short = eq_id
            for prefix in ["roman_armor_", "medieval_armor_set_", "demonking_assortment_",
                           "ecbluemech", "eclavabeast", "eclightknight", "ecruby",
                           "witchcaster_"]:
                if short.startswith(prefix):
                    short = short[len(prefix):]
                    break
            # Remove _armor suffix for matching with model base names
            # e.g. "medieval_armor_set_heavy_armor" → "heavy" to match "heavy_boots" → "heavy"
            short = short.replace("_armor", "")
            if short:
                eq_lookup[short] = eq_id
            eq_lookup[eq_id] = eq_id  # Also store full ID
    
    for base in search_bases:
        assets_dir = base / "assets"
        if not assets_dir.exists():
            continue
        for ns_dir in sorted(assets_dir.iterdir()):
            if not ns_dir.is_dir():
                continue
            namespace = ns_dir.name
            if namespace in ("minecraft", "_iainternal"):
                continue
            # Scan model dirs recursively (supports sub-folders like medieval_armor_set/)
            for models_root in [ns_dir / "models" / "auto_generated", ns_dir / "models"]:
                if not models_root.exists():
                    continue
                for model_file in sorted(models_root.rglob("*.json")):
                    model_name = model_file.stem
                    # Check slot keywords
                    for kw, slot_idx in SLOT_KEYWORDS:
                        if kw in model_name:
                            # Strip slot keyword to get base name
                            base_name = model_name.replace(kw, "", 1)
                            
                            # Try to find matching eq_id
                            eq_id = ""
                            if overlay_eq:
                                # Try direct lookup
                                if base_name in eq_lookup:
                                    eq_id = eq_lookup[base_name]
                                else:
                                    # Fuzzy: find eq_id that ends with base_name
                                    for short, full in eq_lookup.items():
                                        if full.endswith(base_name) or base_name.endswith(short):
                                            eq_id = full
                                            break
                                # Still no match: try using full model_name (without slot kw) as eq_id key
                                if not eq_id and base_name in eq_lookup:
                                    eq_id = eq_lookup[base_name]
                            
                            if not eq_id:
                                eq_id = base_name  # fallback: use base_name as eq_id
                            
                            # Derive model_path (directory-only, matching converter.sh)
                            models_dir = ns_dir / "models"
                            if "auto_generated" in str(model_file):
                                model_path = "auto_generated"
                            else:
                                try:
                                    rel = model_file.relative_to(models_dir)
                                    model_path = "" if str(rel.parent) == "." else str(rel.parent).replace("\\", "/")
                                except ValueError:
                                    model_path = ""
                            
                            dedup = (namespace, model_name, slot_idx)
                            if dedup not in seen:
                                seen.add(dedup)
                                items.append((namespace, model_path, model_name, slot_idx, eq_id))
                            break  # found slot, stop checking other slots
    return items


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
    layer_path = eq_data.get(layer_key, "") if eq_data else ""

    # Find the armor layer PNG
    found_png = None
    if layer_path:
        # Search using layer_path from YAML config
        found_png = find_armor_texture(pack_dir, namespace, eq_id, layer_path, layer_key, slot_idx)
    else:
        # No YAML config — search using eq_id directly in overlay dirs
        layer_sub = "humanoid_leggings" if slot_idx == 2 else "humanoid"
        for base in [Path(pack_dir), Path(".")]:
            # Direct overlay texture path
            p = base / "assets" / namespace / "textures" / "entity" / "equipment" / layer_sub / f"{eq_id}.png"
            if p.exists():
                found_png = p
                break
            # Also check ia_overlay_* dirs
            for od in sorted(base.glob("ia_overlay_*/")):
                p = od / "assets" / namespace / "textures" / "entity" / "equipment" / layer_sub / f"{eq_id}.png"
                if p.exists():
                    found_png = p
                    break
            if found_png:
                break
    
    if not found_png:
        print(f"  [SKIP] {item_name}: layer PNG not found for eq={eq_id}")
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
        # Use item_name (pure model name) for hash, not model_path (directory-only)
        gmdl = generate_gmdl(f"{namespace}:{item_name}")
        # Copy item icon texture (if available)
        copy_item_texture(pack_dir, staging_dir, namespace, item_name)
        # Generate item attachable at converter.sh-compatible path
        afile_dir = f"{staging_dir}/target/rp/attachables/{namespace}/{model_path}"
        os.makedirs(afile_dir, exist_ok=True)
        afile = f"{afile_dir}/{item_name}.{gmdl}.attachable.json"
        generate_item_attachable(afile, gmdl, namespace, model_path, item_name)
        print(f"  [GEN]  {item_name}: generated attachable (gmdl={gmdl})")

    # Generate .player attachable
    pfile = afile.replace(".json", ".player.json")
    write_player_attachable(pfile, gmdl, layer_name, slot_idx)
    print(f"  [OK]   {item_name} -> {layer_name} (gmdl={gmdl})")
    
    # Only mark as processed on SUCCESS
    processed.add(dedup_key)
    return True


def main(argv: list[str] | None = None):
    if argv is None:
        argv = sys.argv
    if len(argv) < 2:
        print("Usage: python armor.py <contents_dir>")
        sys.exit(1)

    contents_dir = argv[1]
    pack_dir = "pack"
    staging_dir = "staging"

    print("[ARMOR] Loading ItemsAdder armor configs...")
    configs = load_armor_configs(contents_dir)

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

                # Extract directory-only model_path (matches converter.sh format)
                raw_path = Path(model_path)
                dir_path = str(raw_path.parent).replace("\\", "/")
                if dir_path == ".":
                    dir_path = ""

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

                ok = process_armor_item(namespace, dir_path or model_path, item_name, eq_id, eq_data,
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

                # Extract directory-only model_path (matches converter.sh format)
                # YAML gives "auto_generated/ecbluemechhelmet" → "auto_generated"
                raw_path = Path(model_path)
                dir_path = str(raw_path.parent).replace("\\", "/")
                if dir_path == ".":
                    dir_path = ""

                ok = process_armor_item(namespace, dir_path or model_path, item_name, eq_id, eq_data,
                                        slot_idx, pack_dir, staging_dir, armor_layer_dir, processed)
                if ok:
                    total_processed += 1
                    direct_count += 1
                else:
                    total_errors += 1

            except Exception as e:
                print(f"  [ERR]  {namespace}:{item_name}: {e}")
                total_errors += 1

        # Also process items from per-source entries (handles same-namespace, different YAML files)
        for src_items in ns_config.get("sources", []):
            for item_name, item_data in src_items.items():
                # Skip if already picked up by main items loop
                main_item = items.get(item_name)
                if main_item and main_item.get("equipment_id") == item_data.get("equipment_id", ""):
                    continue
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
                    dedup_key = (namespace, eq_id, slot_idx)
                    if dedup_key in processed:
                        continue
                    raw_path = Path(model_path)
                    dir_path = str(raw_path.parent).replace("\\", "/")
                    if dir_path == ".":
                        dir_path = ""
                    ok = process_armor_item(namespace, dir_path or model_path, item_name, eq_id, eq_data,
                                            slot_idx, pack_dir, staging_dir, armor_layer_dir, processed)
                    if ok:
                        total_processed += 1
                        direct_count += 1
                    else:
                        total_errors += 1
                except Exception as e:
                    print(f"  [ERR]  {namespace}:{item_name} (source): {e}")
                    total_errors += 1

    if direct_count:
        print(f"\n[DIRECT SCAN] {direct_count} additional items processed from YAML configs")

    # --- PASS 3: Process items detected from auto_generated models + overlay equipment ---
    # This works WITHOUT contents/ YAML configs — reads item models and overlay textures directly
    print(f"\n{'='*50}")
    print("[OVERLAY SCAN] Scanning auto_generated models + overlay equipment...")
    overlay_count = 0

    # Load overlay equipment definitions (ia_overlay_*/equipment/ or models/equipment/)
    overlay_eq = load_overlay_equipment(pack_dir)
    print(f"  [INFO] Loaded {len(overlay_eq)} overlay equipment definitions")

    # Scan auto_generated models for potential armor items
    armor_candidates = scan_armor_models(pack_dir, overlay_eq)
    print(f"  [INFO] Found {len(armor_candidates)} potential armor items by naming convention")

    for namespace, model_path, item_name, slot_idx, eq_id in armor_candidates:
        try:
            # Skip if already processed via YAML/leather passes
            dedup_key = (namespace, eq_id, slot_idx)
            if dedup_key in processed:
                continue

            ok = process_armor_item(namespace, model_path, item_name, eq_id, {},
                                    slot_idx, pack_dir, staging_dir, armor_layer_dir, processed)
            if ok:
                total_processed += 1
                overlay_count += 1
            else:
                total_errors += 1

        except Exception as e:
            print(f"  [ERR]  {namespace}:{item_name}: {e}")
            total_errors += 1

    if overlay_count:
        print(f"\n[OVERLAY SCAN] {overlay_count} additional items processed from overlay scan")

    # --- SUMMARY: Count generated armor layer PNGs ---
    print(f"\n{'='*50}")
    generated_layers = sorted(armor_layer_dir.glob("*.png"))
    generated_names = {p.stem for p in generated_layers}
    
    # Per-namespace breakdown from processed set
    ns_counts = {}
    for (ns, eq_id, slot_idx) in processed:
        ns_counts.setdefault(ns, set()).add((eq_id, slot_idx))
    
    print(f"[SUMMARY] Generated {len(generated_layers)} armor layer textures")
    print(f"[SUMMARY] Processed {total_processed} items ({total_errors} errors)")
    
    # Show per-namespace equipment sets
    for ns in sorted(ns_counts):
        eq_sets = set()
        for (_, eq_id, _) in ns_counts[ns]:
            base_eq = eq_id.rsplit("_", 1)[0] if any(eq_id.endswith(f"_{c}") for c in ["black","blue","brown","cyan","gray","green","orange","pink","purple","red","teal","white","yellow","darkblue","darkbrown","darkgreen","darkorange","darkpink","darkpurple","darkred","darkyellow","lightblue","lightgray","lightgreen","lightpurple","lightred"]) else eq_id
            eq_sets.add(base_eq if base_eq != eq_id else eq_id)
        print(f"[SUMMARY]   {ns}: {len(ns_counts[ns])} item-slots across {len(eq_sets)} equipment IDs")
    
    # Compare with config expectations
    if configs:
        expected_eq = 0
        for ns, cfg in configs.items():
            expected_eq += len(cfg.get("equipments", {}))
        # Each equipment can have up to 4 slots, but some are partial sets
        print(f"[SUMMARY] YAML configs define {expected_eq} total equipment entries across {len(configs)} namespaces")


if __name__ == "__main__":
    main()
