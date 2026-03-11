# webhook_receiver.py
import os
import logging
import urllib.parse
from flask import Flask, request, jsonify, abort
import requests

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

VILOUD_UPLOAD = "https://api.viloud.tv/v1/videos"
VILOUD_API_KEY = os.environ.get("VILOUD_API_KEY")  # set in Render env
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET")  # set in Render env (optional)

def find_first_url(obj):
    if not obj:
        return None
    if isinstance(obj, str):
        if obj.startswith("http://") or obj.startswith("https://"):
            return obj
        return None
    if isinstance(obj, list):
        for item in obj:
            r = find_first_url(item)
            if r:
                return r
    if isinstance(obj, dict):
        # Prefer the exact Upload field if present
        fields = obj.get("Fields")
        if isinstance(fields, dict):
            upload = fields.get("UploadYourVideoSketchHERE")
            if isinstance(upload, dict):
                for key in ("Url", "UrlFull", "UrlFullSecure", "fileUrl", "url"):
                    if upload.get(key):
                        return upload.get(key)
            # fallback: search inside Fields
            r = find_first_url(fields)
            if r:
                return r
        # generic search
        for v in obj.values():
            r = find_first_url(v)
            if r:
                return r
    return None

@app.route("/cognito-webhook", methods=["POST"])
def cognito_webhook():
    # optional token check: https://your-service/cognito-webhook?token=SECRET
    token = request.args.get("token")
    if WEBHOOK_SECRET and token != WEBHOOK_SECRET:
        logging.warning("Unauthorized webhook call (bad token)")
        abort(403)

    try:
        raw_text = request.get_data(as_text=True)
        logging.info("Webhook raw body received")
        payload = None
        try:
            payload = request.get_json(force=True)
        except Exception:
            logging.warning("Payload not JSON-parsable")

        # find temp file URL
        temp_url = find_first_url(payload) if payload else None
        logging.info("Extracted temp file URL: %s", temp_url)

        if not temp_url:
            logging.error("No file URL found in payload. Raw payload logged.")
            logging.debug(raw_text)
            return jsonify({"error": "no_file_url"}), 400

        # Stream download from Cognito temp URL
        logging.info("Starting download from Cognito temp URL")
        r = requests.get(temp_url, stream=True, timeout=60)
        r.raise_for_status()

        filename = os.path.basename(urllib.parse.urlparse(temp_url).path) or "upload.mp4"
        files = {"file": (filename, r.raw, r.headers.get("Content-Type", "video/mp4"))}

        # metadata - try to get a title from fields
        title = None
        if payload and isinstance(payload, dict):
            try:
                title = payload.get("Fields", {}).get("EnterTheNameOfYourVideoSketch") or payload.get("EnterTheNameOfYourVideoSketch")
            except Exception:
                title = None
        data = {"title": title or filename, "description": "Uploaded via Cognito webhook"}

        headers = {"Authorization": f"Bearer {VILOUD_API_KEY}"} if VILOUD_API_KEY else {}

        logging.info("Uploading to ViLoud...")
        viloud_resp = requests.post(VILOUD_UPLOAD, headers=headers, files=files, data=data, timeout=300)
        viloud_resp.raise_for_status()
        viloud_json = viloud_resp.json()
        logging.info("ViLoud upload successful: %s", viloud_json.get("id"))

        # return success
        return jsonify({"status": "ok", "viloud": viloud_json}), 200

    except requests.exceptions.RequestException as e:
        logging.exception("Network error during download/upload")
        return jsonify({"error": "network", "message": str(e)}), 500
    except Exception as e:
        logging.exception("Unexpected error")
        return jsonify({"error": "unexpected", "message": str(e)}), 500

if __name__ == "__main__":
    # for local testing
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
A couple quick notes after you paste:

requirements.txt should include: Flask==2.2.5 requests==2.31.0 gunicorn==20.1.0
When you deploy on Render, set the environment variables VILOUD_API_KEY and WEBHOOK_SECRET (the secret is optional but recommended).
After Render deploy, update your Cognito SubmitEndpoint to: https://your-service.onrender.com/cognito-webhook?token=YOUR_SECRET
