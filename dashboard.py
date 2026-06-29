from flask import Flask, render_template, jsonify, request, Response
from database import init_db, get_db, save_scan, get_scans, get_last_scan
from datetime import datetime
import psycopg2
import os
import re
import io
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.enums import TA_LEFT, TA_CENTER

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
    save_scan(data["app_name"], data["repo"], 
    data["push_time"], data["risk_level"], data["files_scanned"], data["report"])
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
    return render_template("app_history.html", app_name=app_name, scans=app_scans)

@app.route("/app/<app_name>/download/<int:scan_id>")
def download_report(app_name, scan_id):
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM scans WHERE id = %s AND app_name = %s", (scan_id, app_name))
    scan = cur.fetchone()
    cur.close()
    conn.close()

    if not scan:
        return jsonify({"error": "Scan not found"}), 404

    # ── colour palette (matches dashboard dark theme) ──
    BLACK      = colors.HexColor("#0d0d0d")
    CARD       = colors.HexColor("#171717")
    CARD2      = colors.HexColor("#1f1f1f")
    BORDER     = colors.HexColor("#2a2a2a")
    WHITE      = colors.HexColor("#f0f0f0")
    MUTED      = colors.HexColor("#737373")
    ACCENT     = colors.HexColor("#e8841a")
    CRITICAL   = colors.HexColor("#ef4444")
    HIGH       = colors.HexColor("#f97316")
    MEDIUM     = colors.HexColor("#eab308")
    LOW        = colors.HexColor("#22c55e")
    NONE_COL   = colors.HexColor("#6b7280")

    risk_colors = {
        "CRITICAL": CRITICAL,
        "HIGH": HIGH,
        "MEDIUM": MEDIUM,
        "LOW": LOW,
        "NONE": NONE_COL
    }

    risk_color = risk_colors.get(scan["risk_level"], MUTED)

    # ── styles ──
    def mono(size=9, color=WHITE, bold=False):
        return ParagraphStyle(
            "mono",
            fontName="Courier-Bold" if bold else "Courier",
            fontSize=size,
            textColor=color,
            leading=size * 1.5
        )

    def sans(size=10, color=WHITE, bold=False, align=TA_LEFT):
        return ParagraphStyle(
            "sans",
            fontName="Helvetica-Bold" if bold else "Helvetica",
            fontSize=size,
            textColor=color,
            leading=size * 1.5,
            alignment=align
        )

    # ── parse markdown table from report ──
    def parse_markdown_table(text):
        lines = text.strip().split("\n")
        table_lines = [l for l in lines if l.strip().startswith("|") and "---" not in l]
        rows = []
        for line in table_lines:
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if cells:
                rows.append(cells)
        return rows

    def get_summary(text):
        lines = text.strip().split("\n")
        summary_lines = []
        in_summary = False
        for line in lines:
            if line.strip().startswith("|") or "---" in line:
                in_summary = False
            if not line.strip().startswith("|") and not line.strip().startswith("RESULT") and line.strip() and "---" not in line:
                summary_lines.append(line.strip())
        return " ".join(summary_lines[:6]) if summary_lines else ""

    # ── build PDF in memory ──
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20*mm,
        rightMargin=20*mm,
        topMargin=20*mm,
        bottomMargin=20*mm
    )

    story = []
    W = A4[0] - 40*mm  # usable width

    # ── header band ──
    header_data = [[
        Paragraph(f"SECDASH", mono(8, ACCENT, bold=True)),
        Paragraph(f"SECURITY SCAN REPORT", mono(8, MUTED)),
    ]]
    header_table = Table(header_data, colWidths=[W*0.5, W*0.5])
    header_table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), BLACK),
        ("ALIGN", (1,0), (1,0), "RIGHT"),
        ("TOPPADDING", (0,0), (-1,-1), 8),
        ("BOTTOMPADDING", (0,0), (-1,-1), 8),
        ("LEFTPADDING", (0,0), (-1,-1), 10),
        ("RIGHTPADDING", (0,0), (-1,-1), 10),
        ("LINEBELOW", (0,0), (-1,-1), 1, ACCENT),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 8*mm))

    # ── app name + risk badge ──
    title_data = [[
        Paragraph(app_name, sans(22, WHITE, bold=True)),
        Paragraph(f'<font color="#{scan["risk_level"] and risk_color.hexval()[1:] or "737373"}">{scan["risk_level"]}</font>', sans(14, risk_color, bold=True, align=TA_CENTER)),
    ]]
    title_table = Table(title_data, colWidths=[W*0.7, W*0.3])
    title_table.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("ALIGN", (1,0), (1,0), "RIGHT"),
        ("BACKGROUND", (1,0), (1,0), CARD2),
        ("ROUNDEDCORNERS", (1,0), (1,0), [4,4,4,4]),
        ("TOPPADDING", (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("LEFTPADDING", (1,0), (1,0), 10),
        ("RIGHTPADDING", (1,0), (1,0), 10),
    ]))
    story.append(title_table)
    story.append(Spacer(1, 4*mm))

    # ── meta info row ──
    meta_data = [[
        Paragraph(f"Repo: {scan['repo']}", mono(8, MUTED)),
        Paragraph(f"Push: {scan['push_time']}", mono(8, MUTED)),
        Paragraph(f"Scan: {scan['scan_time']}", mono(8, MUTED)),
    ]]
    meta_table = Table(meta_data, colWidths=[W*0.4, W*0.3, W*0.3])
    meta_table.setStyle(TableStyle([
        ("TOPPADDING", (0,0), (-1,-1), 0),
        ("BOTTOMPADDING", (0,0), (-1,-1), 0),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 6*mm))
    story.append(HRFlowable(width=W, color=BORDER, thickness=1))
    story.append(Spacer(1, 6*mm))

    # ── files scanned ──
    story.append(Paragraph("FILES SCANNED", mono(8, ACCENT, bold=True)))
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph(scan["files_scanned"] or "N/A", mono(9, WHITE)))
    story.append(Spacer(1, 6*mm))
    story.append(HRFlowable(width=W, color=BORDER, thickness=1))
    story.append(Spacer(1, 6*mm))

    # ── vulnerability table ──
    story.append(Paragraph("VULNERABILITY FINDINGS", mono(8, ACCENT, bold=True)))
    story.append(Spacer(1, 3*mm))

    table_rows = parse_markdown_table(scan["report"])

    if table_rows:
        headers = table_rows[0]
        data_rows = table_rows[1:]

        # header row
        styled_headers = [Paragraph(h.upper(), mono(7, MUTED, bold=True)) for h in headers]

        # data rows
        styled_rows = []
        for row in data_rows:
            styled_row = []
            for i, cell in enumerate(row):
                # colour the severity/likelihood cells
                cell_color = WHITE
                if i == 1:  # severity column
                    sev = cell.upper()
                    cell_color = risk_colors.get(sev, WHITE)
                elif i == 2:  # likelihood column
                    lik = cell.upper()
                    cell_color = risk_colors.get(lik, WHITE)
                styled_row.append(Paragraph(cell, mono(7, cell_color)))
            # pad if row is shorter than headers
            while len(styled_row) < len(headers):
                styled_row.append(Paragraph("", mono(7, WHITE)))
            styled_rows.append(styled_row)

        all_rows = [styled_headers] + styled_rows

        # column widths — distribute based on number of columns
        n_cols = len(headers)
        if n_cols == 5:
            col_widths = [W*0.18, W*0.10, W*0.10, W*0.25, W*0.37]
        elif n_cols == 6:
            col_widths = [W*0.15, W*0.09, W*0.09, W*0.09, W*0.22, W*0.36]
        else:
            col_widths = [W/n_cols] * n_cols

        vuln_table = Table(all_rows, colWidths=col_widths, repeatRows=1)
        vuln_table.setStyle(TableStyle([
            # header
            ("BACKGROUND", (0,0), (-1,0), CARD2),
            ("LINEBELOW", (0,0), (-1,0), 1, BORDER),
            # rows
            ("BACKGROUND", (0,1), (-1,-1), CARD),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [CARD, BLACK]),
            ("LINEBELOW", (0,0), (-1,-1), 0.5, BORDER),
            ("GRID", (0,0), (-1,-1), 0.5, BORDER),
            # padding
            ("TOPPADDING", (0,0), (-1,-1), 6),
            ("BOTTOMPADDING", (0,0), (-1,-1), 6),
            ("LEFTPADDING", (0,0), (-1,-1), 6),
            ("RIGHTPADDING", (0,0), (-1,-1), 6),
            ("VALIGN", (0,0), (-1,-1), "TOP"),
        ]))
        story.append(vuln_table)
    else:
        story.append(Paragraph("No structured vulnerability table found in report.", mono(9, MUTED)))

    story.append(Spacer(1, 6*mm))
    story.append(HRFlowable(width=W, color=BORDER, thickness=1))
    story.append(Spacer(1, 6*mm))

    # ── summary ──
    story.append(Paragraph("SUMMARY", mono(8, ACCENT, bold=True)))
    story.append(Spacer(1, 3*mm))
    summary = get_summary(scan["report"])
    if summary:
        story.append(Paragraph(summary, sans(9, MUTED)))
    story.append(Spacer(1, 6*mm))

    # ── overall result ──
    result_data = [[
        Paragraph("OVERALL RISK RATING", mono(8, MUTED, bold=True)),
        Paragraph(scan["risk_level"], sans(14, risk_color, bold=True, align=TA_CENTER)),
    ]]
    result_table = Table(result_data, colWidths=[W*0.7, W*0.3])
    result_table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), CARD),
        ("LINEABOVE", (0,0), (-1,-1), 2, risk_color),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("ALIGN", (1,0), (1,0), "CENTER"),
        ("TOPPADDING", (0,0), (-1,-1), 10),
        ("BOTTOMPADDING", (0,0), (-1,-1), 10),
        ("LEFTPADDING", (0,0), (-1,-1), 10),
        ("RIGHTPADDING", (0,0), (-1,-1), 10),
    ]))
    story.append(result_table)
    story.append(Spacer(1, 8*mm))

    # ── footer ──
    story.append(HRFlowable(width=W, color=BORDER, thickness=1))
    story.append(Spacer(1, 3*mm))
    footer_data = [[
        Paragraph("SecDash — AI-powered CI/CD security scanner", mono(7, MUTED)),
        Paragraph("LangGraph · Groq · Flask", mono(7, MUTED)),
    ]]
    footer_table = Table(footer_data, colWidths=[W*0.6, W*0.4])
    footer_table.setStyle(TableStyle([
        ("ALIGN", (1,0), (1,0), "RIGHT"),
        ("TOPPADDING", (0,0), (-1,-1), 0),
        ("BOTTOMPADDING", (0,0), (-1,-1), 0),
    ]))
    story.append(footer_table)

    # ── build and return ──
    doc.build(story)
    buffer.seek(0)

    return Response(
        buffer.getvalue(),
        mimetype="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename={app_name}-security-report.pdf"
        }
    )
@app.route("/api/history/<app_name>", methods=["GET"])
def get_history(app_name):
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT risk_level, report, scan_time 
        FROM scans 
        WHERE app_name = %s 
        ORDER BY scan_time DESC 
        LIMIT 10
    """, (app_name,))
    scans = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([dict(s) for s in scans])

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=False)