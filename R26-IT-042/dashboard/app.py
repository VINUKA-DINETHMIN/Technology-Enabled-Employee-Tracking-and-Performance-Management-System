"""
R26-IT-042 — Employee Activity Monitoring System
dashboard/app.py

Flask web dashboard for real-time monitoring.
Serves the HTML templates and exposes a REST API for alert data.

Run with:
    python dashboard/app.py
    # or
    uvicorn dashboard.app:app --reload   (if refactored to FastAPI)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from flask import Flask, render_template, jsonify

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import settings
from common.database import MongoDBClient

app = Flask(__name__, template_folder="templates")

# Lazy DB connection
_db: MongoDBClient | None = None


def get_db() -> MongoDBClient:
    global _db
    if _db is None or not _db.is_connected:
        _db = MongoDBClient(uri=settings.MONGO_URI)
        _db.connect()
    return _db


@app.route("/")
def index():
    """Dashboard home — overview of active sessions."""
    return render_template("index.html", app_name=settings.APP_NAME)


@app.route("/alerts")
def alerts_page():
    """Alert log page."""
    return render_template("alerts.html", app_name=settings.APP_NAME)


@app.route("/productivity")
def productivity_page():
    """Productivity scores page."""
    return render_template("productivity.html", app_name=settings.APP_NAME)


@app.route("/api/alerts")
def api_alerts():
    """REST endpoint returning the 50 most recent alerts as JSON."""
    col = get_db().get_collection("alerts")
    if col is None:
        return jsonify({"error": "Database unavailable"}), 503
    docs = list(col.find({}, {"_id": 0}).sort("timestamp", -1).limit(50))
    return jsonify(docs)


@app.route("/api/sessions")
def api_sessions():
    """REST endpoint returning active sessions."""
    col = get_db().get_collection("sessions")
    if col is None:
        return jsonify({"error": "Database unavailable"}), 503
    docs = list(col.find({"status": "active"}, {"_id": 0}).limit(20))
    return jsonify(docs)


if __name__ == "__main__":
    app.run(debug=True, port=5000, host="0.0.0.0")
