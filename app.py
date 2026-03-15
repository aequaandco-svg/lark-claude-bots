import os
import json
from flask import Flask, request, jsonify
import anthropic
import requests

app = Flask(__name__)

# ── Clients & config ──────────────────────────────────────────────────────────
claude  = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
APP_ID  = os.environ["LARK_APP_ID"]
APP_SECRET = os.environ["LARK_APP_SECRET"]

SYSTEM_PROMPT = (
    "You are Claude, an AI assistant embedded inside the Aequa & Co. Lark workspace. "
    "Aequa & Co. is a fine men's jewelry brand. Be helpful, concise, and professional. "
    "You assist with content creation, X (Twitter) post drafting, scheduling, "
    "analytics summaries, and general business tasks. "
    "When writing X posts keep them under 280 characters unless asked for a thread."
)

# ── Lark API helpers ──────────────────────────────────────────────────────────
def get_tenant_token():
    resp = requests.post(
        "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": APP_ID, "app_secret": APP_SECRET},
        timeout=10,
    )
    return resp.json().get("tenant_access_token", "")


def reply_to_chat(chat_id: str, text: str):
    token = get_tenant_token()
    requests.post(
        "https://open.larksuite.com/open-apis/im/v1/messages",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={
            "receive_id_type": "chat_id",
            "receive_id": chat_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}),
        },
        timeout=10,
    )


# ── Webhook endpoint ──────────────────────────────────────────────────────────
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True) or {}

    # 1. Lark URL-verification handshake (one-time, during setup)
    if data.get("type") == "url_verification":
        return jsonify({"challenge": data.get("challenge")})

    header     = data.get("header", {})
    event_type = header.get("event_type", "")

    # 2. Incoming message event
    if event_type == "im.message.receive_v1":
        event   = data.get("event", {})
        message = event.get("message", {})
        sender  = event.get("sender", {})

        # Ignore messages sent by bots (including ourselves)
        if sender.get("sender_type") == "app":
            return jsonify({"code": 0})

        # Only handle plain-text messages
        if message.get("message_type") != "text":
            return jsonify({"code": 0})

        content   = json.loads(message.get("content", "{}"))
        user_text = content.get("text", "").strip()

        # Strip @mention tags Lark injects (e.g. <at user_id="...">Claude</at>)
        import re
        user_text = re.sub(r"<at[^>]*>.*?</at>", "", user_text).strip()

        if not user_text:
            return jsonify({"code": 0})

        chat_id = message.get("chat_id", "")

        # Call Claude
        try:
            response = claude.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1500,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_text}],
            )
            reply_text = response.content[0].text
        except Exception as exc:
            reply_text = f"⚠️ Error reaching Claude: {exc}"

        reply_to_chat(chat_id, reply_text)

    return jsonify({"code": 0})


# ── Health check ──────────────────────────────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "bot": "lark-claude-bot"})


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
