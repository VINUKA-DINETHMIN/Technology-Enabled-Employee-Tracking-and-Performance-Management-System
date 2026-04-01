#!/usr/bin/env python3
"""
Download FaceNet model for face verification.
Run this once after installation to get the pre-trained model.
"""

import os
import sys
from pathlib import Path
from urllib.request import urlretrieve

_ROOT = Path(__file__).resolve().parent
MODEL_DIR = _ROOT / "models"
MODEL_FILE = MODEL_DIR / "face_recognition_sface.onnx"

MODEL_URL = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/"
    "face_recognition_sface/face_recognition_sface_2021dec.onnx"
)

def download_facenet_model():
    """Download FaceNet model from GitHub."""
    
    print("\n" + "="*70)
    print("FaceNet Model Downloader")
    print("="*70 + "\n")
    
    # Check if already exists
    if MODEL_FILE.exists():
        size_mb = MODEL_FILE.stat().st_size / (1024 * 1024)
        print(f"✓ FaceNet model already exists: {MODEL_FILE} ({size_mb:.1f} MB)\n")
        return True
    
    # Create directory
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Downloading FaceNet model ({MODEL_URL})...")
    print(f"Destination: {MODEL_FILE}\n")
    
    try:
        def progress_hook(block_num, block_size, total_size):
            downloaded = block_num * block_size
            percent = min(downloaded * 100 // total_size, 100)
            mb = downloaded / (1024 * 1024)
            total_mb = total_size / (1024 * 1024)
            bar_width = 40
            filled = int(bar_width * percent // 100)
            bar = "█" * filled + "░" * (bar_width - filled)
            print(f"\r[{bar}] {percent}% ({mb:.1f}/{total_mb:.1f} MB)", end="", flush=True)
        
        urlretrieve(MODEL_URL, str(MODEL_FILE), progress_hook)
        print("\n\n✓ Download complete!\n")
        
        size_mb = MODEL_FILE.stat().st_size / (1024 * 1024)
        print(f"Model size: {size_mb:.1f} MB")
        print(f"Model path: {MODEL_FILE}\n")
        
        print("="*70)
        print("✓ FaceNet model ready for use")
        print("="*70 + "\n")
        return True
        
    except Exception as e:
        print(f"\n❌ Download failed: {e}\n")
        print("Manual download:")
        print(f"  URL: {MODEL_URL}")
        print(f"  Save to: {MODEL_FILE}\n")
        return False

if __name__ == "__main__":
    success = download_facenet_model()
    sys.exit(0 if success else 1)
