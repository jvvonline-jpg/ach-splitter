import streamlit as st
import pdfplumber
from pypdf import PdfReader, PdfWriter
import io
import zipfile
import re

st.set_page_config(page_title="ACH Smart Payee Splitter", layout="wide")
st.title("🏦 ACH Smart Payee Splitter")

def is_valid_payee(name):
    """Checks if the name is a proper payee based on your rules."""
    if not name:
        return False
    
    # 1. Standardize to uppercase for easier comparison
    clean_name = name.upper().strip()
    
    # 2. Define forbidden 'internal' or 'generic' terms
    forbidden = ["CORNERSTONES", "CORNERSTONES INC", "TRANSFER", "INTERNAL"]
    
    # 3. Rule Check: Not forbidden, not a number, and not empty
    if any(f in clean_name for f in forbidden):
        return False
    if clean_name.replace('.', '').isdigit(): # Catches "6465"
        return False
    
    return True

def get_best_payee(block_text):
    """Prioritizes fields to find the actual payee name."""
    # Search patterns for the three fields
    receiver_search = re.search(r"Receiver Name:[\",\s]*(.*?)[ \",\n]", block_text)
    entry_search = re.search(r"Entry Description:[\",\s]*(.*?)[ \",\n]", block_text)
    originator_search = re.search(r"Originator Name:[\",\s]*(.*?)[ \",\n]", block_text)

    # Put them in a prioritized list
    candidates = [
        receiver_search.group(1) if receiver_search else None,
        entry_search.group(1) if entry_search else None,
        originator_search.group(1) if originator_search else None
    ]

    # Return the first one that passes our validity rules
    for candidate in candidates:
        if is_valid_payee(candidate):
            return candidate.strip()
            
    return "Unknown_Payee"

def process_ach_smart_naming(uploaded_file):
    zip_buffer = io.BytesIO()
    summary_data = []
    global_counter = 1
    
    with pdfplumber.open(uploaded_file) as pdf:
        reader = PdfReader(uploaded_file)
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
            for i, page in enumerate(pdf.pages):
                words = page.extract_words()
                header_tops = [w['top'] for w in words if "RECEIVER" in w['text']]
                text = page.extract_text()
                
                # Split page text into blocks for analysis
                blocks = re.split(r"RECEIVER INFORMATION", text)[1:]
                amounts = re.findall(r"Amount:[\",\s]*\\?\$?([\d,.]+)", text)
                
                for j, start_y in enumerate(header_tops):
                    if j >= len(blocks): break
                    
                    # Determine Payee Name and Amount
                    payee_name = get_best_payee(blocks[j])
                    amt = amounts[j] if j < len(amounts) else "0.00"
                    
                    # Apply your NEW syntax: Split File 01 (Name) $Amount.pdf
                    file_num = f"{global_counter:02d}"
                    filename = f"Split File {file_num} ({payee_name}) ${amt}.pdf"
                    
                    # Surgical Crop Logic
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
                    summary_data.append(filename)
                    global_counter += 1
                    
    return zip_buffer, summary_data

uploaded_file = st.file_uploader("Upload ACH Report", type="pdf")

if uploaded_file:
    if st.button("🚀 Run Smart Naming & Split"):
        with st.spinner("Finding proper payees..."):
            zip_data, summary = process_ach_smart_naming(uploaded_file)
            st.success(f"Processed {len(summary)} files!")
            st.table({"Generated Filenames": summary})
            st.download_button("📥 Download ZIP", zip_data.getvalue(), "Smart_ACH_Split.zip")
