import zipfile, os, sys

# Only extract input_pack if it exists — converter.sh extracts pack/ directly
if os.path.exists("staging/input_pack.zip"):
    with zipfile.ZipFile("staging/input_pack.zip", "r") as file:
        file.extractall("pack/")

try: 
    if os.getenv("SOUNDS_CONVERSION") == "true": import sound
except Exception as e: print(e)
try:
    if os.getenv("MEG3_FIX") == "true": import meg3
except Exception as e: print(e)
try:
    if os.getenv("ARMOR_CONVERSION") == "true":
        import armor
        contents_dir = os.getenv("ARMOR_CONTENTS_DIR", "contents")
        armor.main([sys.argv[0], contents_dir] if len(sys.argv) < 2 else sys.argv)
except Exception as e: print(e)
try:
    if os.getenv("FONT_CONVERSION") == "true": import font
except Exception as e: print(e)
try:
    if os.getenv("BOW_CONVERSION") == "true": import bow
except Exception as e: print(e)
try:
    if os.getenv("SHIELD_CONVERSION") == "true": import shield
except Exception as e: print(e)
try:
    if os.getenv("BLOCK_CONVERSION") == "true": import blocks
except Exception as e: print(e)
