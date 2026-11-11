"""
report_generator.py - Generate PowerPoint report

Features:
- Support template .pptx (taruh di lambda-utilization/template.pptx)
- Auto-split tables kalau rows terlalu banyak buat 1 slide
- Safe margins supaya konten ga keluar dari slide
"""

import os
import logging
from pptx import Presentation

logger = logging.getLogger(__name__)
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

# ============================================================
# Constants — safe area within slide
# ============================================================

# ============================================================
# Layout config — gets set dynamically based on actual slide size
# ============================================================

class Layout:
    """Dynamic layout config based on actual slide dimensions."""
    def __init__(self, prs):
        self.W = prs.slide_width
        self.H = prs.slide_height
        self.ML = Inches(0.4)  # margin left
        self.MT = Inches(1.0)  # margin top (below title)
        self.MR = Inches(0.4)  # margin right
        self.MB = Inches(1.0)  # margin bottom (above footer bar)
        self.CW = self.W - self.ML - self.MR  # content width
        self.CH = self.H - self.MT - self.MB   # content height
        self.RH = Inches(0.28)  # row height

L = None  # global layout, set in generate_report()
HEADER_BG = RGBColor(0x2E, 0x75, 0xB6)
HEADER_TEXT = RGBColor(0xFF, 0xFF, 0xFF)
ALT_ROW_BG = RGBColor(0xD6, 0xE4, 0xF0)
FONT_NAME = "Calibri"

def _set_font(font, size=None, bold=None, color=None, name=FONT_NAME):
    """Set font properties. Skip name if None (use theme font)."""
    if size: font.size = size
    if bold is not None: font.bold = bold
    if color: font.color.rgb = color
    if name: font.name = name
TITLE_COLOR = RGBColor(0x1F, 0x4E, 0x79)

# Template path (relative to this file)
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "template.pptx")


# ============================================================
# Helpers
# ============================================================

def _find_blank_layout(prs):
    """Find the 'Blank' slide layout (no placeholders or minimal)."""
    for layout in prs.slide_layouts:
        if layout.name.lower() == "blank":
            return layout
    # Fallback: last layout or layout with fewest placeholders
    return min(prs.slide_layouts, key=lambda l: len(list(l.placeholders)))


def _new_slide(prs):
    """Add blank slide using the Blank layout."""
    layout = _find_blank_layout(prs)
    slide = prs.slides.add_slide(layout)
    # Remove any placeholder shapes from the slide (inherited from layout)
    for ph in list(slide.placeholders):
        sp = ph._element
        sp.getparent().remove(sp)
    return slide


def add_title(slide, text):
    """Add title textbox at safe position."""
    txBox = slide.shapes.add_textbox(L.ML, Inches(0.3), L.CW, Inches(0.6))
    p = txBox.text_frame.paragraphs[0]
    p.text = text
    p.font.size = Pt(22); p.font.name = FONT_NAME
    p.font.bold = True
    p.font.color.rgb = TITLE_COLOR


def add_table(slide, rows, headers, left=None, top=None, width=None):
    """Add formatted table. Returns table object."""
    left = left or L.ML
    top = top or L.MT
    width = width or L.CW
    num_rows = len(rows) + 1
    height = L.RH * num_rows
    tbl = slide.shapes.add_table(num_rows, len(headers), left, top, width, height).table

    for i, h in enumerate(headers):
        c = tbl.cell(0, i)
        c.text = h
        c.fill.solid(); c.fill.fore_color.rgb = HEADER_BG
        for p in c.text_frame.paragraphs:
            p.font.size = Pt(9); p.font.name = FONT_NAME; p.font.bold = True
            p.font.color.rgb = HEADER_TEXT; p.alignment = PP_ALIGN.LEFT
        c.vertical_anchor = MSO_ANCHOR.MIDDLE

    for r, row in enumerate(rows):
        for ci, val in enumerate(row):
            c = tbl.cell(r + 1, ci)
            c.text = str(val) if val not in (None, "") else "-"
            if r % 2 == 0:
                c.fill.solid(); c.fill.fore_color.rgb = ALT_ROW_BG
            for p in c.text_frame.paragraphs:
                p.font.size = Pt(8); p.font.name = FONT_NAME; p.alignment = PP_ALIGN.LEFT
            c.vertical_anchor = MSO_ANCHOR.MIDDLE
    return tbl


def add_table_split(prs, title, rows, headers, max_rows=12, max_chars=600):
    """Add table with auto-split. Split based on row count OR total character count (whichever hits first)."""
    if not rows:
        slide = _new_slide(prs); add_title(slide, title); return

    chunks = []
    current_chunk = []
    current_chars = 0

    for row in rows:
        row_chars = sum(len(str(v)) for v in row)
        if current_chunk and (len(current_chunk) >= max_rows or current_chars + row_chars > max_chars):
            chunks.append(current_chunk)
            current_chunk = []
            current_chars = 0
        current_chunk.append(row)
        current_chars += row_chars

    if current_chunk:
        chunks.append(current_chunk)

    for i, chunk in enumerate(chunks):
        slide = _new_slide(prs)
        suffix = f" (cont.)" if i > 0 else ""
        add_title(slide, f"{title}{suffix}")
        add_table(slide, chunk, headers)


def generate_pie_chart(services, output_path):
    """Generate pie chart PNG. Show major services, group small ones as Others."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    if not services: return None

    # For pie: group services < 5% into Others to avoid label overlap
    pie_threshold = 5
    main = []
    others_pct, others_cost = 0, 0
    for s in services:
        if s["percent"] >= pie_threshold:
            main.append(s)
        else:
            others_pct += s["percent"]
            others_cost += s.get("cost", 0)
    if others_pct > 0:
        main.append({"service": "Others", "percent": round(others_pct, 1), "cost": round(others_cost, 2)})

    # Fix rounding so total = 100%
    total_pct = sum(s["percent"] for s in main)
    if main and total_pct != 100:
        diff = round(100 - total_pct, 1)
        main[-1] = {**main[-1], "percent": round(main[-1]["percent"] + diff, 1)}

    labels = []
    for s in main:
        l = s["service"].replace("Amazon ","").replace("AWS ","")
        l = l.replace("Elastic Compute Cloud - Compute","EC2").replace("Relational Database Service","RDS")
        l = l.replace("Simple Storage Service","S3").replace("EC2 - Other","EC2 Other")
        labels.append(l[:25] if len(l) <= 25 else l[:23]+"..")

    sizes = [s["percent"] for s in main]
    colors = ['#AEC6CF','#FFB7B2','#B5EAD7','#E2C2F0','#FFDAC1','#C7CEEA','#F0E68C','#D4A5A5','#A8D8EA','#CFCFC4','#DDDDDD']
    while len(colors) < len(labels): colors.extend(colors)

    fig, ax = plt.subplots(figsize=(7, 5))

    wedges, _ = ax.pie(sizes, colors=colors[:len(labels)],
           startangle=90, wedgeprops={"edgecolor": "white", "linewidth": 1.5},
           labels=[f'{labels[i]}\n{sizes[i]:.0f}%' for i in range(len(labels))],
           labeldistance=1.15,
           textprops={'fontsize': 8})

    ax.set_title("Top Service Spender", fontsize=12, fontweight="bold", pad=12)
    plt.tight_layout()
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    plt.savefig(output_path, dpi=150, bbox_inches="tight", facecolor="white"); plt.close()
    return output_path


# ============================================================
# Slide builders
# ============================================================

def slide_title(prs, data, use_existing=False):
    """Title slide. If use_existing=True, reuse first slide from template."""
    name = data.get("customer_name", "-")
    account_id = data.get("account_id", "-")
    region = data.get("region", "-")
    period = data.get("period", "-")

    # Determine month from period (e.g. "2026-02-25 to 2026-03-27" → "February 2026")
    try:
        from datetime import datetime as _dt
        start_str = period.split(" to ")[0]
        start_dt = _dt.strptime(start_str, "%Y-%m-%d")
        month_str = start_dt.strftime("%B %Y")
    except:
        month_str = "-"

    # Current date for Publish Date
    from datetime import datetime as _dt2, timezone as _tz
    publish_date = _dt2.now(_tz.utc).strftime("%d %B %Y")

    if use_existing and len(prs.slides) > 0:
        slide = prs.slides[0]
        # Replace ALL text placeholders that contain TITLE/PRESENTATION
        title_replaced = False
        for shape in list(slide.shapes):
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    text = para.text.strip().upper()
                    if "TITTLE" in text or "TITLE" in text or "PRESENTATION" in text:
                        if not title_replaced:
                            # First match: replace with our title
                            para.text = "Monthly Support Report"
                            for run in para.runs:
                                run.font.size = Pt(28)
                                run.font.bold = True
                                run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
                            title_replaced = True
                        else:
                            # Subsequent matches: clear the text
                            para.text = ""

        # Add info box
        info = slide.shapes.add_textbox(L.ML, Inches(3.5), Inches(6), Inches(2.5))
        tf = info.text_frame; tf.word_wrap = True
        details = [
            ("Customer Name", name),
            ("AWS Account ID", account_id),
            ("Support Type", "Advanced Support"),
            ("Month", month_str),
            ("Publish Date", publish_date),
        ]
        for i, (label, val) in enumerate(details):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.text = f"{label:<22}: {val}"
            p.font.size = Pt(12); p.font.bold = True
            p.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

        # Confidential label
        p = tf.add_paragraph()
        p.text = ""  # spacer
        p = tf.add_paragraph()
        p.text = "  Confidential  "
        p.font.size = Pt(11); p.font.bold = True
        p.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

    else:
        slide = _new_slide(prs)
        txBox = slide.shapes.add_textbox(L.ML, Inches(1.2), L.CW, Inches(1.2))
        p = txBox.text_frame.paragraphs[0]
        p.text = "Monthly Support Report"
        p.font.size = Pt(32); p.font.bold = True
        p.font.color.rgb = TITLE_COLOR; p.alignment = PP_ALIGN.CENTER

        info = slide.shapes.add_textbox(L.ML, Inches(3), L.CW, Inches(3))
        tf = info.text_frame; tf.word_wrap = True
        for label, val in [("Customer Name", name), ("AWS Account ID", account_id),
                           ("Support Type", "Advanced Support"), ("Month", month_str),
                           ("Publish Date", publish_date)]:
            p = tf.add_paragraph()
            p.text = f"{label:<22}: {val}"
            p.font.size = Pt(14)
            p.font.color.rgb = RGBColor(0x44, 0x44, 0x44)


def slide_approval(prs, data):
    """Approval/signature slide after cover. Uses title-slide blue background.
    Prepared & Supervised left blank; rest fixed."""
    # Use Title Slide layout (index 0) which has the blue background — same as cover
    layout = prs.slide_layouts[0]
    slide = prs.slides.add_slide(layout)
    for ph in list(slide.placeholders):
        ph._element.getparent().remove(ph._element)

    TXT = RGBColor(0xFF, 0xFF, 0xFF)  # white text over blue bg

    # Header text
    hdr = slide.shapes.add_textbox(L.ML, Inches(0.5), Inches(5), Inches(0.8))
    tf = hdr.text_frame; tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = "This Monthly Report"; p.font.size = Pt(16); p.font.bold = True
    p.font.color.rgb = TXT
    p2 = tf.add_paragraph()
    p2.text = "Document is"; p2.font.size = Pt(16); p2.font.bold = True
    p2.font.color.rgb = TXT

    # Prepared / Supervised rows (values left blank to be filled manually)
    def _row(top, label, sep, value):
        lbl = slide.shapes.add_textbox(L.ML, top, Inches(3.0), Inches(0.35))
        lp = lbl.text_frame.paragraphs[0]
        lp.text = label; lp.font.size = Pt(13); lp.font.color.rgb = TXT
        sepbox = slide.shapes.add_textbox(L.ML + Inches(3.0), top, Inches(0.8), Inches(0.35))
        sp = sepbox.text_frame.paragraphs[0]
        sp.text = sep; sp.font.size = Pt(13); sp.font.color.rgb = TXT
        val = slide.shapes.add_textbox(L.ML + Inches(3.8), top, Inches(4.0), Inches(0.35))
        vp = val.text_frame.paragraphs[0]
        vp.text = value; vp.font.size = Pt(13); vp.font.color.rgb = TXT

    _row(Inches(1.4), "Prepared", "by  :", "")     # blank
    _row(Inches(1.8), "Supervised", "by  :", "")   # blank

    # Reviewed and Approved
    _row(Inches(2.5), "Reviewed and Approved", "on  :", "")

    by_lbl = slide.shapes.add_textbox(L.ML, Inches(2.9), Inches(1.5), Inches(0.35))
    bp = by_lbl.text_frame.paragraphs[0]
    bp.text = "by:"; bp.font.size = Pt(13); bp.font.color.rgb = TXT

    # Signature image — fit within a small bounding box, keep aspect ratio
    sig_path = os.path.join(os.path.dirname(__file__), "signature.png")
    box_left = L.ML + Inches(0.6)
    box_w = Inches(2.6)     # max width
    box_h = Inches(0.85)    # max height
    sig_top = Inches(2.95)
    if os.path.exists(sig_path):
        try:
            from PIL import Image
            with Image.open(sig_path) as im:
                iw, ih = im.size
            scale = min(box_w / iw, box_h / ih)
            final_w = int(iw * scale)
            final_h = int(ih * scale)
        except Exception:
            final_w, final_h = box_w, box_h
        # Center image within the box horizontally
        img_left = box_left + int((box_w - final_w) / 2)
        slide.shapes.add_picture(sig_path, img_left, sig_top, final_w, final_h)

    # Name + title (fixed positions) — centered under the signature box
    name_top = sig_top + box_h + Inches(0.1)
    nm = slide.shapes.add_textbox(box_left, name_top, box_w, Inches(0.35))
    np = nm.text_frame.paragraphs[0]
    np.text = "Indra Adi Respati"; np.font.size = Pt(14); np.font.color.rgb = TXT
    np.alignment = PP_ALIGN.CENTER
    ti = slide.shapes.add_textbox(box_left, name_top + Inches(0.4), box_w, Inches(0.35))
    tp = ti.text_frame.paragraphs[0]
    tp.text = "(Cloud Operation Manager)"; tp.font.size = Pt(14); tp.font.bold = True
    tp.font.color.rgb = TXT
    tp.alignment = PP_ALIGN.CENTER


def slide_agenda(prs, data):
    slide = _new_slide(prs)
    name = data.get("customer_name", "-")
    txBox = slide.shapes.add_textbox(L.ML, Inches(0.3), L.CW, Inches(0.6))
    p = txBox.text_frame.paragraphs[0]
    p.text = "Agenda"; p.font.size = Pt(28)
    p.font.bold = True; p.font.color.rgb = TITLE_COLOR; p.alignment = PP_ALIGN.CENTER

    box = slide.shapes.add_textbox(L.ML + Inches(0.5), L.MT, L.CW - Inches(1), L.CH)
    tf = box.text_frame; tf.word_wrap = True
    items = [
        f"1.  Monthly Support Report for {name}", "2.  Monthly Incident Report",
        "3.  Monthly AWS CloudWatch Alarm & Notification Report",
        "4.  Monthly Berca Support Activities",
        "5.  Summary of AWS Infrastructure Capacity & Utilization",
        "      a. Infrastructure Summary", "      b. Compute & Memory Utilization",
        "      c. Database Utilization (RDS)", "      d. EBS Storage Utilization",
        "      e. S3 Storage Utilization", "      f. VPN Connection",
        "      g. Elastic Disaster Recovery", "      h. EFS", "6.  Top Spender",
        "7.  Savings Plans Inventory, Utilization and Coverage",
        "8.  Cost Optimization Recommendation", "9.  Security Alert and Finding", "10.  Support Flow",
    ]
    for i, item in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = item; p.font.size = Pt(14); p.font.name = FONT_NAME
        p.font.color.rgb = RGBColor(0x33,0x33,0x33)


def slide_placeholder(prs, title):
    slide = _new_slide(prs); add_title(slide, title)


def _add_note(slide, text, top, size=11, bold=False):
    """Add a single-line text note inside the content area."""
    tb = slide.shapes.add_textbox(L.ML, top, L.CW, Inches(0.4))
    tb.text_frame.word_wrap = True
    p = tb.text_frame.paragraphs[0]
    p.text = text
    _set_font(p.font, size=Pt(size), bold=bold)


def _trunc(text, n):
    text = str(text) if text not in (None, "") else "-"
    return text if len(text) <= n else text[:n - 3] + "..."


def slide_security(prs, data):
    """Security Alert and Finding slide: GuardDuty findings table (top 10)."""
    label = data.get("label", "")
    suffix = f" ({label})" if label else ""
    slide = _new_slide(prs); add_title(slide, f"9. Security Alert and Finding{suffix}")
    gd = data.get("guardduty")
    regions = (gd or {}).get("regions", [])
    ok = [r for r in regions if r.get("status") == "ok"]
    if not ok:
        msgs = []
        for r in regions:
            m = r.get("message") or "Unable to retrieve GuardDuty findings"
            msgs.append(f"{m} in {r.get('region', '-')}" if r.get("status") == "not_enabled" else m)
        _add_note(slide, "; ".join(msgs) or "Unable to retrieve GuardDuty findings", L.MT)
        return
    findings = gd.get("findings", [])
    if not findings:
        _add_note(slide, "No active GuardDuty findings in this report period.", L.MT)
        return
    s = gd.get("summary", {})
    _add_note(slide, f"High: {s.get('High', 0)} | Medium: {s.get('Medium', 0)} | "
                     f"Low: {s.get('Low', 0)} | Total: {s.get('total', len(findings))}", L.MT, bold=True)
    top_tbl = L.MT + Inches(0.5)
    max_rows = max(1, min(10, int((L.H - L.MB - top_tbl) / L.RH) - 1))
    headers = ["Severity", "Type", "Title", "Resource Type", "Region", "Count", "Last Seen"]
    rows = [[f.get("severity", "-"), _trunc(f.get("type"), 45), _trunc(f.get("title"), 60),
             f.get("resource_type", "-"), f.get("region", "-"), f.get("count", "-"),
             f.get("last_seen", "-")] for f in findings[:max_rows]]
    add_table(slide, rows, headers, top=top_tbl)
    if len(findings) > len(rows):
        _add_note(slide, f"Showing top {len(rows)} of {len(findings)} findings",
                  top_tbl + L.RH * (len(rows) + 1) + Inches(0.3), size=9)


def slide_monthly_summary(prs, data, tmp_dir):
    """Slide 1: Monthly Support Summary — top spender pie (left) + cost recommendation table (right)."""
    name = data.get("customer_name", "-")
    slide = _new_slide(prs)
    add_title(slide, f"1. BHP Support Summary for {name}")

    cost_data = data.get("cost_by_service", {})
    services = cost_data.get("services", [])
    half_w = int(L.CW / 2) - Inches(0.1)

    # Top spender pie chart — left side, compact
    if services:
        chart_path = os.path.join(tmp_dir, "summary_pie.png")
        result = generate_pie_chart(services, chart_path)
        if result and os.path.exists(result):
            slide.shapes.add_picture(result, L.ML, L.MT, half_w, Inches(3.5))

    # Cost recommendation table — right side
    tbl_left = L.ML + half_w + Inches(0.2)
    tbl_w = half_w
    rec_headers = ["No", "Recommendation", "Target Saving"]
    rec_rows = [["1", "-", "-"], ["2", "-", "-"], ["3", "-", "-"]]
    tbl_top = L.MT + Inches(0.3)
    tbl_height = L.RH * 4
    # Add sub-title for table
    lbl = slide.shapes.add_textbox(tbl_left, L.MT, tbl_w, Inches(0.25))
    p = lbl.text_frame.paragraphs[0]
    p.text = "Improvement & Cost Recommendation"; p.font.size = Pt(10)
    p.font.bold = True; p.font.name = FONT_NAME; p.font.color.rgb = TITLE_COLOR
    tbl = slide.shapes.add_table(4, 3, tbl_left, tbl_top + Inches(0.25), tbl_w, tbl_height).table
    for i, h in enumerate(rec_headers):
        c = tbl.cell(0, i)
        c.text = h
        c.fill.solid(); c.fill.fore_color.rgb = HEADER_BG
        for p in c.text_frame.paragraphs:
            p.font.size = Pt(9); p.font.name = FONT_NAME; p.font.bold = True
            p.font.color.rgb = HEADER_TEXT; p.alignment = PP_ALIGN.LEFT
        c.vertical_anchor = MSO_ANCHOR.MIDDLE
    for r, row in enumerate(rec_rows):
        for ci, val in enumerate(row):
            c = tbl.cell(r + 1, ci)
            c.text = str(val)
            if r % 2 == 0:
                c.fill.solid(); c.fill.fore_color.rgb = ALT_ROW_BG
            for p in c.text_frame.paragraphs:
                p.font.size = Pt(8); p.font.name = FONT_NAME; p.alignment = PP_ALIGN.LEFT
            c.vertical_anchor = MSO_ANCHOR.MIDDLE


def slide_infra_summary(prs, data):
    items = data.get("infrastructure_summary", [])
    label = data.get("label", "")
    per_account = data.get("per_account", [])

    if per_account and len(per_account) > 1:
        # Multi-account: combine all accounts with Account column
        rows = []
        for acct in per_account:
            acct_label = acct.get("label", "-")
            acct_items = acct.get("infrastructure_summary", [])
            for idx, i in enumerate(acct_items):
                rows.append([i.get("category","-"), i.get("service","-"), acct_label, idx+1, i.get("type","-"), i.get("qty",0)])
        add_table_split(prs, "5.a. Infrastructure Summary", rows,
                        ["Category","AWS Service","Account","No","Type","Qty"])
    elif label:
        # Single per-account call (shouldn't happen now but just in case)
        rows = []
        for idx, i in enumerate(items):
            rows.append([i.get("category","-"), i.get("service","-"), label, idx+1, i.get("type","-"), i.get("qty",0)])
        add_table_split(prs, "5.a. Infrastructure Summary", rows,
                        ["Category","AWS Service","Account","No","Type","Qty"])
    else:
        rows = [[i.get("category","-"), i.get("service","-"), i.get("type","-"), i.get("qty",0)] for i in items]
        add_table_split(prs, "5.a. Infrastructure Summary", rows, ["Category","AWS Service","Type","Qty"])


def slide_hld(prs, data, output_dir):
    hld_bytes = data.get("hld_image")
    if not hld_bytes:
        slide = _new_slide(prs); add_title(slide, "5. Summary of AWS Infrastructure Capacity & Utilization")
        # Sub-title
        lbl = slide.shapes.add_textbox(L.ML, L.MT, L.CW, Inches(0.4))
        p = lbl.text_frame.paragraphs[0]
        p.text = "High Level Design"; p.font.size = Pt(16); p.font.name = FONT_NAME
        p.font.color.rgb = RGBColor(0x33, 0x33, 0x33)
        return
    slide = _new_slide(prs); add_title(slide, "5. Summary of AWS Infrastructure Capacity & Utilization")
    # Sub-title
    lbl = slide.shapes.add_textbox(L.ML, Inches(0.7), L.CW, Inches(0.3))
    p = lbl.text_frame.paragraphs[0]
    p.text = "High Level Design"; p.font.size = Pt(14); p.font.name = FONT_NAME
    p.font.color.rgb = RGBColor(0x33, 0x33, 0x33)
    hld_path = os.path.join(output_dir, "hld_diagram.png")
    os.makedirs(output_dir, exist_ok=True)
    with open(hld_path, "wb") as f: f.write(hld_bytes)
    # Try to upscale and maintain aspect ratio
    try:
        from PIL import Image
        img = Image.open(hld_path)
        img_w, img_h = img.size
        # Target minimum width for crisp display on slide (1920px ~ Full HD)
        min_width = 1920
        if img_w < min_width:
            scale_up = min_width / img_w
            new_w = int(img_w * scale_up)
            new_h = int(img_h * scale_up)
            img = img.resize((new_w, new_h), Image.LANCZOS)
            img.save(hld_path, dpi=(300, 300))
            img_w, img_h = new_w, new_h
        # Fit within available slide area maintaining aspect ratio
        avail_w = L.CW
        avail_h = L.CH - Inches(0.1)
        img_top = L.MT + Inches(0.1)
        scale_w = avail_w / img_w
        scale_h = avail_h / img_h
        scale = min(scale_w, scale_h)
        final_w = int(img_w * scale)
        final_h = int(img_h * scale)
        # Center horizontally
        left = L.ML + int((avail_w - final_w) / 2)
        slide.shapes.add_picture(hld_path, left, img_top, final_w, final_h)
    except Exception:
        # Fallback: insert image as-is without upscale (e.g. unsupported format)
        try:
            img_top = L.MT + Inches(0.1)
            slide.shapes.add_picture(hld_path, L.ML, img_top, L.CW, L.CH - Inches(0.1))
        except Exception as e:
            logger.warning(f"Gagal insert HLD image: {e}")


def slide_compute(prs, data, charts_dir):
    instances = data.get("compute_utilization", [])
    label = data.get("label", "")
    suffix = f" ({label})" if label else ""
    # Compute & Memory table
    headers = ["No.","Instance Type","Instance ID","Name","OS",
               "Max CPU(%)","Avg CPU(%)","Max Mem(%)","Avg Mem(%)",
               "Avg Disk(%)","NetworkIn Avg","NetworkOut Avg","State","Note"]
    rows = [[i+1, inst.get("instance_type","-"), inst.get("instance_id","-"), inst.get("name","-"),
             inst.get("os","-"), inst.get("max_cpu_percent","-"), inst.get("avg_cpu_percent","-"),
             inst.get("max_mem_percent","-"), inst.get("avg_mem_percent","-"),
             inst.get("avg_disk_percent","-"), inst.get("net_in_avg","-"), inst.get("net_out_avg","-"),
             inst.get("state","-"), inst.get("remark","-")] for i, inst in enumerate(instances)]
    add_table_split(prs, f"5.b. Compute & Memory Utilization{suffix}", rows, headers, max_rows=5, max_chars=400)

    # Disk Utilization table
    disk_headers = ["Instance Name","Instance ID","Instance type","OS",
                    "Root Disk Util (%)","VolumeReadBytes Average","VolumeWriteBytes Average","State","Note"]
    disk_rows = [[inst.get("name","-"), inst.get("instance_id","-"), inst.get("instance_type","-"),
                  inst.get("os","-"), inst.get("avg_disk_percent","-"),
                  inst.get("vol_read_avg","-"), inst.get("vol_write_avg","-"),
                  inst.get("state","-"), inst.get("remark","-")] for inst in instances]
    add_table_split(prs, f"5.b. Disk Utilization{suffix}", disk_rows, disk_headers, max_rows=8, max_chars=600)

    # Chart slides — 4 columns grid, 1 instance per slide
    # Row 1: CPU, Memory, VolumeWriteBytes, NetworkOut
    # Row 2: Disk, (skip), VolumeReadBytes, NetworkIn
    chart_keys_row1 = ["cpu_chart", "mem_chart", "vol_write_chart", "net_out_chart"]
    chart_keys_row2 = ["disk_chart", None, "vol_read_chart", "net_in_chart"]
    chart_instances = [inst for inst in instances
                       if any(inst.get(k) for k in chart_keys_row1 + chart_keys_row2 if k)]
    if chart_instances:
        chart_h = Inches(2.1)
        chart_w = int(L.CW / 4) - Inches(0.1)
        col_gap = Inches(0.13)
        row_gap = Inches(0.1)
        label_h = Inches(0.25)

        for inst in chart_instances:
            name_label = inst.get("name", inst.get("instance_id", ""))
            slide = _new_slide(prs)
            add_title(slide, f"5.b. Compute & Memory Utilization")
            y = L.MT
            # Instance name label
            lbl = slide.shapes.add_textbox(L.ML, y, L.CW, label_h)
            p = lbl.text_frame.paragraphs[0]
            p.text = name_label; p.font.size = Pt(10); p.font.bold = True
            p.font.name = FONT_NAME; p.font.color.rgb = TITLE_COLOR
            y += label_h
            # Row 1
            for col, key in enumerate(chart_keys_row1):
                cp = inst.get(key)
                if cp and os.path.exists(cp):
                    x = L.ML + col * (chart_w + col_gap)
                    slide.shapes.add_picture(cp, x, y, chart_w, chart_h)
            y += chart_h + row_gap
            # Row 2
            for col, key in enumerate(chart_keys_row2):
                if key is None: continue
                cp = inst.get(key)
                if cp and os.path.exists(cp):
                    x = L.ML + col * (chart_w + col_gap)
                    slide.shapes.add_picture(cp, x, y, chart_w, chart_h)


def slide_rds(prs, data, charts_dir):
    dbs = data.get("rds_utilization", [])
    label = data.get("label", "")
    suffix = f" ({label})" if label else ""
    if not dbs:
        add_table_split(prs, f"5.c. Database Utilization (RDS){suffix}",
                        [["-","-","-","-","-","-","-","-"]],
                        ["DB Identifier","Instance Type","Engine","Max CPU(%)","Avg CPU(%)","Freeable Mem","Free Storage","Remark"])
        return
    headers = ["DB Identifier","Instance Type","Engine","Max CPU(%)","Avg CPU(%)","Freeable Mem","Free Storage","Remark"]
    rows = [[db.get("db_identifier","-"), db.get("instance_type","-"), db.get("engine","-").title(),
             db.get("max_cpu_percent","-"), db.get("avg_cpu_percent","-"),
             db.get("freeable_memory","-"),
             db.get("free_storage","-"), db.get("remark","-")] for db in dbs]
    add_table_split(prs, f"5.c. Database Utilization (RDS){suffix}", rows, headers)

    # Chart slides — grid layout for RDS
    chart_dbs = [db for db in dbs if any(db.get(k) for k in ("cpu_chart","mem_chart","storage_chart"))]
    if chart_dbs:
        rows_per_slide = 2
        chart_h = Inches(1.5)
        chart_w = int(L.CW / 3) - Inches(0.15)
        row_gap = Inches(0.15)
        label_h = Inches(0.25)

        for page_start in range(0, len(chart_dbs), rows_per_slide):
            page = chart_dbs[page_start:page_start + rows_per_slide]
            slide = _new_slide(prs)
            add_title(slide, "5.c. Database Utilization (RDS)")
            y = L.MT
            for db in page:
                paths = [db.get("cpu_chart"), db.get("mem_chart"), db.get("storage_chart")]
                valid = [p for p in paths if p and os.path.exists(p)]
                if not valid: continue
                lbl = slide.shapes.add_textbox(L.ML, y, L.CW, label_h)
                p = lbl.text_frame.paragraphs[0]
                p.text = db.get("db_identifier", ""); p.font.size = Pt(9)
                p.font.bold = True; p.font.name = FONT_NAME; p.font.color.rgb = TITLE_COLOR
                y += label_h
                for idx, path in enumerate(valid):
                    x = L.ML + idx * (chart_w + Inches(0.15))
                    slide.shapes.add_picture(path, x, y, chart_w, chart_h)
                y += chart_h + row_gap


def slide_ebs(prs, data):
    volumes = data.get("ebs_utilization", [])
    label = data.get("label", "")
    suffix = f" ({label})" if label else ""
    if not volumes:
        add_table_split(prs, f"5.d. EBS Storage Utilization{suffix}",
                        [["-","-","-","-","-","-","-"]],
                        ["Instance ID","Volume ID","Storage Type","Total (GB)","Usage (%)","State","Remark"])
        return

    # Group volumes by instance
    from collections import OrderedDict
    groups = OrderedDict()
    for v in volumes:
        key = f"{v.get('instance_id','-')} ({v.get('instance_name','-')})"
        if key not in groups:
            groups[key] = []
        groups[key].append(v)

    # Build rows: each group has a header row (instance) then volume rows
    headers = ["Instance ID","Volume ID","Storage Type","Total (GB)","Usage (%)","State","Remark"]
    all_rows = []
    for instance_label, vols in groups.items():
        # First volume row includes instance label
        for i, v in enumerate(vols):
            inst_col = instance_label if i == 0 else ""
            all_rows.append([inst_col, v.get("volume_id","-"),
                f"EBS {v.get('storage_type','-').upper()}", v.get("size_gb",0),
                v.get("free_space_percent","-"), v.get("state","-"), v.get("remark","-")])

    add_table_split(prs, f"5.d. EBS Storage Utilization{suffix}", all_rows, headers)


def slide_s3(prs, data):
    buckets = data.get("s3_utilization", [])
    label = data.get("label", "")
    suffix = f" ({label})" if label else ""
    if not buckets:
        add_table_split(prs, f"5.e. S3 Storage Utilization{suffix}",
                        [["-","-","-","-","-","-"]],
                        ["S3 Bucket Name","Region","Total Size","Object Count","Avg Object Size","Remark"])
        return
    headers = ["S3 Bucket Name","Region","Total Size","Object Count","Avg Object Size","Remark"]
    rows = []
    for b in buckets:
        oc = b.get("object_count", "-")
        if oc != "-" and isinstance(oc, (int, float)):
            oc = f"{int(oc):,}"
        rows.append([b.get("bucket_name","-"), b.get("region","-"), b.get("total_size","-"),
                     oc, b.get("avg_object_size","-"), b.get("remark","-")])
    add_table_split(prs, f"5.e. S3 Storage Utilization{suffix}", rows, headers)


def slide_vpn(prs, data):
    vpns = data.get("vpn_connections", [])
    label = data.get("label", "")
    suffix = f" ({label})" if label else ""
    if not vpns:
        add_table_split(prs, f"5.f. VPN Connection{suffix}",
                        [[1,"-","-","-"]],
                        ["No","Name","VPN ID","Remark"], max_chars=800)
        return
    headers = ["No", "Name", "VPN ID", "Remark"]
    rows = [[i+1, v.get("name", "-"), v.get("vpn_id", "-"),
             v.get("remark", "-")] for i, v in enumerate(vpns)]
    add_table_split(prs, f"5.f. VPN Connection{suffix}", rows, headers, max_chars=800)


def slide_efs(prs, data):
    efs_list = data.get("efs_filesystems", [])
    label = data.get("label", "")
    suffix = f" ({label})" if label else ""
    if not efs_list:
        add_table_split(prs, f"5.h. EFS{suffix}",
                        [["-","-","-","-","-"]],
                        ["Name","File system ID","Encrypted","Total Size","File system state"], max_chars=800)
        return
    headers = ["Name", "File system ID", "Encrypted", "Total Size", "File system state"]
    rows = [[e.get("name", "-"), e.get("file_system_id", "-"), e.get("encrypted", "-"),
             e.get("total_size", "-"), e.get("state", "-")] for e in efs_list]
    add_table_split(prs, f"5.h. EFS{suffix}", rows, headers, max_chars=800)


def slide_lightsail(prs, data):
    """Optional slide — only rendered if there are Lightsail instances."""
    ls_list = data.get("lightsail_instances", [])
    if not ls_list:
        return  # Skip slide entirely if no Lightsail instances
    label = data.get("label", "")
    suffix = f" ({label})" if label else ""
    headers = ["No","Name","Blueprint","Bundle","vCPU","RAM(GB)","Max CPU(%)","Avg CPU(%)","Net In","Net Out","State"]
    rows = [[i+1, ls.get("name","-"), ls.get("blueprint","-"), ls.get("bundle","-"),
             ls.get("cpu_count","-"), ls.get("ram_gb","-"),
             ls.get("max_cpu_percent","-"), ls.get("avg_cpu_percent","-"),
             ls.get("net_in","-"), ls.get("net_out","-"), ls.get("state","-")]
            for i, ls in enumerate(ls_list)]
    add_table_split(prs, f"5.i. Lightsail Utilization{suffix}", rows, headers, max_chars=600)

    # Chart slides — grid layout (like RDS)
    chart_instances = [ls for ls in ls_list
                       if any(ls.get(k) for k in ("cpu_chart", "burst_chart", "net_chart"))]
    if chart_instances:
        rows_per_slide = 2
        chart_h = Inches(1.5)
        chart_w = int(L.CW / 3) - Inches(0.15)
        row_gap = Inches(0.2)
        label_h = Inches(0.25)
        for page_start in range(0, len(chart_instances), rows_per_slide):
            page = chart_instances[page_start:page_start + rows_per_slide]
            slide = _new_slide(prs)
            add_title(slide, f"5.i. Lightsail Utilization{suffix}")
            y = L.MT
            for ls in page:
                paths = [ls.get("cpu_chart"), ls.get("burst_chart"), ls.get("net_chart")]
                valid = [p for p in paths if p and os.path.exists(p)]
                if not valid: continue
                lbl = slide.shapes.add_textbox(L.ML, y, L.CW, label_h)
                p = lbl.text_frame.paragraphs[0]
                p.text = ls.get("name", ""); p.font.size = Pt(9)
                p.font.bold = True; p.font.name = FONT_NAME; p.font.color.rgb = TITLE_COLOR
                y += label_h
                for idx, path in enumerate(valid):
                    x = L.ML + idx * (chart_w + Inches(0.15))
                    slide.shapes.add_picture(path, x, y, chart_w, chart_h)
                y += chart_h + row_gap


def slide_lightsail_buckets(prs, data):
    """Optional slide — only rendered if there are Lightsail object storage buckets."""
    bk_list = data.get("lightsail_buckets", [])
    if not bk_list:
        return  # Skip slide entirely if no buckets
    label = data.get("label", "")
    suffix = f" ({label})" if label else ""
    headers = ["No","Bucket Name","Region","Plan Size","Object Count","Stored Data","Quota Used","Access"]
    rows = [[i+1, bk.get("name","-"), bk.get("region","-"), bk.get("plan_size","-"),
             bk.get("object_count","-"), bk.get("stored_data","-"),
             bk.get("quota_used","-"), bk.get("access","-")]
            for i, bk in enumerate(bk_list)]
    add_table_split(prs, f"5.j. Lightsail Object Storage{suffix}", rows, headers, max_chars=600)


def slide_drs(prs, data):
    servers = data.get("drs_source_servers", [])
    label = data.get("label", "")
    suffix = f" ({label})" if label else ""
    if not servers:
        add_table_split(prs, f"5.g. Elastic Disaster Recovery{suffix}",
                        [[1,"-","-","-","-","-"]],
                        ["No","Source Server","OS/DB","Disk Size","Repl. State","Health"], max_chars=800)
        return
    headers = ["No","Source Server","OS/DB","Disk Size","Repl. State","Lag","Health"]
    rows = [[i+1, s.get("source_server","-"), s.get("os","-"),
             s.get("disk_size","-"), s.get("repl_state","-"),
             s.get("lag","-"), s.get("health","-")] for i, s in enumerate(servers)]
    add_table_split(prs, f"5.g. Elastic Disaster Recovery{suffix}", rows, headers, max_chars=800)

    # Chart slides — Backlog & LagDuration per source server (grid layout)
    chart_servers = [s for s in servers if s.get("backlog_chart") or s.get("lag_chart")]
    if chart_servers:
        rows_per_slide = 2
        chart_h = Inches(1.6)
        chart_w = int(L.CW / 2) - Inches(0.2)
        row_gap = Inches(0.25)
        label_h = Inches(0.25)
        for page_start in range(0, len(chart_servers), rows_per_slide):
            page = chart_servers[page_start:page_start + rows_per_slide]
            slide = _new_slide(prs)
            add_title(slide, f"5.g. Elastic Disaster Recovery{suffix}")
            y = L.MT
            for s in page:
                paths = [s.get("backlog_chart"), s.get("lag_chart")]
                valid = [p for p in paths if p and os.path.exists(p)]
                if not valid: continue
                lbl = slide.shapes.add_textbox(L.ML, y, L.CW, label_h)
                pr = lbl.text_frame.paragraphs[0]
                pr.text = s.get("source_server", ""); pr.font.size = Pt(9)
                pr.font.bold = True; pr.font.name = FONT_NAME; pr.font.color.rgb = TITLE_COLOR
                y += label_h
                for idx, path in enumerate(valid):
                    x = L.ML + idx * (chart_w + Inches(0.2))
                    slide.shapes.add_picture(path, x, y, chart_w, chart_h)
                y += chart_h + row_gap


def slide_top_spender(prs, data, tmp_dir):
    cost_data = data.get("cost_by_service", {})
    services = cost_data.get("services", [])
    if not services:
        slide = _new_slide(prs); add_title(slide, "6. Top Spender")
        add_table(slide, [["1","-","$0.00","0%"]], ["No.","Service","Cost","%"])
        return

    slide = _new_slide(prs); add_title(slide, "6. Top Spender")
    chart_path = os.path.join(tmp_dir, "top_spender_pie.png")
    result = generate_pie_chart(services, chart_path)
    half_w = int(L.CW / 2)
    if result and os.path.exists(result):
        slide.shapes.add_picture(result, L.ML, L.MT, half_w, Inches(4.2))

    # Top 10 services + Others (same logic as pie chart)
    top_n = 10
    main = services[:top_n]
    others = services[top_n:]
    others_cost = sum(s.get("cost", 0) for s in others)
    others_pct = sum(s["percent"] for s in others)
    if others_pct > 0:
        main.append({"service": "Others", "cost": round(others_cost, 2), "percent": round(others_pct, 1)})

    # Fix rounding so total = 100%
    total_pct = sum(s["percent"] for s in main)
    if main and total_pct != 100:
        diff = round(100 - total_pct, 1)
        main[-1] = {**main[-1], "percent": round(main[-1]["percent"] + diff, 1)}

    rows = []
    for i, svc in enumerate(main):
        n = svc["service"].replace("Amazon ","").replace("AWS ","")
        n = n.replace("Elastic Compute Cloud - Compute","EC2").replace("Relational Database Service","RDS")
        n = n.replace("Simple Storage Service","S3").replace("EC2 - Other","EC2 Other")
        rows.append([i+1, n, f"${svc.get('cost',0):,.2f}", f"{svc.get('percent',0)}%"])
    rows.append(["", "Total", f"${cost_data.get('total_cost',0):,.2f}", "100%"])
    add_table(slide, rows, ["No.","Service","Cost","%"], left=L.ML + half_w + Inches(0.2), top=L.MT, width=half_w - Inches(0.2))


def slide_cost_recommendation(prs, data):
    slide = _new_slide(prs); add_title(slide, "8. Cost Optimization Recommendation")
    add_table(slide, [["1","-","-","-"]], ["No.","Recommendation","Est. saving(%)","Remark"])


def slide_savings_plans(prs, data):
    sp = data.get("savings_plans", {})
    if isinstance(sp, list): plans, summary, inventory, cov_bd = sp, {}, [], []
    else:
        plans = sp.get("plans", [])
        summary = sp.get("summary", {})
        inventory = sp.get("inventory", [])
        cov_bd = sp.get("coverage_breakdown", [])
    if not plans and not summary and not inventory:
        slide = _new_slide(prs); add_title(slide, "7. Savings Plans Inventory, Utilization and Coverage")
        return

    # Summary slide
    slide = _new_slide(prs); add_title(slide, "7. Savings Plans Inventory, Utilization and Coverage")
    if summary:
        add_table(slide, [[summary.get("sp_spend","-"), summary.get("on_demand_equivalent","-"),
            summary.get("total_net_savings","-"), summary.get("utilization_percent","-"),
            summary.get("average_coverage","-")]],
            ["SP Spend","On-Demand Equivalent","Net Savings","Utilization","Avg Coverage"])

    # Inventory (active plans)
    if inventory:
        headers = ["SP ID","Status","Type","Instance Family","Region","Commitment","Start (UTC)","End (UTC)"]
        rows = [[inv.get("savings_plan_id","-"), inv.get("status","-"), inv.get("type","-"),
                 inv.get("ec2_instance_family","-"), inv.get("region","-"), inv.get("commitment","-"),
                 inv.get("start","-"), inv.get("end","-")] for inv in inventory]
        add_table_split(prs, "7. Savings Plans Inventory (Active)", rows, headers)

    # Utilization Breakdown
    if plans:
        headers = ["SP ID","Type","Instance Family","Region","Status","Utilization","Total Commitment","Used Commitment","Net Savings"]
        rows = [[pl.get("savings_plan_id","-"), pl.get("type","-"), pl.get("ec2_instance_family","-"),
                 pl.get("region","-"), pl.get("state","-"), pl.get("utilization_percent","-"),
                 pl.get("total_commitment","-"), pl.get("used_commitment","-"),
                 pl.get("net_savings","-")] for pl in plans]
        add_table_split(prs, "7. Savings Plans Utilization Breakdown", rows, headers)

    # Coverage Breakdown
    if cov_bd:
        headers = ["Service","Instance Family","Region","SP Covered Spend","On-Demand Spend","Coverage"]
        rows = [[c.get("service","-"), c.get("instance_family","-"), c.get("region","-"),
                 c.get("sp_covered_spend","-"), c.get("on_demand_spend","-"),
                 c.get("coverage","-")] for c in cov_bd]
        add_table_split(prs, "7. Savings Plans Coverage Breakdown", rows, headers)

def slide_support_flow(prs):
    """Support Flow slide — title hitam + gambar support.png."""
    slide = _new_slide(prs)
    add_title(slide, "10. Support Flow")
    # Add support flow image
    img_path = os.path.join(os.path.dirname(__file__), "support.png")
    if os.path.exists(img_path):
        slide.shapes.add_picture(img_path, L.ML, L.MT, L.CW, L.CH)


def slide_thank_you(prs):
    """Thank You slide — same layout as title slide (uses Title Slide layout for blue bg)."""
    # Use Title Slide layout (index 0) which has the blue background
    layout = prs.slide_layouts[0]
    slide = prs.slides.add_slide(layout)
    # Clear all placeholder text and remove placeholders
    for ph in list(slide.placeholders):
        ph._element.getparent().remove(ph._element)
    # THANK YOU
    txBox = slide.shapes.add_textbox(L.ML, Inches(1.0), Inches(5), Inches(1.2))
    p = txBox.text_frame.paragraphs[0]
    p.text = "THANK YOU"
    p.font.size = Pt(36); p.font.bold = True
    p.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    # Contact info
    info = slide.shapes.add_textbox(L.ML, Inches(2.5), Inches(5), Inches(3))
    tf = info.text_frame; tf.word_wrap = True
    lines = [("Any Question?", Pt(18), False), ("Contact Us", Pt(18), False), ("", Pt(10), False),
             ("PT. Berca Hardayaperkasa", Pt(20), True), ("021 \u2013 380-0902", Pt(20), True),
             ("WA 081378283782", Pt(20), True),
             ("cloud.support@berca.co.id", Pt(20), True),
             ("www.berca.co.id", Pt(20), True)]
    for i, (text, size, bold) in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = text; p.font.size = size; p.font.bold = bold
        p.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)


def generate_report(data, output_dir="/tmp/report", template_path=None):
    """
    Generate PPTX report.

    Args:
        data: dict dengan semua data report
        output_dir: folder output
        template_path: path ke template .pptx (optional).
                       Kalau None, cek TEMPLATE_PATH default.
                       Kalau ga ada template, pakai blank.
    """
    os.makedirs(output_dir, exist_ok=True)
    charts_dir = os.path.join(output_dir, "charts")
    os.makedirs(charts_dir, exist_ok=True)

    # Load template or blank
    tpl = template_path or TEMPLATE_PATH
    has_template = os.path.exists(tpl)

    if has_template:
        prs = Presentation(tpl)
        # Delete ALL slides except first (title)
        xml_slides = prs.slides._sldIdLst
        while len(xml_slides) > 1:
            rId = xml_slides[-1].get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
            prs.part.drop_rel(rId)
            xml_slides.remove(xml_slides[-1])
    else:
        prs = Presentation()
        prs.slide_width = Inches(13.333)
        prs.slide_height = Inches(7.5)

    # Set dynamic layout based on actual slide size
    global L
    L = Layout(prs)

    # Build slides
    slide_title(prs, data, use_existing=has_template)
    slide_approval(prs, data)
    slide_agenda(prs, data)
    slide_monthly_summary(prs, data, output_dir)
    slide_placeholder(prs, "2. Monthly Incident Report")
    slide_placeholder(prs, "3. Monthly AWS CloudWatch Alarm & Notification Report")
    slide_placeholder(prs, "4. Monthly Berca Support Activities")

    # Per-account slides (HLD, infra, compute, rds, ebs, s3, vpn, drs, efs)
    per_account = data.get("per_account", [])
    if per_account and len(per_account) > 1:
        # Multiple accounts: HLD per account
        for acct in per_account:
            label = acct["label"]
            acct_data = {"label": label, "hld_image": acct.get("hld_image")}
            slide_hld(prs, acct_data, output_dir)

        # Infrastructure Summary: combined with Account column
        slide_infra_summary(prs, data)

        # Compute, RDS, EBS, S3, VPN, DRS, EFS: grouped by service type
        # Compute per account
        for acct in per_account:
            label = acct["label"]
            acct_charts = os.path.join(charts_dir, label.replace(" ", "_"))
            os.makedirs(acct_charts, exist_ok=True)
            acct_data = {"label": label, "compute_utilization": acct.get("compute_utilization", [])}
            slide_compute(prs, acct_data, acct_charts)
        # RDS per account
        for acct in per_account:
            label = acct["label"]
            acct_charts = os.path.join(charts_dir, label.replace(" ", "_"))
            acct_data = {"label": label, "rds_utilization": acct.get("rds_utilization", [])}
            slide_rds(prs, acct_data, acct_charts)
        # EBS per account
        for acct in per_account:
            acct_data = {"label": acct["label"], "ebs_utilization": acct.get("ebs_utilization", [])}
            slide_ebs(prs, acct_data)
        # S3 per account
        for acct in per_account:
            acct_data = {"label": acct["label"], "s3_utilization": acct.get("s3_utilization", [])}
            slide_s3(prs, acct_data)
        # VPN per account
        for acct in per_account:
            acct_data = {"label": acct["label"], "vpn_connections": acct.get("vpn_connections", [])}
            slide_vpn(prs, acct_data)
        # DRS per account
        for acct in per_account:
            acct_data = {"label": acct["label"], "drs_source_servers": acct.get("drs_source_servers", [])}
            slide_drs(prs, acct_data)
        # EFS per account
        for acct in per_account:
            acct_data = {"label": acct["label"], "efs_filesystems": acct.get("efs_filesystems", [])}
            slide_efs(prs, acct_data)
        # Lightsail per account (optional, only rendered if present)
        for acct in per_account:
            acct_data = {"label": acct["label"], "lightsail_instances": acct.get("lightsail_instances", [])}
            slide_lightsail(prs, acct_data)
        # Lightsail buckets per account (optional)
        for acct in per_account:
            acct_data = {"label": acct["label"], "lightsail_buckets": acct.get("lightsail_buckets", [])}
            slide_lightsail_buckets(prs, acct_data)
    else:
        # Single account or no per_account data
        slide_hld(prs, data, output_dir)
        slide_infra_summary(prs, data)
        slide_compute(prs, data, charts_dir)
        slide_rds(prs, data, charts_dir)
        slide_ebs(prs, data)
        slide_s3(prs, data)
        slide_vpn(prs, data)
        slide_drs(prs, data)
        slide_efs(prs, data)
        slide_lightsail(prs, data)
        slide_lightsail_buckets(prs, data)

    slide_top_spender(prs, data, output_dir)
    slide_savings_plans(prs, data)
    slide_cost_recommendation(prs, data)
    if per_account and len(per_account) > 1:
        for acct in per_account:
            slide_security(prs, {"label": acct["label"], "guardduty": acct.get("guardduty")})
    else:
        slide_security(prs, data)

    # Trailing slides
    slide_placeholder(prs, "11. Technical Recommendation")
    slide_support_flow(prs)
    slide_thank_you(prs)

    customer = data.get("customer_name", "unknown").lower().replace(" ", "-")
    # Sanitize filename — remove characters invalid on Windows
    import re as _re
    safe_customer = _re.sub(r'[<>:"/\\|?*]', '', customer)
    filename = f"{safe_customer}_report.pptx"
    filepath = os.path.join(output_dir, filename)
    prs.save(filepath)
    return filepath
