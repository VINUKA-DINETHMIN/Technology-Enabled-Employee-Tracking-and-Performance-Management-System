# C2 — Facial Liveness Detection

Verifies that a real human face is present at login using MediaPipe + OpenCV.

## Owner
Team Member 2

## Dependencies
```
opencv-python
mediapipe
Pillow
pymongo
```

## Interface
- `run_liveness_check(user_id) -> bool` — returns True if a live face is detected

## How it works
1. Open webcam via OpenCV
2. Run MediaPipe FaceMesh to detect landmarks
3. Apply blink / head-movement challenge to confirm liveness
4. Return True on pass, False otherwise
