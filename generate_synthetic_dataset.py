#!/usr/bin/env python3
import os
import sys
import base64
import requests
import random
from PIL import Image, ImageEnhance, ImageFilter

# 1. Config paths
ENV_PATH = "/Users/nsaviour/.hermes/.env"
OUTPUT_DIR = "/Users/nsaviour/Project/AppleProject/Mosquito-finder/data/synthetic"

os.makedirs(OUTPUT_DIR, exist_ok=True)

# 2. Parse API Key
api_key = None
if os.path.exists(ENV_PATH):
    with open(ENV_PATH, "r") as f:
        for line in f:
            if line.startswith("GOOGLE_API_KEY="):
                api_key = line.split("=", 1)[1].strip()
                break

if not api_key:
    print("Error: GOOGLE_API_KEY not found in ~/.hermes/.env", file=sys.stderr)
    sys.exit(1)

# 3. Define target samples
# 3 positive, 6 negative, 2 hard negative
targets = [
    # --- Positive Samples ---
    {
        "filename": "20260524_AI_whitewall_1x_torchon_mosquito_001.jpg",
        "prompt": "Macro close-up shot of a single mosquito resting on a plain white wall, sharp focus on its body, legs, and wings, realistic lighting, macro photography."
    },
    {
        "filename": "20260524_AI_wooddoor_1x_torchon_mosquito_002.jpg",
        "prompt": "A mosquito resting on a brown wooden door surface, oblique angle view, medium shot, natural indoor lighting with slight shadows, photorealistic."
    },
    {
        "filename": "20260524_AI_curtain_1x_torchon_mosquito_003.jpg",
        "prompt": "A mosquito sitting on a fabric curtain texture, side view, macro photography, soft indoor lighting, detailed fibers."
    },
    # --- Negative Samples ---
    {
        "filename": "20260524_AI_whitewall_1x_torchon_notmosquito_001.jpg",
        "prompt": "A close-up photograph of a small dark nail hole and plaster crack on a white-painted wall, detailed texture."
    },
    {
        "filename": "20260524_AI_whitewall_1x_torchon_notmosquito_002.jpg",
        "prompt": "A small black dirt smudge or stain on a light grey wall surface, micro-lens focus."
    },
    {
        "filename": "20260524_AI_tile_1x_torchon_notmosquito_003.jpg",
        "prompt": "A single small black ant walking on a clean bathroom ceramic tile, macro photography."
    },
    {
        "filename": "20260524_AI_ceiling_1x_torchon_notmosquito_004.jpg",
        "prompt": "A tiny fruit fly resting on a plain white ceiling, close-up shot."
    },
    {
        "filename": "20260524_AI_curtain_1x_torchon_notmosquito_005.jpg",
        "prompt": "A small dark speck of dust or lint resting on a fabric curtain texture, detailed close-up."
    },
    {
        "filename": "20260524_AI_whitewall_1x_torchon_notmosquito_006.jpg",
        "prompt": "Close-up of a small dark paint splatter or bubble defect on a drywall surface."
    },
    # --- Hard Negative Samples ---
    {
        "filename": "20260524_AI_whitewall_1x_torchon_hardnegative_001.jpg",
        "prompt": "A small irregular peeling paint chip and dark crack on a wall under low-light high-contrast shadow, resembling a small insect shape."
    },
    {
        "filename": "20260524_AI_wooddoor_1x_torchon_hardnegative_002.jpg",
        "prompt": "A dark knot or small splinter on a wooden surface with strong direct flashlight illumination (torch light), creating deep shadows that mimic thin legs."
    }
]

def generate_image_google(prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-4.0-generate-001:predict?key={api_key}"
    payload = {
        "instances": [
            {"prompt": prompt}
        ],
        "parameters": {
            "sampleCount": 1,
            "aspectRatio": "1:1",
            "outputMimeType": "image/jpeg"
        }
    }
    
    # Retry logic up to 3 times
    for attempt in range(1, 4):
        try:
            response = requests.post(url, json=payload, timeout=45)
            if response.status_code == 200:
                data = response.json()
                pred = data["predictions"][0]
                img_data = base64.b64decode(pred["bytesBase64Encoded"])
                return img_data
            else:
                print(f"  [Attempt {attempt}] HTTP Error {response.status_code}: {response.text[:200]}", file=sys.stderr)
        except Exception as e:
            print(f"  [Attempt {attempt}] Exception: {e}", file=sys.stderr)
    return None

def augment_image(img_path, base_filename):
    """
    Apply traditional image augmentation to produce 5 variants.
    """
    img = Image.open(img_path)
    
    # Variant A: Torch on (Simulate direct flashlight)
    # Increase brightness and contrast
    enhancer_b = ImageEnhance.Brightness(img)
    img_b = enhancer_b.enhance(1.4)
    enhancer_c = ImageEnhance.Contrast(img_b)
    img_a = enhancer_c.enhance(1.2)
    path_a = os.path.join(OUTPUT_DIR, base_filename.replace(".jpg", "_varA_torchon.jpg"))
    img_a.save(path_a, "JPEG")
    
    # Variant B: Low light / Shadows (Simulate low-light indoor environment)
    enhancer_b2 = ImageEnhance.Brightness(img)
    img_b_low = enhancer_b2.enhance(0.5)
    path_b = os.path.join(OUTPUT_DIR, base_filename.replace(".jpg", "_varB_lowlight.jpg"))
    img_b_low.save(path_b, "JPEG")
    
    # Variant C: Real World Mosquito Simulation (Tiny dark spot with 3D drop shadow)
    # This simulates a mosquito illuminated by a flashlight, casting a tiny shadow
    img_sim = img.convert("RGBA")
    sim_width, sim_height = img_sim.size
    
    # Create a clean white/gray background to overlay the fake dot on
    bg = Image.new("RGBA", (sim_width, sim_height), (230, 230, 230, 255))
    
    # Create the "mosquito" (a small 5x5 to 10x10 dark blob)
    dot_size = random.randint(4, 8)
    shadow_offset_x = random.randint(2, 6) # Flashlight from side
    shadow_offset_y = random.randint(2, 6)
    
    from PIL import ImageDraw
    draw = ImageDraw.Draw(bg)
    
    center_x = random.randint(30, sim_width - 30)
    center_y = random.randint(30, sim_height - 30)
    
    # Draw faint shadow first
    draw.ellipse([center_x + shadow_offset_x - dot_size/2, 
                  center_y + shadow_offset_y - dot_size/2, 
                  center_x + shadow_offset_x + dot_size/2, 
                  center_y + shadow_offset_y + dot_size/2], 
                 fill=(50, 50, 50, 100))
    
    # Draw core body
    draw.ellipse([center_x - dot_size/2, 
                  center_y - dot_size/2, 
                  center_x + dot_size/2, 
                  center_y + dot_size/2], 
                 fill=(10, 10, 10, 255))
    
    # Composite over original heavily blurred image (to simulate out-of-focus background)
    blurred_base = img.filter(ImageFilter.GaussianBlur(radius=5)).convert("RGBA")
    final_sim = Image.alpha_composite(blurred_base, bg).convert("RGB")
    
    path_c = os.path.join(OUTPUT_DIR, base_filename.replace(".jpg", "_varC_3dshadow.jpg"))
    final_sim.save(path_c, "JPEG")
    
    # Variant D: Noise (Simulate camera high-ISO digital noise)
    img_noise = img.convert("RGB")
    pixels = img_noise.load()
    width, height = img_noise.size
    # Corrupt around 1.5% pixels with random salt/pepper
    for _ in range(int(width * height * 0.015)):
        x = random.randint(0, width - 1)
        y = random.randint(0, height - 1)
        if random.random() < 0.5:
            pixels[x, y] = (0, 0, 0)
        else:
            pixels[x, y] = (255, 255, 255)
    path_d = os.path.join(OUTPUT_DIR, base_filename.replace(".jpg", "_varD_noise.jpg"))
    img_noise.save(path_d, "JPEG")
    
    # Variant E: Spatial (Simulate horizontal flip & 90 deg rotation)
    img_spatial = img.transpose(Image.FLIP_LEFT_RIGHT).transpose(Image.ROTATE_90)
    path_e = os.path.join(OUTPUT_DIR, base_filename.replace(".jpg", "_varE_spatial.jpg"))
    img_spatial.save(path_e, "JPEG")
    
    print(f"  -> Generated 5 augmented variants for {base_filename}")

def main():
    print("================================================================================")
    print("Mosquito Finder Dataset Synthetic Generator & Augmenter (0.2% -> 1.0%)")
    print("================================================================================")
    print(f"Target directory: {OUTPUT_DIR}")
    print(f"Total AI base images to generate: {len(targets)}")
    
    success_count = 0
    for idx, target in enumerate(targets, 1):
        filename = target["filename"]
        prompt = target["prompt"]
        out_path = os.path.join(OUTPUT_DIR, filename)
        
        print(f"\n[{idx}/{len(targets)}] Generating: {filename}")
        print(f"  Prompt: \"{prompt}\"")
        
        img_bytes = generate_image_google(prompt)
        if img_bytes:
            with open(out_path, "wb") as f:
                f.write(img_bytes)
            print(f"  Successfully saved base image to {out_path}")
            
            # Apply Augmentations
            augment_image(out_path, filename)
            success_count += 1
        else:
            print(f"  FAILED to generate image {filename} after all attempts.", file=sys.stderr)
            
    print("\n================================================================================")
    print(f"Generation completed! Successfully processed {success_count}/{len(targets)} base images.")
    print(f"Total images in dataset folder: {len(os.listdir(OUTPUT_DIR))}")
    print("================================================================================")

if __name__ == "__main__":
    main()
