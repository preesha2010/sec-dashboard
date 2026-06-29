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

    # ── colour palette ──
    PRIMARY = colors.HexColor("#2563EB")
    PRIMARY_LIGHT = colors.HexColor("#EFF6FF")

    TEXT = colors.HexColor("#111827")
    MUTED = colors.HexColor("#6B7280")

    BORDER = colors.HexColor("#E5E7EB")

    BACKGROUND = colors.white
    CARD = colors.HexColor("#F9FAFB")

    RISK = {
        "CRITICAL": colors.HexColor("#DC2626"),
        "HIGH": colors.HexColor("#EA580C"),
        "MEDIUM": colors.HexColor("#CA8A04"),
        "LOW": colors.HexColor("#16A34A"),
        "NONE": colors.HexColor("#64748B")
    }

    risk_colour = RISK.get(scan["risk_level"], MUTED)

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "title",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=24,
        textColor=TEXT,
        spaceAfter=4
    )

    heading_style = ParagraphStyle(
        "heading",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=13,
        textColor=PRIMARY,
        spaceBefore=12,
        spaceAfter=8
    )

    body_style = ParagraphStyle(
        "body",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=15,
        textColor=TEXT
    )

    small_style = ParagraphStyle(
        "small",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=8,
        leading=12,
        textColor=MUTED
    )

    mono_style = ParagraphStyle(
        "mono",
        parent=styles["BodyText"],
        fontName="Courier",
        fontSize=8,
        leading=12,
        textColor=TEXT
    )

    badge_style = ParagraphStyle(
        "badge",
        parent=styles["BodyText"],
        alignment=TA_CENTER,
        fontName="Helvetica-Bold",
        fontSize=11,
        textColor=risk_colour
    )

    # ── parse markdown table from report ──
    def parse_markdown_table(text):
        rows = []
        for line in text.splitlines():
            if not line.startswith("|"):
                continue
            if "---" in line:
                continue
            cols = [
                c.strip()
                for c in line.strip().strip("|").split("|")
            ]
            rows.append(cols)
        return rows
    
    def clean_summary(text):
        lines = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("|"):
                continue
            if "---" in line:
                continue
            if line.upper().startswith("RESULT"):
                continue
            lines.append(line)
        return "<br/>".join(lines[:8])
    
    def add_section(story, title):
        story.append(Spacer(1, 6))
        story.append(Paragraph(title, heading_style))
        story.append(HRFlowable(
            width="100%",
            thickness=0.5,
            color=BORDER
        ))
        story.append(Spacer(1, 8))

    # ── build PDF in memory ──
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18*mm,
        rightMargin=18*mm,
        topMargin=18*mm,
        bottomMargin=18*mm
    )

    story = []

    # ======================================================
    # COVER HEADER
    # ======================================================

    story.append(
        Paragraph(
            "<font color='#2563EB'><b>SECDASH</b></font>",
            small_style
        )
    )
    story.append(Spacer(1, 4))
    story.append(
        Paragraph(
            "Security Assessment Report",
            title_style
        )
    )
    story.append(
        Paragraph(
            "AI-assisted CI/CD Security Scan",
            small_style
        )
    )
    story.append(Spacer(1, 18))
    # ======================================================
    # RISK SUMMARY CARD
    # ======================================================
    risk_card = Table(
        [
            [
                Paragraph("<b>Application</b>", small_style),
                Paragraph(app_name, body_style)
            ],
            [
                Paragraph("<b>Repository</b>", small_style),
                Paragraph(scan["repo"], body_style)
            ],
            [
                Paragraph("<b>Overall Risk</b>", small_style),
                Paragraph(
                    f"<font color='{risk_colour}'><b>{scan['risk_level']}</b></font>",
                    badge_style
                )
            ]
        ],
        colWidths=[45*mm, 115*mm]
    )

    risk_card.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),CARD),
        ("BOX",(0,0),(-1,-1),0.6,BORDER),
        ("INNERGRID",(0,0),(-1,-1),0.3,BORDER),
        ("TOPPADDING",(0,0),(-1,-1),10),
        ("BOTTOMPADDING",(0,0),(-1,-1),10),
        ("LEFTPADDING",(0,0),(-1,-1),12),
        ("RIGHTPADDING",(0,0),(-1,-1),12)
    ]))
    story.append(risk_card)
    story.append(Spacer(1,18))
    # ======================================================
    # EXECUTIVE SUMMARY
    # ======================================================
    add_section(story,"Executive Summary")
    summary = clean_summary(scan["report"])
    if summary:
        story.append(
            Paragraph(summary, body_style)
        )
    else:
        story.append(
            Paragraph(
                "No executive summary was available for this scan.",
                body_style
            )
        )
    story.append(Spacer(1,16))
    # ======================================================
    # SCAN INFORMATION
    # ======================================================
    add_section(story,"Scan Information")
    info_table = Table(
        [
            [
                Paragraph("<b>Push Time</b>",small_style),
                Paragraph(scan["push_time"],mono_style),
                Paragraph("<b>Scan Time</b>",small_style),
                Paragraph(scan["scan_time"],mono_style)
            ],
            [
                Paragraph("<b>Files Scanned</b>",small_style),
                Paragraph(str(scan["files_scanned"]),mono_style),
                Paragraph("<b>Repository</b>",small_style),
                Paragraph(scan["repo"],mono_style)

            ]
        ],
        colWidths=[28*mm,57*mm,28*mm,57*mm]
    )

    info_table.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),colors.white),
        ("GRID",(0,0),(-1,-1),0.35,BORDER),
        ("BOX",(0,0),(-1,-1),0.5,BORDER),
        ("TOPPADDING",(0,0),(-1,-1),8),
        ("BOTTOMPADDING",(0,0),(-1,-1),8),
        ("LEFTPADDING",(0,0),(-1,-1),8),
        ("RIGHTPADDING",(0,0),(-1,-1),8),
    ]))

    story.append(info_table)
    story.append(Spacer(1,18))
    # ======================================================
    # FILES SCANNED
    # ======================================================
    add_section(story,"Files Scanned")
    files = scan["files_scanned"] or "No file list available."
    if "," in files:
        file_list = "<br/>".join(
            f"• {f.strip()}"
            for f in files.split(",")
        )
    else:
        file_list = files.replace("\n","<br/>")
    story.append(
        Paragraph(
            file_list,
            mono_style
        )
    )
    story.append(Spacer(1,18))

    # ======================================================
    # VULNERABILITY FINDINGS
    # ======================================================

    add_section(story, "Vulnerability Findings")
    rows = parse_markdown_table(scan["report"])
    if rows:
        headers = rows[0]
        data_rows = rows[1:]
        table_data = []
        # ---------------- HEADER ----------------
        header_row = []
        for h in headers:
            header_row.append(
                Paragraph(
                    f"<b>{h.upper()}</b>",
                    ParagraphStyle(
                        "header",
                        parent=small_style,
                        textColor=colors.white,
                        alignment=TA_CENTER,
                        fontName="Helvetica-Bold"
                    )
                )
            )
        table_data.append(header_row)

        # ---------------- BODY ----------------

        for row in data_rows:
            while len(row) < len(headers):
                row.append("")
            styled = []
            for i, cell in enumerate(row):
                colour = TEXT
                value = cell.upper()
                if value == "CRITICAL":
                    colour = RISK["CRITICAL"]
                elif value == "HIGH":
                    colour = RISK["HIGH"]
                elif value == "MEDIUM":
                    colour = RISK["MEDIUM"]
                elif value == "LOW":
                    colour = RISK["LOW"]
                elif value == "NONE":
                    colour = RISK["NONE"]
                styled.append(
                    Paragraph(
                        f"<font color='{colour}'>{cell}</font>",
                        ParagraphStyle(
                            "cell",
                            parent=body_style,
                            alignment=TA_LEFT
                        )
                    )
                )
            table_data.append(styled)

        # -------------------------------------------------
        # COLUMN WIDTHS
        # -------------------------------------------------

        width = doc.width
        if len(headers) == 5:
            col_widths = [
                width * 0.16,
                width * 0.12,
                width * 0.12,
                width * 0.24,
                width * 0.36
            ]
        elif len(headers) == 6:
            col_widths = [
                width * 0.15,
                width * 0.10,
                width * 0.10,
                width * 0.12,
                width * 0.18,
                width * 0.35
            ]
        else:
            col_widths = [width / len(headers)] * len(headers)
        findings_table = Table(
            table_data,
            colWidths=col_widths,
            repeatRows=1
        )
        findings_table.setStyle(TableStyle([
            # Header
            ("BACKGROUND",(0,0),(-1,0),PRIMARY),
            ("TEXTCOLOR",(0,0),(-1,0),colors.white),
            ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
            ("ALIGN",(0,0),(-1,0),"CENTER"),
            ("BOTTOMPADDING",(0,0),(-1,0),10),
            ("TOPPADDING",(0,0),(-1,0),10),
            # Body
            ("ROWBACKGROUNDS",
             (0,1),
             (-1,-1),
             [colors.white, CARD]),
            ("GRID",
             (0,0),
             (-1,-1),
             0.35,
             BORDER),
            ("BOX",
             (0,0),
             (-1,-1),
             0.6,
             BORDER),
            ("LEFTPADDING",
             (0,0),
             (-1,-1),
             8),
            ("RIGHTPADDING",
             (0,0),
             (-1,-1),
             8),
            ("TOPPADDING",
             (0,1),
             (-1,-1),
             9),
            ("BOTTOMPADDING",
             (0,1),
             (-1,-1),
             9),
            ("VALIGN",
             (0,0),
             (-1,-1),
             "TOP")
        ]))
        story.append(findings_table)
    else:
        story.append(
            Table(
                [[
                    Paragraph(
                        "No structured vulnerability table was detected in this report.",
                        body_style
                    )
                ]],
                colWidths=[doc.width]
            )
        )
    story.append(Spacer(1,18))

    # ======================================================
    # AI ANALYSIS
    # ======================================================

    add_section(story, "AI Analysis")
    summary = clean_summary(scan["report"])
    if summary:
        analysis_box = Table(
            [[Paragraph(summary, body_style)]],
            colWidths=[doc.width]
        )
        analysis_box.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,-1),CARD),
            ("BOX",(0,0),(-1,-1),0.5,BORDER),
            ("LEFTPADDING",(0,0),(-1,-1),12),
            ("RIGHTPADDING",(0,0),(-1,-1),12),
            ("TOPPADDING",(0,0),(-1,-1),12),
            ("BOTTOMPADDING",(0,0),(-1,-1),12)
        ]))
        story.append(analysis_box)
    else:
        story.append(
            Paragraph(
                "No AI-generated analysis was available.",
                body_style
            )
        )
    story.append(Spacer(1,20))

    # ======================================================
    # OVERALL RISK
    # ======================================================

    add_section(story, "Overall Assessment")
    risk_card = Table(
        [
            [
                Paragraph(
                    "<b>Overall Risk Rating</b>",
                    body_style
                ),
                Paragraph(
                    f"<font color='{risk_colour}'><b>{scan['risk_level']}</b></font>",
                    ParagraphStyle(
                        "risk",
                        parent=body_style,
                        alignment=TA_CENTER,
                        fontName="Helvetica-Bold",
                        fontSize=16
                    )
                )
            ]
        ],
        colWidths=[doc.width * 0.70, doc.width * 0.30]
    )
    risk_card.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),PRIMARY_LIGHT),
        ("BOX",(0,0),(-1,-1),1,PRIMARY),
        ("LINEBEFORE",(1,0),(1,0),1,PRIMARY),
        ("LEFTPADDING",(0,0),(-1,-1),12),
        ("RIGHTPADDING",(0,0),(-1,-1),12),
        ("TOPPADDING",(0,0),(-1,-1),12),
        ("BOTTOMPADDING",(0,0),(-1,-1),12),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE")
    ]))
    story.append(risk_card)
    story.append(Spacer(1,30))

    # ======================================================
    # FOOTER
    # ======================================================

    story.append(
        HRFlowable(
            width="100%",
            thickness=0.5,
            color=BORDER
        )
    )
    story.append(Spacer(1,8))
    footer = Table(
        [
            [
                Paragraph(
                    "<b>SecDash</b><br/>AI-powered CI/CD Security Scanner",
                    small_style
                ),
                Paragraph(
                    "Generated using LangGraph • Groq • Flask",
                    ParagraphStyle(
                        "footer_right",
                        parent=small_style,
                        alignment=TA_RIGHT
                    )
                )
            ]
        ],
        colWidths=[doc.width * 0.60, doc.width * 0.40]
    )
    footer.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"TOP")
    ]))
    story.append(footer)

    # ======================================================
    # PAGE NUMBERS
    # ======================================================

    def add_page_number(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica",8)
        canvas.setFillColor(MUTED)
        canvas.drawRightString(
            A4[0]-18*mm,
            10*mm,
            f"Page {doc.page}"
        )
        canvas.restoreState()

    # ======================================================
    # BUILD PDF
    # ======================================================

    doc.build(
        story,
        onFirstPage=add_page_number,
        onLaterPages=add_page_number
    )

    buffer.seek(0)

    return Response(
        buffer.getvalue(),
        mimetype="application/pdf",
        headers={
            "Content-Disposition":
            f"attachment; filename={app_name}-security-report.pdf"
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