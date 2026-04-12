import streamlit as st
import streamlit.components.v1 as components
from pypdf import PdfReader, PdfWriter
import io
import re
import zipfile
import fitz  # pymupdf
import base64
import os
import tempfile

st.set_page_config(page_title="ACH Remittance Splitter", layout="wide")

# ── Custom component (written to temp dir at runtime for portability) ─────────
_COMPONENT_HTML = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: transparent; }
  .instructions {
    font-size: 13px; color: #64748b; padding: 8px 12px; text-align: center;
    background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px;
    margin-bottom: 8px; line-height: 1.5;
  }
  .instructions strong { color: #334155; }
  #wrapper {
    position: relative; display: block; border: 1px solid #e2e8f0;
    border-radius: 8px; overflow: hidden; background: #fff;
  }
  #page-image {
    display: block; width: 100%; user-select: none;
    -webkit-user-drag: none; pointer-events: none;
  }
  #overlay { position: absolute; top: 0; left: 0; width: 100%; height: 100%; }
  .line-count {
    font-size: 13px; color: #475569; padding: 8px 12px;
    text-align: center; margin-top: 8px;
  }
  .line-count strong { color: #16a34a; }
</style>
</head>
<body>
<div class="instructions">
  <strong>Click</strong> anywhere to add a split line &nbsp;&middot;&nbsp;
  <strong>Drag</strong> a line to move it &nbsp;&middot;&nbsp;
  <strong>Double-click</strong> a line to remove it
</div>
<div id="wrapper">
  <img id="page-image" />
  <canvas id="overlay"></canvas>
</div>
<div id="line-count" class="line-count"></div>
<script>
(function() {
  var GRAB_THRESHOLD = 12;
  var lines = [], dragging = null, hoveredLine = -1, lastSentJSON = "", imageLoaded = false;
  var imgEl = document.getElementById('page-image');
  var canvas = document.getElementById('overlay');
  var ctx = canvas.getContext('2d');
  var lineCountEl = document.getElementById('line-count');

  function drawRoundRect(cx, x, y, w, h, r) {
    cx.beginPath(); cx.moveTo(x+r,y); cx.lineTo(x+w-r,y);
    cx.quadraticCurveTo(x+w,y,x+w,y+r); cx.lineTo(x+w,y+h-r);
    cx.quadraticCurveTo(x+w,y+h,x+w-r,y+h); cx.lineTo(x+r,y+h);
    cx.quadraticCurveTo(x,y+h,x,y+h-r); cx.lineTo(x,y+r);
    cx.quadraticCurveTo(x,y,x+r,y); cx.closePath(); cx.fill();
  }
  function sendReady() { window.parent.postMessage({type:"streamlit:componentReady",apiVersion:1},"*"); }
  function sendValue(v) {
    var j=JSON.stringify(v); if(j===lastSentJSON)return; lastSentJSON=j;
    window.parent.postMessage({type:"streamlit:setComponentValue",value:v},"*");
  }
  function setFrameHeight(h) { window.parent.postMessage({type:"streamlit:setFrameHeight",height:h},"*"); }

  window.addEventListener("message",function(event){
    if(!event.data||event.data.type!=="streamlit:render")return;
    var args=event.data.args;
    lines=args.lines?args.lines.slice():[];
    lastSentJSON=JSON.stringify(lines);
    var b64=args.image_b64; if(!b64)return;
    var newSrc="data:image/png;base64,"+b64;
    if(imgEl.src!==newSrc){
      imgEl.onload=function(){
        imageLoaded=true; resizeCanvas(); drawLines(); updateLineCount();
        setTimeout(function(){setFrameHeight(document.body.scrollHeight+10);},60);
      };
      imgEl.src=newSrc;
    } else { resizeCanvas(); drawLines(); updateLineCount(); }
  });

  function resizeCanvas(){if(!imgEl.naturalWidth)return;canvas.width=imgEl.naturalWidth;canvas.height=imgEl.naturalHeight;}
  function getMouseY(e){var r=canvas.getBoundingClientRect();return(e.clientY-r.top)*(canvas.height/r.height);}
  function findNearestLine(mouseY){
    var best=-1,bestDist=Infinity;
    for(var i=0;i<lines.length;i++){var d=Math.abs(mouseY-lines[i]*canvas.height);if(d<bestDist){bestDist=d;best=i;}}
    var r=canvas.getBoundingClientRect();
    return bestDist<=GRAB_THRESHOLD*(canvas.height/r.height)?best:-1;
  }
  function drawLines(){
    if(!imageLoaded)return; ctx.clearRect(0,0,canvas.width,canvas.height);
    for(var i=0;i<lines.length;i++){
      var y=lines[i]*canvas.height, isA=(i===hoveredLine)||(i===dragging);
      ctx.beginPath();ctx.setLineDash([18,10]);
      ctx.strokeStyle=isA?'#dc2626':'#22c55e';ctx.lineWidth=isA?4:3;
      ctx.moveTo(0,y);ctx.lineTo(canvas.width,y);ctx.stroke();ctx.setLineDash([]);
      var pct=Math.round(lines[i]*100),label=isA?'\u2715  '+pct+'%':pct+'%';
      ctx.font='bold 13px -apple-system,BlinkMacSystemFont,sans-serif';
      var tw=ctx.measureText(label).width,lx=canvas.width-tw-24,ly=y-10;
      if(ly<4)ly=y+22;
      ctx.fillStyle=isA?'rgba(220,38,38,0.9)':'rgba(34,197,94,0.9)';
      drawRoundRect(ctx,lx-6,ly-13,tw+12,20,4);
      ctx.fillStyle='#fff';ctx.fillText(label,lx,ly+2);
    }
  }
  function updateLineCount(){
    lineCountEl.innerHTML=lines.length===0?'No split lines on this page. Click on the image to add one.':
      '<strong>'+lines.length+'</strong> split line'+(lines.length>1?'s':'')+' on this page';
  }

  var clickStartY=null,didDrag=false;
  canvas.addEventListener('mousedown',function(e){
    e.preventDefault();var my=getMouseY(e);clickStartY=my;didDrag=false;
    var idx=findNearestLine(my);if(idx>=0)dragging=idx;
  });
  canvas.addEventListener('mousemove',function(e){
    e.preventDefault();var my=getMouseY(e);
    if(dragging!==null){didDrag=true;lines[dragging]=Math.max(0.01,Math.min(0.99,my/canvas.height));canvas.style.cursor='grabbing';drawLines();}
    else{var idx=findNearestLine(my);hoveredLine=idx;canvas.style.cursor=idx>=0?'ns-resize':'crosshair';drawLines();}
  });
  canvas.addEventListener('mouseup',function(e){
    var my=getMouseY(e);
    if(dragging!==null){lines.sort(function(a,b){return a-b;});dragging=null;hoveredLine=-1;sendValue(lines.slice());drawLines();updateLineCount();}
    else if(!didDrag&&clickStartY!==null){var idx=findNearestLine(my);if(idx<0){var yF=Math.max(0.01,Math.min(0.99,my/canvas.height));lines.push(yF);lines.sort(function(a,b){return a-b;});sendValue(lines.slice());drawLines();updateLineCount();}}
    clickStartY=null;didDrag=false;
  });
  canvas.addEventListener('mouseleave',function(e){
    if(dragging!==null){lines.sort(function(a,b){return a-b;});dragging=null;sendValue(lines.slice());drawLines();updateLineCount();}
    hoveredLine=-1;canvas.style.cursor='crosshair';drawLines();clickStartY=null;didDrag=false;
  });
  canvas.addEventListener('dblclick',function(e){
    e.preventDefault();var my=getMouseY(e),idx=findNearestLine(my);
    if(idx>=0){lines.splice(idx,1);hoveredLine=-1;dragging=null;sendValue(lines.slice());drawLines();updateLineCount();}
  });
  canvas.addEventListener('contextmenu',function(e){e.preventDefault();});

  var touchStartY=null,touchDragging=null,touchDidDrag=false;
  function getTouchY(e){var t=e.touches[0]||e.changedTouches[0],r=canvas.getBoundingClientRect();return(t.clientY-r.top)*(canvas.height/r.height);}
  canvas.addEventListener('touchstart',function(e){e.preventDefault();var my=getTouchY(e);touchStartY=my;touchDidDrag=false;var idx=findNearestLine(my);if(idx>=0){touchDragging=idx;dragging=idx;}},{passive:false});
  canvas.addEventListener('touchmove',function(e){e.preventDefault();var my=getTouchY(e);if(touchDragging!==null){touchDidDrag=true;lines[touchDragging]=Math.max(0.01,Math.min(0.99,my/canvas.height));dragging=touchDragging;drawLines();}},{passive:false});
  canvas.addEventListener('touchend',function(e){e.preventDefault();var my=getTouchY(e);if(touchDragging!==null){lines.sort(function(a,b){return a-b;});touchDragging=null;dragging=null;sendValue(lines.slice());drawLines();updateLineCount();}else if(!touchDidDrag&&touchStartY!==null){var idx=findNearestLine(my);if(idx<0){var yF=Math.max(0.01,Math.min(0.99,my/canvas.height));lines.push(yF);lines.sort(function(a,b){return a-b;});sendValue(lines.slice());drawLines();updateLineCount();}}touchStartY=null;touchDidDrag=false;},{passive:false});

  sendReady();
})();
</script>
</body>
</html>"""

# Write component HTML to a stable temp directory
_component_dir = os.path.join(tempfile.gettempdir(), "st_split_line_editor")
os.makedirs(_component_dir, exist_ok=True)
_index_path = os.path.join(_component_dir, "index.html")
with open(_index_path, "w") as _f:
    _f.write(_COMPONENT_HTML)

_split_editor = components.declare_component("split_line_editor", path=_component_dir)


def split_editor(image_b64, lines, key=None):
    """Render the interactive split-line editor. Returns updated list of y-fractions."""
    return _split_editor(image_b64=image_b64, lines=lines, key=key, default=lines)


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

# ── Helper: render a PDF page to a base64 PNG ────────────────────────────────
def render_page(pdf_bytes, page_num, zoom=1.4):
    doc  = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[page_num]
    mat  = fitz.Matrix(zoom, zoom)
    pix  = page.get_pixmap(matrix=mat)
    img_bytes = pix.tobytes("png")
    doc.close()
    return img_bytes, pix.width, pix.height

# ── Helper: build split PDFs from line positions ──────────────────────────────
def build_split_pdfs(pdf_bytes, split_points):
    """
    split_points: list of (page_index, y_fraction) sorted by page then y.
    Returns list of (filename, pdf_bytes).
    """
    src = fitz.open(stream=pdf_bytes, filetype="pdf")
    total_pages = len(src)

    # Build list of cut positions: (page_idx, y_frac)
    cuts = sorted(split_points, key=lambda x: (x[0], x[1]))

    # Build segments: each segment is a list of (page_idx, y_start_frac, y_end_frac)
    segments = []
    seg_start = (0, 0.0)  # (page_idx, y_frac)

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
            page     = reader.pages[p]
            page_h   = float(page.mediabox.height)
            page_w   = float(page.mediabox.width)

            crop_top    = 0.0
            crop_bottom = 0.0

            if p == start_page and start_y > 0.0:
                # crop from top down to start_y
                crop_top = start_y * page_h

            if p == end_page and end_y < 1.0:
                # crop from end_y to bottom
                crop_bottom = (1.0 - end_y) * page_h

            if crop_top > 0 or crop_bottom > 0:
                from pypdf.generic import RectangleObject
                new_bottom = float(page.mediabox.bottom) + crop_bottom
                new_top    = float(page.mediabox.top)    - crop_top
                page.mediabox = RectangleObject(
                    [page.mediabox.left, new_bottom, page.mediabox.right, new_top]
                )

            writer.add_page(page)

        # Try to extract ACH info from first page of segment for naming
        try:
            seg_text   = reader.pages[start_page].extract_text() or ""
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
if "split_lines"   not in st.session_state: st.session_state.split_lines   = {}  # {page_idx: [y_frac, ...]}
if "stage"         not in st.session_state: st.session_state.stage         = "upload"  # upload | mark | done
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
        st.session_state.pdf_bytes   = pdf_bytes
        st.session_state.total_pages = len(doc)
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

    pdf_bytes   = st.session_state.pdf_bytes
    total_pages = st.session_state.total_pages
    pg          = st.session_state.current_page

    # Page navigation
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

    # Render current page as base64 PNG
    img_bytes, img_w, img_h = render_page(pdf_bytes, pg)
    img_b64 = base64.b64encode(img_bytes).decode()

    # Get current lines for this page
    current_lines = list(st.session_state.split_lines.get(pg, []))

    # ── Interactive split-line editor ─────────────────────────────────────────
    result = split_editor(
        image_b64=img_b64,
        lines=current_lines,
        key=f"editor_{pg}"
    )

    # Update session state from component
    if result is not None:
        new_lines = sorted(result)
        if new_lines != current_lines:
            if len(new_lines) > 0:
                st.session_state.split_lines[pg] = new_lines
            elif pg in st.session_state.split_lines:
                del st.session_state.split_lines[pg]

    # ── Total lines summary ───────────────────────────────────────────────────
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
            "No split lines added yet. Click on the page image to add lines, "
            "or proceed without splitting to download the original PDF."
        )

    # ── Action buttons ────────────────────────────────────────────────────────
    col_reset, col_approve = st.columns([1, 3])
    with col_reset:
        if st.button("🔄 Start over"):
            st.session_state.stage        = "upload"
            st.session_state.pdf_bytes    = None
            st.session_state.split_lines  = {}
            st.rerun()
    with col_approve:
        if total_lines == 0:
            btn_label = "⏩ Skip Splitting — Download Original"
        else:
            btn_label = "✅ Approve & Split PDF"

        if st.button(btn_label, type="primary"):
            if total_lines == 0:
                # No split lines — return the original PDF as-is
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

    # Individual downloads
    for filename, data in results:
        st.download_button(
            label=f"📄 {filename}",
            data=data,
            file_name=filename,
            mime="application/pdf",
            key=f"dl_{filename}"
        )

    # ZIP download
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
        st.session_state.stage        = "upload"
        st.session_state.pdf_bytes    = None
        st.session_state.split_lines  = {}
        st.session_state.split_results = []
        st.rerun()
