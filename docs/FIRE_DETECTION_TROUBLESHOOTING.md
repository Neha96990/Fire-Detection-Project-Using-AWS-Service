# 🔥 Fire Detection Troubleshooting Guide

## Problem: Fire Not Being Detected Properly

Follow these steps to diagnose and fix the issue:

---

## **1. VERIFY AWS API ENDPOINT**

### Quick Test with PowerShell:
```powershell
# Test if API is accessible
$api_url = "https://uy3abarouf.execute-api.ap-south-1.amazonaws.com/upload"
curl -X POST -H "Content-Type: image/jpeg" --data "test" $api_url
```

### What to Look For:
- ✅ Status 200-299: API is working
- ❌ 404: Wrong endpoint URL
- ❌ 502/503: API/Lambda is down
- ❌ Timeout: Network/firewall issue

### Fix:
If the endpoint is unreachable:
1. Check `.env` file: `FIRE_API_URL` is correct
2. Verify AWS credentials in your environment
3. Check AWS API Gateway CloudWatch logs
4. Verify Lambda function is deployed and active

---

## **2. CHECK RESPONSE FORMAT**

Run the Python debug script:
```powershell
cd "d:\Python Projects\Fire Detection using AWS"
.\.venv\Scripts\Activate.ps1
python debug_fire_detection.py
```

### Expected AWS API Response Should Include One Of:
```json
{
  "fire_detected": true
}
```
or
```json
{
  "message": "Fire detected"
}
```
or
```json
{
  "label": "fire"
}
```

### Common Issues:
- ❌ Empty response `{}` - Lambda not processing correctly
- ❌ Wrong key names - Detection logic won't parse it
- ❌ Error response - Lambda has a bug

---

## **3. ENABLE DETAILED LOGGING**

Update `.env`:
```env
FLASK_DEBUG=true
```

Restart the app and check Flask logs for:
- API response content
- Detection signal parsing results
- Error messages

### Add Logging to app.py (Line ~515):

Replace this line:
```python
detection = send_image_bytes(image_bytes)
```

With this:
```python
detection = send_image_bytes(image_bytes)
print(f"DEBUG: API Response = {detection}", flush=True)  # Add this line
```

---

## **4. TEST RESPONSE PARSING**

Your `detect_fire_signal()` function looks for these patterns:

| Response Format | Will Be Detected? |
|---|---|
| `{"fire_detected": true}` | ✅ YES |
| `{"message": "Fire detected"}` | ✅ YES |
| `{"label": "flame"}` | ✅ YES |
| `{"result": "smoke alert"}` | ✅ YES |
| `{"status": "no fire"}` | ✅ NO (negative) |
| `{}` | ❌ NO |
| `{"error": "..."}` | ❌ NO |

**If your AWS Lambda returns a different format**, you need to update the detection logic.

---

## **5. UPDATE DETECTION LOGIC (If Needed)**

If your AWS API returns a response that's not being recognized, modify the `detect_fire_signal()` function in `app.py` around **line 308**:

### Example: If API returns `{"confidence": 0.9, "prediction": "fire"}`
```python
FIRE_KEYS = {
    "fire", "fire_detected", "has_fire", "smoke", "smoke_detected", 
    "flame_detected", "confidence"  # ADD THIS
}
```

### Example: If API returns confidence threshold
```python
def detect_fire_signal(value: Any) -> bool:
    # Check for numeric confidence score
    if isinstance(value, (int, float)):
        return value > 0.5  # Adjust threshold as needed
    
    # ... rest of existing logic ...
```

---

## **6. TEST LOCALLY WITHOUT AWS**

### Option A: Mock the API Response

Create `test_fire_detection_local.py`:
```python
import requests
from fire_client import normalize_response_payload
from app import detect_fire_signal

# Test different AWS response formats
test_responses = [
    {"fire_detected": True},
    {"message": "Fire detected in frame"},
    {"label": "flame", "confidence": 0.95},
    {"status": "Area is clear"},
    {"error": "Model error"},
]

for response in test_responses:
    result = detect_fire_signal(response)
    print(f"{response} => Fire: {result}")
```

Run it:
```powershell
python test_fire_detection_local.py
```

### Option B: Test with a Real Image File

If you have test images:
```powershell
python -c "
import cv2
from fire_client import send_image_bytes

img = cv2.imread('path/to/test_image.jpg')
success, img_bytes = cv2.imencode('.jpg', img)
if success:
    response = send_image_bytes(img_bytes.tobytes())
    print(response)
"
```

---

## **7. VERIFY AWS LAMBDA FUNCTION**

Check AWS Console:
1. Go to Lambda → Functions
2. Find the fire detection function
3. Check recent invocations
4. View CloudWatch logs

### Check for Errors:
- Missing dependencies (e.g., PyTorch, TensorFlow)
- Model file not uploaded
- Incorrect input/output format
- Timeout issues

---

## **8. BROWSER DEVELOPER CONSOLE**

1. Open your web app (http://localhost:5000)
2. Press `F12` → Console tab
3. Click "Start Live Scan"
4. Check console output:

```javascript
// You should see this in Console:
Request: POST /analyze-frame
Response: {
  "ok": true,
  "detection": {...},
  "fire_detected": false,
  ...
}
```

If you see **401** or **error**, check Flask server logs.

---

## **9. CHECKLIST**

- [ ] AWS API endpoint is reachable
- [ ] AWS API returns valid JSON
- [ ] Response contains expected keys/values
- [ ] Flask receives detection results
- [ ] Detection logic correctly parses response
- [ ] Frontend displays results correctly
- [ ] Camera permission granted
- [ ] Network connection stable

---

## **10. COMMON FIXES**

### Fix 1: Wrong API URL
```env
FIRE_API_URL=https://correct-url.execute-api.region.amazonaws.com/stage/endpoint
```

### Fix 2: AWS Lambda Returns Wrong Format
Modify the Lambda function to return:
```json
{
  "fire_detected": true,
  "message": "Fire signal detected in the image",
  "confidence": 0.95
}
```

### Fix 3: API Timeout
Increase timeout in `fire_client.py` (line 43):
```python
timeout=30  # Was 10, now 30 seconds
```

### Fix 4: Update Fire Detection Keywords
Edit `app.py` around line 300 to add your AWS response keywords:
```python
FIRE_KEYS = {"fire", "fire_detected", "has_fire", "smoke", ...}
```

---

## **NEXT STEPS**

1. **Run the debug script**: `python debug_fire_detection.py`
2. **Check the response**: What does AWS API actually return?
3. **Update detection logic**: Modify `app.py` if response format is different
4. **Test again**: Restart app and check if fire is now detected
5. **Enable logging**: Set `FLASK_DEBUG=true` for detailed logs

---

## **Need Help?**

If detection still doesn't work:
1. Share the AWS API response from the debug script
2. Check CloudWatch logs for Lambda errors
3. Verify your ML model is correctly deployed
4. Test with known fire/non-fire images

