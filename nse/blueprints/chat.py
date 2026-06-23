from flask import Blueprint, request, jsonify

from ..ai import ask as ai_ask

chat_bp = Blueprint("chat", __name__, url_prefix="/chat")


@chat_bp.route("/ask", methods=["POST"])
def ask():
    data = request.get_json(silent=True) or {}
    messages = data.get("messages", [])
    # Keep only role/content and cap length for safety.
    clean = [
        {"role": m.get("role", "user"), "content": str(m.get("content", ""))[:2000]}
        for m in messages if m.get("content")
    ][-10:]
    if not clean:
        return jsonify({"reply": "Please type a question."})
    return jsonify({"reply": ai_ask(clean)})
