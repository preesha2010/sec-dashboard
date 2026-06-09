from flask import Flask, render_template, jsonify, request
from database import init_db, get_db, save_scan, get_scans, get_last_scan
from datetime import datetime
import os

app = Flask(__name__)

init_db()   # initialize the database when the app starts

#   API endpoint - what scan.py calls after a scan is done
@app.route("/api/report", methods=["POST"])  # submitting scan report
def api_report():
    data = request.json # parse payload into python dict
    # validate report data fields
    required_fields = ["app_name", "repo", "push_time", "risk_level", "files_scanned", "report"]
    for f in required_fields:
        if f not in data:
            return jsonify({"error": f"Missing field: {f}"}), 400
    # save the scan report to the database   
    save_scan(data["app_name"], data["repo"], data["push_time"], data["risk_level"], data["files_scanned"], data["report"])
    return jsonify({"message": "Scan report saved successfully."}), 201

# Dashboard page
@app.route("/")
def dashboard():
    last = get_last_scan()  # get the most recent scan for each app
    all_scans = get_scans()
    return render_template("index.html", last=last, all_scans=all_scans)

# App history page
@app.route("/app/<app_name>")
def app_history(app_name):
    all_scans = get_scans()
    app_scans = [s for s in all_scans if s["app_name"]==app_name]
    return render_template("app_history.html", app_scans=app_scans)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=False)