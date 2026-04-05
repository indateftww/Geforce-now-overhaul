"""Cyberpunk 2077 Companion - Breach Protocol Solver & Game Database (Web App)."""

import json
import webbrowser
import threading
from pathlib import Path

from flask import Flask, request, jsonify

from solver import solve_best_effort
from screen_monitor import monitor

BASE = Path(__file__).parent
DATA = BASE / "data"
PROGRESS_PATH = BASE / "progress.json"

app = Flask(__name__)

# Read HTML from external file
with open(BASE / "ui.html", "r", encoding="utf-8") as _f:
    HTML = _f.read()


# ─── Helpers ───────────────────────────────────────────────────────────

def load_json(path):
    """Load a JSON file, return empty list if it doesn't exist."""
    p = Path(path)
    if not p.exists():
        return []
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def load_progress():
    """Load progress file, create with defaults if missing."""
    if not PROGRESS_PATH.exists():
        return {"completed": []}
    with open(PROGRESS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_progress(data):
    """Save progress data to file."""
    with open(PROGRESS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ─── API Routes ────────────────────────────────────────────────────────

@app.route("/")
def index():
    return HTML


# Breach Protocol Solver
@app.route("/api/solve", methods=["POST"])
def api_solve():
    data = request.json
    matrix = data.get("matrix", [])
    sequences = data.get("sequences", [])
    buffer_size = data.get("buffer_size", 7)

    result = solve_best_effort(matrix, sequences, buffer_size)

    return jsonify({
        "ok": True,
        "path": result["path"],
        "values": result["values"],
        "matched": result["matched"],
        "score": result["score"],
    })


# Map Data
@app.route("/api/locations")
def api_locations():
    locations = load_json(DATA / "locations.json")
    category = request.args.get("category", "")
    if category:
        locations = [loc for loc in locations if loc.get("category") == category]
    return jsonify(locations)


@app.route("/api/categories")
def api_categories():
    return jsonify(load_json(DATA / "categories.json"))


# Progress Tracking
@app.route("/api/progress")
def api_progress():
    return jsonify(load_progress())


@app.route("/api/progress/toggle", methods=["POST"])
def api_progress_toggle():
    data = request.json
    location_id = data.get("location_id", "")
    progress = load_progress()

    if location_id in progress["completed"]:
        progress["completed"].remove(location_id)
    else:
        progress["completed"].append(location_id)

    save_progress(progress)
    return jsonify({"ok": True, "completed": progress["completed"]})


# Game Database
@app.route("/api/weapons")
def api_weapons():
    return jsonify(load_json(DATA / "weapons.json"))


@app.route("/api/cyberware")
def api_cyberware():
    return jsonify(load_json(DATA / "cyberware.json"))


@app.route("/api/quickhacks")
def api_quickhacks():
    return jsonify(load_json(DATA / "quickhacks.json"))


@app.route("/api/vehicles")
def api_vehicles():
    return jsonify(load_json(DATA / "vehicles.json"))


@app.route("/api/builds")
def api_builds():
    return jsonify(load_json(DATA / "builds.json"))


# Quest & Dialogue
@app.route("/api/quests")
def api_quests():
    return jsonify(load_json(DATA / "quests.json"))


@app.route("/api/dialogues")
def api_dialogues():
    return jsonify(load_json(DATA / "dialogues.json"))


# Search
@app.route("/api/search")
def api_search():
    q = request.args.get("q", "").lower()
    if not q:
        return jsonify([])

    results = []

    for quest in load_json(DATA / "quests.json"):
        name = quest.get("name", "")
        desc = quest.get("description", "")
        if q in name.lower() or q in desc.lower():
            results.append({"type": "quest", "item": quest})

    for dlg in load_json(DATA / "dialogues.json"):
        text = dlg.get("text", "")
        speaker = dlg.get("speaker", "")
        if q in text.lower() or q in speaker.lower():
            results.append({"type": "dialogue", "item": dlg})

    return jsonify(results)


# Screen Monitor / Overwatch
@app.route("/api/monitor/start", methods=["POST"])
def api_monitor_start():
    data = request.json or {}
    interval = data.get("interval", 2.0)
    region = data.get("region")  # [x, y, w, h] or null

    monitor.interval = max(0.5, min(interval, 10.0))
    if region and len(region) == 4:
        monitor.set_region(*region)

    result = monitor.start()
    return jsonify(result)


@app.route("/api/monitor/stop", methods=["POST"])
def api_monitor_stop():
    result = monitor.stop()
    return jsonify(result)


@app.route("/api/monitor/state")
def api_monitor_state():
    return jsonify(monitor.get_state())


@app.route("/api/monitor/snapshot", methods=["POST"])
def api_monitor_snapshot():
    """Take a single on-demand screenshot and analyze it."""
    result = monitor.take_single_screenshot()
    return jsonify(result)


@app.route("/api/monitor/capabilities")
def api_monitor_capabilities():
    """Report which monitor features are available."""
    return jsonify(monitor.capabilities)


@app.route("/api/monitor/region", methods=["POST"])
def api_monitor_region():
    """Set the screen capture region."""
    data = request.json
    x = data.get("x", 0)
    y = data.get("y", 0)
    w = data.get("width", 1920)
    h = data.get("height", 1080)
    monitor.set_region(x, y, w, h)
    return jsonify({"ok": True, "region": [x, y, w, h]})


# ─── Start ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = 2077
    print(f"\n  Cyberpunk Companion starting on http://localhost:{port}")
    print(f"  Opening in browser...\n")

    threading.Timer(1.0, lambda: webbrowser.open(f"http://localhost:{port}")).start()

    app.run(host="127.0.0.1", port=port, debug=False)
