"""
docx_parser.py - Parse file CloudViz .docx
Cuma ambil: 3 baris awal (customer_name, account_id, region) + HLD image
"""
import re, logging, zipfile
from docx import Document

logger = logging.getLogger(__name__)


def parse_cloudviz_docx(file_path):
    doc = Document(file_path)
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    if len(paragraphs) < 2:
        raise ValueError("File CloudViz tidak valid — minimal 2 baris")

    return {
        "customer_name": paragraphs[0],
        "account_id": paragraphs[1],
        "region": _extract_region(paragraphs),
        "hld_image": _extract_hld_image(file_path),
    }


def _extract_region(paragraphs):
    for p in paragraphs[:5]:
        if re.match(r"^[\w]+-[\w]+-\d+$", p):
            return p
    for p in paragraphs:
        m = re.match(r"^([\w]+-[\w]+-\d+)[a-z]$", p)
        if m:
            return m.group(1)
    return "-"


def _extract_hld_image(docx_path):
    try:
        with zipfile.ZipFile(docx_path, 'r') as z:
            # Only pick supported image formats (PNG, JPEG, GIF)
            supported_ext = ('.png', '.jpg', '.jpeg', '.gif')
            media = [f for f in z.namelist()
                     if f.startswith("word/media/") and not f.endswith("/")
                     and f.lower().endswith(supported_ext)]
            if not media:
                # Fallback: try any media file
                media = [f for f in z.namelist() if f.startswith("word/media/") and not f.endswith("/")]
            if not media:
                return None
            # Pick the largest image file (likely highest resolution)
            largest = max(media, key=lambda f: z.getinfo(f).file_size)
            return z.read(largest)
    except Exception as e:
        logger.warning(f"Gagal extract HLD image: {e}")
    return None
