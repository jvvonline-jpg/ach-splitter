import streamlit as st
import pdfplumber
from pypdf import PdfReader, PdfWriter
import io
import zipfile
import re

st.set_page_config(page_title="ACH Smart Splitter", layout="wide")
st.title("🏦 ACH Smart Splitter (Surgical Crop)")

def is_valid_payee(name):
    """Filters out internal bank terms, numeric codes, and noise."""
    if not name:
        return False
    clean_name = name.upper().strip()
    
    # List of terms to ignore
    forbidden = ["CORNERSTONES", "CORNERSTONES INC", "TRANSFER", "INTERNAL", "CUSTOMER REFERENCE NUMBER"]
    
    if any(f == clean_name for f in forbidden):
        return False
    if clean_name.replace('.', '').isdigit(): 
        return False
    
    return True

def get_best_payee(block_text):
    """Prioritizes the 'Description' field for the new format, then falls back."""
    # 1. New Format: Look for 'Description' field
    # We look for the description following 'Cross Reference Number' or similar headers
    desc_search = re.findall(r"Description\s+(.*)", block_text)
    
    # 2. Previous Format: Receiver -> Entry -> Originator
    receiver_search = re.search(r"Receiver Name:[\",\s]*(.*?)[ \",\n]", block_text)
    entry_search = re.search(r"Entry Description:[\",\s]*(.*?)[ \",\n]", block_text)
    originator_search = re.search(r"Originator Name:[\",\s]*(.*?)[ \",\n]", block_text)

    # Prioritized list of candidates
    candidates = []
    if desc_search:
        candidates.extend(desc_search) # Check all 'Description' fields found
    
    candidates.extend([
        receiver_search.group(1) if receiver_search else None,
        entry_search.group(1) if entry_search else None,
        originator_search.group(1) if originator_search else None
    ])

    for candidate in candidates:
        if is_valid_payee(candidate):
            return candidate.strip()
            
    return "Unknown_Payee"

def process_ach_multi_format(uploaded_file):
    zip_buffer = io.BytesIO()
    summary_data = []
    global_counter = 1
    
    with pdfplumber.open(uploaded_file) as pdf:
        reader = PdfReader(uploaded_file)
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text()
                
                # Detect start of records (using either header type)
                words = page.extract_words()
                header_tops = [w['top'] for w in words if w['text'] in ["RECEIVER", "Party"]]
                
                # Split blocks by headers
                blocks = re.split(r"(?:RECEIVER INFORMATION|Party Identification)", text)[1:]
                
                # Extract amounts (handles '$465.00' and 'Monetary Amount $771.65')
                amounts = re.findall(r"(?:Amount|Monetary Amount)[\":,\s]*\\?\$?([\d,.]+)", text)
                # Remove 0.00 values if found in new format
                amounts = [a for a in amounts if float(a.replace(',', '')) > 0]
                
                for j, start_y in enumerate(header_tops):
                    if j >= len(blocks): break
                    
                    payee_name = get_best_payee(blocks[j])
                    amt = amounts[j] if j < len(amounts) else "0.00"
                    
                    # Naming: Split File XX PayeeName $Amount.pdf
                    file_num = f"{global_counter:02d}"
                    filename = f"Split File {file_num} {payee_name} ${amt}.pdf"
                    
                    # Surgical Crop
                    end_y = header_tops[j+1] if j+1 < len(header_tops) else page.height
                    pypdf_page = reader.pages[i]
                    pypdf_page.mediabox.upper_right = (pypdf_page.mediabox.right, float(page.height - start_y + 20))
                    pypdf_page.mediabox.lower_left = (0, float(page.height - end_y - 10))
                    
                    writer = PdfWriter()
                    writer.add_page(pypdf_page)
                    pdf_out = io.BytesIO()
                    writer.write(pdf_out)
                    zip_file.writestr(filename, pdf_out.getvalue())
                    summary_data.append(filename)
                    global_counter += 1
                    
    return zip_buffer, summary_data

uploaded_file = st.file_uploader("Upload ACH Report", type="pdf")

if uploaded_file:
    if st.button("🚀 Run Multi-Format Split"):
        with st.spinner("Analyzing report structure..."):
            zip_data, summary = process_ach_multi_format(uploaded_file)
            st.success(f"Generated {len(summary)} files!")
            st.table({"Files Created": summary})
            st.download_button("📥 Download ZIP", zip_data.getvalue(), "ACH_Split_Surgical.zip")
