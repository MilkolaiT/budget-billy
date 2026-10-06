import os
import base64
import requests
import jwt
from datetime import datetime, timezone
from flask import Flask, jsonify

app = Flask(__name__)

ENABLE_BANKING_API = "https://api.enablebanking.com"


def create_enable_banking_token():
    app_id = os.environ["ENABLE_BANKING_APP_ID"]
    private_key_b64 = os.environ["ENABLE_BANKING_PRIVATE_KEY_B64"]

    private_key = base64.b64decode(private_key_b64)

    now = int(datetime.now(timezone.utc).timestamp())

    return jwt.encode(
        {
            "iss": "enablebanking.com",
            "aud": "api.enablebanking.com",
            "iat": now,
            "exp": now + 3600,
        },
        private_key,
        algorithm="RS256",
        headers={
            "typ": "JWT",
            "kid": app_id,
        },
    )


@app.get("/")
def home():
    return jsonify({
        "service": "Budget Billy",
        "status": "online"
    })


@app.get("/health")
def health():
    return jsonify({
        "status": "ok"
    })


@app.get("/enable-banking/status")
def enable_banking_status():
    try:
        token = create_enable_banking_token()

        response = requests.get(
            f"{ENABLE_BANKING_API}/application",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            timeout=30,
        )

        if response.status_code != 200:
            return jsonify({
                "connected": False,
                "http_status": response.status_code
            }), 502

        data = response.json()

        return jsonify({
            "connected": True,
            "application": data.get("name"),
            "environment": data.get("environment"),
            "services": data.get("services")
        })

    except Exception as exc:
        return jsonify({
            "connected": False,
            "error": type(exc).__name__
        }), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
