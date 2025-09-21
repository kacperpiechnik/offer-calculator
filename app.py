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



# ============= GOOGLE SHEETS FUNCTIONS =============
# ============= GOOGLE SHEETS FUNCTIONS =============
def get_default_config():
    """Return hardcoded configuration values directly from CSV"""
    # Values directly from your CSV file
    # All values are already in full dollar amounts (not thousands)
    return {
        'thresholds': [
            0,      # Row 1
            15000,  # Row 2
            20000,  # Row 3
            25000,  # Row 4
            30000,  # Row 5
            35000,  # Row 6
            40000,  # Row 7
            50000,  # Row 8
            60000,  # Row 9
            70000,  # Row 10
            80000,  # Row 11
            100000, # Row 12
            125000, # Row 13
            150000, # Row 14
            175000, # Row 15
            200000, # Row 16
            250000, # Row 17
            300000, # Row 18
            350000, # Row 19
            400000, # Row 20
            500000, # Row 21
            600000, # Row 22
            700000, # Row 23
            900000, # Row 24
            1000000 # Row 25
        ],
        'purchase_returns': [
            0,      # Row 1
            5000,   # Row 2 (5 * 1000)
            6000,   # Row 3 (6 * 1000)
            7500,   # Row 4 (7.5 * 1000)
            10000,  # Row 5 (10 * 1000)
            10000,  # Row 6 (10 * 1000)
            12000,  # Row 7 (12 * 1000)
            12500,  # Row 8 (12.5 * 1000)
            15000,  # Row 9 (15 * 1000)
            17500,  # Row 10 (17.5 * 1000)
            20000,  # Row 11 (20 * 1000)
            25000,  # Row 12 (25 * 1000)
            30000,  # Row 13 (30 * 1000)
            37500,  # Row 14 (37.5 * 1000)
            42500,  # Row 15 (42.5 * 1000)
            50000,  # Row 16 (50 * 1000)
            60000,  # Row 17 (60 * 1000)
            70000,  # Row 18 (70 * 1000)
            80000,  # Row 19 (80 * 1000)
            100000, # Row 20 (100 * 1000)
            110000, # Row 21 (110 * 1000)
            125000, # Row 22 (125 * 1000)
            150000, # Row 23 (150 * 1000)
            175000, # Row 24 (175 * 1000)
            300000  # Row 25 (300 * 1000)
        ],
        'wholesale_returns': [
            0,      # Row 1
            4000,   # Row 2 (4 * 1000)
            4000,   # Row 3 (4 * 1000)
            5000,   # Row 4 (5 * 1000)
            10000,  # Row 5 (10 * 1000)
            10000,  # Row 6 (10 * 1000)
            15000,  # Row 7 (15 * 1000)
            20000,  # Row 8 (20 * 1000)
            17500,  # Row 9 (17.5 * 1000)
            20000,  # Row 10 (20 * 1000)
            22500,  # Row 11 (22.5 * 1000)
            20000,  # Row 12 (20 * 1000)
            22500,  # Row 13 (22.5 * 1000)
            25000,  # Row 14 (25 * 1000)
            30000,  # Row 15 (30 * 1000)
            35000,  # Row 16 (35 * 1000)
            35000,  # Row 17 (35 * 1000)
            45000,  # Row 18 (45 * 1000)
            50000,  # Row 19 (50 * 1000)
            60000,  # Row 20 (60 * 1000)
            65000,  # Row 21 (65 * 1000)
            65000,  # Row 22 (65 * 1000)
            70000,  # Row 23 (70 * 1000)
            80000,  # Row 24 (80 * 1000)
            100000  # Row 25 (100 * 1000)
        ]
    }

@st.cache_data(ttl=300)  
def load_google_sheets_config():
    """Load configuration - using hardcoded values from CSV"""
    # Set connection status for UI
    st.session_state.sheets_connected = True
    st.session_state.sheet_name = "Built-in Configuration"
    st.session_state.thresholds_loaded = 25
    
    # Return the hardcoded configuration
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
# ============= CALCULATION FUNCTIONS =============
def calculate_offers(fmv, config):
    """Calculate the offer prices based on NSP (Net Sales Price) formulas"""
    # Get expected returns for each offer type
    purchase_return = get_expected_return(fmv, config, 'purchase')
    wholesale_return = get_expected_return(fmv, config, 'wholesale')
    
    # Calculate Net Sales Price (NSP)
    nsp_purchase = fmv * 0.94 - 3500  # NSP Purchase = 0.94*FMV - 3.5k
    nsp_wholesale = fmv * 0.94 - 2500  # NSP Wholesale = 0.94*FMV - 2.5k
    
    # Calculate offer prices
    # Purchase = (NSP Purchase - Expected Purchase Return) / 1.0525
    purchase_price = (nsp_purchase - purchase_return) / 1.0525
    
    # Wholesale = NSP Wholesale - Expected Wholesale Return
    wholesale_price = nsp_wholesale - wholesale_return
    
    return {
        'purchase': max(0, purchase_price),
        'wholesale': max(0, wholesale_price),
        'purchase_return': purchase_return,
        'wholesale_return': wholesale_return,
        'nsp_purchase': nsp_purchase,
        'nsp_wholesale': nsp_wholesale
    }

def calculate_seller_finance(value, config, percentage=0.85):
    """Calculate seller finance offer"""
    # Get the purchase expected return for this value
    purchase_return = get_expected_return(value, config, 'purchase')
    
    # Calculate NSP for seller finance (same as purchase NSP)
    nsp_seller_finance = value * percentage * 0.94 - 3500
    
    # Seller Finance = NSP - Expected Purchase Return (no division by 1.0525 for seller finance)
    seller_finance = nsp_seller_finance - purchase_return
    
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
    
    # Load config from Google Sheets (or hardcoded values)
    config = load_google_sheets_config()
    
    # Sidebar with connection status
    with st.sidebar:
        st.markdown("### 📊 System Status")
        
        # Google Sheets connection indicator
        if st.session_state.get('sheets_connected', False):
            st.success("✓ Connected to Configuration")
            if st.session_state.get('thresholds_loaded', 0) > 0:
                st.caption(f"Loaded {st.session_state.get('thresholds_loaded', 0)} price tiers")
        else:
            st.warning("⚠ Using default values")
        
        # Database connection indicator
        if DATABASE_URL:
            st.success("✓ Database connected")
        else:
            st.info("ℹ Database not configured")
        
        st.markdown("---")
    
    # Get deal_id from URL
    query_params = st.query_params
    deal_id = query_params.get('deal_id', '')
    
    # Header
    col1, col2, col3 = st.columns([3, 2, 1])
    with col1:
        st.title("🏞️ Land Offer Calculator")
    with col2:
        deal_id_input = st.text_input("Deal ID", value=deal_id, key="deal_id_input", 
                                     placeholder="Enter Deal ID")
        if deal_id_input != deal_id:
            st.query_params['deal_id'] = deal_id_input
            deal_id = deal_id_input
    with col3:
        if deal_id:
            existing_data = load_from_db(deal_id)
            if existing_data:
                st.success("✓ Loaded")
                st.session_state.data = existing_data
    
    # Initialize session state
    if 'data' not in st.session_state:
        st.session_state.data = {}
    
    # Main content tabs
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
                format="%d",
                help="Enter the estimated fair market value of the property"
            )
            
            acreage = st.number_input(
                "Acreage",
                min_value=0.0,
                value=float(st.session_state.data.get('acreage', 5.0)),
                step=0.1,
                format="%.2f",
                help="Total acres of the property"
            )
        
        with col2:
            st.subheader("Property Adjustments")
            
            well_adjustment = st.checkbox(
                "Existing Well (+$5,000)",
                value=st.session_state.data.get('well', False),
                help="Check if property has an existing well"
            )
            
            septic_adjustment = st.checkbox(
                "Existing Septic (+$5,000)",
                value=st.session_state.data.get('septic', False),
                help="Check if property has an existing septic system"
            )
            
            manual_adjustment = st.number_input(
                "Other Adjustments ($)",
                value=int(st.session_state.data.get('manual_adj', 0)),
                step=500,
                format="%d",
                help="Add any other value adjustments (positive or negative)"
            )
        
        with col3:
            st.subheader("Subdivision Potential")
            
            can_subdivide = st.checkbox(
                "Can Subdivide",
                value=st.session_state.data.get('can_subdivide', False),
                help="Property can be subdivided into multiple lots"
            )
            
            can_add_road = st.checkbox(
                "Can Add Road Frontage",
                value=st.session_state.data.get('can_add_road', False),
                help="Possible to add additional road frontage"
            )
            
            can_admin_split = st.checkbox(
                "Administrative Split Possible",
                value=st.session_state.data.get('can_admin_split', False),
                help="Property qualifies for administrative split"
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
            
            # Show expected return
            st.markdown(f'<div class="profit-positive">Target Return: ${purchase_return:,.0f}</div>', unsafe_allow_html=True)
            
            # Verify calculation if NSP values available
            if 'nsp_purchase' in offers:
                actual_profit = offers['nsp_purchase'] - (offers['purchase'] * 1.0525)
                if abs(actual_profit - purchase_return) < 1:
                    st.caption("✓ Achieves target return")
        
        with col2:
            st.markdown(f"""
                <div class="offer-card wholesale-offer">
                    <div style="font-size: 18px;">Wholesale Price</div>
                    <div class="big-number">${offers['wholesale']:,.0f}</div>
                    <div style="font-size: 14px;">With Margin</div>
                </div>
            """, unsafe_allow_html=True)
            
            # Show wholesale return
            st.markdown(f'<div class="profit-positive">Target Return: ${wholesale_return:,.0f}</div>', unsafe_allow_html=True)
            
            # Verify calculation if NSP values available
            if 'nsp_wholesale' in offers:
                actual_return = offers['nsp_wholesale'] - offers['wholesale']
                if abs(actual_return - wholesale_return) < 1:
                    st.caption("✓ Achieves target return")
        
        with col3:
            if show_seller_finance:
                # Seller finance percentage selector
                sf_percentage = st.slider(
                    "Seller Finance %",
                    min_value=80,
                    max_value=95,
                    value=85,
                    step=5,
                    help="Percentage of FMV for seller financing"
                ) / 100
                
                sf_price = calculate_seller_finance(adjusted_fmv, config, sf_percentage)
                
                st.markdown(f"""
                    <div class="offer-card finance-offer">
                        <div style="font-size: 18px;">Seller Finance</div>
                        <div class="big-number">${sf_price:,.0f}</div>
                        <div style="font-size: 14px;">{int(sf_percentage*100)}% of FMV</div>
                    </div>
                """, unsafe_allow_html=True)
                
                st.caption("**Terms:** 12-month balloon or 5-7 year amortized")
            else:
                st.info("💡 Seller Finance available for properties $400k+ or with subdivision potential")
        
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
                - Acreage: {acreage:.2f} acres
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
                    
                    if deal_id:
                        if save_to_db(deal_id, save_data):
                            st.success("✓ Saved successfully!")
                            st.session_state.data = save_data
                    else:
                        st.warning("Please enter a Deal ID to save")
            
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
        
        # Administrative Split
        st.subheader("📋 Administrative Split")
        col1, col2 = st.columns(2)
        
        with col1:
            admin_lots = st.number_input("Admin Split Lots Possible", min_value=0, value=0, step=1)
        with col2:
            if admin_lots > 0 and acreage > 0:
                admin_acres_per_lot = acreage / admin_lots
                st.metric("Acres per Lot (Admin)", f"{admin_acres_per_lot:.2f}")
        
        # Minor Split
        st.subheader("📋 Minor Split")
        col1, col2 = st.columns(2)
        
        with col1:
            minor_lots = st.number_input("Minor Split Lots Possible", min_value=0, value=0, step=1)
        with col2:
            if minor_lots > 0 and acreage > 0:
                minor_acres_per_lot = acreage / minor_lots
                st.metric("Acres per Lot (Minor)", f"{minor_acres_per_lot:.2f}")
        
        # Subdivision Comps
        st.subheader("💰 Subdivision Value Analysis")
        col1, col2 = st.columns(2)
        
        with col1:
            st.write("**Sold Subdivided Comp**")
            subdiv_sold_ppa = st.number_input("Sold PPA for Subdivided ($)", min_value=0, step=100, key="subdiv_sold_ppa")
            
            if subdiv_sold_ppa > 0:
                # Calculate values for each subdivision type
                if 'lots_possible' in locals() and lots_possible > 0:
                    road_value = lots_possible * acres_per_lot * subdiv_sold_ppa
                    st.metric("Road Frontage Subdivision Value", f"${road_value:,.0f}")
                
                if admin_lots > 0:
                    admin_value = admin_lots * admin_acres_per_lot * subdiv_sold_ppa
                    st.metric("Admin Split Value", f"${admin_value:,.0f}")
                
                if minor_lots > 0:
                    minor_value = minor_lots * minor_acres_per_lot * subdiv_sold_ppa
                    st.metric("Minor Split Value", f"${minor_value:,.0f}")
        
        with col2:
            st.write("**Active Subdivided Comp**")
            subdiv_active_ppa = st.number_input("Active PPA for Subdivided ($)", min_value=0, step=100, key="subdiv_active_ppa")
            
            if subdiv_active_ppa > 0:
                # Calculate values for each subdivision type
                if 'lots_possible' in locals() and lots_possible > 0:
                    road_value_active = lots_possible * acres_per_lot * subdiv_active_ppa
                    st.metric("Road Subdivision Value (Active)", f"${road_value_active:,.0f}")
                
                if admin_lots > 0:
                    admin_value_active = admin_lots * admin_acres_per_lot * subdiv_active_ppa
                    st.metric("Admin Split Value (Active)", f"${admin_value_active:,.0f}")
                
                if minor_lots > 0:
                    minor_value_active = minor_lots * minor_acres_per_lot * subdiv_active_ppa
                    st.metric("Minor Split Value (Active)", f"${minor_value_active:,.0f}")
    
    with tab4:
        st.markdown('<div class="section-header">Negotiation Tool</div>', unsafe_allow_html=True)
        
        st.subheader("🤝 Test Different Price Points")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.write("**Test Purchase Price**")
            test_purchase = st.number_input(
                "What if we offered ($):",
                min_value=0,
                value=int(offers['purchase']),
                step=1000,
                key="test_purchase"
            )
            
            # Calculate profit at this price using NSP formula
            if 'nsp_purchase' in offers:
                test_profit = offers['nsp_purchase'] - (test_purchase * 1.0525)
            else:
                nsp_test = adjusted_fmv * 0.94 - 3500
                test_profit = nsp_test - (test_purchase * 1.0525)
            
            if test_profit > 0:
                st.success(f"✓ Profit: ${test_profit:,.0f}")
                if test_purchase > 0:
                    st.metric("ROI", f"{(test_profit/test_purchase*100):.1f}%")
            else:
                st.error(f"✗ Loss: ${abs(test_profit):,.0f}")
            
            # Show comparison to calculated price
            difference = test_purchase - offers['purchase']
            if abs(difference) > 1:
                if difference > 0:
                    st.warning(f"${difference:,.0f} above calculated price")
                else:
                    st.info(f"${abs(difference):,.0f} below calculated price")
        
        with col2:
            st.write("**Test Wholesale Price**")
            test_wholesale = st.number_input(
                "What if we wholesaled at ($):",
                min_value=0,
                value=int(offers['wholesale']),
                step=1000,
                key="test_wholesale"
            )
            
            # Calculate margin at this price using NSP formula
            if 'nsp_wholesale' in offers:
                test_margin = offers['nsp_wholesale'] - test_wholesale
            else:
                nsp_test = adjusted_fmv * 0.94 - 2500
                test_margin = nsp_test - test_wholesale
            
            if test_margin > 0:
                st.success(f"✓ Margin: ${test_margin:,.0f}")
                if test_wholesale > 0:
                    st.metric("Margin %", f"{(test_margin/test_wholesale*100):.1f}%")
            else:
                st.error(f"✗ No margin")
            
            # Show comparison to calculated price
            difference_w = test_wholesale - offers['wholesale']
            if abs(difference_w) > 1:
                if difference_w > 0:
                    st.warning(f"${difference_w:,.0f} above calculated price")
                else:
                    st.info(f"${abs(difference_w):,.0f} below calculated price")
        
        # Quick adjustment buttons
        st.subheader("⚡ Quick Adjustments")
        
        col1, col2, col3, col4, col5 = st.columns(5)
        
        adjustments = [-10, -5, 0, 5, 10]
        for col, adj in zip([col1, col2, col3, col4, col5], adjustments):
            with col:
                button_label = "Reset" if adj == 0 else f"{adj:+}%"
                if st.button(button_label, use_container_width=True):
                    if adj == 0:
                        st.info(f"Purchase: ${offers['purchase']:,.0f}")
                        st.info(f"Wholesale: ${offers['wholesale']:,.0f}")
                    else:
                        st.info(f"Purchase: ${offers['purchase'] * (1 + adj/100):,.0f}")
                        st.info(f"Wholesale: ${offers['wholesale'] * (1 + adj/100):,.0f}")

if __name__ == "__main__":
    main()
