import streamlit as st
from pypdf import PdfReader, PdfWriter
import io
import re
import zipfile

st.set_page_config(page_title="ACH Remittance Splitter", layout="wide")
st.title("🏦 ACH Remittance Splitter")
st.write("Upload an ACH Remittance Advice Detail Report to split into individual vendor files.")

def extract_ach_info(text):
    """Extracts Name, Amount, and Trace Number using Regex."""
    # Pattern matching based on Source 1.pdf structure
    name_search = re.search(r"Receiver Name:\s*(.*)", text)
    amount_search = re.search(r"Amount:\s*(\$[\d,.]*)", text)
    trace_search = re.search(r"ACH Trace Number:\s*(\d+)", text)
    
    name = name_search.group(1).strip() if name_search else "Unknown_Receiver"
    amount = amount_search.group(1).replace('$', '').strip() if amount_search else "0.00"
    trace = trace_search.group(1).strip() if trace_search else "No_Trace"
    
    # Clean name for filesystem safety
    safe_name = "".join([c for c in name if c.isalnum() or c in (' ', '_')]).rstrip()
    return f"{safe_name}_Amt_{amount}_Trace_{trace}"

def process_ach_pdf(uploaded_file):
    reader = PdfReader(uploaded_file)
    zip_buffer = io.BytesIO()
    summary_data = []

    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        for i, page in enumerate(reader.pages):
            writer = PdfWriter()
            writer.add_page(page)
            
            # Extract text and identify the record
            page_text = page.extract_text()
            file_name_base = extract_ach_info(page_text)
            
            # Create PDF
            pdf_out = io.BytesIO()
            writer.write(pdf_out)
            
            # Add to ZIP and log for summary
            file_name = f"{file_name_base}.pdf"
            zip_file.writestr(file_name, pdf_out.getvalue())
            summary_data.append(file_name)
            
    return zip_buffer, summary_data

uploaded_file = st.file_uploader("Upload 'Source 1.pdf'", type="pdf")

if uploaded_file:
    if st.button("🚀 Split ACH Records"):
        with st.spinner("Parsing records..."):
            zip_data, summary = process_ach_pdf(uploaded_file)
            
            st.success(f"Successfully split {len(summary)} records!")
            
            # Display summary of what was found
            st.table(summary) 
            
            st.download_button(
                label="📥 Download Split Records (ZIP)",
                data=zip_data.getvalue(),
                file_name="ACH_Split_Records.zip",
                mime="application/zip"
            )