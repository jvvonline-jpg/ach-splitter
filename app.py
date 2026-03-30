import streamlit as st
import pdfplumber
from pypdf import PdfReader, PdfWriter
import io
import zipfile
import re
import pandas as pd

st.set_page_config(page_title="ACH Smart Splitter + Search", layout="wide")
st.title("🏦 ACH Smart Splitter with Searchable Index")

# --- CORE LOGIC ---
def is_valid_payee(name):
    if not name: return False
    clean_name = name.upper().strip()
    forbidden = ["CORNERSTONES", "CORNERSTONES INC", "TRANSFER", "INTERNAL", "CUSTOMER REFERENCE NUMBER"]
    if any(f == clean_name for f in forbidden): return False
    if clean_name.replace('.', '').isdigit(): return False
    return True

def get_best_payee(block_text):
    desc_search = re.findall(r"Description\s+(.*)", block_text)
    receiver_search = re.search(r"Receiver Name:[\",\s]*(.*?)[ \",\n]", block_text)
    entry_search = re.search(r"Entry Description:[\",\s]*(.*?)[ \",\n]", block_text)
    
    candidates = desc_search + [
        receiver_search.group(1) if receiver_search else None,
        entry_search.group(1) if entry_search else None
    ]
    for candidate in candidates:
        if is_valid_payee(candidate): return candidate.strip()
    return "Unknown_Payee"

def process_with_search(uploaded_file):
    zip_buffer = io.BytesIO()
    records_list = [] # List of dicts for Pandas
    preview_img = None
    global_counter = 1
    
    with pdfplumber.open(uploaded_file) as pdf:
        reader = PdfReader(uploaded_file)
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text()
                words = page.extract_words()
                header_tops = [w['top'] for w in words if w['text'] in ["RECEIVER", "Party"]]
                blocks = re.split(r"(?:RECEIVER INFORMATION|Party Identification)", text)[1:]
                amounts = re.findall(r"(?:Amount|Monetary Amount)[\":,\s]*\\?\$?([\d,.]+)", text)
                amounts = [a for a in amounts if float(a.replace(',', '')) > 0]
                
                for j, start_y in enumerate(header_tops):
                    if j >= len(blocks): break
                    payee_name = get_best_payee(blocks[j])
                    amt = amounts[j] if j < len(amounts) else "0.00"
                    
                    file_num = f"{global_counter:02d}"
                    filename = f"Split File {file_num} {payee_name} ${amt}.pdf"
                    
                    # Surgical Crop
                    end_y = header_tops[j+1] if j+1 < len(header_tops) else page.height
                    
                    if global_counter == 1:
                        cropped_page = page.crop((0, start_y - 10, page.width, end_y + 10))
                        preview_img = cropped_page.to_image(resolution=150).original
                    
                    pypdf_page = reader.pages[i]
                    pypdf_page.mediabox.upper_right = (pypdf_page.mediabox.right, float(page.height - start_y + 20))
                    pypdf_page.mediabox.lower_left = (0, float(page.height - end_y - 10))
                    
                    writer = PdfWriter()
                    writer.add_page(pypdf_page)
                    pdf_out = io.BytesIO()
                    writer.write(pdf_out)
                    zip_file.writestr(filename, pdf_out.getvalue())
                    
                    # Save to list for the Searchable Table
                    records_list.append({
                        "ID": file_num,
                        "Payee": payee_name,
                        "Amount": float(amt.replace(',', '')),
                        "Filename": filename
                    })
                    global_counter += 1
                    
    return zip_buffer, pd.DataFrame(records_list), preview_img

# --- UI ---
uploaded_file = st.file_uploader("Upload Atlantic Union Bank Report", type="pdf")

if uploaded_file:
    if st.button("🚀 Process & Generate Index"):
        zip_data, df, preview_img = process_with_search(uploaded_file)
        
        # Store in session state so search doesn't trigger a re-run
        st.session_state['zip_data'] = zip_data
        st.session_state['df'] = df
        st.session_state['preview_img'] = preview_img

if 'df' in st.session_state:
    st.subheader("🔍 Extraction Results & Search")
    
    # Search Inputs
    search_query = st.text_input("Search by Payee Name or Filename", placeholder="e.g. HYPOTHERMIA")
    
    # Filter DataFrame
    filtered_df = st.session_state['df']
    if search_query:
        filtered_df = filtered_df[
            filtered_df['Payee'].str.contains(search_query, case=False) | 
            filtered_df['Filename'].str.contains(search_query, case=False)
        ]

    # Show Preview and Download
    col1, col2 = st.columns([1, 2])
    with col1:
        if st.session_state['preview_img']:
            st.image(st.session_state['preview_img'], caption="Record 01 Preview", use_container_width=True)
        st.download_button("📥 Download Full ZIP", st.session_state['zip_data'].getvalue(), "ACH_Split_Surgical.zip")
    
    with col2:
        st.dataframe(filtered_df, use_container_width=True, hide_index=True)
