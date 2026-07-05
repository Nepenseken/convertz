import json
import os
import re
import sys
from pathlib import Path

def roundit(val):
    if val is None:
        return None
    return round(float(val) * 10000) / 10000

def to_bool(val):
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() == "true"
    return False

def clean_null_values(d):
    if isinstance(d, dict):
        return {k: clean_null_values(v) for k, v in d.items() if v is not None}
    elif isinstance(d, list):
        return [clean_null_values(v) for v in d if v is not None]
    return d

def convert_geometry(file_path, generated, geometry_name):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"ERROR reading Java model {file_path}: {e}")
        return None

    elements = data.get("elements", [])
    element_array = []
    
    for elem in elements:
        from_val = elem.get("from", [0, 0, 0])
        to_val = elem.get("to", [0, 0, 0])
        
        # Origin and Size calculation
        origin = [
            roundit(-to_val[0] + 8),
            roundit(from_val[1]),
            roundit(from_val[2] - 8)
        ]
        size = [
            roundit(to_val[0] - from_val[0]),
            roundit(to_val[1] - from_val[1]),
            roundit(to_val[2] - from_val[2])
        ]
        
        # Rotation calculation
        rotation = None
        rot_orig = elem.get("rotation", {})
        axis = rot_orig.get("axis")
        angle = rot_orig.get("angle")
        if axis and angle is not None:
            angle = float(angle)
            if axis == "x":
                rotation = [roundit(-angle), 0, 0]
            elif axis == "y":
                rotation = [0, roundit(-angle), 0]
            elif axis == "z":
                rotation = [0, 0, roundit(angle)]
                
        # Pivot calculation
        pivot = None
        origin_orig = rot_orig.get("origin")
        if origin_orig:
            pivot = [
                roundit(-origin_orig[0] + 8),
                roundit(origin_orig[1]),
                roundit(origin_orig[2] - 8)
            ]
            
        # Faces UV calculation
        uv_faces = {}
        faces = elem.get("faces", {})
        for face_name in ["north", "south", "east", "west", "up", "down"]:
            face_data = faces.get(face_name)
            if face_data:
                uv = face_data.get("uv", [0, 0, 16, 16])
                u0, v0, u1, v1 = uv[0], uv[1], uv[2], uv[3]
                x_sign = 1 if (u1 - u0) >= 0 else -1
                y_sign = 1 if (v1 - v0) >= 0 else -1
                
                if face_name in ["up", "down"]:
                    uv_pos = [roundit(u1 - 0.016 * x_sign), roundit(v1 - 0.016 * y_sign)]
                    uv_size = [roundit(u0 - u1 + 0.016 * x_sign), roundit(v0 - v1 + 0.016 * y_sign)]
                else:
                    uv_pos = [roundit(u0 + 0.016 * x_sign), roundit(v0 + 0.016 * y_sign)]
                    uv_size = [roundit(u1 - u0 - 0.016 * x_sign), roundit(v1 - v0 - 0.016 * y_sign)]
                    
                uv_faces[face_name] = {
                    "uv": uv_pos,
                    "uv_size": uv_size
                }
                
        cube = {
            "origin": origin,
            "size": size,
            "uv": uv_faces
        }
        if rotation:
            cube["rotation"] = rotation
        if pivot:
            cube["pivot"] = pivot
            
        element_array.append(cube)

    # Pivot groups calculation
    pivot_groups = []
    seen_rotations = []
    
    for elem in elements:
        rot_orig = elem.get("rotation", {})
        axis = rot_orig.get("axis")
        angle = rot_orig.get("angle")
        origin_orig = rot_orig.get("origin")
        
        if axis and angle is not None and origin_orig:
            angle = float(angle)
            i_piv = [
                roundit(-origin_orig[0] + 8),
                roundit(origin_orig[1]),
                roundit(origin_orig[2] - 8)
            ]
            if axis == "x":
                i_rot = [roundit(-angle), 0, 0]
            elif axis == "y":
                i_rot = [0, roundit(-angle), 0]
            else:
                i_rot = [0, 0, roundit(angle)]
                
            rot_key = (tuple(i_piv), tuple(i_rot))
            if rot_key not in seen_rotations:
                seen_rotations.append(rot_key)
                
                # Find matching cubes
                matching_cubes = []
                for cube in element_array:
                    if cube.get("rotation") == i_rot and cube.get("pivot") == i_piv:
                        # Copy cube without rotation and pivot
                        c_copy = dict(cube)
                        c_copy.pop("rotation", None)
                        c_copy.pop("pivot", None)
                        matching_cubes.append(c_copy)
                        
                pivot_groups.append({
                    "parent": "geyser_custom_z",
                    "pivot": i_piv,
                    "rotation": i_rot,
                    "cubes": matching_cubes
                })

    # Build final geometry JSON
    binding = "c.item_slot == 'head' ? 'head' : q.item_slot_to_bone_name(c.item_slot)"
    
    bone_z = {
        "name": "geyser_custom_z",
        "parent": "geyser_custom_y",
        "pivot": [0, 8, 0]
    }
    
    if generated:
        bone_z["texture_meshes"] = [{
            "texture": "default",
            "position": [0, 8, 0],
            "rotation": [90, 0, -180],
            "local_pivot": [8, 0.5, 8]
        }]
    else:
        # Cubes with no rotation
        bone_z["cubes"] = [
            clean_null_values(dict(c)) for c in element_array if c.get("rotation") is None
        ]
        
    bones = [
        {"name": "geyser_custom", "binding": binding, "pivot": [0, 8, 0]},
        {"name": "geyser_custom_x", "parent": "geyser_custom", "pivot": [0, 8, 0]},
        {"name": "geyser_custom_y", "parent": "geyser_custom_x", "pivot": [0, 8, 0]},
        bone_z
    ]
    
    for idx, pg in enumerate(pivot_groups):
        bones.append({
            "name": f"rot_{idx+1}",
            "parent": "geyser_custom_z",
            "pivot": pg["pivot"],
            "rotation": pg["rotation"],
            "cubes": pg["cubes"]
        })

    geo_data = {
        "format_version": "1.16.0",
        "minecraft:geometry": [{
            "description": {
                "identifier": f"geometry.geyser_custom.{geometry_name}",
                "texture_width": 16,
                "texture_height": 16,
                "visible_bounds_width": 4,
                "visible_bounds_height": 4.5,
                "visible_bounds_offset": [0, 0.75, 0]
            },
            "bones": clean_null_values(bones)
        }]
    }
    
    return geo_data

def get_bone_animation(display_section, bone_name, divide_translation=1.0, multiply_scale=1.0):
    if not display_section:
        return None
        
    rot = display_section.get("rotation")
    trans = display_section.get("translation")
    scale = display_section.get("scale")
    
    bone_anim = {}
    if rot:
        bone_anim["rotation"] = [roundit(-rot[0]), roundit(-rot[1]), roundit(rot[2])]
    if trans:
        bone_anim["position"] = [
            roundit(-trans[0] * divide_translation),
            roundit(trans[1] * divide_translation),
            roundit(trans[2] * divide_translation)
        ]
    if scale:
        bone_anim["scale"] = [
            roundit(scale[0] * multiply_scale),
            roundit(scale[1] * multiply_scale),
            roundit(scale[2] * multiply_scale)
        ]
        
    if not bone_anim:
        return None
    return bone_anim

def convert_animations(file_path, geometry_name):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None

    display = data.get("display", {})
    
    thirdperson_righthand = display.get("thirdperson_righthand", {})
    thirdperson_lefthand = display.get("thirdperson_lefthand", {})
    head = display.get("head", {})
    firstperson_righthand = display.get("firstperson_righthand", {})
    firstperson_lefthand = display.get("firstperson_lefthand", {})

    anims = {}
    
    # thirdperson_main_hand
    tp_main = {}
    bone_x = get_bone_animation(thirdperson_righthand, "geyser_custom_x")
    if bone_x:
        tp_main["geyser_custom_x"] = {
            "rotation": [bone_x["rotation"][0], 0, 0] if "rotation" in bone_x else None,
            "position": bone_x.get("position"),
            "scale": bone_x.get("scale")
        }
    if thirdperson_righthand.get("rotation"):
        tp_main["geyser_custom_y"] = {
            "rotation": [0, roundit(-thirdperson_righthand["rotation"][1]), 0]
        }
        tp_main["geyser_custom_z"] = {
            "rotation": [0, 0, roundit(thirdperson_righthand["rotation"][2])]
        }
    tp_main["geyser_custom"] = {
        "rotation": [90, 0, 0],
        "position": [0, 13, -3]
    }
    anims[f"animation.geyser_custom.{geometry_name}.thirdperson_main_hand"] = {
        "loop": True,
        "bones": clean_null_values(tp_main)
    }

    # thirdperson_off_hand
    tp_off = {}
    bone_x_lh = get_bone_animation(thirdperson_lefthand, "geyser_custom_x")
    if bone_x_lh:
        tp_off["geyser_custom_x"] = {
            "rotation": [bone_x_lh["rotation"][0], 0, 0] if "rotation" in bone_x_lh else None,
            "position": bone_x_lh.get("position"),
            "scale": bone_x_lh.get("scale")
        }
    if thirdperson_lefthand.get("rotation"):
        tp_off["geyser_custom_y"] = {
            "rotation": [0, roundit(-thirdperson_lefthand["rotation"][1]), 0]
        }
        tp_off["geyser_custom_z"] = {
            "rotation": [0, 0, roundit(thirdperson_lefthand["rotation"][2])]
        }
    tp_off["geyser_custom"] = {
        "rotation": [90, 0, 0],
        "position": [0, 13, -3]
    }
    anims[f"animation.geyser_custom.{geometry_name}.thirdperson_off_hand"] = {
        "loop": True,
        "bones": clean_null_values(tp_off)
    }

    # head
    head_anim = {}
    head_x = get_bone_animation(head, "geyser_custom_x", divide_translation=0.625, multiply_scale=0.625)
    if head_x:
        head_anim["geyser_custom_x"] = {
            "rotation": [head_x["rotation"][0], 0, 0] if "rotation" in head_x else None,
            "position": head_x.get("position"),
            "scale": head_x.get("scale") if "scale" in head_x else [0.625, 0.625, 0.625]
        }
    if head.get("rotation"):
        head_anim["geyser_custom_y"] = {
            "rotation": [0, roundit(-head["rotation"][1]), 0]
        }
        head_anim["geyser_custom_z"] = {
            "rotation": [0, 0, roundit(head["rotation"][2])]
        }
    head_anim["geyser_custom"] = {
        "position": [0, 19.9, 0]
    }
    anims[f"animation.geyser_custom.{geometry_name}.head"] = {
        "loop": True,
        "bones": clean_null_values(head_anim)
    }

    # firstperson_main_hand
    fp_main = {
        "geyser_custom": {
            "rotation": [90, 60, -40],
            "position": [4, 10, 4],
            "scale": 1.5
        }
    }
    fp_r_x = get_bone_animation(firstperson_righthand, "geyser_custom_x")
    if fp_r_x:
        fp_main["geyser_custom_x"] = {
            "position": [fp_r_x["position"][0], fp_r_x["position"][1], -fp_r_x["position"][2]] if "position" in fp_r_x else None,
            "rotation": [fp_r_x["rotation"][0], 0, 0] if "rotation" in fp_r_x else [0.1, 0.1, 0.1],
            "scale": fp_r_x.get("scale")
        }
    else:
        fp_main["geyser_custom_x"] = {
            "rotation": [0.1, 0.1, 0.1]
        }
    if firstperson_righthand.get("rotation"):
        fp_main["geyser_custom_y"] = {
            "rotation": [0, roundit(-firstperson_righthand["rotation"][1]), 0]
        }
        fp_main["geyser_custom_z"] = {
            "rotation": [0, 0, roundit(firstperson_righthand["rotation"][2])]
        }
    anims[f"animation.geyser_custom.{geometry_name}.firstperson_main_hand"] = {
        "loop": True,
        "bones": clean_null_values(fp_main)
    }

    # firstperson_off_hand
    fp_off = {
        "geyser_custom": {
            "rotation": [90, 60, -40],
            "position": [4, 10, 4],
            "scale": 1.5
        }
    }
    fp_l_x = get_bone_animation(firstperson_lefthand, "geyser_custom_x")
    if fp_l_x:
        fp_off["geyser_custom_x"] = {
            "position": [fp_l_x["position"][0], fp_l_x["position"][1], -fp_l_x["position"][2]] if "position" in fp_l_x else None,
            "rotation": [fp_l_x["rotation"][0], 0, 0] if "rotation" in fp_l_x else [0.1, 0.1, 0.1],
            "scale": fp_l_x.get("scale")
        }
    else:
        fp_off["geyser_custom_x"] = {
            "rotation": [0.1, 0.1, 0.1]
        }
    if firstperson_lefthand.get("rotation"):
        fp_off["geyser_custom_y"] = {
            "rotation": [0, roundit(-firstperson_lefthand["rotation"][1]), 0]
        }
        fp_off["geyser_custom_z"] = {
            "rotation": [0, 0, roundit(firstperson_lefthand["rotation"][2])]
        }
    anims[f"animation.geyser_custom.{geometry_name}.firstperson_off_hand"] = {
        "loop": True,
        "bones": clean_null_values(fp_off)
    }

    return {
        "format_version": "1.8.0",
        "animations": anims
    }

def main():
    print("Starting fast Python model compiler...")
    
    with open("config.json", "r", encoding="utf-8") as f:
        config = json.load(f)
        
    # Get user flags / materials
    attachable_material = "entity_alphatest_one_sided"
    block_material = "alpha_test"
    
    # Parse arguments from command line if any
    for arg in sys.argv[1:]:
        if arg.startswith("attachable_material="):
            attachable_material = arg.split("=", 1)[1]
        elif arg.startswith("block_material="):
            block_material = arg.split("=", 1)[1]

    # Resolve union atlas map
    try:
        with open("scratch_files/union_atlas.temp", "r", encoding="utf-8") as f:
            union_atlas = json.load(f)
        # Build mapping from texture to atlas index
        tex_to_atlas = {}
        for i, group in enumerate(union_atlas):
            for t in group:
                tex_to_atlas[t] = i
    except Exception:
        tex_to_atlas = {}

    icons_csv_lines = []
    
    total = len(config)
    print(f"Processing {total} items...")
    
    for idx, (geyser_id, entry) in enumerate(config.items()):
        file_path = entry.get("path")
        generated = to_bool(entry.get("generated"))
        namespace = entry.get("namespace", "minecraft")
        model_path = entry.get("model_path", "")
        model_name = entry.get("model_name", "")
        path_hash = entry.get("path_hash")
        geometry = entry.get("geometry")
        
        if not file_path or not path_hash:
            continue
            
        # 3D block model vs 2D item model
        if not generated:
            # 1. Generate RP Geometry
            geo_data = convert_geometry(file_path, generated, geometry)
            if geo_data:
                dest = Path(f"./target/rp/models/blocks/{namespace}/{model_path}/{model_name}.json")
                dest.parent.mkdir(parents=True, exist_ok=True)
                with open(dest, "w", encoding="utf-8") as f:
                    json.dump(geo_data, f, ensure_ascii=False, separators=(",", ":"))

            # 2. Generate RP Animations
            anim_data = convert_animations(file_path, geometry)
            if anim_data:
                dest = Path(f"./target/rp/animations/{namespace}/{model_path}/animation.{model_name}.json")
                dest.parent.mkdir(parents=True, exist_ok=True)
                with open(dest, "w", encoding="utf-8") as f:
                    json.dump(anim_data, f, ensure_ascii=False, separators=(",", ":"))

            # 3. Find atlas index
            # Find first texture of the model
            atlas_index = 0
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    java_model = json.load(f)
                textures = java_model.get("textures", {})
                
                # Get first texture reference
                texture_ref = None
                for key, val in textures.items():
                    if isinstance(val, str) and not val.startswith("#"):
                        texture_ref = val
                        break
                        
                if texture_ref:
                    t_ns, t_sub = texture_ref.split(":", 1) if ":" in texture_ref else ("minecraft", texture_ref)
                    tex_file = f"./assets/{t_ns}/textures/{t_sub}.png"
                    
                    # Look up in union atlas map
                    atlas_index = tex_to_atlas.get(tex_file, 0)
                    
                    # Copy standalone texture
                    src_tex = Path(tex_file)
                    if src_tex.exists():
                        dest_tex = Path(f"./target/rp/textures/{namespace}/{model_path}/{model_name}.png")
                        dest_tex.parent.mkdir(parents=True, exist_ok=True)
                        import shutil
                        shutil.copy2(src_tex, dest_tex)
                        icons_csv_lines.append(f"{path_hash},textures/{namespace}/{model_path}/{model_name}")
            except Exception:
                pass

            # 4. Generate BP Block Definition
            bp_block = {
                "format_version": "1.16.100",
                "minecraft:block": {
                    "description": {
                        "identifier": f"geyser_custom:{path_hash}"
                    },
                    "components": {
                        "minecraft:material_instances": {
                            "*": {
                                "texture": f"gmdl_atlas_{atlas_index}",
                                "render_method": block_material,
                                "face_dimming": False,
                                "ambient_occlusion": False
                            }
                        },
                        "minecraft:geometry": f"geometry.geyser_custom.{geometry}",
                        "minecraft:placement_filter": {
                            "conditions": [{
                                "allowed_faces": [],
                                "block_filter": []
                            }]
                        }
                    }
                }
            }
            dest = Path(f"./target/bp/blocks/{namespace}/{model_path}/{model_name}.json")
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "w", encoding="utf-8") as f:
                json.dump(bp_block, f, ensure_ascii=False, separators=(",", ":"))

            # 5. Generate RP Attachable Definition
            bp_attachable = {
                "format_version": "1.10.0",
                "minecraft:attachable": {
                    "description": {
                        "identifier": f"geyser_custom:{path_hash}",
                        "materials": {
                            "default": attachable_material,
                            "enchanted": attachable_material
                        },
                        "textures": {
                            "default": f"textures/{namespace}/{model_path}/{model_name}".replace("//", "/"),
                            "enchanted": "textures/misc/enchanted_item_glint"
                        },
                        "geometry": {
                            "default": f"geometry.geyser_custom.{geometry}"
                        },
                        "scripts": {
                            "pre_animation": [
                                "v.main_hand = c.item_slot == 'main_hand';",
                                "v.off_hand = c.item_slot == 'off_hand';",
                                "v.head = c.item_slot == 'head';"
                            ],
                            "animate": [
                                {"thirdperson_main_hand": "v.main_hand && !c.is_first_person"},
                                {"thirdperson_off_hand": "v.off_hand && !c.is_first_person"},
                                {"thirdperson_head": "v.head && !c.is_first_person"},
                                {"firstperson_main_hand": "v.main_hand && c.is_first_person"},
                                {"firstperson_off_hand": "v.off_hand && c.is_first_person"},
                                {"firstperson_head": "c.is_first_person && v.head"}
                            ]
                        },
                        "animations": {
                            "thirdperson_main_hand": f"animation.geyser_custom.{geometry}.thirdperson_main_hand",
                            "thirdperson_off_hand": f"animation.geyser_custom.{geometry}.thirdperson_off_hand",
                            "thirdperson_head": f"animation.geyser_custom.{geometry}.head",
                            "firstperson_main_hand": f"animation.geyser_custom.{geometry}.firstperson_main_hand",
                            "firstperson_off_hand": f"animation.geyser_custom.{geometry}.firstperson_off_hand",
                            "firstperson_head": "animation.geyser_custom.disable"
                        },
                        "render_controllers": ["controller.render.item_default"]
                    }
                }
            }
            dest = Path(f"./target/rp/attachables/{namespace}/{model_path}/{model_name}.{path_hash}.attachable.json")
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "w", encoding="utf-8") as f:
                json.dump(bp_attachable, f, ensure_ascii=False, separators=(",", ":"))

        else:
            # 2D item model
            bp_item = {
                "format_version": "1.16.100",
                "minecraft:item": {
                    "description": {
                        "identifier": f"geyser_custom:{path_hash}",
                        "category": "items"
                    },
                    "components": {
                        "minecraft:icon": {
                            "texture": path_hash
                        }
                    }
                }
            }
            dest = Path(f"./target/bp/items/{namespace}/{model_path}/{model_name}.{path_hash}.json")
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "w", encoding="utf-8") as f:
                json.dump(bp_item, f, ensure_ascii=False, separators=(",", ":"))
                
        if idx > 0 and idx % 1000 == 0:
            print(f"Processed {idx}/{total} items...")

    # Write icons.csv
    try:
        with open("scratch_files/icons.csv", "w", encoding="utf-8") as f:
            f.write("\n".join(icons_csv_lines) + "\n")
    except Exception as e:
        print(f"ERROR writing icons.csv: {e}")
        
    print(f"Successfully processed all {total} items!")

if __name__ == "__main__":
    main()
