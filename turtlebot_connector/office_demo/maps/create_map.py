from pathlib import Path
from PIL import Image, ImageFilter

print("=== INICIO SCRIPT ===")

BASE_DIR = Path(__file__).resolve().parent
input_path = BASE_DIR / "office_floorplan.png"
output_path = BASE_DIR / "office_map.pgm"

print(f"Script en: {BASE_DIR}")
print(f"Entrada existe: {input_path.exists()} -> {input_path}")
print(f"Salida prevista: {output_path}")

if not input_path.exists():
    raise FileNotFoundError(f"No encuentro la imagen: {input_path}")

img = Image.open(input_path).convert("L")
print(f"Imagen cargada correctamente: {img.size}")

map_img = img.point(lambda p: 0 if p < 180 else 254)
map_img = map_img.filter(ImageFilter.MinFilter(3))

map_img.save(output_path)

print(f"Guardado ejecutado: {output_path}")
print(f"Salida existe ahora: {output_path.exists()}")
print("=== FIN SCRIPT ===")