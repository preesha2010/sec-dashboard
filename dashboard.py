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
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    HRFlowable,
)

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

    # ── Professional colour palette ──
    INK         = colors.HexColor("#0f0f0f")
    INK_SOFT    = colors.HexColor("#374151")
    MUTED       = colors.HexColor("#6B7280")
    RULE        = colors.HexColor("#D1D5DB")
    SURFACE     = colors.HexColor("#F9FAFB")
    WHITE       = colors.white
    ACCENT      = colors.HexColor("#1E3A5F")   # deep navy — professional, not loud
    ACCENT_SOFT = colors.HexColor("#EEF2F7")

    RISK = {
        "CRITICAL": colors.HexColor("#B91C1C"),
        "HIGH":     colors.HexColor("#C2410C"),
        "MEDIUM":   colors.HexColor("#92400E"),
        "LOW":      colors.HexColor("#166534"),
        "NONE":     colors.HexColor("#374151"),
    }
    RISK_BG = {
        "CRITICAL": colors.HexColor("#FEF2F2"),
        "HIGH":     colors.HexColor("#FFF7ED"),
        "MEDIUM":   colors.HexColor("#FFFBEB"),
        "LOW":      colors.HexColor("#F0FDF4"),
        "NONE":     colors.HexColor("#F9FAFB"),
    }
    RISK_BORDER = {
        "CRITICAL": colors.HexColor("#FECACA"),
        "HIGH":     colors.HexColor("#FED7AA"),
        "MEDIUM":   colors.HexColor("#FDE68A"),
        "LOW":      colors.HexColor("#BBF7D0"),
        "NONE":     colors.HexColor("#D1D5DB"),
    }

    risk_colour    = RISK.get(scan["risk_level"], MUTED)
    risk_bg        = RISK_BG.get(scan["risk_level"], SURFACE)
    risk_border    = RISK_BORDER.get(scan["risk_level"], RULE)

    # ── Typography ──
    def style(name, font="Helvetica", size=9.5, color=INK_SOFT,
              leading=None, align=TA_LEFT, space_before=0, space_after=0,
              bold=False):
        return ParagraphStyle(
            name,
            fontName=f"Helvetica-Bold" if bold else font,
            fontSize=size,
            textColor=color,
            leading=leading or size * 1.55,
            alignment=align,
            spaceBefore=space_before,
            spaceAfter=space_after,
        )

    S = {
        "label":    style("label",   size=7.5, color=MUTED,     font="Helvetica-Bold"),
        "value":    style("value",   size=9,   color=INK),
        "mono":     style("mono",    size=8,   color=INK_SOFT,  font="Courier"),
        "body":     style("body",    size=9.5, color=INK_SOFT,  leading=15),
        "h2":       style("h2",      size=11,  color=ACCENT,    bold=True, space_before=4, space_after=2),
        "title":    style("title",   size=22,  color=INK,       bold=True, leading=26),
        "subtitle": style("subtitle",size=9,   color=MUTED),
        "th":       style("th",      size=8,   color=WHITE,     bold=True, align=TA_LEFT),
        "td":       style("td",      size=8.5, color=INK_SOFT,  leading=13),
        "td_risk":  style("td_risk", size=8.5, color=INK,       bold=True),
        "footer":   style("footer",  size=7.5, color=MUTED),
        "footer_r": style("footer_r",size=7.5, color=MUTED,     align=TA_RIGHT),
        "badge":    style("badge",   size=12,  color=risk_colour, bold=True, align=TA_CENTER),
    }

    # ── Helpers ──
    def rule(story, color=RULE, thickness=0.5, space=4):
        story.append(Spacer(1, space))
        story.append(HRFlowable(width="100%", thickness=thickness, color=color))
        story.append(Spacer(1, space))

    def section(story, title):
        story.append(Spacer(1, 10))
        story.append(Paragraph(title, S["h2"]))
        story.append(HRFlowable(width="100%", thickness=0.75, color=ACCENT))
        story.append(Spacer(1, 8))

    def parse_markdown_table(text):
        rows = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped.startswith("|"):
                continue
            if re.match(r"^\|[\s\-|]+\|$", stripped):
                continue
            cols = [c.strip() for c in stripped.strip("|").split("|")]
            if cols:
                rows.append(cols)
        return rows

    def clean_summary(text):
        lines = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("|") or re.match(r"^\|[\s\-|]+\|$", line):
                continue
            if re.match(r"^RESULT\s*:", line, re.IGNORECASE):
                continue
            if re.match(r"^#{1,3}\s", line):
                continue
            lines.append(line)
        return " ".join(lines[:10])

    # ── Build PDF ──
    buffer = io.BytesIO()
    PAGE_W, PAGE_H = A4
    MARGIN = 20 * mm
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=22 * mm,
    )
    W = doc.width
    story = []

    # ── Page number callback ──
    def on_page(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(MARGIN, 12 * mm, "SecDash — AI-powered CI/CD Security Scanner")
        canvas.drawRightString(PAGE_W - MARGIN, 12 * mm, f"Page {doc.page}")
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.4)
        canvas.line(MARGIN, 15 * mm, PAGE_W - MARGIN, 15 * mm)
        canvas.restoreState()

    # ======================================================
    # HEADER
    # ======================================================
    story.append(Paragraph("SECDASH", style("brand", size=8, color=ACCENT, bold=True)))
    story.append(Spacer(1, 6))
    story.append(Paragraph("Security Assessment Report", S["title"]))
    story.append(Paragraph("AI-assisted CI/CD Security Scan", S["subtitle"]))
    story.append(Spacer(1, 14))

    # ── Risk summary card ──
    risk_card = Table(
        [
            [
                Paragraph("APPLICATION", S["label"]),
                Paragraph(app_name, style("app", size=10, color=INK, bold=True)),
                Paragraph("OVERALL RISK", S["label"]),
                Paragraph(scan["risk_level"], S["badge"]),
            ],
            [
                Paragraph("REPOSITORY", S["label"]),
                Paragraph(scan["repo"], S["mono"]),
                Paragraph("RISK LEVEL", S["label"]),
                Paragraph(
                    scan["risk_level"],
                    style("rl", size=8, color=risk_colour, bold=True, align=TA_CENTER)
                ),
            ],
        ],
        colWidths=[28*mm, W*0.42, 28*mm, W*0.25],
    )
    risk_card.setStyle(TableStyle([
        ("BACKGROUND",      (0,0), (-1,-1), SURFACE),
        ("BACKGROUND",      (2,0), (3,0),   risk_bg),
        ("BOX",             (0,0), (-1,-1), 0.6, RULE),
        ("INNERGRID",       (0,0), (-1,-1), 0.3, RULE),
        ("TOPPADDING",      (0,0), (-1,-1), 10),
        ("BOTTOMPADDING",   (0,0), (-1,-1), 10),
        ("LEFTPADDING",     (0,0), (-1,-1), 10),
        ("RIGHTPADDING",    (0,0), (-1,-1), 10),
        ("VALIGN",          (0,0), (-1,-1), "MIDDLE"),
        ("LINEAFTER",       (1,0), (1,-1),  1, RULE),
    ]))
    story.append(risk_card)
    story.append(Spacer(1, 20))

    # ======================================================
    # SCAN INFORMATION
    # ======================================================
    section(story, "Scan Information")
    info = Table(
        [
            [
                Paragraph("Push Time",     S["label"]),
                Paragraph(scan["push_time"],  S["mono"]),
                Paragraph("Scan Time",     S["label"]),
                Paragraph(scan["scan_time"],  S["mono"]),
            ],
            [
                Paragraph("Files Scanned", S["label"]),
                Paragraph(str(scan["files_scanned"] or "—"), S["mono"]),
                Paragraph("Repository",    S["label"]),
                Paragraph(scan["repo"],    S["mono"]),
            ],
        ],
        colWidths=[28*mm, W*0.38, 28*mm, W*0.28],
    )
    info.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), WHITE),
        ("GRID",          (0,0), (-1,-1), 0.35, RULE),
        ("BOX",           (0,0), (-1,-1), 0.5,  RULE),
        ("TOPPADDING",    (0,0), (-1,-1), 8),
        ("BOTTOMPADDING", (0,0), (-1,-1), 8),
        ("LEFTPADDING",   (0,0), (-1,-1), 8),
        ("RIGHTPADDING",  (0,0), (-1,-1), 8),
        ("BACKGROUND",    (0,0), (0,-1), SURFACE),
        ("BACKGROUND",    (2,0), (2,-1), SURFACE),
    ]))
    story.append(info)
    story.append(Spacer(1, 20))

    # ======================================================
    # VULNERABILITY FINDINGS
    # ======================================================
    section(story, "Vulnerability Findings")
    rows = parse_markdown_table(scan["report"])

    if rows:
        headers   = rows[0]
        data_rows = rows[1:]
        n         = len(headers)

        # Column widths — no word should be cut off
        # Vulnerability gets the most space; short cols (severity, likelihood) stay narrow
        if n == 5:
            cw = [W*0.18, W*0.12, W*0.12, W*0.20, W*0.38]
        elif n == 6:
            cw = [W*0.16, W*0.11, W*0.11, W*0.10, W*0.17, W*0.35]
        else:
            cw = [W/n]*n

        table_data = []

        # Header row
        table_data.append([Paragraph(h.upper(), S["th"]) for h in headers])

        # Data rows
        for row in data_rows:
            while len(row) < n:
                row.append("")
            styled = []
            for i, cell in enumerate(row):
                upper = cell.strip().upper()
                # colour only severity/likelihood columns (1 and 2)
                if i in (1, 2) and upper in RISK:
                    p = Paragraph(
                        f"<b>{cell}</b>",
                        style(f"td_c{i}", size=8.5, color=RISK[upper], bold=True)
                    )
                else:
                    p = Paragraph(cell, S["td"])
                styled.append(p)
            table_data.append(styled)

        findings = Table(table_data, colWidths=cw, repeatRows=1)
        findings.setStyle(TableStyle([
            # header
            ("BACKGROUND",    (0,0), (-1,0),  ACCENT),
            ("TEXTCOLOR",     (0,0), (-1,0),  WHITE),
            ("TOPPADDING",    (0,0), (-1,0),  9),
            ("BOTTOMPADDING", (0,0), (-1,0),  9),
            # body
            ("ROWBACKGROUNDS",(0,1), (-1,-1), [WHITE, SURFACE]),
            ("GRID",          (0,0), (-1,-1), 0.35, RULE),
            ("BOX",           (0,0), (-1,-1), 0.6,  RULE),
            ("TOPPADDING",    (0,1), (-1,-1), 8),
            ("BOTTOMPADDING", (0,1), (-1,-1), 8),
            ("LEFTPADDING",   (0,0), (-1,-1), 8),
            ("RIGHTPADDING",  (0,0), (-1,-1), 8),
            ("VALIGN",        (0,0), (-1,-1), "TOP"),
            # left border accent on first col
            ("LINEBEFORE",    (0,0), (0,-1),  2, ACCENT),
        ]))
        story.append(findings)

    else:
        story.append(Paragraph("No structured vulnerability table was detected in this report.", S["body"]))

    story.append(Spacer(1, 20))

    # ======================================================
    # AI ANALYSIS / SUMMARY
    # ======================================================
    section(story, "AI Analysis")
    summary = clean_summary(scan["report"])
    if summary:
        box = Table(
            [[Paragraph(summary, S["body"])]],
            colWidths=[W],
        )
        box.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,-1), ACCENT_SOFT),
            ("BOX",           (0,0), (-1,-1), 0.5, ACCENT),
            ("LINEBEFORE",    (0,0), (0,-1),  3,   ACCENT),
            ("LEFTPADDING",   (0,0), (-1,-1), 14),
            ("RIGHTPADDING",  (0,0), (-1,-1), 14),
            ("TOPPADDING",    (0,0), (-1,-1), 12),
            ("BOTTOMPADDING", (0,0), (-1,-1), 12),
        ]))
        story.append(box)
    else:
        story.append(Paragraph("No AI-generated analysis was available.", S["body"]))

    story.append(Spacer(1, 20))

    # ======================================================
    # OVERALL ASSESSMENT
    # ======================================================
    section(story, "Overall Assessment")
    overall = Table(
        [[
            Paragraph("Overall Risk Rating", S["label"]),
            Paragraph(
                scan["risk_level"],
                style("ovr", size=16, color=risk_colour, bold=True, align=TA_CENTER)
            ),
        ]],
        colWidths=[W * 0.72, W * 0.28],
    )
    overall.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (0,0),  SURFACE),
        ("BACKGROUND",    (1,0), (1,0),  risk_bg),
        ("BOX",           (0,0), (-1,-1),1,   risk_border),
        ("LINEBEFORE",    (0,0), (0,-1), 3,   ACCENT),
        ("LINEAFTER",     (0,0), (0,-1), 0.5, risk_border),
        ("LEFTPADDING",   (0,0), (-1,-1),12),
        ("RIGHTPADDING",  (0,0), (-1,-1),12),
        ("TOPPADDING",    (0,0), (-1,-1),14),
        ("BOTTOMPADDING", (0,0), (-1,-1),14),
        ("VALIGN",        (0,0), (-1,-1),"MIDDLE"),
    ]))
    story.append(overall)
    story.append(Spacer(1, 30))

    # ── Build ──
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    buffer.seek(0)

    return Response(
        buffer.getvalue(),
        mimetype="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename={app_name}-security-report.pdf"
        },
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