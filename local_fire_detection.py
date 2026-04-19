"""
Local Fire Detection Fallback
Uses OpenCV to detect fire-like colors when AWS API fails.
This is intentionally conservative to avoid misclassifying skin tones or warm indoor lighting.
"""

import cv2
import numpy as np


def detect_fire_color(image_bytes: bytes) -> dict:
    """
    Detect fire using HSV color and shape heuristics.
    Falls back to this when AWS API fails.
    """
    try:
        # Decode image
        nparr = np.frombuffer(image_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if frame is None:
            return {"error": "Could not decode image"}

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        ycrcb = cv2.cvtColor(frame, cv2.COLOR_BGR2YCrCb)

        # Define fire hue ranges (red/orange/yellow)
        lower_red1 = np.array([0, 120, 120])
        upper_red1 = np.array([10, 255, 255])
        lower_red2 = np.array([170, 120, 120])
        upper_red2 = np.array([180, 255, 255])
        lower_orange = np.array([10, 120, 120])
        upper_orange = np.array([25, 255, 255])
        lower_yellow = np.array([25, 120, 120])
        upper_yellow = np.array([35, 255, 255])

        mask_red1 = cv2.inRange(hsv, lower_red1, upper_red1)
        mask_red2 = cv2.inRange(hsv, lower_red2, upper_red2)
        mask_orange = cv2.inRange(hsv, lower_orange, upper_orange)
        mask_yellow = cv2.inRange(hsv, lower_yellow, upper_yellow)

        fire_mask = cv2.bitwise_or(mask_red1, mask_red2)
        fire_mask = cv2.bitwise_or(fire_mask, mask_orange)
        fire_mask = cv2.bitwise_or(fire_mask, mask_yellow)

        # Reduce noise and connect fire-like regions
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        fire_mask = cv2.morphologyEx(fire_mask, cv2.MORPH_OPEN, kernel, iterations=1)
        fire_mask = cv2.morphologyEx(fire_mask, cv2.MORPH_CLOSE, kernel, iterations=1)

        fire_pixels = cv2.countNonZero(fire_mask)
        total_pixels = max(1, frame.shape[0] * frame.shape[1])
        fire_percentage = (fire_pixels / total_pixels) * 100

        # Avoid false positives from skin tones and indoor lighting.
        # Skin tone detection in YCrCb can help reduce face-triggered alerts.
        lower_skin = np.array([0, 133, 77], dtype=np.uint8)
        upper_skin = np.array([255, 173, 127], dtype=np.uint8)
        skin_mask = cv2.inRange(ycrcb, lower_skin, upper_skin)
        skin_pixels = cv2.countNonZero(skin_mask)
        skin_percentage = (skin_pixels / total_pixels) * 100

        # Initialize variables
        mean_brightness = 0.0
        fire_detected = False

        if fire_percentage >= 2.5:
            # Require a reasonably bright fire-like region.
            fire_pixels_masked = cv2.bitwise_and(hsv, hsv, mask=fire_mask)
            brightness = fire_pixels_masked[:, :, 2]
            mean_brightness = float(np.mean(brightness[fire_mask > 0])) if fire_pixels > 0 else 0.0

            if mean_brightness >= 160:
                if not (skin_percentage > 8.0 and fire_percentage < 10.0):
                    # Evaluate shape and size of fire-like regions.
                    contours, _ = cv2.findContours(fire_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    if contours:
                        largest_area = max(cv2.contourArea(c) for c in contours)
                        fire_detected = fire_percentage > 5.0 or largest_area > max(2000.0, fire_pixels * 0.25)

        return {
            "fire_detected": bool(fire_detected),
            "fire_percentage": round(fire_percentage, 2),
            "skin_percentage": round(skin_percentage, 2),
            "brightness": round(mean_brightness, 2),
            "method": "local_hsv_detection",
            "message": (
                "Fire-like color detected" if fire_detected else "No strong fire signature found"
            ),
        }


    except Exception as e:
        return {
            "error": str(e),
            "fire_detected": False,
            "method": "local_detection_error",
        }


def test_local_detection():
    """Test with a simple image"""
    # Create a test image with some red/orange
    test_image = np.zeros((480, 640, 3), dtype=np.uint8)
    # Add a red rectangle (BGR format, so red is [0, 0, 255])
    cv2.rectangle(test_image, (100, 100), (300, 300), (0, 100, 255), -1)
    
    # Encode to JPEG
    success, img_bytes = cv2.imencode('.jpg', test_image)
    if success:
        result = detect_fire_color(img_bytes.tobytes())
        print("Local Detection Test:")
        print(f"  Fire Detected: {result.get('fire_detected')}")
        print(f"  Fire %: {result.get('fire_percentage')}")
        print(f"  Message: {result.get('message')}")
        return result
    return None


if __name__ == "__main__":
    test_local_detection()
