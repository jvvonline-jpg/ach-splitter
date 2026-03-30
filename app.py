import streamlit as st
import pdfplumber
from pypdf import PdfReader, PdfWriter
import io
import zipfile
import re
import pandas as pd

st.set_page_config(page_title="ACH Master Splitter", layout="wide")
st.title("🏦 ACH Master Precision Splitter")

def is_valid_payee(name):
    """Refined filter to strictly capture actual payee names."""
    if not name: return False
    clean_name = name.upper().strip()
    
    # Internal terms to reject
    forbidden = [
        "CORNERSTONES", "CORNERSTONES INC", "TRANSFER", "INTERNAL", 
        "CUSTOMER REFERENCE NUMBER", "CORP PYMNT", "DEMAND CREDIT", "PAYEE"
    ]
    
    if any(f == clean_name for f in forbidden): return False
    if clean_name.replace('.', '').isdigit(): return False # Rejects codes like '6465'
    
    return True

def get_best_payee(block_text):
    """Prioritizes Payee fields for the Master PDF format."""
    # 1. Look for 'Originator Name' (Fairfax One / FundraiseUp)
    orig_search = re.search(r"Originator Name:[\",\s]*(.*?)[ \",\n]", block_text)
    # 2. Look for 'Description' (Hypothermia)
    desc_search = re.findall(r"Description\s+(.*)", block_text)
    # 3. Look for 'Entry Description' (BB Merchan)
    entry_search = re.search(r"Entry Description:[\",\s]*(.*?)[ \",\n]", block_text)

    candidates = []
    if orig_search: candidates.append(orig_search.group(1))
    if desc_search: candidates.extend(desc_search)
    if entry_search: candidates.append(entry_search.group(1))

    for candidate in candidates:
        if is_valid_payee(candidate): return candidate.strip()
            
    return "Unknown_Payee"

def process_master_pdf(uploaded_file):
    zip_buffer = io.BytesIO()
    records_list = []
    global_counter = 1
    
    with pdfplumber.open(uploaded_file) as pdf:
        reader = PdfReader(uploaded_file)
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text()
                
                # Determine splitting logic by page
                # Page 3 has two 'RECEIVER INFORMATION' blocks. Pages 1 & 2 are single records.
                if "Page 3" in text:
                    header_triggers = ["RECEIVER INFORMATION"]
                else:
                    # Treat the whole page as one record block for Pages 1 & 2
                    header_triggers = ["ACH REMITTANCE ADVICE"]

                blocks = re.split(r"|".join(header_triggers), text)[1:]
                
                # Extract clean amounts ($771.65, $465.00, $242.74)
                amounts = re.findall(r"(?:Amount|Monetary Amount)[\":,\s]*\\?\$?([\d,.]+)", text)
                unique_amounts = []
                for a in amounts:
                    val = float(a.replace(',', ''))
                    if val > 0 and a not in unique_amounts:
                        unique_amounts.append(a)

                # Find vertical positions for surgical cropping
                words = page.extract_words()
                header_tops = [w['top'] for w in words if w['text'] in ["RECEIVER", "Party"]]
                # For single-record pages, we just take the top-most header
                if "Page 3" not in text: header_tops = [header_tops[0]] if header_tops else [50]

                for j, start_y in enumerate(header_tops):
                    if j >= len(blocks) or j >= len(unique_amounts): break
                    
                    payee_name = get_best_payee(blocks[j])
                    amt = unique_amounts[j]
                    
                    # Final Naming Syntax
                    file_num = f"{global_counter:02d}"
                    filename = f"Split File {file_num} {payee_name} ${amt}.pdf"
                    
                    # Surgical Crop
                    end_y = header_tops[j+1] if j+1 < len(header_tops) else page.height
                    pypdf_page = reader.pages[i]
                    pypdf_page.mediabox.upper_right = (pypdf_page.mediabox.right, float(page.height - start_y + 20))
                    pypdf_page.mediabox.lower_left = (0, float(page.height - end_y - 10))
                    
                    # Save
                    writer = PdfWriter()
                    writer.add_page(pypdf_page)
                    pdf_out = io.BytesIO()
                    writer.write(pdf_out)
                    zip_file.writestr(filename, pdf_out.getvalue())
                    
                    records_list.append({"ID": file_num, "Payee": payee_name, "Amount": amt, "Filename": filename})
                    global_counter += 1
                    
    return zip_buffer, pd.DataFrame(records_list)

# --- UI ---
uploaded_file = st.file_uploader("Upload Master.pdf", type="pdf")
if uploaded_file:
    if st.button("🚀 Generate 4 Surgical Files"):
        zip_data, df = process_master_pdf(uploaded_file)
        st.success(f"Successfully isolated {len(df)} records.")
        st.dataframe(df, hide_index=True)
        st.download_button("📥 Download Master ZIP", zip_data.getvalue(), "Master_Split.zip")
