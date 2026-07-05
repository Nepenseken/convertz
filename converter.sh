#!/usr/bin/env bash
# Add common Windows ImageMagick installation directories to PATH if magick is not found
if ! command -v magick &>/dev/null; then
  for dir in "/c/Program Files"/ImageMagick* "C:/Program Files"/ImageMagick* "/cygdrive/c/Program Files"/ImageMagick*; do
    if [ -d "$dir" ]; then
      export PATH="${dir}:${PATH}"
      break
    fi
  done
fi
export PATH="${PWD}/imagemagick_shims:${PATH}"
: ${1?'Please specify an input resource pack in the same directory as the script (e.g. ./converter.sh MyResourcePack.zip)'}

# define color placeholders
C_RED='\e[31m'
C_GREEN='\e[32m'
C_YELLOW='\e[33m'
C_BLUE='\e[36m'
C_GRAY='\e[37m'
C_CLOSE='\e[m'

# status message function depending on message type
# usage: status <completion|process|critical|error|info|plain> <message>
status_message () {
  case $1 in
    "completion")
      printf "${C_GREEN}[+] ${C_GRAY}${2}${C_CLOSE}\n"
      ;;
    "process")
      printf "${C_YELLOW}[•] ${C_GRAY}${2}${C_CLOSE}\n"
      ;;
    "critical")
      printf "${C_RED}[X] ${C_GRAY}${2}${C_CLOSE}\n"
      ;;
    "error")
      printf "${C_RED}[ERROR] ${C_GRAY}${2}${C_CLOSE}\n"
      ;;
    "info")
      printf "${C_BLUE}${2}${C_CLOSE}\n"
      ;;
    "plain")
      printf "${C_GRAY}${2}${C_CLOSE}\n"
      ;;
  esac
}

# dependency check function ensures important required programs are installed
# usage: dependency_check <program_name> <program_site> <test_command> <grep_expression>
dependency_check () {
  if command ${3} 2>/dev/null | grep -q "${4}"; then
      status_message completion "Dependency ${1} satisfied"
  else
      status_message error "Dependency ${1} must be installed to proceed\nSee ${2}\nExiting script..."
      exit 1
  fi
}

# user input function to prompt user for info when needed
# usage: user_input <prompt_message> <default_value> <value_description>
user_input () {
  if [[ -z "${!1}" ]]; then
    status_message plain "${2} ${C_YELLOW}[${3}]\n"
    read -p "${4}: " ${1}
    echo
  fi
}

# wait for jobs function prevents the next job from starting until there is a free CPU thread
wait_for_jobs () {
  while test $(jobs -p | wc -w) -ge "$((2*$(nproc)))"; do wait -n; done
}

# ensure input pack exists
if ! test -f "${1}"; then
   status_message error "Input resource pack ${1} is not in this directory"
   exit 1
else
  status_message process "Input file ${1} detected"
fi

# get user defined start flags
while getopts w:m:a:b:f:v:r:s:u: flag "${@:2}"
do
    case "${flag}" in
        w) warn=${OPTARG};;
        m) merge_input=${OPTARG};;
        a) attachable_material=${OPTARG};;
        b) block_material=${OPTARG};;
        f) fallback_pack=${OPTARG};;
        v) default_asset_version=${OPTARG};;
	r) rename_model_files=${OPTARG};;
        s) save_scratch=${OPTARG};;
        u) disable_ulimit=${OPTARG};;
    esac
done

if [[ ${disable_ulimit} == "true" ]]
then
  getconf ARG_MAX
  ulimit -s unlimited
  status_message info "Changed ulimit settings for script:"
  ulimit -a
  echo | xargs --show-limits
  getconf ARG_MAX

fi

# warn user about limitations of the script
printf '\e[1;31m%-6s\e[m\n' "
███████████████████████████████████████████████████████████████████████████████
████████████████████████ # <!> # W A R N I N G # <!> # ████████████████████████
███████████████████████████████████████████████████████████████████████████████
███ This script has been provided as is. If your resource pack does not     ███
███ entirely conform the vanilla resource specification, including but not  ███
███ limited to, missing textures, improper parenting, improperly defined    ███
███ predicates, and malformed JSON files, among other problems, there is a  ███
███ strong possibility this script will fail. Please remedy any potential   ███
███ resource pack formatting errors before attempting to make use of this   ███
███ converter. You have been warned.                                        ███
███████████████████████████████████████████████████████████████████████████████
███████████████████████████████████████████████████████████████████████████████
███████████████████████████████████████████████████████████████████████████████
"

if [[ ${warn} != "false" ]]; then
read -p $'\e[37mTo acknowledge and continue, press enter. To exit, press Ctrl+C.:\e[0m

'
fi

dependency_check "jq" "https://stedolan.github.io/jq/download/" "jq --version" "1.6\|1.7\|1.8"
sponge () {
  cat > "${1}.tmp" && mv "${1}.tmp" "${1}"
}
if command -v magick &>/dev/null; then
  convert () {
    magick convert "$@"
  }
  mogrify () {
    magick mogrify "$@"
  }
  status_message completion "Dependency imagemagick satisfied"
elif command -v convert &>/dev/null && convert -version 2>&1 | grep -q "ImageMagick"; then
  convert () {
    command convert "$@"
  }
  mogrify () {
    command mogrify "$@"
  }
  status_message completion "Dependency imagemagick satisfied"
else
  status_message error "Dependency imagemagick must be installed to proceed\nSee https://imagemagick.org/script/download.php\nExiting script..."
  exit 1
fi
dependency_check "spritesheet-js" "https://www.npmjs.com/package/spritesheet-js" "-v spritesheet-js" ""
status_message completion "All dependencies have been satisfied\n"

# prompt user for initial configuration
status_message info "This script will now ask some configuration questions. Default values are yellow. Simply press enter to use the defaults.\n"
user_input merge_input "Is there an existing bedrock pack in this directory with which you would like the output merged? (e.g. input.mcpack)" "null" "Input pack to merge"
user_input attachable_material "What material should we use for the attachables?" "entity_alphatest_one_sided" "Attachable material"
user_input block_material "What material should we use for the blocks?" "alpha_test" "Block material"
user_input fallback_pack "From what URL should we download the fallback resource pack? (must be a direct link)\n Use 'none' if default resources are not needed." "null" "Fallback pack URL"

# print initial configuration for user and set default values if none were specified
status_message plain "
Generating Bedrock 3D resource pack with settings:
${C_GRAY}Input pack to merge: ${C_BLUE}${merge_input:=null}
${C_GRAY}Attachable material: ${C_BLUE}${attachable_material:=entity_alphatest_one_sided}
${C_GRAY}Block material: ${C_BLUE}${block_material:=alpha_test}
${C_GRAY}Fallback pack URL: ${C_BLUE}${fallback_pack:=null}
"

# decompress our input pack
status_message process "Decompressing input pack"
python -c "import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall('.')" "${1}"
status_message completion "Input pack decompressed"

# ItemsAdder fix: merge contents/*/resource_pack/assets and resolve ia: texture references.
IA_FIX_SCRIPT="./ia_fix.py"
if [ ! -f "$IA_FIX_SCRIPT" ] && [ -f "../ia_fix.py" ]; then
  IA_FIX_SCRIPT="../ia_fix.py"
fi
if [ -f "$IA_FIX_SCRIPT" ]; then
  status_message process "Resolving ItemsAdder resource-pack overlays and ia: texture references"
  python "$IA_FIX_SCRIPT" . || python3 "$IA_FIX_SCRIPT" . || true
fi


# exit the script if no input pack exists by checking for a pack.mcmeta file
if [ ! -f pack.mcmeta ]
then
	status_message error "Invalid resource pack! The pack.mcmeta file does not exist. Is the resource pack improperly compressed in an enclosing folder?"
  exit 1
fi

# ensure the directory that would contain predicate definitions exists
if test -d "./assets/minecraft/models/item"
then 
  status_message completion "Minecraft namespace item folder found."
else
  # create our initial directories for bp & rp
  status_message process "Generating initial directory strucutre for our bedrock packs"
  mkdir -p ./target/rp/models/blocks && mkdir -p ./target/rp/textures && mkdir -p ./target/rp/attachables && mkdir -p ./target/rp/animations && mkdir -p ./target/bp/blocks && mkdir -p ./target/bp/items

  # copy over our pack.png if we have one
  if test -f "./pack.png"; then
      cp ./pack.png ./target/rp/pack_icon.png && cp ./pack.png ./target/bp/pack_icon.png
  fi

  # generate uuids for our manifests
  uuid1=($(python -c "import uuid; print(uuid.uuid4())"))
  uuid2=($(python -c "import uuid; print(uuid.uuid4())"))
  uuid3=($(python -c "import uuid; print(uuid.uuid4())"))
  uuid4=($(python -c "import uuid; print(uuid.uuid4())"))

  # get pack description if we have one
  pack_desc="$(jq -r '(.pack.description // "Geyser 3D Items Resource Pack")' ./pack.mcmeta)"

  # generate rp manifest.json
  status_message process "Generating resource pack manifest"
  jq -c --arg pack_desc "${pack_desc}" --arg uuid1 "${uuid1}" --arg uuid2 "${uuid2}" -n '
  {
      "format_version": 2,
      "header": {
          "description": "Adds 3D items for use with a Geyser proxy",
          "name": $pack_desc,
          "uuid": ($uuid1 | ascii_downcase),
          "version": [1, 0, 0],
          "min_engine_version": [1, 18, 3]
      },
      "modules": [
          {
              "description": "Adds 3D items for use with a Geyser proxy",
              "type": "resources",
              "uuid": ($uuid2 | ascii_downcase),
              "version": [1, 0, 0]
          }
      ]
  }
  ' | sponge ./target/rp/manifest.json

  # generate bp manifest.json
  status_message process "Generating behavior pack manifest"
  jq -c --arg pack_desc "${pack_desc}" --arg uuid1 "${uuid1}" --arg uuid3 "${uuid3}" --arg uuid4 "${uuid4}" -n '
  {
      "format_version": 2,
      "header": {
          "description": "Adds 3D items for use with a Geyser proxy",
          "name": $pack_desc,
          "uuid": ($uuid3 | ascii_downcase),
          "version": [1, 0, 0],
          "min_engine_version": [ 1, 18, 3]
      },
      "modules": [
          {
              "description": "Adds 3D items for use with a Geyser proxy",
              "type": "data",
              "uuid": ($uuid4 | ascii_downcase),
              "version": [1, 0, 0]
          }
      ],
      "dependencies": [
          {
              "uuid": ($uuid1 | ascii_downcase),
              "version": [1, 0, 0]
          }
      ]
  }
  ' | sponge ./target/bp/manifest.json

  # generate rp terrain_texture.json
  status_message process "Generating resource pack terrain texture definition"
  jq -nc '
  {
    "resource_pack_name": "geyser_custom",
    "texture_name": "atlas.terrain",
    "texture_data": {
    }
  }
  ' | sponge ./target/rp/textures/terrain_texture.json

  # generate rp item_texture.json
  status_message process "Generating resource pack item texture definition"
  jq -nc '
  {
    "resource_pack_name": "geyser_custom",
    "texture_name": "atlas.items",
    "texture_data": {}
  }
  ' | sponge ./target/rp/textures/item_texture.json

  status_message process "Generating resource pack disabling animation"
  # generate our disabling animation
  jq -nc '
  {
    "format_version": "1.8.0",
    "animations": {
      "animation.geyser_custom.disable": {
        "loop": true,
        "override_previous_animation": true,
        "bones": {
          "geyser_custom": {
            "scale": 0
          }
        }
      }
    }
  }
  ' | sponge ./target/rp/animations/animation.geyser_custom.disable.json
  if [[ -d "./staging" ]]; then
    ARMOR_CONVERSION="${ARMOR_CONVERSION:-true}" ARMOR_CONTENTS_DIR="${ARMOR_CONTENTS_DIR:-contents}" python manager.py
  else
    cd ..
    ARMOR_CONVERSION="${ARMOR_CONVERSION:-true}" ARMOR_CONTENTS_DIR="${ARMOR_CONTENTS_DIR:-contents}" python manager.py
    cd ./staging
  fi

  # Deduplicate geyser_mappings.json entries (armor conversion may introduce duplicates)
  if [ -f ./target/geyser_mappings.json ]; then
    status_message process "Deduplicating geyser_mappings.json entries"
    jq '
      .items |= (to_entries | map(.value |= unique) | from_entries)
    ' ./target/geyser_mappings.json | sponge ./target/geyser_mappings.json
  fi

  # ItemsAdder/Geyser postprocess fix: geometry texture sizes and missing armor player layers.
  POSTPROCESS_SCRIPT="./itemsadder_postprocess.py"
  if [ ! -f "$POSTPROCESS_SCRIPT" ] && [ -f "../itemsadder_postprocess.py" ]; then
    POSTPROCESS_SCRIPT="../itemsadder_postprocess.py"
  fi
  if [ -f "$POSTPROCESS_SCRIPT" ]; then
    status_message process "Applying ItemsAdder/Geyser texture and armor fixes"
    python "$POSTPROCESS_SCRIPT" "${1}" ./target/rp || python3 "$POSTPROCESS_SCRIPT" "${1}" ./target/rp || true
  fi

  # Deduplicate geyser_mappings.json entries (armor conversion may introduce duplicates)
  if [ -f ./target/geyser_mappings.json ]; then
    status_message process "Deduplicating geyser_mappings.json entries"
    jq '
      .items |= (to_entries | map(.value |= unique) | from_entries)
    ' ./target/geyser_mappings.json | sponge ./target/geyser_mappings.json
  fi

  # cleanup assets and pack files now that the post-processor has finished
  rm -rf assets && rm -f pack.mcmeta && rm -f pack.png

  ZIP_HELPER="./zip_pack.py"
  if [ ! -f "$ZIP_HELPER" ] && [ -f "../zip_pack.py" ]; then
    ZIP_HELPER="../zip_pack.py"
  fi

  if [[ ${save_scratch} != "true" ]] 
  then
    rm -rf scratch_files
    status_message critical "Deleted scratch files"
  else
    python "$ZIP_HELPER" scratch_files ./target/scratch_files.zip
    status_message completion "Archived scratch files\n"
  fi

  status_message process "Compressing output packs"
  mkdir -p ./target/packaged
  python "$ZIP_HELPER" ./target/rp ./target/packaged/geyser_resources_preview.mcpack
  python "$ZIP_HELPER" ./target/bp ./target/packaged/geyser_behaviors_preview.mcpack
  python "$ZIP_HELPER" ./target/packaged ./target/packaged/geyser_addon.mcaddon "_preview.mcpack"

  if [ -f ./target/rp/textures/terrain_texture.json ]; then
    jq 'delpaths([paths | select(.[-1] | strings | startswith("gmdl_atlas_"))])' ./target/rp/textures/terrain_texture.json | sponge ./target/rp/textures/terrain_texture.json
  fi
  python "$ZIP_HELPER" ./target/rp ./target/packaged/geyser_resources.mcpack

  mkdir -p ./target/unpackaged
  mv ./target/rp ./target/unpackaged/rp && mv ./target/bp ./target/unpackaged/bp

  exit
fi

# Download geyser mappings
status_message process "Downloading the latest geyser item mappings"
mkdir -p ./scratch_files
printf "\e[3m\e[37m"
echo
COLUMNS=$COLUMNS-1 curl --no-styled-output -#L -o scratch_files/item_mappings.json https://raw.githubusercontent.com/GeyserMC/mappings/master/items.json
echo
COLUMNS=$COLUMNS-1 curl --no-styled-output -#L -o scratch_files/item_texture.json https://raw.githubusercontent.com/Kas-tle/java2bedrockMappings/main/item_texture.json
echo
printf "${C_CLOSE}"

# setup our initial config by iterating over all json files in the block and item folders
# technically we only need to iterate over actual item models that contain overrides, but the constraints of bash would likely make such an approach less efficent 
status_message process "Iterating through all vanilla associated model JSONs to generate initial predicate config\nOn a large pack, this may take some time...\n"

jq --slurpfile item_texture scratch_files/item_texture.json --slurpfile item_mappings scratch_files/item_mappings.json -n '
[inputs | {(input_filename | sub("(.+)/(?<itemname>.*?).json"; .itemname)): .overrides?[]?}] |

def maxdur($input):
($item_mappings[] |
[to_entries | map(.key as $key | .value | .java_identifer = $key) | .[] | select(.max_damage)] 
| map({(.java_identifer | split(":") | .[1]): (.max_damage)}) 
| add
| .[$input] // 1)
;

def bedrocktexture($input):
($item_texture[] | .[$input] // {"icon": "camera", "frame": 0})
;

def namespace:
if contains(":") then sub("\\:(.+)"; "") else "minecraft" end
;

[.[] | to_entries | map( select((.value.predicate.damage != null) or (.value.predicate.damaged != null)  or (.value.predicate.custom_model_data != null)) |
      (if .value.predicate.damage then (.value.predicate.damage * maxdur(.key) | ceil) else null end) as $damage
    | (if .value.predicate.damaged == 0 then true else null end) as $unbreakable
    | (if .value.predicate.custom_model_data then .value.predicate.custom_model_data else null end) as $custom_model_data |
  {
    "item": .key,
    "bedrock_icon": bedrocktexture(.key),
    "nbt": ({
      "Damage": $damage,
      "Unbreakable": $unbreakable,
      "CustomModelData": $custom_model_data
    }),
    "path": ("./assets/" + (.value.model | namespace) + "/models/" + (.value.model | sub("(.*?)\\:"; "")) + ".json"),
    "namespace": (.value.model | namespace),
    "model_path": ((.value.model | sub("(.*?)\\:"; "")) | split("/")[:-1] | map(. + "/") | add[:-1] // ""),
    "model_name": ((.value.model | sub("(.*?)\\:"; "")) | split("/")[-1]),
    "generated": false

}) | .[]]
| walk(if type == "object" then with_entries(select(.value != null)) else . end)
| to_entries | map( ((.value.geyserID = "gmdl_\(1+.key)") | .value))
| INDEX(.geyserID)

' ./assets/minecraft/models/item/*.json > config.json || { status_message error "Invalid JSON exists in block or item folder! See above log."; exit 1; }
status_message completion "Initial predicate config generated"

# get a list of all model json files in our resource pack
status_message process "Generating an array of all model JSON files to crosscheck with our predicate config"
find ./assets/**/models -type f -name '*.json' > scratch_files/json_files.txt
jq -R . scratch_files/json_files.txt | jq -s . > scratch_files/json_files.json

# ensure all our reference files in config.json exist, and delete the entry if they do not
status_message critical "Removing config entries that do not have an associated JSON file in the pack"
jq -s '
  (.[0] | map({(.): true}) | add) as $files_dict
  | .[1] | map_values(if $files_dict[.path] then . else empty end)
' scratch_files/json_files.json config.json | sponge config.json

# find initial parental information
status_message process "Doing an initial sweep for level 1 parentals"
python -c '
import json
from pathlib import Path
config = json.loads(Path("config.json").read_text(encoding="utf-8"))
paths = sorted(list(set(v["path"] for v in config.values() if "path" in v)))
parents = []
for p in paths:
    path_obj = Path(p)
    if not path_obj.exists():
        continue
    try:
        data = json.loads(path_obj.read_text(encoding="utf-8"))
        parent = data.get("parent")
        if parent:
            ns, name = parent.split(":", 1) if ":" in parent else ("minecraft", parent)
            parent_path = f"./assets/{ns}/models/{name}.json"
        else:
            parent_path = "./assets/minecraft/models/.json"
        parents.append({"path": p, "parent": parent_path})
    except Exception:
        pass
Path("scratch_files/parents.json").write_text(json.dumps(parents), encoding="utf-8")
'

# add initial parental information to config.json
status_message critical "Removing config entries with non-supported parentals\n"
jq -s '

def gtest($input_g):
[ 
  "./assets/minecraft/models/block/block.json", 
  "./assets/minecraft/models/block/cube.json", 
  "./assets/minecraft/models/block/cube_column.json", 
  "./assets/minecraft/models/block/cube_directional.json", 
  "./assets/minecraft/models/block/cube_mirrored.json", 
  "./assets/minecraft/models/block/observer.json", 
  "./assets/minecraft/models/block/orientable_with_bottom.json", 
  "./assets/minecraft/models/block/piston_extended.json", 
  "./assets/minecraft/models/block/redstone_dust_side.json", 
  "./assets/minecraft/models/block/redstone_dust_side_alt.json", 
  "./assets/minecraft/models/block/template_single_face.json", 
  "./assets/minecraft/models/block/thin_block.json", 
  "./assets/minecraft/models/builtin/entity.json"
]
| index($input_g) // null;

(.[0] | map({(.path): .parent}) | add) as $parents_dict |
.[1] | map_values(. + ({"parent": ($parents_dict[.path] // null)} | if gtest(.parent) == null then . else empty end))
| walk(if type == "object" then with_entries(select(.value != null)) else . end)

' scratch_files/parents.json config.json | sponge config.json

# obtain hashes of all model predicate info to ensure consistent model naming
python -c '
import json, hashlib
from pathlib import Path
config = json.loads(Path("config.json").read_text(encoding="utf-8"))
hashes = []
for gid, entry in config.items():
    item = entry.get("item", "")
    cmd = entry.get("nbt", {}).get("CustomModelData", "")
    dmg = entry.get("nbt", {}).get("Damage", "")
    unb = entry.get("nbt", {}).get("Unbreakable", "")
    predicate = f"{item}_c{cmd}_d{dmg}_u{unb}"
    path = entry.get("path", "")
    entry_hash = hashlib.md5(predicate.encode("utf-8")).hexdigest()[:7]
    path_hash = hashlib.md5(path.encode("utf-8")).hexdigest()[:7]
    hashes.append(f"{gid},{entry_hash},{path_hash}")
Path("scratch_files/hashes.csv").write_text("\n".join(hashes) + "\n", encoding="utf-8")
'
jq -cR 'split(",")' scratch_files/hashes.csv | jq -s 'map({(.[0]): [.[1], .[2]]}) | add' > scratch_files/hashmap.json

jq --slurpfile hashmap scratch_files/hashmap.json '
    map_values(
        .geyserID as $gid 
        | . += {
          "path_hash": ("gmdl_" + ($hashmap[] | .[($gid)] | .[0])),
          "geometry": ("geo_" + ($hashmap[] | .[($gid)] | .[1]))
          }
    )
' config.json | sponge config.json

# create our initial directories for bp & rp
status_message process "Generating initial directory strucutre for our bedrock packs"
mkdir -p ./target/rp/models/blocks && mkdir -p ./target/rp/textures && mkdir -p ./target/rp/attachables && mkdir -p ./target/rp/animations && mkdir -p ./target/bp/blocks && mkdir -p ./target/bp/items

# copy over our pack.png if we have one
if test -f "./pack.png"; then
    cp ./pack.png ./target/rp/pack_icon.png && cp ./pack.png ./target/bp/pack_icon.png
fi

# generate uuids for our manifests
uuid1=($(python -c "import uuid; print(uuid.uuid4())"))
uuid2=($(python -c "import uuid; print(uuid.uuid4())"))
uuid3=($(python -c "import uuid; print(uuid.uuid4())"))
uuid4=($(python -c "import uuid; print(uuid.uuid4())"))

# get pack description if we have one
pack_desc="$(jq -r '(.pack.description // "Geyser 3D Items Resource Pack")' ./pack.mcmeta)"

# generate rp manifest.json
status_message process "Generating resource pack manifest"
jq -c --arg pack_desc "${pack_desc}" --arg uuid1 "${uuid1}" --arg uuid2 "${uuid2}" -n '
{
    "format_version": 2,
    "header": {
        "description": "Adds 3D items for use with a Geyser proxy",
        "name": $pack_desc,
        "uuid": ($uuid1 | ascii_downcase),
        "version": [1, 0, 0],
        "min_engine_version": [1, 18, 3]
    },
    "modules": [
        {
            "description": "Adds 3D items for use with a Geyser proxy",
            "type": "resources",
            "uuid": ($uuid2 | ascii_downcase),
            "version": [1, 0, 0]
        }
    ]
}
' | sponge ./target/rp/manifest.json

# generate bp manifest.json
status_message process "Generating behavior pack manifest"
jq -c --arg pack_desc "${pack_desc}" --arg uuid1 "${uuid1}" --arg uuid3 "${uuid3}" --arg uuid4 "${uuid4}" -n '
{
    "format_version": 2,
    "header": {
        "description": "Adds 3D items for use with a Geyser proxy",
        "name": $pack_desc,
        "uuid": ($uuid3 | ascii_downcase),
        "version": [1, 0, 0],
        "min_engine_version": [ 1, 18, 3]
    },
    "modules": [
        {
            "description": "Adds 3D items for use with a Geyser proxy",
            "type": "data",
            "uuid": ($uuid4 | ascii_downcase),
            "version": [1, 0, 0]
        }
    ],
    "dependencies": [
        {
            "uuid": ($uuid1 | ascii_downcase),
            "version": [1, 0, 0]
        }
    ]
}
' | sponge ./target/bp/manifest.json

# generate rp terrain_texture.json
status_message process "Generating resource pack terrain texture definition"
jq -nc '
{
  "resource_pack_name": "geyser_custom",
  "texture_name": "atlas.terrain",
  "texture_data": {
  }
}
' | sponge ./target/rp/textures/terrain_texture.json

# generate rp item_texture.json
status_message process "Generating resource pack item texture definition"
jq -nc '
{
  "resource_pack_name": "geyser_custom",
  "texture_name": "atlas.items",
  "texture_data": {}
}
' | sponge ./target/rp/textures/item_texture.json

status_message process "Generating resource pack disabling animation"
# generate our disabling animation
jq -nc '
{
  "format_version": "1.8.0",
  "animations": {
    "animation.geyser_custom.disable": {
      "loop": true,
      "override_previous_animation": true,
      "bones": {
        "geyser_custom": {
          "scale": 0
        }
      }
    }
  }
}
' | sponge ./target/rp/animations/animation.geyser_custom.disable.json

# DO DEFAULT ASSETS HERE!!
# get the current default textures and merge them with our rp
if [[ ${fallback_pack} != none ]] && [[ ! -f default_assets.zip ]]
then
  status_message process "Now downloading the fallback resource pack:"
  printf "\e[3m\e[37m"
  echo
  COLUMNS=$COLUMNS-1 curl --no-styled-output -#L -o default_assets.zip https://github.com/InventivetalentDev/minecraft-assets/zipball/refs/tags/${default_asset_version:=1.19.2}
  echo
  printf "${C_CLOSE}"
  status_message completion "Fallback resources downloaded"
fi

if [[ ${fallback_pack} != null &&  ${fallback_pack} != none ]]
then
  printf "\e[3m\e[37m"
  echo
  COLUMNS=$COLUMNS-1 curl --no-styled-output -#L -o provided_assets.zip "${fallback_pack}"
  echo
  printf "${C_CLOSE}"
  status_message completion "Provided resources downloaded"
  mkdir ./providedassetholding
  unzip -n -q -d ./providedassetholding provided_assets.zip "assets/**"
  status_message completion "Provided resources decompressed"
  cp -n -r "./providedassetholding/assets"/** './assets/'
  status_message completion "Provided resources merged with target pack"
fi

if [[ ${fallback_pack} != none ]]
then
  root_folder=($(unzip -Z -1 default_assets.zip | head -1))
  mkdir ./defaultassetholding
  unzip -n -q -d ./defaultassetholding default_assets.zip "${root_folder}assets/minecraft/textures/**/*"
  unzip -n -q -d ./defaultassetholding default_assets.zip "${root_folder}assets/minecraft/models/**/*"
  status_message completion "Fallback resources decompressed"
  mkdir -p './assets/minecraft/textures/'
  cp -n -r "./defaultassetholding/${root_folder}assets/minecraft/textures"/* './assets/minecraft/textures/'
  cp -n -r "./defaultassetholding/${root_folder}assets/minecraft/models"/* './assets/minecraft/models/'
  status_message completion "Fallback resources merged with target pack"
  rm -rf defaultassetholding
  #rm -f default_assets.zip
  status_message critical "Extraneous fallback resources deleted\n"
fi

# generate a fallback texture
convert -size 16x16 xc:\#FFFFFF ./assets/minecraft/textures/0.png

# make sure we crop all mcmeta associated png files
status_message process "Cropping animated textures"
for i in $(find ./assets/**/textures -type f -name "*.mcmeta" | sed 's/\.mcmeta//'); do 
convert ${i} -set option:distort:viewport "%[fx:min(w,h)]x%[fx:min(w,h)]" -distort affine "0,0 0,0" -define png:format=png8 -clamp ${i} 2> /dev/null
done

status_message completion "Initial pack setup complete\n"

jq -r '.[] | select(.parent != null) | [.path, .geyserID, .parent, .namespace, .model_path, .model_name, .path_hash] | @tsv | gsub("\\t";",")' config.json | sponge scratch_files/pa.csv

_start=1
_end="$(jq -r '(. | length) + ([.[] | select(.parent != null)] | length)' config.json)"
cur_pos=0

function ProgressBar {
    let _progress=(${1}*100/${2}*100)/100
    let _done=(${_progress}*6)/10
    let _left=60-$_done
    _fill=$(printf "%${_done}s")
    _empty=$(printf "%${_left}s")
printf "\r\e[37m█\e[m \e[37m${_fill// /█}\e[m\e[37m${_empty// /•}\e[m \e[37m█\e[m \e[33m${_progress}％\e[m\n"
}

# first, deal with parented models
python resolve_parentals.py

# update generated models in config
if [[ -f scratch_files/generated.csv ]]
then
  jq -cR 'split(",")' scratch_files/generated.csv | jq -s 'map({(.[0]): true}) | add' > scratch_files/generated.json
  jq -s '
  .[0] as $generated_models
  | .[1]
  | map_values(
    .geyserID as $gid
    | .generated = ($generated_models[($gid)] // false)
  )
  ' scratch_files/generated.json config.json | sponge config.json
fi

# add icon textures to item atlas
if [[ -f scratch_files/icons.csv ]]
then
  jq -cR 'split(",")' scratch_files/icons.csv | jq -s 'map({(.[0]): {"textures": (.[1] | gsub("//"; "/"))}}) | add' > scratch_files/icons.json
  jq -s '
  .[0] as $icons
  | .[1] 
  | .texture_data += $icons
  ' scratch_files/icons.json ./target/rp/textures/item_texture.json | sponge ./target/rp/textures/item_texture.json
fi

# delete unsuitable models
if [[ -f scratch_files/deleted.csv ]]
then
  jq -cR 'split(",")' scratch_files/deleted.csv  | jq -s '.' > scratch_files/deleted.json
  jq -s '.[0] as $deleted | .[1] | delpaths($deleted)' scratch_files/deleted.json config.json | sponge config.json
fi

status_message process "Compiling final model list"
# get our final 3d model list from the config
model_list=( $(jq -r '.[] | select(.generated == false) | .path' config.json) )

# get our final texture list to be atlased
# get a bash array of all texture files in our resource pack
status_message process "Generating an array of all model PNG files to crosscheck with our atlas"
find ./assets/**/textures -type f -name '*.png' > scratch_files/all_textures_list.txt
jq -R . scratch_files/all_textures_list.txt | jq -s . > scratch_files/all_textures.temp

# get bash array of all texture files listed in our models
status_message process "Generating union atlas arrays for all model textures"
python -c '
import json
from pathlib import Path
config = json.loads(Path("config.json").read_text(encoding="utf-8"))
model_paths = sorted(list(set(v["path"] for v in config.values() if v.get("generated") is False and "path" in v)))
union_atlas = []
for p in model_paths:
    path_obj = Path(p)
    if not path_obj.exists():
        continue
    try:
        data = json.loads(path_obj.read_text(encoding="utf-8"))
        textures = data.get("textures", {})
        if not isinstance(textures, dict):
            continue
        tex_refs = sorted(list(set(v for v in textures.values() if isinstance(v, str) and not v.startswith("#"))))
        png_paths = []
        for ref in tex_refs:
            ns, t_path = ref.split(":", 1) if ":" in ref else ("minecraft", ref)
            png_paths.append(f"./assets/{ns}/textures/{t_path}.png")
        union_atlas.append(png_paths)
    except Exception:
        pass
Path("scratch_files/union_atlas.temp").write_text(json.dumps(union_atlas), encoding="utf-8")
'
jq '
def intersects(a;b): any(a[]; . as $x | any(b[]; . == $x));

def mapatlas(set):
(set | unique) as $unique_set
| (map(if intersects(.; $unique_set) then . else empty end) | add + $unique_set | unique) as $new_set
| map(if intersects(.; $new_set) then empty else . end) + [$new_set];

[["./assets/minecraft/textures/0.png"]] +
reduce .[] as $entry ([]; mapatlas($entry))
' scratch_files/union_atlas.temp | sponge scratch_files/union_atlas.temp
total_union_atlas=($(jq -r 'length - 1' scratch_files/union_atlas.temp))

python generate_atlases.py

# generate terrain texture atlas
jq -cR 'split(",")' scratch_files/atlases.csv | jq -s 'map({("gmdl_atlas_" + .[0]): {"textures": ("textures/" + .[0])}}) | add' > scratch_files/atlases.json
jq -s '
.[0] as $atlases
| .[1] 
| .texture_data += $atlases
' scratch_files/atlases.json ./target/rp/textures/terrain_texture.json | sponge ./target/rp/textures/terrain_texture.json

status_message completion "All sprite sheets generated"
mv scratch_files/spritesheet/*.png ./target/rp/textures

# begin conversion
python convert_models.py "attachable_material=${attachable_material}" "block_material=${block_material}"
 # wait for all the jobs to finish

# write lang file US
status_message process "Writing en_US and en_GB lang files"
mkdir ./target/rp/texts
jq -r '

def format: (.[0:1] | ascii_upcase ) + (.[1:] | gsub( "_(?<a>[a-z])"; (" " + .a) | ascii_upcase));
.[]|"\("item.geyser_custom:" + .path_hash + ".name")=\(.item | format)"

' config.json | sponge ./target/rp/texts/en_US.lang

# copy US lang to GB
cp ./target/rp/texts/en_US.lang ./target/rp/texts/en_GB.lang

# write supported languages file
jq -n '["en_US","en_GB"]' | sponge ./target/rp/texts/languages.json
status_message completion "en_US and en_GB lang files written\n"

# Ensure images are in the correct color space
status_message process "Setting all images to png8"
python convert_png8.py
status_message completion "All images set to png8"

if [[ ${rename_model_files} == "true" ]]
then
    status_message process "Consolidating model files"
    python consolidate.py
fi

# attempt to merge with existing pack if input was provided
if test -f ${merge_input}; then
  mkdir inputbedrockpack
  status_message process "Decompressing input bedrock pack"
  unzip -q ${merge_input} -d ./inputbedrockpack
  status_message process "Merging input bedrock pack with generated bedrock assets"
  cp -n -r "./inputbedrockpack"/* './target/rp/'
  if test -f ./inputbedrockpack/textures/terrain_texture.json; then
    status_message process "Merging terrain texture files"
    jq -s '
    {
      "resource_pack_name": "geyser_custom",
      "texture_name": "atlas.terrain",
      "texture_data": (.[1].texture_data + .[0].texture_data)
    }
    ' ./target/rp/textures/terrain_texture.json ./inputbedrockpack/textures/terrain_texture.json | sponge ./target/rp/textures/terrain_texture.json
  fi
  if test -f ./inputbedrockpack/textures/item_texture.json; then
    status_message process "Merging item texture files"
    jq -s '
    {
      "resource_pack_name": "geyser_custom",
      "texture_name": "atlas.items",
      "texture_data": (.[1].texture_data + .[0].texture_data)
    }
    ' ./target/rp/textures/item_texture.json ./inputbedrockpack/textures/item_texture.json | sponge ./target/rp/textures/item_texture.json
  fi
  if test -f ./inputbedrockpack/texts/languages.json; then
    status_message process "Merging languages file"
    jq -s '.[0] + .[1] | unique' | sponge ./target/rp/texts/languages.json
  fi
  if test -f ./inputbedrockpack/texts/en_US.lang; then
    status_message process "Merging en_US lang file"
    cat ./inputbedrockpack/texts/en_US.lang >> ./target/rp/texts/en_US.lang
  fi
  if test -f ./inputbedrockpack/texts/en_GB.lang; then
    status_message process "Merging en_GB lang file"
    cat ./inputbedrockpack/texts/en_GB.lang >> ./target/rp/texts/en_GB.lang
  fi
  status_message critical "Deleting input bedrock pack scratch direcotry"
  rm -rf inputbedrockpack
  status_message completion "Input bedrock pack merged with generated assets\n"
fi

status_message process "Creating Geyser mappings in target directory"
echo
python generate_mappings.py

# Add sprites if sprites.json exists in the root pack
if [ -f sprites.json ]; then
  status_message process "Adding provided sprite paths from sprites.json"
  python -c '
import json, hashlib
from pathlib import Path
if Path("sprites.json").exists():
    sprites_data = json.loads(Path("sprites.json").read_text(encoding="utf-8"))
    sprite_hashes = []
    for item, entries in sprites_data.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            cmd = entry.get("custom_model_data", "")
            dmg = entry.get("damage_predicate", "")
            unb = entry.get("unbreakable", "")
            sprite = entry.get("sprite", "")
            item_suffix = item.split(":")[-1]
            predicate = f"{item_suffix}_c{cmd}_d{dmg}_u{unb}"
            entry_hash = hashlib.md5(predicate.encode("utf-8")).hexdigest()[:7]
            sprite_hashes.append(f"{sprite},{entry_hash}")
    Path("scratch_files/sprite_hashes.csv").write_text("\n".join(sprite_hashes) + "\n", encoding="utf-8")
'

  jq -cR 'split(",")' scratch_files/sprite_hashes.csv | jq -s 'map({("gmdl_" + .[1]): {"textures": .[0]}}) | add' > scratch_files/sprite_hashmap.json

  jq -s '
  .[0] as $icon_sprites
  | .[1] 
  | .texture_data += $icon_sprites
  ' scratch_files/sprite_hashmap.json ./target/rp/textures/item_texture.json | sponge ./target/rp/textures/item_texture.json
  
  jq -s '
  {
  "format_version": "1",
  "items": 
    ((.[0] | keys | map({(.): (.)}) | add) as $sprites | .[1].items | to_entries | map(
    (.key | split(":")[1]) as $item
    | .value | {("minecraft:" + $item): (map(
      .name as $name
      | .icon as $icon
      | .icon = ($sprites[($name)] // $icon)
    ))}
    ) | add)
  }
  ' scratch_files/sprite_hashmap.json ./target/geyser_mappings.json | sponge ./target/geyser_mappings.json
  
fi

if [[ -d "./staging" ]]; then
  ARMOR_CONVERSION="${ARMOR_CONVERSION:-true}" ARMOR_CONTENTS_DIR="${ARMOR_CONTENTS_DIR:-contents}" python manager.py
else
  cd ..
  ARMOR_CONVERSION="${ARMOR_CONVERSION:-true}" ARMOR_CONTENTS_DIR="${ARMOR_CONTENTS_DIR:-contents}" python manager.py
  cd ./staging
fi

# Deduplicate geyser_mappings.json entries (armor conversion may introduce duplicates)
if [ -f ./target/geyser_mappings.json ]; then
  status_message process "Deduplicating geyser_mappings.json entries"
  jq '
    .items |= (to_entries | map(.value |= unique) | from_entries)
  ' ./target/geyser_mappings.json | sponge ./target/geyser_mappings.json
fi

# ItemsAdder/Geyser postprocess fix: geometry texture sizes and missing armor player layers.
POSTPROCESS_SCRIPT="./itemsadder_postprocess.py"
if [ ! -f "$POSTPROCESS_SCRIPT" ] && [ -f "../itemsadder_postprocess.py" ]; then
  POSTPROCESS_SCRIPT="../itemsadder_postprocess.py"
fi
if [ -f "$POSTPROCESS_SCRIPT" ]; then
  status_message process "Applying ItemsAdder/Geyser texture and armor fixes"
  python "$POSTPROCESS_SCRIPT" "${1}" ./target/rp || python3 "$POSTPROCESS_SCRIPT" "${1}" ./target/rp || true
fi

# cleanup
rm -rf assets && rm -f pack.mcmeta && rm -f pack.png

ZIP_HELPER="./zip_pack.py"
if [ ! -f "$ZIP_HELPER" ] && [ -f "../zip_pack.py" ]; then
  ZIP_HELPER="../zip_pack.py"
fi

if [[ ${save_scratch} != "true" ]] 
then
  rm -rf scratch_files
  status_message critical "Deleted scratch files"
else
  python "$ZIP_HELPER" scratch_files ./target/scratch_files.zip
  status_message completion "Archived scratch files\n"
fi

status_message process "Compressing output packs"
mkdir -p ./target/packaged
python "$ZIP_HELPER" ./target/rp ./target/packaged/geyser_resources_preview.mcpack
python "$ZIP_HELPER" ./target/bp ./target/packaged/geyser_behaviors_preview.mcpack
python "$ZIP_HELPER" ./target/packaged ./target/packaged/geyser_addon.mcaddon "_preview.mcpack"

if [ -f ./target/rp/textures/terrain_texture.json ]; then
  jq 'delpaths([paths | select(.[-1] | strings | startswith("gmdl_atlas_"))])' ./target/rp/textures/terrain_texture.json | sponge ./target/rp/textures/terrain_texture.json
fi
python "$ZIP_HELPER" ./target/rp ./target/packaged/geyser_resources.mcpack

mkdir -p ./target/unpackaged
mv ./target/rp ./target/unpackaged/rp && mv ./target/bp ./target/unpackaged/bp

echo
printf "\e[32m[+]\e[m \e[1m\e[37mConversion Process Complete\e[m\n\n\e[37mExiting...\e[m\n\n"
