import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import psycopg2
from psycopg2.extras import RealDictCursor
import json
from datetime import datetime
import requests
import numpy as np
from decimal import Decimal
import os

# Page config
st.set_page_config(
    page_title="Land Offer Calculator",
    page_icon="🏞️",
    layout="wide"
)

# ============= CONFIGURATION =============
# You'll need to set these as Streamlit secrets or environment variables
PIPEDRIVE_API_TOKEN = st.secrets.get("PIPEDRIVE_API_TOKEN", "")
PIPEDRIVE_DOMAIN = st.secrets.get("PIPEDRIVE_DOMAIN", "")  # e.g., "yourcompany"

# Pipedrive field IDs
PIPEDRIVE_FIELDS = {
    "purchase_price": "f35b15a7532b71e471559326865cd44dafe84545",
    "wholesale_price": "c9a33092e8932b3fb7f872a1fdd0db38b677759d", 
    "calculator_link": "cd46fcc11c8f25cf11645579ab6d2c7c1a112729",
    "seller_finance": "6a272500b072703c514c17e219443220fb4a2f10"
}

# Database config - using Supabase or any PostgreSQL
DATABASE_URL = st.secrets.get("DATABASE_URL", "")

# Google Sheets config
GOOGLE_SHEETS_CREDS = st.secrets.get("gcp_service_account", {})
SHEET_ID = st.secrets.get("GOOGLE_SHEET_ID", "1HJEx8uuMEA-PPM_gGghmYLaMusVTdUsAEENqqBEmuhM")  # <-- PUT YOUR SHEET ID HERE
WORKSHEET_NAME = "logic"

# ============= STYLING =============
st.markdown("""
<style>
    .offer-card {
        padding: 20px;
        border-radius: 12px;
        margin: 15px 0;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .purchase-offer {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
    }
    .wholesale-offer {
        background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
        color: white;
    }
    .finance-offer {
        background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
        color: white;
    }
    .big-number {
        font-size: 36px;
        font-weight: bold;
        margin: 10px 0;
    }
    .profit-positive { color: #10b981; }
    .profit-negative { color: #ef4444; }
    .section-header {
        background: linear-gradient(90deg, #1e3a8a 0%, #3b82f6 100%);
        color: white;
        padding: 10px 20px;
        border-radius: 8px;
        margin: 20px 0 10px 0;
    }
    .stButton > button {
        background: #3b82f6;
        color: white;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

# ============= DATABASE FUNCTIONS =============
@st.cache_resource
def init_db():
    """Initialize PostgreSQL connection"""
    if not DATABASE_URL:
        return None
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS calculations (
                id SERIAL PRIMARY KEY,
                deal_id VARCHAR(20) UNIQUE NOT NULL,
                data JSONB NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        cur.close()
        return conn
    except Exception as e:
        st.error(f"Database connection failed: {e}")
        return None

def save_to_db(deal_id, data):
    """Save calculation data to database"""
    conn = init_db()
    if not conn:
        return False
    
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO calculations (deal_id, data, updated_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (deal_id) 
            DO UPDATE SET data = %s, updated_at = %s
        """, (deal_id, json.dumps(data), datetime.now(), json.dumps(data), datetime.now()))
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        st.error(f"Save failed: {e}")
        return False

def load_from_db(deal_id):
    """Load calculation data from database"""
    conn = init_db()
    if not conn or not deal_id:
        return None
    
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT data FROM calculations WHERE deal_id = %s", (deal_id,))
        result = cur.fetchone()
        cur.close()
        return result['data'] if result else None
    except Exception as e:
        st.error(f"Load failed: {e}")
        return None


# Add this debug function to test the connection
def test_google_sheets_connection():
    """Test Google Sheets connection with detailed debugging"""
    st.subheader("🔍 Google Sheets Connection Debugger")
    
    try:
        # Step 1: Check credentials
        st.write("**Step 1: Checking credentials...**")
        if "gcp_service_account" not in st.secrets:
            st.error("❌ No service account credentials found in secrets!")
            st.stop()
        else:
            st.success("✓ Service account credentials found")
            
            # Show service account email
            service_account_info = dict(st.secrets["gcp_service_account"])
            if "client_email" in service_account_info:
                st.info(f"Service Account: {service_account_info['client_email']}")
        
        # Step 2: Authenticate
        st.write("**Step 2: Authenticating...**")
        scope = ['https://spreadsheets.google.com/feeds',
                 'https://www.googleapis.com/auth/spreadsheets',
                 'https://www.googleapis.com/auth/drive']
        
        creds = Credentials.from_service_account_info(
            service_account_info, 
            scopes=scope
        )
        client = gspread.authorize(creds)
        st.success("✓ Authentication successful")
        
        # Step 3: List accessible sheets (optional)
        st.write("**Step 3: Testing access...**")
        try:
            all_sheets = client.openall()
            st.success(f"✓ Can access {len(all_sheets)} spreadsheets")
            
            # Show sheet names
            with st.expander("View accessible sheets"):
                for sheet in all_sheets[:10]:  # Show first 10
                    st.write(f"- {sheet.title}")
                if len(all_sheets) > 10:
                    st.write(f"... and {len(all_sheets) - 10} more")
        except Exception as e:
            st.warning(f"Could not list sheets: {e}")
        
        # Step 4: Try to open the specific sheet
        st.write("**Step 4: Opening your specific sheet...**")
        st.code(f"Sheet ID: {SHEET_ID}")
        
        try:
            spreadsheet = client.open_by_key(SHEET_ID)
            st.success(f"✓ Successfully opened sheet: {spreadsheet.title}")
            
            # List worksheets
            worksheets = spreadsheet.worksheets()
            st.write(f"Found {len(worksheets)} worksheet(s):")
            for ws in worksheets:
                st.write(f"- '{ws.title}'")
            
            # Try to access the 'logic' worksheet
            if WORKSHEET_NAME in [ws.title for ws in worksheets]:
                worksheet = spreadsheet.worksheet(WORKSHEET_NAME)
                st.success(f"✓ Found worksheet '{WORKSHEET_NAME}'")
                
                # Show preview
                all_values = worksheet.get_all_values()
                st.write(f"Sheet contains {len(all_values)} rows")
                
                if all_values:
                    st.write("**Preview (first 3 rows):**")
                    for i, row in enumerate(all_values[:3]):
                        st.write(f"Row {i+1}: {row[:5]}")  # Show first 5 columns
            else:
                st.error(f"❌ Worksheet '{WORKSHEET_NAME}' not found!")
                st.info(f"Available worksheets: {[ws.title for ws in worksheets]}")
                
        except gspread.exceptions.SpreadsheetNotFound:
            st.error("❌ Spreadsheet not found!")
            st.info("This usually means:")
            st.info("1. The sheet ID is incorrect, OR")
            st.info("2. The sheet is not shared with the service account")
            
        except gspread.exceptions.APIError as e:
            error_msg = str(e)
            if "403" in error_msg or "PERMISSION_DENIED" in error_msg:
                st.error("❌ Permission denied!")
                st.warning("**To fix this:**")
                st.info("1. Open your Google Sheet")
                st.info("2. Click the Share button")
                st.info("3. Add this email: principal-acres-script-kpi-tra@database-project-468600.iam.gserviceaccount.com")
                st.info("4. Give it 'Editor' or 'Viewer' access")
                st.info("5. Click Share (uncheck 'Notify people')")
            elif "404" in error_msg:
                st.error("❌ Sheet not found (404)")
                st.info("Check that the Sheet ID is correct")
            else:
                st.error(f"❌ API Error: {error_msg}")
                
        except Exception as e:
            st.error(f"❌ Unexpected error: {e}")
            st.exception(e)
            
    except Exception as e:
        st.error(f"❌ Connection test failed: {e}")
        st.exception(e)

# Add this to your main() function, right after init_db():
def main():
    # Initialize database
    init_db()
    
    # Add debug mode toggle in sidebar
    with st.sidebar:
        debug_mode = st.checkbox("🔧 Debug Google Sheets Connection")
        
        if debug_mode:
            test_google_sheets_connection()
            st.stop()  # Stop here when in debug mode
    
    # Rest of your main() function continues...
    # Load config from Google Sheets
    config = load_google_sheets_config()

# ============= GOOGLE SHEETS FUNCTIONS =============
def get_default_config():
    """Return default configuration values when Google Sheets is not available"""
    st.warning("⚠️ Using default values - Google Sheets not connected")
    return {
        'thresholds': [0, 15000, 20000, 25000, 30000, 35000, 40000, 50000, 
                      60000, 80000, 100000, 150000, 200000, 250000, 300000, 400000, 500000],
        'purchase_returns': [0, 2000, 2500, 3000, 4000, 5000, 5500, 7000, 
                           8000, 10000, 12500, 17500, 20000, 22500, 25000, 30000, 35000],
        'wholesale_returns': [0, 4000, 5000, 6000, 7000, 7500, 8500, 10000,
                            12000, 15000, 20000, 25000, 30000, 35000, 40000, 50000, 60000]
    }

@st.cache_data(ttl=300)  
def load_google_sheets_config():
    """Load configuration from Google Sheets using direct Sheet ID"""
    try:
        # Authenticate with Google Sheets
        scope = ['https://spreadsheets.google.com/feeds',
                 'https://www.googleapis.com/auth/spreadsheets',
                 'https://www.googleapis.com/auth/drive']
        
        # Check if credentials exist
        if "gcp_service_account" not in st.secrets:
            st.error("❌ Missing gcp_service_account in Streamlit secrets!")
            st.info("Add your service account JSON to Streamlit secrets under 'gcp_service_account'")
            return get_default_config()
        
        # Check if Sheet ID is configured
        if SHEET_ID == "YOUR_SHEET_ID_HERE" or not SHEET_ID:
            st.error("❌ Google Sheet ID not configured!")
            st.info("Add GOOGLE_SHEET_ID to your Streamlit secrets, or update the SHEET_ID variable in the code")
            st.info("Find your Sheet ID in the URL: docs.google.com/spreadsheets/d/[SHEET_ID]/edit")
            return get_default_config()
        
        creds = Credentials.from_service_account_info(
            dict(st.secrets["gcp_service_account"]), 
            scopes=scope
        )
        client = gspread.authorize(creds)
        
        # Open spreadsheet by ID (more reliable than by name)
        try:
            spreadsheet = client.open_by_key(SHEET_ID)
            st.success(f"✓ Connected to Google Sheet")
            
            # Try to get sheet title for confirmation
            try:
                sheet_title = spreadsheet.title
                st.info(f"Sheet name: {sheet_title}")
            except:
                pass
                
        except gspread.exceptions.APIError as e:
            if "403" in str(e):
                st.error("❌ Permission denied! Sheet is not shared with service account.")
                st.info("Share your sheet with: principal-acres-script-kpi-tra@database-project-468600.iam.gserviceaccount.com")
            else:
                st.error(f"❌ API Error: {e}")
            return get_default_config()
        except Exception as e:
            st.error(f"❌ Could not open sheet with ID: {SHEET_ID}")
            st.error(f"Error: {e}")
            return get_default_config()
        
        # Get the worksheet
        worksheet = None
        try:
            worksheet = spreadsheet.worksheet(WORKSHEET_NAME)
            st.success(f"✓ Found worksheet: '{WORKSHEET_NAME}'")
        except gspread.WorksheetNotFound:
            # List all available worksheets
            worksheet_names = [ws.title for ws in spreadsheet.worksheets()]
            st.warning(f"❌ Worksheet '{WORKSHEET_NAME}' not found!")
            st.info(f"Available worksheets: {worksheet_names}")
            
            # Try to use the first worksheet as fallback
            if worksheet_names:
                worksheet = spreadsheet.worksheet(worksheet_names[0])
                st.info(f"Using worksheet: '{worksheet_names[0]}'")
            else:
                st.error("No worksheets found in the spreadsheet!")
                return get_default_config()
        
        # Get all values from the sheet
        all_values = worksheet.get_all_values()
        
        if not all_values:
            st.error("❌ Sheet is empty!")
            return get_default_config()
        
        # Show sheet info for debugging
        st.info(f"📊 Sheet has {len(all_values)} rows × {len(all_values[0]) if all_values else 0} columns")
        
        # Show first few rows to help debug structure
        with st.expander("🔍 Preview sheet data (first 5 rows)"):
            for i, row in enumerate(all_values[:5]):
                # Show only first 3 columns to keep it clean
                preview = row[:3] if len(row) >= 3 else row
                st.write(f"Row {i+1}: {preview}")
        
        # Parse the data
        thresholds = []
        purchase_returns = []
        wholesale_returns = []
        
        # Detect if first row has headers
        first_row = all_values[0] if all_values else []
        has_headers = False
        
        # Check for common header keywords
        if first_row:
            first_row_str = " ".join(str(cell).upper() for cell in first_row[:3])
            if any(keyword in first_row_str for keyword in ["FMV", "PURCHASE", "WHOLESALE", "THRESHOLD", "RETURN"]):
                has_headers = True
                st.info(f"📋 Headers detected: {first_row[:3]}")
        
        start_row = 1 if has_headers else 0
        
        # Process data rows
        rows_processed = 0
        rows_skipped = 0
        
        for i in range(start_row, len(all_values)):
            row = all_values[i]
            
            # Skip empty rows
            if not row or not row[0] or str(row[0]).strip() == '':
                rows_skipped += 1
                continue
            
            try:
                # Clean and parse Column A (FMV threshold)
                fmv_str = str(row[0]).replace(',', '').replace('$', '').strip()
                fmv_value = float(fmv_str)
                
                # Auto-detect if values need to be multiplied by 1000
                # (if the first valid value is less than 1000, assume it's in thousands)
                if rows_processed == 0 and fmv_value < 1000:
                    st.info("💡 Values appear to be in thousands, multiplying by 1000")
                
                if fmv_value < 1000:
                    fmv_value *= 1000
                
                thresholds.append(fmv_value)
                
                # Column B: Purchase Expected Return
                purchase_value = 0
                if len(row) > 1 and row[1] and str(row[1]).strip():
                    purchase_str = str(row[1]).replace(',', '').replace('$', '').strip()
                    purchase_value = float(purchase_str)
                purchase_returns.append(purchase_value)
                
                # Column C: Wholesale Expected Return
                wholesale_value = 0
                if len(row) > 2 and row[2] and str(row[2]).strip():
                    wholesale_str = str(row[2]).replace(',', '').replace('$', '').strip()
                    wholesale_value = float(wholesale_str)
                wholesale_returns.append(wholesale_value)
                
                rows_processed += 1
                    
            except ValueError as e:
                st.warning(f"⚠️ Could not parse row {i+1}: {row[:3]} - Skipping...")
                rows_skipped += 1
                continue
        
        if len(thresholds) == 0:
            st.error("❌ No valid data found in sheet!")
            st.info("Make sure your sheet has numeric values in columns A, B, and C")
            return get_default_config()
        
        st.success(f"✅ Successfully loaded {len(thresholds)} threshold levels")
        if rows_skipped > 0:
            st.info(f"Skipped {rows_skipped} invalid/empty rows")
        
        # Show summary of loaded data
        with st.expander("📊 Loaded data summary"):
            st.write(f"**Data range:**")
            st.write(f"- FMV: ${min(thresholds):,.0f} to ${max(thresholds):,.0f}")
            st.write(f"- Purchase returns: ${min(purchase_returns):,.0f} to ${max(purchase_returns):,.0f}")
            st.write(f"- Wholesale returns: ${min(wholesale_returns):,.0f} to ${max(wholesale_returns):,.0f}")
            
            # Show first few entries
            st.write("\n**First 3 entries:**")
            for i in range(min(3, len(thresholds))):
                st.write(f"{i+1}. FMV ${thresholds[i]:,.0f} → Purchase ${purchase_returns[i]:,.0f}, Wholesale ${wholesale_returns[i]:,.0f}")
        
        return {
            'thresholds': thresholds,
            'purchase_returns': purchase_returns,
            'wholesale_returns': wholesale_returns
        }
        
    except Exception as e:
        st.error(f"❌ Unexpected error loading Google Sheets: {str(e)}")
        st.exception(e)  # Show full traceback for debugging
        return get_default_config()

def get_expected_return(fmv, config, offer_type='purchase'):
    """Get expected return based on FMV using the threshold table"""
    thresholds = config['thresholds']
    
    if offer_type == 'purchase':
        returns = config['purchase_returns']
    else:  # wholesale
        returns = config['wholesale_returns']
    
    # Find the appropriate return based on FMV
    for i in range(len(thresholds) - 1, -1, -1):
        if fmv >= thresholds[i]:
            return returns[i]
    return 0

# ============= CALCULATION FUNCTIONS =============
def calculate_offers(fmv, config):
    """Calculate the three offer prices based on formulas"""
    # Get expected returns for each offer type
    purchase_return = get_expected_return(fmv, config, 'purchase')
    wholesale_return = get_expected_return(fmv, config, 'wholesale')
    
    # Purchase Price = (FMV × 0.94 - purchase_return) / 1.0525
    purchase_price = (fmv * 0.94 - purchase_return) / 1.0525
    
    # Wholesale Price = FMV × 0.94 - 2500 - wholesale_return
    wholesale_price = fmv * 0.94 - 2500 - wholesale_return
    
    return {
        'purchase': max(0, purchase_price),
        'wholesale': max(0, wholesale_price),
        'purchase_return': purchase_return,
        'wholesale_return': wholesale_return
    }

def calculate_seller_finance(value, config, percentage=0.85):
    """Calculate seller finance offer"""
    # Get the purchase expected return for this value
    purchase_return = get_expected_return(value, config, 'purchase')
    # Seller Finance = value × percentage × 0.94 - 3500 - purchase_return
    seller_finance = value * percentage * 0.94 - 3500 - purchase_return
    return max(0, seller_finance)

# ============= PIPEDRIVE FUNCTIONS =============
def push_to_pipedrive(deal_id, data):
    """Push calculated values to Pipedrive"""
    if not PIPEDRIVE_API_TOKEN or not PIPEDRIVE_DOMAIN:
        st.warning("Pipedrive credentials not configured")
        return False
    
    try:
        url = f"https://{PIPEDRIVE_DOMAIN}.pipedrive.com/api/v1/deals/{deal_id}?api_token={PIPEDRIVE_API_TOKEN}"
        
        # Prepare the data
        payload = {
            PIPEDRIVE_FIELDS['purchase_price']: data['purchase_price'],
            PIPEDRIVE_FIELDS['wholesale_price']: data['wholesale_price'],
            PIPEDRIVE_FIELDS['seller_finance']: data.get('seller_finance', 0),
            PIPEDRIVE_FIELDS['calculator_link']: st.get_url() + f"?deal_id={deal_id}"
        }
        
        response = requests.put(url, json=payload)
        return response.status_code == 200
    except Exception as e:
        st.error(f"Pipedrive update failed: {e}")
        return False

# ============= MAIN APP =============
# ============= MAIN APP =============
def main():
    # Initialize database
    init_db()
    
    # Add debug mode toggle in sidebar
    with st.sidebar:
        st.markdown("### 🛠️ Debug Tools")
        debug_mode = st.checkbox("Debug Google Sheets Connection")
        
        if debug_mode:
            test_google_sheets_connection()
            st.markdown("---")
            st.info("Debug mode is ON. Uncheck to use the calculator.")
            st.stop()  # Stop here when in debug mode
    
    # Load config from Google Sheets
    config = load_google_sheets_config()
    
    # Get deal_id from URL
    query_params = st.query_params
    deal_id = query_params.get('deal_id', '')
    
    # Header
    col1, col2, col3 = st.columns([3, 2, 1])
    with col1:
        st.title("🏞️ Land Offer Calculator")
    with col2:
        deal_id_input = st.text_input("Deal ID", value=deal_id, key="deal_id_input")
        if deal_id_input != deal_id:
            st.query_params['deal_id'] = deal_id_input
            deal_id = deal_id_input
    with col3:
        if deal_id:
            existing_data = load_from_db(deal_id)
            if existing_data:
                st.success("✓ Data Loaded")
    
    # Initialize session state
    if 'data' not in st.session_state:
        st.session_state.data = {}
    
    # Main content
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Property & Offers", "🏘️ Comps Analysis", "📐 Subdivision", "💰 Negotiation"])
    
    with tab1:
        st.markdown('<div class="section-header">Property Details</div>', unsafe_allow_html=True)
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            fmv_input = st.number_input(
                "Fair Market Value ($)",
                min_value=0,
                value=int(st.session_state.data.get('fmv', 100000)),
                step=1000,
                key="fmv"
            )
            
            acreage = st.number_input(
                "Acreage",
                min_value=0.0,
                value=float(st.session_state.data.get('acreage', 5.0)),
                step=0.1,
                key="acreage"
            )
        
        with col2:
            st.subheader("Property Adjustments")
            
            well_adjustment = st.checkbox(
                "Existing Well (+$5,000)",
                value=st.session_state.data.get('well', False)
            )
            
            septic_adjustment = st.checkbox(
                "Existing Septic (+$5,000)",
                value=st.session_state.data.get('septic', False)
            )
            
            manual_adjustment = st.number_input(
                "Other Adjustments ($)",
                value=int(st.session_state.data.get('manual_adj', 0)),
                step=500,
                key="manual_adj"
            )
        
        with col3:
            st.subheader("Subdivision Potential")
            
            can_subdivide = st.checkbox(
                "Can Subdivide",
                value=st.session_state.data.get('can_subdivide', False)
            )
            
            can_add_road = st.checkbox(
                "Can Add Road Frontage",
                value=st.session_state.data.get('can_add_road', False)
            )
            
            can_admin_split = st.checkbox(
                "Administrative Split Possible",
                value=st.session_state.data.get('can_admin_split', False)
            )
        
        # Calculate adjusted FMV
        total_adjustments = 0
        if well_adjustment:
            total_adjustments += 5000
        if septic_adjustment:
            total_adjustments += 5000
        total_adjustments += manual_adjustment
        
        adjusted_fmv = fmv_input + total_adjustments
        
        # Calculate offers
        offers = calculate_offers(adjusted_fmv, config)
        purchase_return = offers['purchase_return']
        wholesale_return = offers['wholesale_return']
        
        # Show seller finance if conditions are met
        show_seller_finance = (can_subdivide or can_add_road or can_admin_split or fmv_input >= 400000)
        
        st.markdown('<div class="section-header">Calculated Offers</div>', unsafe_allow_html=True)
        
        # Display offers
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.markdown(f"""
                <div class="offer-card purchase-offer">
                    <div style="font-size: 18px;">Purchase Price</div>
                    <div class="big-number">${offers['purchase']:,.0f}</div>
                    <div style="font-size: 14px;">Direct Purchase</div>
                </div>
            """, unsafe_allow_html=True)
            
            # Show profit calculation
            profit = adjusted_fmv * 0.94 - 3500 - offers['purchase'] * 1.0525
            profit_class = "profit-positive" if profit > 0 else "profit-negative"
            st.markdown(f'<div class="{profit_class}">Expected Profit: ${profit:,.0f}</div>', unsafe_allow_html=True)
        
        with col2:
            st.markdown(f"""
                <div class="offer-card wholesale-offer">
                    <div style="font-size: 18px;">Wholesale Price</div>
                    <div class="big-number">${offers['wholesale']:,.0f}</div>
                    <div style="font-size: 14px;">With Margin</div>
                </div>
            """, unsafe_allow_html=True)
            
            # Show wholesale margin
            margin = adjusted_fmv * 0.94 - 2500 - offers['wholesale']
            st.markdown(f'<div class="profit-positive">Wholesale Margin: ${margin:,.0f}</div>', unsafe_allow_html=True)
        
        with col3:
            if show_seller_finance:
                # Seller finance percentage selector
                sf_percentage = st.slider(
                    "Seller Finance %",
                    min_value=80,
                    max_value=95,
                    value=85,
                    step=5,
                    key="sf_percentage"
                ) / 100
                
                sf_price = calculate_seller_finance(adjusted_fmv, config, sf_percentage)
                
                st.markdown(f"""
                    <div class="offer-card finance-offer">
                        <div style="font-size: 18px;">Seller Finance</div>
                        <div class="big-number">${sf_price:,.0f}</div>
                        <div style="font-size: 14px;">{int(sf_percentage*100)}% of FMV</div>
                    </div>
                """, unsafe_allow_html=True)
                
                # Show terms
                st.markdown("""
                    **Terms Options:**
                    - 12-month interest-only, balloon
                    - 5-7 year amortized
                """)
            else:
                st.info("Seller Finance not available (requires subdivision potential or $400k+ value)")
        
        # Summary section
        st.markdown('<div class="section-header">Summary</div>', unsafe_allow_html=True)
        
        summary_col1, summary_col2 = st.columns(2)
        
        with summary_col1:
            st.markdown(f"""
                **Property Analysis:**
                - Fair Market Value: ${fmv_input:,.0f}
                - Adjustments: ${total_adjustments:,.0f}
                - Adjusted FMV: ${adjusted_fmv:,.0f}
                - Purchase Expected Return: ${purchase_return:,.0f}
                - Wholesale Expected Return: ${wholesale_return:,.0f}
                - Acreage: {acreage} acres
                - Price per Acre: ${(adjusted_fmv/acreage if acreage > 0 else 0):,.0f}
            """)
        
        with summary_col2:
            # Save and Push buttons
            col_save, col_push = st.columns(2)
            
            with col_save:
                if st.button("💾 Save Calculations", use_container_width=True):
                    # Prepare data for saving
                    save_data = {
                        'fmv': fmv_input,
                        'acreage': acreage,
                        'well': well_adjustment,
                        'septic': septic_adjustment,
                        'manual_adj': manual_adjustment,
                        'adjusted_fmv': adjusted_fmv,
                        'purchase_return': purchase_return,
                        'wholesale_return': wholesale_return,
                        'purchase_price': offers['purchase'],
                        'wholesale_price': offers['wholesale'],
                        'can_subdivide': can_subdivide,
                        'can_add_road': can_add_road,
                        'can_admin_split': can_admin_split
                    }
                    
                    if show_seller_finance:
                        save_data['seller_finance'] = sf_price
                        save_data['sf_percentage'] = sf_percentage
                    
                    if save_to_db(deal_id, save_data):
                        st.success("✓ Saved successfully!")
                        st.session_state.data = save_data
            
            with col_push:
                if st.button("📤 Push to Pipedrive", use_container_width=True):
                    if deal_id:
                        push_data = {
                            'purchase_price': offers['purchase'],
                            'wholesale_price': offers['wholesale'],
                            'seller_finance': sf_price if show_seller_finance else 0
                        }
                        if push_to_pipedrive(deal_id, push_data):
                            st.success("✓ Pushed to Pipedrive!")
                        else:
                            st.error("Failed to push to Pipedrive")
                    else:
                        st.warning("Enter a Deal ID first")
    
    with tab2:
        st.markdown('<div class="section-header">Comp Analysis</div>', unsafe_allow_html=True)
        
        # Sold Comp
        st.subheader("🔍 Most Relevant Sold Comp")
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            sold_comp_link = st.text_input("Zillow/Redfin Link", key="sold_link")
        with col2:
            sold_comp_price = st.number_input("Sale Price ($)", min_value=0, step=1000, key="sold_price")
        with col3:
            sold_comp_acres = st.number_input("Acreage", min_value=0.0, step=0.1, key="sold_acres")
        with col4:
            if sold_comp_acres > 0:
                sold_ppa = sold_comp_price / sold_comp_acres
                st.metric("Price per Acre", f"${sold_ppa:,.0f}")
                
                if acreage > 0:
                    subject_value_sold = sold_ppa * acreage
                    st.metric("Subject Value (Sold Comp)", f"${subject_value_sold:,.0f}")
        
        # Active Comp
        st.subheader("🔍 Most Accurate Active Comp")
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            active_comp_link = st.text_input("Zillow/Redfin Link", key="active_link")
        with col2:
            active_comp_price = st.number_input("Listing Price ($)", min_value=0, step=1000, key="active_price")
        with col3:
            active_comp_acres = st.number_input("Acreage", min_value=0.0, step=0.1, key="active_acres")
        with col4:
            if active_comp_acres > 0:
                active_ppa = active_comp_price / active_comp_acres
                st.metric("Price per Acre", f"${active_ppa:,.0f}")
                
                if acreage > 0:
                    subject_value_active = active_ppa * acreage
                    st.metric("Subject Value (Active)", f"${subject_value_active:,.0f}")
    
    with tab3:
        st.markdown('<div class="section-header">Subdivision Analysis</div>', unsafe_allow_html=True)
        
        # Road Frontage Subdivision
        st.subheader("🛣️ Road Frontage Subdivision")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            road_frontage = st.number_input("Road Frontage (ft)", min_value=0, value=0, step=10)
        with col2:
            frontage_required = st.number_input("Frontage Required per Lot (ft)", min_value=0, value=100, step=10)
        with col3:
            if frontage_required > 0:
                lots_possible = int(road_frontage / frontage_required)
                st.metric("Lots Possible", lots_possible)
                
                if lots_possible > 0 and acreage > 0:
                    acres_per_lot = acreage / lots_possible
                    st.metric("Acres per Lot", f"{acres_per_lot:.2f}")
        
        # Rest of tab3 content...
        # [Include the rest of your tab3 and tab4 content here]

if __name__ == "__main__":
    main()
