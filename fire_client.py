import json
import os
from typing import Any

import requests


DEFAULT_API_URL = "https://uy3abarouf.execute-api.ap-south-1.amazonaws.com/upload"


def get_api_url() -> str:
    return os.getenv("FIRE_API_URL", DEFAULT_API_URL)


def normalize_response_payload(response: requests.Response) -> dict[str, Any]:
    content_type = response.headers.get("Content-Type", "")

    if "application/json" in content_type:
        try:
            parsed = response.json()
            if isinstance(parsed, dict):
                return parsed
            return {"result": parsed}
        except ValueError:
            pass

    text = response.text.strip()
    if not text:
        return {"message": "Empty response from detection service"}

    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        parsed = None

    if isinstance(parsed, dict):
        return parsed

    return {"message": text}


def use_local_fallback(image_bytes: bytes) -> dict[str, Any]:
    """Fallback to local fire detection when AWS API fails"""
    try:
        from local_fire_detection import detect_fire_color
        payload = detect_fire_color(image_bytes)
        payload["fallback_method"] = True
        return payload
    except Exception as e:
        return {
            "error": f"Fallback detection failed: {str(e)}",
            "fire_detected": False,
            "status_code": 500,
            "fallback_method": True
        }


def send_image_bytes(image_bytes: bytes, timeout: int = 10, use_fallback: bool = True) -> dict[str, Any]:
    """
    Send image to AWS API, with optional fallback to local detection
    
    Args:
        image_bytes: JPEG image as bytes
        timeout: Request timeout in seconds
        use_fallback: Use local detection if AWS API fails
    
    Returns:
        Detection result dictionary
    """
    try:
        response = requests.post(
            get_api_url(),
            data=image_bytes,
            headers={"Content-Type": "image/jpeg"},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = normalize_response_payload(response)
        payload["status_code"] = response.status_code
        return payload
    except requests.exceptions.RequestException as e:
        # AWS API failed
        if use_fallback:
            print(f"⚠️  AWS API failed ({type(e).__name__}), using local fallback detection")
            return use_local_fallback(image_bytes)
        else:
            return {
                "error": f"AWS API failed: {str(e)}",
                "fire_detected": False,
                "status_code": 502
            }
