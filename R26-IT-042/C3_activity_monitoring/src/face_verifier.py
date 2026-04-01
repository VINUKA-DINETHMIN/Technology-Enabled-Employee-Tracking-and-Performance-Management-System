"""
R26-IT-042 — Employee Activity Monitoring System
C3_activity_monitoring/src/face_verifier.py

FaceVerifier — Face embedding + verification using FaceNet (OpenCV DNN)
Pre-trained model: face_recognition_sface.onnx (1.7 MB)
128-dimensional embeddings with cosine similarity matching.

Usage:
  >>> verifier = FaceVerifier(model_path="models/face_recognition_sface.onnx")
  >>> embedding = verifier.get_embedding(frame)  # numpy array or None
  >>> is_match, score = verifier.verify(live_frame, stored_embedding, threshold=0.85)
"""

from __future__ import annotations

import logging
import numpy as np
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class FaceVerifier:
    """
    FaceNet-based face verification using OpenCV FaceRecognizerSF.
    
    Features:
    - Pre-trained 128-dimensional embeddings (SFaceNet)
    - Cosine similarity matching (>= 0.85 = match)
    - Fast inference (~50ms per frame)
    - Robust to lighting, pose, expression
    - On-device (no cloud calls)
    
    Requirements:
    - opencv-contrib-python (cv2.FaceRecognizerSF)
    - Model file: face_recognition_sface.onnx (1.7 MB)
    """

    def __init__(self, model_path: str | Path = "models/face_recognition_sface.onnx") -> None:
        """
        Initialize FaceNet verifier.
        
        Args:
            model_path: Path to face_recognition_sface.onnx model file
        
        Raises:
            FileNotFoundError: If model file not found
            RuntimeError: If FaceRecognizerSF not available (need opencv-contrib-python)
        """
        self.model_path = Path(model_path)
        self.recognizer = None
        self._initialized = False
        
        try:
            import cv2
            if not hasattr(cv2, 'FaceRecognizerSF'):
                raise RuntimeError(
                    "cv2.FaceRecognizerSF not available. "
                    "Install: pip install opencv-contrib-python"
                )
            
            if not self.model_path.exists():
                raise FileNotFoundError(
                    f"FaceNet model not found: {self.model_path}\n"
                    f"Download: wget -O {self.model_path} "
                    f"'https://github.com/opencv/opencv_zoo/raw/main/models/"
                    f"face_recognition_sface/face_recognition_sface_2021dec.onnx'"
                )
            
            # Load the pre-trained FaceNet model
            self.recognizer = cv2.FaceRecognizerSF.create(str(self.model_path), "")
            self._initialized = True
            logger.info(
                f"FaceVerifier initialized with model: {self.model_path} "
                f"(128-dim embeddings)"
            )
            
        except (ImportError, RuntimeError, FileNotFoundError) as e:
            logger.error(f"FaceVerifier initialization failed: {e}")
            self._initialized = False
            raise

    def get_embedding(
        self, 
        frame: np.ndarray,
        detection_box: Optional[np.ndarray] = None,
    ) -> Optional[np.ndarray]:
        """
        Extract 128-dimensional face embedding from frame.
        
        Args:
            frame: BGR image from cv2.VideoCapture
            detection_box: Optional bbox (x, y, w, h) if already detected.
                          If None, expects single centered face.
        
        Returns:
            128-dim numpy array (float32) or None if no face or error
        """
        if not self._initialized or self.recognizer is None:
            return None
        
        try:
            import cv2
            
            h, w = frame.shape[:2]

            if detection_box is not None:
                x, y, box_w, box_h = [int(v) for v in np.array(detection_box).flatten()[:4]]
                x, y = max(0, x), max(0, y)
                box_w = min(box_w, w - x)
                box_h = min(box_h, h - y)
                if box_w <= 0 or box_h <= 0:
                    return None
                face_roi = frame[y:y + box_h, x:x + box_w]
            else:
                # For already-cropped registration images, use full frame.
                face_roi = frame

            if face_roi is None or face_roi.size == 0:
                return None

            # Normalize lighting so live webcam frames are closer to stored registration crops.
            gray = cv2.cvtColor(face_roi, cv2.COLOR_BGR2GRAY)
            gray = cv2.equalizeHist(gray)
            face_input = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

            # SFace expects canonical face-like input size.
            face_input = cv2.resize(face_input, (112, 112), interpolation=cv2.INTER_AREA)
            embedding = self.recognizer.feature(face_input)
            
            # Flatten to 1D and return
            return embedding.flatten().astype(np.float32)
            
        except Exception as e:
            logger.debug(f"Failed to extract embedding: {e}")
            return None

    def cosine_similarity(
        self, 
        embedding1: np.ndarray, 
        embedding2: np.ndarray,
    ) -> float:
        """
        Compute cosine similarity between two 128-dim embeddings.
        
        Args:
            embedding1: 128-dim array
            embedding2: 128-dim array
        
        Returns:
            Float in range [-1, 1]. 1.0 = identical, 0.0 = orthogonal, -1.0 = opposite
        """
        try:
            e1 = np.array(embedding1, dtype=np.float32).flatten()
            e2 = np.array(embedding2, dtype=np.float32).flatten()
            
            if e1.size != e2.size:
                # Pad to match length
                min_len = min(len(e1), len(e2))
                e1, e2 = e1[:min_len], e2[:min_len]
            
            norm1 = np.linalg.norm(e1)
            norm2 = np.linalg.norm(e2)
            
            if norm1 < 1e-6 or norm2 < 1e-6:
                return 0.0
            
            return float(np.dot(e1, e2) / (norm1 * norm2))
            
        except Exception as e:
            logger.warning(f"Cosine similarity computation failed: {e}")
            return 0.0

    def verify(
        self,
        live_frame: np.ndarray,
        stored_embedding: list | np.ndarray,
        threshold: float = 0.85,
        detection_box: Optional[np.ndarray] = None,
    ) -> Tuple[bool, float]:
        """
        Verify if live frame matches stored embedding.
        
        Args:
            live_frame: Current BGR frame from webcam
            stored_embedding: Stored 128-dim embedding (list or numpy array)
            threshold: Similarity threshold for match (default: 0.85)
            detection_box: Optional bbox if face already detected
        
        Returns:
            (is_match: bool, similarity_score: float)
            Example: (True, 0.92) means match with 92% similarity
        """
        if not self._initialized:
            return False, 0.0
        
        live_emb = self.get_embedding(live_frame, detection_box)
        if live_emb is None:
            return False, 0.0
        
        stored_emb = np.array(stored_embedding, dtype=np.float32).flatten()
        score = self.cosine_similarity(live_emb, stored_emb)
        
        is_match = score >= threshold
        return is_match, round(score, 4)

    def embeddings_distance(
        self,
        embedding1: list | np.ndarray,
        embedding2: list | np.ndarray,
    ) -> float:
        """
        Compute distance metric between embeddings (1 - cosine_similarity).
        Useful for clustering or threshold tuning.
        
        Args:
            embedding1: 128-dim array
            embedding2: 128-dim array
        
        Returns:
            Float in range [0, 2]. 0 = identical, 2 = opposite.
        """
        similarity = self.cosine_similarity(embedding1, embedding2)
        return round(1.0 - similarity, 4)

    def close(self) -> None:
        """Release resources."""
        self.recognizer = None
        self._initialized = False
