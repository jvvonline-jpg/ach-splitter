import streamlit as st
from pypdf import PdfReader, PdfWriter
import io
import re
import zipfile

st.set_page_config(page_title="ACH Sequential Splitter", layout="wide")
st.title("🏦 ACH Sequential Record Splitter")
st.write("Splits ACH reports into individual files using the 'Split File XX $Amount' syntax.")

def extract_amounts(text):
    """Finds all dollar amounts following 'Amount:' in the text."""
    # Matches the specific punctuation in Source 1.pdf like "Amount: ","\$465.00 "
    # We account for the backslash, quotes, and commas
    return re.findall(r"Amount:[\",\s]*\\?\$?([\d,.]+)", text)

def process_ach_sequential(uploaded_file):
    reader = PdfReader(uploaded_file)
    zip_buffer = io.BytesIO()
    summary_data = []
    
    # Initialize the Global Counter
    global_counter = 1

    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        for i, page in enumerate(reader.pages):
            page_text = page.extract_text()
            amounts = extract_amounts(page_text)
            
            for amount in amounts:
                # Format the counter as 01, 02, etc.
                file_number = f"{global_counter:02d}"
                
                # Apply your specific syntax
                filename = f"Split File {file_number} ${amount}.pdf"
                
                # Create the PDF for this record
                writer = PdfWriter()
                writer.add_page(page)
                pdf_out = io.BytesIO()
                writer.write(pdf_out)
                
                # Add to ZIP and Log
                zip_file.writestr(filename, pdf_out.getvalue())
                summary_data.append(filename)
                
                # Increment for the next record found
                global_counter += 1
            
    return zip_buffer, summary_data

uploaded_file = st.file_uploader("Upload ACH Report", type="pdf")

if uploaded_file:
    if st.button("🚀 Run Sequential Split"):
        with st.spinner("Numbering and splitting records..."):
            zip_data, summary = process_ach_sequential(uploaded_file)
            
            if summary:
                st.success(f"Processed {len(summary)} records successfully!")
                # Show the new filenames in a table
                st.table({"Generated Filenames": summary})
                
                st.download_button(
                    label="📥 Download ZIP",
                    data=zip_data.getvalue(),
                    file_name="ACH_Sequential_Split.zip",
                    mime="application/zip"
                )
            else:
                st.error("No amounts detected. Please check the PDF format.")
