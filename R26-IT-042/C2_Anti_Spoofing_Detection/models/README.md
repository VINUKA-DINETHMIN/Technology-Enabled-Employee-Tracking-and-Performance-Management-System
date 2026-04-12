# Anti-Spoofing Model Files

## Expected Model

**File name:** `best_anti_spoofing_model.keras`

This is the trained ResNet50 anti-spoofing model that detects whether a face is real or fake.

### Model Details
- **Architecture:** ResNet50 (transfer learning)
- **Input:** 96×96 RGB images
- **Output:** Binary classification (0 = Real, 1 = Fake)
- **Training:** Trained on real selfies, live videos vs. printouts, cut-outs, replay videos
- **Format:** TensorFlow Keras (.keras)

### How to Deploy

1. Train the model using the provided training scripts (Script 2 recommended)
2. Export the model as `best_anti_spoofing_model.keras`
3. Place it in this folder: `C2_Anti_Spoofing_Detection/models/`

### Usage

The `AntiSpoofingDetector` class in `src/antispoofing_detector.py` will automatically load the model from this location.

```python
from C2_Anti_Spoofing_Detection.src.antispoofing_detector import AntiSpoofingDetector

detector = AntiSpoofingDetector()
if detector.load_model():
    is_real, confidence, reason = detector.predict(frame)
    print(f"Real: {is_real}, Confidence: {confidence:.2f}")
```

### Model Training

Refer to the training scripts in the parent directory:
- `Script 2`: Recommended comprehensive training with model comparison (ResNet50, MobileNetV2, CNN)

The trained model should achieve:
- **Test Accuracy:** >95%
- **Real Detection Rate:** >95% (minimize false positives on actual faces)
- **Fake Detection Rate:** >95% (catches printouts & replays)
