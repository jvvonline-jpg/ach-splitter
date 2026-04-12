import streamlit as st
from pypdf import PdfReader, PdfWriter
import io
import re
import zipfile
import fitz  # pymupdf
import base64
from PIL import Image, ImageDraw, ImageFont

st.set_page_config(page_title="ACH Remittance Splitter", layout="wide")

# ── Styles ────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
.step-badge {
    display: inline-block;
    background: #16a34a;
    color: white;
    border-radius: 20px;
    padding: 2px 12px;
    font-size: 12px;
    font-weight: 600;
    margin-bottom: 4px;
}
.info-box {
    background: #f0fdf4;
    border: 1px solid #86efac;
    border-radius: 8px;
    padding: 10px 14px;
    font-size: 14px;
    color: #166534;
    margin-bottom: 12px;
}
.split-summary {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 10px 14px;
    font-size: 13px;
    margin-bottom: 8px;
}
.line-row {
    background: #f0fdf4;
    border: 1px solid #bbf7d0;
    border-radius: 8px;
    padding: 6px 12px;
    margin-bottom: 6px;
}
</style>
""", unsafe_allow_html=True)

st.title("🏦 ACH Remittance Splitter")
st.write("Upload an ACH Remittance PDF, mark where to split it with green dashed lines, then download the split files.")

# ── Helper: extract ACH info from page text ───────────────────────────────────
def extract_ach_info(text):
    name_search   = re.search(r"Receiver Name:\s*(.*)", text)
    amount_search = re.search(r"Amount:\s*(\$[\d,.]*)", text)
    trace_search  = re.search(r"ACH Trace Number:\s*(\d+)", text)

    name   = name_search.group(1).strip()   if name_search   else "Unknown_Receiver"
    amount = amount_search.group(1).replace("$", "").strip() if amount_search else "0.00"
    trace  = trace_search.group(1).strip()  if trace_search  else "No_Trace"

    safe_name = "".join([c for c in name if c.isalnum() or c in (" ", "_")]).rstrip()
    return safe_name, amount, trace

# ── Helper: render a PDF page to PIL Image ───────────────────────────────────
def render_page_image(pdf_bytes, page_num, zoom=1.4):
    doc  = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[page_num]
    mat  = fitz.Matrix(zoom, zoom)
    pix  = page.get_pixmap(matrix=mat)
    img  = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    doc.close()
    return img

# ── Helper: draw split lines on image ────────────────────────────────────────
def draw_lines_on_image(img, y_fracs):
    """Return a new image with green dashed lines and labels drawn at each y_frac."""
    overlay = img.copy().convert("RGBA")
    draw_layer = Image.new("RGBA", overlay.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(draw_layer)

    for idx, y_frac in enumerate(sorted(y_fracs)):
        y_px = int(y_frac * img.height)
        pct  = int(y_frac * 100)

        # Dashed green line
        dash_len, gap_len = 18, 10
        x = 0
        while x < img.width:
            draw.line(
                [(x, y_px), (min(x + dash_len, img.width), y_px)],
                fill=(34, 197, 94, 220), width=3
            )
            x += dash_len + gap_len

        # Label background + text
        label = f" Line {idx+1} — {pct}% "
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
        except Exception:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), label, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        lx = img.width - tw - 16
        ly = y_px - th - 8
        if ly < 2:
            ly = y_px + 6
        draw.rounded_rectangle([lx - 4, ly - 2, lx + tw + 4, ly + th + 4], radius=4,
                               fill=(34, 197, 94, 220))
        draw.text((lx, ly), label, fill=(255, 255, 255, 255), font=font)

    result = Image.alpha_composite(overlay, draw_layer).convert("RGB")
    return result

# ── Helper: build split PDFs from line positions ──────────────────────────────
def build_split_pdfs(pdf_bytes, split_points):
    """
    split_points: list of (page_index, y_fraction) sorted by page then y.
    Returns list of (filename, pdf_bytes).
    """
    src = fitz.open(stream=pdf_bytes, filetype="pdf")
    total_pages = len(src)

    cuts = sorted(split_points, key=lambda x: (x[0], x[1]))

    segments = []
    seg_start = (0, 0.0)

    for cut_page, cut_y in cuts:
        segments.append((seg_start, (cut_page, cut_y)))
        seg_start = (cut_page, cut_y)
    segments.append((seg_start, (total_pages - 1, 1.0)))

    results = []
    reader = PdfReader(io.BytesIO(pdf_bytes))

    for seg_idx, (start, end) in enumerate(segments):
        start_page, start_y = start
        end_page,   end_y   = end

        writer = PdfWriter()

        for p in range(start_page, end_page + 1):
            page   = reader.pages[p]
            page_h = float(page.mediabox.height)

            crop_top    = 0.0
            crop_bottom = 0.0

            if p == start_page and start_y > 0.0:
                crop_top = start_y * page_h
            if p == end_page and end_y < 1.0:
                crop_bottom = (1.0 - end_y) * page_h

            if crop_top > 0 or crop_bottom > 0:
                from pypdf.generic import RectangleObject
                new_bottom = float(page.mediabox.bottom) + crop_bottom
                new_top    = float(page.mediabox.top)    - crop_top
                page.mediabox = RectangleObject(
                    [page.mediabox.left, new_bottom, page.mediabox.right, new_top]
                )

            writer.add_page(page)

        try:
            seg_text = reader.pages[start_page].extract_text() or ""
            name, amt, trace = extract_ach_info(seg_text)
            filename = f"Split_{seg_idx + 1}_{name}_Amt_{amt}.pdf"
        except Exception:
            filename = f"Split_{seg_idx + 1}.pdf"

        buf = io.BytesIO()
        writer.write(buf)
        results.append((filename, buf.getvalue()))

    return results

# ── Session state init ────────────────────────────────────────────────────────
if "pdf_bytes"     not in st.session_state: st.session_state.pdf_bytes     = None
if "total_pages"   not in st.session_state: st.session_state.total_pages   = 0
if "current_page"  not in st.session_state: st.session_state.current_page  = 0
if "split_lines"   not in st.session_state: st.session_state.split_lines   = {}
if "stage"         not in st.session_state: st.session_state.stage         = "upload"
if "split_results" not in st.session_state: st.session_state.split_results = []

# ══════════════════════════════════════════════════════════════════════════════
# STAGE 1 — UPLOAD
# ══════════════════════════════════════════════════════════════════════════════
if st.session_state.stage == "upload":
    st.markdown('<div class="step-badge">Step 1 — Upload</div>', unsafe_allow_html=True)

    uploaded = st.file_uploader("Choose your ACH Remittance PDF", type="pdf")

    if uploaded:
        pdf_bytes = uploaded.read()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        st.session_state.pdf_bytes    = pdf_bytes
        st.session_state.total_pages  = len(doc)
        st.session_state.current_page = 0
        st.session_state.split_lines  = {}
        doc.close()

        st.success(f"Loaded **{uploaded.name}** — {st.session_state.total_pages} page(s) detected.")

        if st.button("▶ Continue to Mark Split Lines"):
            st.session_state.stage = "mark"
            st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# STAGE 2 — MARK SPLIT LINES
# ══════════════════════════════════════════════════════════════════════════════
elif st.session_state.stage == "mark":
    st.markdown('<div class="step-badge">Step 2 — Mark split lines</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="info-box">Use the slider to position a split line, then click <b>Add</b>. '
        'Move existing lines with their sliders. Remove lines with the <b>✕</b> button.</div>',
        unsafe_allow_html=True
    )

    pdf_bytes   = st.session_state.pdf_bytes
    total_pages = st.session_state.total_pages
    pg          = st.session_state.current_page

    # ── Page navigation ──────────────────────────────────────────────────────
    col_prev, col_info, col_next = st.columns([1, 3, 1])
    with col_prev:
        if st.button("⬅ Prev", disabled=(pg == 0)):
            st.session_state.current_page -= 1
            st.rerun()
    with col_info:
        st.markdown(
            f"<div style='text-align:center;font-weight:500;padding-top:6px'>"
            f"Page {pg+1} of {total_pages}</div>",
            unsafe_allow_html=True
        )
    with col_next:
        if st.button("Next ➡", disabled=(pg == total_pages - 1)):
            st.session_state.current_page += 1
            st.rerun()

    # ── Render page with lines ───────────────────────────────────────────────
    lines_on_page = sorted(st.session_state.split_lines.get(pg, []))
    base_img = render_page_image(pdf_bytes, pg)

    if lines_on_page:
        display_img = draw_lines_on_image(base_img, lines_on_page)
    else:
        display_img = base_img

    st.image(display_img, use_container_width=True)

    # ── Add a new split line ─────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("**Add a new split line**")
    col_slider, col_add = st.columns([5, 1])
    with col_slider:
        y_pct = st.slider(
            "Position (% from top of page)",
            min_value=1, max_value=99, value=50,
            key=f"new_line_slider_{pg}",
            help="Drag to position, then click Add."
        )
    with col_add:
        st.markdown("<div style='padding-top:28px'>", unsafe_allow_html=True)
        if st.button("➕ Add", key=f"add_line_{pg}"):
            y_frac = y_pct / 100.0
            if pg not in st.session_state.split_lines:
                st.session_state.split_lines[pg] = []
            if y_frac not in st.session_state.split_lines[pg]:
                st.session_state.split_lines[pg].append(y_frac)
                st.session_state.split_lines[pg].sort()
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    # ── Existing lines on this page (move / remove) ──────────────────────────
    if lines_on_page:
        st.markdown(f"**Split lines on page {pg+1}:**")
        for i, y_frac in enumerate(lines_on_page):
            col_label, col_move, col_del = st.columns([2, 4, 1])
            with col_label:
                st.markdown(
                    f'<div style="padding-top:10px">🟢 <b>Line {i+1}</b> — {int(y_frac*100)}%</div>',
                    unsafe_allow_html=True
                )
            with col_move:
                new_pct = st.slider(
                    "Move",
                    min_value=1, max_value=99,
                    value=int(y_frac * 100),
                    key=f"move_{pg}_{i}",
                    label_visibility="collapsed"
                )
                new_frac = new_pct / 100.0
                if new_frac != y_frac:
                    st.session_state.split_lines[pg][i] = new_frac
                    st.session_state.split_lines[pg].sort()
                    st.rerun()
            with col_del:
                st.markdown("<div style='padding-top:4px'>", unsafe_allow_html=True)
                if st.button("✕", key=f"del_{pg}_{i}"):
                    st.session_state.split_lines[pg].remove(y_frac)
                    if not st.session_state.split_lines[pg]:
                        del st.session_state.split_lines[pg]
                    st.rerun()
                st.markdown("</div>", unsafe_allow_html=True)

    # ── Total lines summary ──────────────────────────────────────────────────
    total_lines = sum(len(v) for v in st.session_state.split_lines.values())
    st.markdown("---")

    if total_lines > 0:
        st.markdown(
            f"**Total split lines across all pages: {total_lines}** "
            f"→ will produce **{total_lines + 1}** output file(s)."
        )
        for p_idx, ys in sorted(st.session_state.split_lines.items()):
            for y in ys:
                st.markdown(f"  - Page {p_idx+1} at {int(y*100)}% from top")
    else:
        st.info(
            "No split lines added yet. Use the slider above to add lines, "
            "or proceed without splitting to download the original PDF."
        )

    # ── Action buttons ───────────────────────────────────────────────────────
    col_reset, col_approve = st.columns([1, 3])
    with col_reset:
        if st.button("🔄 Start over"):
            st.session_state.stage       = "upload"
            st.session_state.pdf_bytes   = None
            st.session_state.split_lines = {}
            st.rerun()
    with col_approve:
        if total_lines == 0:
            btn_label = "⏩ Skip Splitting — Download Original"
        else:
            btn_label = "✅ Approve & Split PDF"

        if st.button(btn_label, type="primary"):
            if total_lines == 0:
                st.session_state.split_results = [("Original.pdf", pdf_bytes)]
            else:
                with st.spinner("Splitting PDF…"):
                    split_points = []
                    for p_idx, ys in st.session_state.split_lines.items():
                        for y in ys:
                            split_points.append((p_idx, y))
                    results = build_split_pdfs(pdf_bytes, split_points)
                    st.session_state.split_results = results
            st.session_state.stage = "done"
            st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# STAGE 3 — DOWNLOAD
# ══════════════════════════════════════════════════════════════════════════════
elif st.session_state.stage == "done":
    st.markdown('<div class="step-badge">Step 3 — Download split files</div>', unsafe_allow_html=True)
    results = st.session_state.split_results
    st.success(f"✅ PDF split into **{len(results)}** file(s). Download individually or as a ZIP.")

    for filename, data in results:
        st.download_button(
            label=f"📄 {filename}",
            data=data,
            file_name=filename,
            mime="application/pdf",
            key=f"dl_{filename}"
        )

    st.markdown("---")
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, data in results:
            zf.writestr(filename, data)

    st.download_button(
        label="📥 Download All as ZIP",
        data=zip_buf.getvalue(),
        file_name="ACH_Split_Records.zip",
        mime="application/zip"
    )

    st.markdown("---")
    if st.button("🔄 Split another PDF"):
        st.session_state.stage         = "upload"
        st.session_state.pdf_bytes     = None
        st.session_state.split_lines   = {}
        st.session_state.split_results = []
        st.rerun()
