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
PIPEDRIVE_API_TOKEN = st.secrets.get("PIPEDRIVE_API_TOKEN", "")
PIPEDRIVE_DOMAIN = st.secrets.get("PIPEDRIVE_DOMAIN", "")

PIPEDRIVE_FIELDS = {
    "purchase_price": "f35b15a7532b71e471559326865cd44dafe84545",
    "wholesale_price": "c9a33092e8932b3fb7f872a1fdd0db38b677759d", 
    "calculator_link": "cd46fcc11c8f25cf11645579ab6d2c7c1a112729",
    "seller_finance": "6a272500b072703c514c17e219443220fb4a2f10"
}

DATABASE_URL = st.secrets.get("DATABASE_URL", "")

# ============= STYLING =============
st.markdown("""
<style>
    .offer-card {
        padding: 20px;
        border-radius: 12px;
        margin: 15px 0;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        min-height: 140px;
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
    .subdiv-card {
        background: linear-gradient(135deg, #fa709a 0%, #fee140 100%);
        color: white;
    }
    .big-number {
        font-size: 32px;
        font-weight: bold;
        margin: 10px 0;
    }
    .small-number {
        font-size: 14px;
        margin: 2px 0;
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
    /* Smaller adjustments text */
    .adjustment-row {
        font-size: 12px !important;
    }
    /* Reduce SF slider spacing */
    .element-container:has(.stSlider) {
        margin-top: -10px !important;
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

# ============= CONFIG FUNCTIONS =============
def get_default_config():
    """Return hardcoded configuration values"""
    return {
        'thresholds': [
            0, 15000, 20000, 25000, 30000, 35000, 40000, 50000,
            60000, 70000, 80000, 100000, 125000, 150000, 175000,
            200000, 250000, 300000, 350000, 400000, 500000, 600000,
            700000, 900000, 1000000
        ],
        'purchase_returns': [
            0, 5000, 6000, 7500, 10000, 10000, 12000, 12500,
            15000, 17500, 20000, 25000, 30000, 37500, 42500,
            50000, 60000, 70000, 80000, 100000, 110000, 125000,
            150000, 175000, 300000
        ],
        'wholesale_returns': [
            0, 4000, 4000, 5000, 10000, 10000, 15000, 20000,
            17500, 20000, 22500, 20000, 22500, 25000, 30000,
            35000, 35000, 45000, 50000, 60000, 65000, 65000,
            70000, 80000, 100000
        ]
    }

@st.cache_data(ttl=300)  
def load_google_sheets_config():
    """Load configuration - using hardcoded values"""
    st.session_state.sheets_connected = True
    st.session_state.sheet_name = "Built-in Configuration"
    st.session_state.thresholds_loaded = 25
    return get_default_config()

def get_expected_return(fmv, config, offer_type='purchase'):
    """Get expected return based on FMV using the threshold table"""
    thresholds = config['thresholds']
    
    if offer_type == 'purchase':
        returns = config['purchase_returns']
    else:
        returns = config['wholesale_returns']
    
    for i in range(len(thresholds) - 1, -1, -1):
        if fmv >= thresholds[i]:
            return returns[i]
    return 0

# ============= CALCULATION FUNCTIONS =============
def calculate_offers(fmv, config, custom_target=None):
    """Calculate the offer prices based on NSP formulas"""
    purchase_return = custom_target if custom_target else get_expected_return(fmv, config, 'purchase')
    wholesale_return = custom_target if custom_target else get_expected_return(fmv, config, 'wholesale')
    
    nsp_purchase = fmv * 0.94 - 3500
    nsp_wholesale = fmv * 0.94 - 2500
    
    purchase_price = (nsp_purchase - purchase_return) / 1.0525
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
    purchase_return = get_expected_return(value, config, 'purchase')
    nsp_seller_finance = value * percentage * 0.94 - 3500
    seller_finance = nsp_seller_finance - purchase_return
    return max(0, seller_finance)

def calculate_subdivision_profit(total_subdiv_value, purchase_price):
    """Calculate profit from subdivision
    Formula: Subdivided total value * 0.94 - 15k - Purchase price * 1.1"""
    return (total_subdiv_value * 0.94) - 15000 - (purchase_price * 1.1)

def calculate_subdivision_purchase(total_subdiv_value, config):
    """Calculate purchase price for subdivision based on expected return"""
    purchase_return = get_expected_return(total_subdiv_value, config, 'purchase')
    nsp_subdiv = total_subdiv_value * 0.94 - 15000
    purchase_price = (nsp_subdiv - purchase_return) / 1.1
    return max(0, purchase_price)

# ============= PIPEDRIVE FUNCTIONS =============
def auto_save_subdivision_data(deal_id, session_state):
    """Helper function to auto-save subdivision data"""
    if not deal_id:
        return
    
    save_data = {
        'subdiv_data': session_state.subdiv_data,
        'timestamp': datetime.now().isoformat()
    }
    
    # Load existing data and merge
    existing = load_from_db(deal_id)
    if existing:
        existing.update(save_data)
        save_data = existing
    
    save_to_db(deal_id, save_data)

def auto_save_all_data(deal_id, fmv, acreage, adjustments, can_subdivide, session_state, config):
    """Auto-save all calculator data"""
    if not deal_id:
        return False
    
    adjusted_fmv = fmv + sum(adj['amount'] for adj in adjustments)
    offers = calculate_offers(adjusted_fmv, config)
    
    save_data = {
        'fmv': fmv,
        'acreage': acreage,
        'adjustments': adjustments,
        'adjusted_fmv': adjusted_fmv,
        'purchase_price': offers['purchase'],
        'wholesale_price': offers['wholesale'],
        'can_subdivide': can_subdivide,
        'comp_values': session_state.comp_values,
        'subdiv_data': session_state.subdiv_data,
        'sf_percentage': session_state.get('sf_percentage', 85),
        'timestamp': datetime.now().isoformat()
    }
    
    return save_to_db(deal_id, save_data)

def push_to_pipedrive(deal_id, data):
    """Push calculated values to Pipedrive"""
    if not PIPEDRIVE_API_TOKEN or not PIPEDRIVE_DOMAIN:
        # For testing: Show what would be sent
        st.warning("Pipedrive not configured. Would send:")
        st.json({
            "deal_id": deal_id,
            "purchase_price": round(data['purchase_price']),
            "wholesale_price": round(data['wholesale_price']),
            "seller_finance": round(data.get('seller_finance', 0))
        })
        return False
    
    try:
        url = f"https://{PIPEDRIVE_DOMAIN}.pipedrive.com/api/v1/deals/{deal_id}?api_token={PIPEDRIVE_API_TOKEN}"
        payload = {
            PIPEDRIVE_FIELDS['purchase_price']: round(data['purchase_price']),
            PIPEDRIVE_FIELDS['wholesale_price']: round(data['wholesale_price']),
            PIPEDRIVE_FIELDS['seller_finance']: round(data.get('seller_finance', 0)),
            PIPEDRIVE_FIELDS['calculator_link']: f"https://pa-offer-calculator.streamlit.app/?deal_id={deal_id}"
        }
        response = requests.put(url, json=payload)
        return response.status_code == 200
    except Exception as e:
        st.error(f"Pipedrive update failed: {e}")
        return False

# ============= MAIN APP =============
def main():
    # Initialize
    init_db()
    config = load_google_sheets_config()
    
    # Get URL parameters for automation FIRST
    query_params = st.query_params
    deal_id = query_params.get('deal_id', '')
    url_fmv = query_params.get('fmv', None)
    url_acreage = query_params.get('acreage', None)
    
    # Convert and validate URL parameters
    try:
        url_fmv_raw = int(url_fmv) if url_fmv and url_fmv != '' else None
        # Apply 94% adjustment to FMV from Pipedrive (you can change this to 0.90 or 0.95)
        url_fmv = int(url_fmv_raw * 0.94) if url_fmv_raw else None
    except (ValueError, TypeError):
        url_fmv = None
    
    try:
        url_acreage = float(url_acreage) if url_acreage and url_acreage != '' else None
    except (ValueError, TypeError):
        url_acreage = None
    
    # Function to update URL with all parameters
    def update_url_params(**kwargs):
        """Update URL parameters with current values"""
        for key, value in kwargs.items():
            if value is not None and value != '' and value != 0:
                st.query_params[key] = str(value)
            elif key in st.query_params:
                del st.query_params[key]
    
    # Initialize session state with URL parameters
    if 'adjustments' not in st.session_state:
        # Try to load adjustments from URL
        url_adjustments = query_params.get('adjustments', None)
        if url_adjustments:
            try:
                st.session_state.adjustments = json.loads(url_adjustments)
            except:
                st.session_state.adjustments = []
        else:
            st.session_state.adjustments = []
    
    if 'subdiv_data' not in st.session_state:
        st.session_state.subdiv_data = {}
        # Load subdivision data from URL if available
        admin_value = query_params.get('admin_value', None)
        minor_value = query_params.get('minor_value', None)
        if admin_value:
            try:
                st.session_state.subdiv_data['admin_value'] = float(admin_value)
            except:
                pass
        if minor_value:
            try:
                st.session_state.subdiv_data['minor_value'] = float(minor_value)
            except:
                pass
    
    if 'comp_values' not in st.session_state:
        st.session_state.comp_values = {'sold': 0, 'active': 0}
        # Load comp values from URL if available
        comp_sold = query_params.get('comp_sold', None)
        comp_active = query_params.get('comp_active', None)
        if comp_sold:
            try:
                st.session_state.comp_values['sold'] = float(comp_sold)
            except:
                pass
        if comp_active:
            try:
                st.session_state.comp_values['active'] = float(comp_active)
            except:
                pass
    
    # Load other URL parameters into session state
    if 'sf_percentage' not in st.session_state:
        sf_perc = query_params.get('sf_percentage', None)
        if sf_perc:
            try:
                st.session_state.sf_percentage = int(sf_perc)
            except:
                st.session_state.sf_percentage = 85
        else:
            st.session_state.sf_percentage = 85
    
    # Sidebar
    with st.sidebar:
        st.markdown("### 📊 System Status")
        if st.session_state.get('sheets_connected', False):
            st.success("✓ Configuration Loaded")
        if DATABASE_URL:
            st.success("✓ Database connected")
        else:
            st.info("ℹ Database not configured")
        st.markdown("---")
    
    # Header
    col1, col2, col3 = st.columns([3, 2, 1])
    with col1:
        st.title("🏞️ Land Offer Calculator")
    with col2:
        deal_id_input = st.text_input("Deal ID", value=deal_id, key="deal_id_input", placeholder="Enter Deal ID")
        if deal_id_input != deal_id:
            st.query_params['deal_id'] = deal_id_input
            deal_id = deal_id_input
    with col3:
        if deal_id:
            existing_data = load_from_db(deal_id)
            if existing_data:
                st.success("✓ Loaded")
                st.session_state.data = existing_data
            # Show auto-save indicator
            if 'last_save' in st.session_state:
                st.caption("Auto-saving...")
    
    if 'data' not in st.session_state:
        st.session_state.data = {}
    
    # Store acreage in session state
    if 'acreage' not in st.session_state:
        st.session_state.acreage = 5.0
    
    # Main tabs
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["📊 Property & Offers", "🏘️ Comps Analysis", "📐 Subdivision", "💰 Negotiation", "🧮 Custom Profit"])
    
    with tab1:
        st.markdown('<div class="section-header">Property Details</div>', unsafe_allow_html=True)
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            # Handle FMV input with proper null/empty handling
            if url_fmv and url_fmv > 0:
                default_fmv = url_fmv
            elif 'fmv' in st.session_state.data and st.session_state.data.get('fmv'):
                default_fmv = int(st.session_state.data.get('fmv'))
            else:
                default_fmv = None  # Keep as None if no value from Pipedrive
            
            # Show FMV input - will be empty if default_fmv is None
            if default_fmv is not None:
                fmv_input = st.number_input(
                    "Fair Market Value ($)",
                    min_value=0,
                    value=default_fmv,
                    step=1000,
                    format="%d"
                )
            else:
                # Show empty input field
                fmv_input = st.number_input(
                    "Fair Market Value ($)",
                    min_value=0,
                    step=1000,
                    format="%d",
                    value=None,
                    placeholder="Enter FMV"
                )
                # If user hasn't entered a value, use 0 for calculations
                if fmv_input is None:
                    fmv_input = 0
            
            # Handle Acreage input with proper null/empty handling
            if url_acreage and url_acreage > 0:
                default_acreage = url_acreage
            elif 'acreage' in st.session_state.data and st.session_state.data.get('acreage'):
                default_acreage = float(st.session_state.data.get('acreage'))
            else:
                default_acreage = None  # Keep as None if no value from Pipedrive
            
            # Show Acreage input - will be empty if default_acreage is None
            if default_acreage is not None:
                acreage = st.number_input(
                    "Acreage",
                    min_value=0.0,
                    value=default_acreage,
                    step=0.1,
                    format="%.2f"
                )
            else:
                # Show empty input field
                acreage = st.number_input(
                    "Acreage",
                    min_value=0.0,
                    step=0.1,
                    format="%.2f",
                    value=None,
                    placeholder="Enter acreage"
                )
                # If user hasn't entered a value, use 0 for calculations
                if acreage is None:
                    acreage = 0.0
            
            st.session_state.acreage = acreage
            
            # Auto-save when FMV or acreage changes
            if deal_id and (fmv_input > 0 or acreage > 0):
                # Use a simple check to prevent too frequent saves
                if 'last_fmv' not in st.session_state or st.session_state.last_fmv != fmv_input:
                    st.session_state.last_fmv = fmv_input
                    auto_save_all_data(deal_id, fmv_input, acreage, st.session_state.adjustments, 
                                     can_subdivide, st.session_state, config)
                elif 'last_acreage' not in st.session_state or st.session_state.last_acreage != acreage:
                    st.session_state.last_acreage = acreage
                    auto_save_all_data(deal_id, fmv_input, acreage, st.session_state.adjustments, 
                                     can_subdivide, st.session_state, config)
        
        with col2:
            st.subheader("Adjustments")
            
            # Compact adjustment input
            col_desc, col_amt = st.columns([2, 1])
            with col_desc:
                new_desc = st.text_input("", key="new_adj_desc", label_visibility="collapsed", placeholder="Description")
            with col_amt:
                new_amt = st.number_input("", step=500, key="new_adj_amt", label_visibility="collapsed", placeholder="Amount")
            
            if st.button("Add", key="add_adj_btn", use_container_width=True):
                if new_desc and new_amt != 0:
                    st.session_state.adjustments.append({'description': new_desc, 'amount': new_amt})
                    # Auto-save when adding adjustment
                    if deal_id:
                        auto_save_all_data(deal_id, fmv_input, acreage, st.session_state.adjustments, 
                                         can_subdivide, st.session_state, config)
                    st.rerun()
            
            # Display adjustments with smaller font
            total_adjustments = 0
            if st.session_state.adjustments:
                for i, adj in enumerate(st.session_state.adjustments):
                    col_d, col_a, col_x = st.columns([3, 2, 1])
                    with col_d:
                        st.markdown(f"<small style='font-size: 11px;'>{adj['description']}</small>", unsafe_allow_html=True)
                    with col_a:
                        st.markdown(f"<small style='font-size: 11px;'>${adj['amount']:,}</small>", unsafe_allow_html=True)
                    with col_x:
                        if st.button("×", key=f"del_{i}", help="Remove"):
                            st.session_state.adjustments.pop(i)
                            st.rerun()
                    total_adjustments += adj['amount']
                
                st.markdown(f"<div style='font-size: 13px; font-weight: bold;'>Total: ${total_adjustments:,}</div>", unsafe_allow_html=True)
            else:
                st.caption("No adjustments")
                total_adjustments = 0
        
        with col3:
            st.subheader("Subdivision")
            
            # Check URL parameter for can_subdivide
            url_can_subdivide = query_params.get('can_subdivide', None)
            if url_can_subdivide == '1':
                default_can_subdivide = True
            elif 'can_subdivide' in st.session_state.data:
                default_can_subdivide = st.session_state.data.get('can_subdivide', False)
            else:
                default_can_subdivide = False
            
            can_subdivide = st.checkbox(
                "Can Subdivide",
                value=default_can_subdivide
            )
            
            if can_subdivide and st.session_state.subdiv_data:
                if 'admin_value' in st.session_state.subdiv_data:
                    st.caption(f"Admin: ${st.session_state.subdiv_data['admin_value']:,.0f}")
                if 'minor_value' in st.session_state.subdiv_data:
                    st.caption(f"Minor: ${st.session_state.subdiv_data['minor_value']:,.0f}")
        
        # Calculate adjusted FMV
        adjusted_fmv = fmv_input + total_adjustments
        
        # Always recalculate offers based on current values
        offers = calculate_offers(adjusted_fmv, config)
        purchase_return = offers['purchase_return']
        wholesale_return = offers['wholesale_return']
        
        # Show comp-based values if available
        if st.session_state.comp_values['sold'] > 0 or st.session_state.comp_values['active'] > 0:
            st.markdown('<div class="section-header">Subject Property Values</div>', unsafe_allow_html=True)
            col1, col2 = st.columns(2)
            with col1:
                if st.session_state.comp_values['sold'] > 0:
                    st.metric("Based on Most Similar Sold Comp", f"${st.session_state.comp_values['sold']:,.0f}")
            with col2:
                if st.session_state.comp_values['active'] > 0:
                    st.metric("Based on Most Similar Active Comp", f"${st.session_state.comp_values['active']:,.0f}")
        
        st.markdown('<div class="section-header">Calculated Offers</div>', unsafe_allow_html=True)
        
        # Manual target profit input
        col1, col2 = st.columns([1, 3])
        with col1:
            manual_target = st.number_input("Custom Target Profit ($)", min_value=0, step=1000, key="manual_target", value=0)
        with col2:
            if manual_target > 0:
                custom_offers = calculate_offers(adjusted_fmv, config, manual_target)
                col_a, col_b = st.columns(2)
                with col_a:
                    st.metric("Custom Purchase", f"${custom_offers['purchase']:,.0f}")
                with col_b:
                    st.metric("Custom Wholesale", f"${custom_offers['wholesale']:,.0f}")
        
        # Show seller finance controls
        show_seller_finance = (can_subdivide or fmv_input >= 400000)
        
        # Recalculate SF price if needed
        sf_price = 0
        if show_seller_finance:
            sf_percentage = st.session_state.get('sf_percentage', 85)
            sf_price = calculate_seller_finance(adjusted_fmv, config, sf_percentage/100)
        
        # Display offers - USING THE CURRENT CALCULATED VALUES
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.markdown(f"""
                <div class="offer-card purchase-offer">
                    <div style="font-size: 16px;">Purchase Price</div>
                    <div class="big-number">${offers['purchase']:,.0f}</div>
                    <div style="font-size: 14px; color: #10b981;">Projected Profit: ${purchase_return:,.0f}</div>
                </div>
            """, unsafe_allow_html=True)
        
        with col2:
            st.markdown(f"""
                <div class="offer-card wholesale-offer">
                    <div style="font-size: 16px;">Wholesale Price</div>
                    <div class="big-number">${offers['wholesale']:,.0f}</div>
                    <div style="font-size: 14px; color: #10b981;">Projected Profit: ${wholesale_return:,.0f}</div>
                </div>
            """, unsafe_allow_html=True)
        
        with col3:
            if show_seller_finance:
                st.markdown(f"""
                    <div class="offer-card finance-offer">
                        <div style="font-size: 16px;">Seller Finance</div>
                        <div class="big-number">${sf_price:,.0f}</div>
                        <div style="font-size: 14px;">{sf_percentage}% of FMV</div>
                    </div>
                """, unsafe_allow_html=True)
                
                # Slider with reduced spacing
                new_sf = st.slider("", min_value=80, max_value=95, value=sf_percentage, step=5, 
                                   key="sf_slider", label_visibility="collapsed")
                if new_sf != sf_percentage:
                    st.session_state.sf_percentage = new_sf
                    st.rerun()
            else:
                st.info("💡 SF: $400k+ or subdividable")
        
        with col4:
            if can_subdivide and st.session_state.subdiv_data:
                # Get highest value and both purchase prices
                admin_val = st.session_state.subdiv_data.get('admin_value', 0)
                minor_val = st.session_state.subdiv_data.get('minor_value', 0)
                
                if admin_val > 0 or minor_val > 0:
                    # Calculate purchase prices for both
                    admin_purchase = calculate_subdivision_purchase(admin_val, config) if admin_val > 0 else 0
                    minor_purchase = calculate_subdivision_purchase(minor_val, config) if minor_val > 0 else 0
                    
                    # Use highest value for main display
                    highest_val = max(admin_val, minor_val)
                    highest_purchase = admin_purchase if admin_val >= minor_val else minor_purchase
                    highest_profit = calculate_subdivision_profit(highest_val, highest_purchase)
                    
                    st.markdown(f"""
                        <div class="offer-card subdiv-card">
                            <div style="font-size: 16px;">Subdivision</div>
                            <div class="small-number">Admin: ${admin_val:,.0f} | Purch: ${admin_purchase:,.0f}</div>
                            <div class="small-number">Minor: ${minor_val:,.0f} | Purch: ${minor_purchase:,.0f}</div>
                            <div class="small-number" style="font-weight: bold;">Best Profit: ${highest_profit:,.0f}</div>
                        </div>
                    """, unsafe_allow_html=True)
            else:
                st.info("💡 Check subdivision tab")
        
        # Summary section
        st.markdown('<div class="section-header">Summary</div>', unsafe_allow_html=True)
        
        summary_col1, summary_col2 = st.columns(2)
        
        with summary_col1:
            st.markdown(f"""
                **Property Analysis:**
                - Fair Market Value: ${fmv_input:,.0f}
                - Adjustments: ${total_adjustments:,.0f}
                - Adjusted FMV: ${adjusted_fmv:,.0f}
                - Acreage: {acreage:.2f} acres
                - Price per Acre: ${(adjusted_fmv/acreage if acreage > 0 else 0):,.0f}
            """)
        
        with summary_col2:
            col_save, col_push = st.columns(2)
            
            with col_save:
                if st.button("💾 Save", use_container_width=True):
                    save_data = {
                        'fmv': fmv_input,
                        'acreage': acreage,
                        'adjustments': st.session_state.adjustments,
                        'adjusted_fmv': adjusted_fmv,
                        'purchase_price': offers['purchase'],
                        'wholesale_price': offers['wholesale'],
                        'can_subdivide': can_subdivide,
                        'manual_target': manual_target
                    }
                    
                    if show_seller_finance:
                        save_data['seller_finance'] = sf_price
                        save_data['sf_percentage'] = st.session_state.get('sf_percentage', 85)
                    
                    # Save comp values if they exist
                    if st.session_state.comp_values['sold'] > 0:
                        save_data['comp_sold_value'] = st.session_state.comp_values['sold']
                    if st.session_state.comp_values['active'] > 0:
                        save_data['comp_active_value'] = st.session_state.comp_values['active']
                    
                    # Save subdivision data if exists
                    if st.session_state.subdiv_data:
                        save_data['subdiv_data'] = st.session_state.subdiv_data
                    
                    # Update URL parameters with all values
                    update_url_params(
                        deal_id=deal_id,
                        fmv=fmv_input if fmv_input > 0 else None,
                        acreage=acreage if acreage > 0 else None,
                        can_subdivide=1 if can_subdivide else None,
                        manual_target=manual_target if manual_target > 0 else None,
                        sf_percentage=st.session_state.get('sf_percentage') if show_seller_finance else None,
                        comp_sold=st.session_state.comp_values['sold'] if st.session_state.comp_values['sold'] > 0 else None,
                        comp_active=st.session_state.comp_values['active'] if st.session_state.comp_values['active'] > 0 else None,
                        admin_value=st.session_state.subdiv_data.get('admin_value') if 'admin_value' in st.session_state.subdiv_data else None,
                        minor_value=st.session_state.subdiv_data.get('minor_value') if 'minor_value' in st.session_state.subdiv_data else None,
                        adjustments=json.dumps(st.session_state.adjustments) if st.session_state.adjustments else None
                    )
                    
                    if deal_id and save_to_db(deal_id, save_data):
                        st.success("✓ Saved!")
                        st.session_state.data = save_data
                    else:
                        st.warning("Enter Deal ID")
            
            with col_push:
                if st.button("📤 Push to Pipedrive", use_container_width=True):
                    if deal_id:
                        # First ensure we have the latest calculated values
                        push_data = {
                            'purchase_price': offers['purchase'],
                            'wholesale_price': offers['wholesale'],
                            'seller_finance': sf_price if show_seller_finance else 0
                        }
                        
                        # Also save current state to database before pushing
                        save_data = {
                            'fmv': fmv_input,
                            'acreage': acreage,
                            'adjustments': st.session_state.adjustments,
                            'adjusted_fmv': adjusted_fmv,
                            'purchase_price': offers['purchase'],
                            'wholesale_price': offers['wholesale'],
                            'can_subdivide': can_subdivide,
                            'manual_target': manual_target
                        }
                        
                        if show_seller_finance:
                            save_data['seller_finance'] = sf_price
                            save_data['sf_percentage'] = st.session_state.get('sf_percentage', 85)
                        
                        # Save comp values if they exist
                        if st.session_state.comp_values['sold'] > 0:
                            save_data['comp_sold_value'] = st.session_state.comp_values['sold']
                        if st.session_state.comp_values['active'] > 0:
                            save_data['comp_active_value'] = st.session_state.comp_values['active']
                        
                        # Save subdivision data if exists
                        if st.session_state.subdiv_data:
                            save_data['subdiv_data'] = st.session_state.subdiv_data
                        
                        # Save to DB first
                        save_to_db(deal_id, save_data)
                        
                        # Then push to Pipedrive
                        if push_to_pipedrive(deal_id, push_data):
                            st.success("✓ Pushed to Pipedrive & Saved!")
                            st.session_state.data = save_data
                        else:
                            st.warning("Push failed but data saved locally")
                    else:
                        st.warning("Enter Deal ID")
    
    with tab2:
        st.markdown('<div class="section-header">Comp Analysis</div>', unsafe_allow_html=True)
        
        acreage = st.session_state.acreage
        
        # Initialize temp storage for current values
        if 'temp_sold' not in st.session_state:
            st.session_state.temp_sold = {'price': 0, 'acres': 0.0}
        if 'temp_active' not in st.session_state:
            st.session_state.temp_active = {'price': 0, 'acres': 0.0}
        
        # Sold Comp
        st.subheader("🔍 Most Relevant Sold Comp")
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            sold_comp_link = st.text_input("Link", key="sold_link", placeholder="Zillow/Redfin")
        with col2:
            sold_comp_price = st.number_input("Sale Price ($)", min_value=0, step=1000, key="sold_price",
                                            value=st.session_state.temp_sold['price'])
            st.session_state.temp_sold['price'] = sold_comp_price
        with col3:
            sold_comp_acres = st.number_input("Acreage", min_value=0.0, step=0.1, key="sold_acres",
                                            value=st.session_state.temp_sold['acres'])
            st.session_state.temp_sold['acres'] = sold_comp_acres
        with col4:
            if sold_comp_acres > 0 and sold_comp_price > 0:
                sold_ppa = sold_comp_price / sold_comp_acres
                st.metric("PPA", f"${sold_ppa:,.0f}")
                
                if acreage > 0:
                    subject_value_sold = sold_ppa * acreage
                    st.metric("Subject Value", f"${subject_value_sold:,.0f}")
                    st.session_state.comp_values['sold'] = subject_value_sold
            
            if st.button("Update Main", key="update_sold"):
                st.rerun()
        
        # Active Comp
        st.subheader("🔍 Most Accurate Active Comp")
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            active_comp_link = st.text_input("Link", key="active_link", placeholder="Zillow/Redfin")
        with col2:
            active_comp_price = st.number_input("Listing ($)", min_value=0, step=1000, key="active_price",
                                              value=st.session_state.temp_active['price'])
            st.session_state.temp_active['price'] = active_comp_price
        with col3:
            active_comp_acres = st.number_input("Acreage", min_value=0.0, step=0.1, key="active_acres",
                                              value=st.session_state.temp_active['acres'])
            st.session_state.temp_active['acres'] = active_comp_acres
        with col4:
            if active_comp_acres > 0 and active_comp_price > 0:
                active_ppa = active_comp_price / active_comp_acres
                st.metric("PPA", f"${active_ppa:,.0f}")
                
                if acreage > 0:
                    subject_value_active = active_ppa * acreage
                    st.metric("Subject Value", f"${subject_value_active:,.0f}")
                    st.session_state.comp_values['active'] = subject_value_active
            
            if st.button("Update Main", key="update_active"):
                st.rerun()
    
    with tab3:
        st.markdown('<div class="section-header">Subdivision Analysis</div>', unsafe_allow_html=True)
        
        acreage = st.session_state.acreage
        
        # Road Frontage (no PPA field)
        st.subheader("🛣️ Road Frontage Subdivision")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            road_frontage = st.number_input("Road Frontage (ft)", min_value=0, value=0, step=10, key="road_front")
        with col2:
            frontage_required = st.number_input("Required/Lot (ft)", min_value=0, value=100, step=10, key="front_req")
        with col3:
            if frontage_required > 0 and road_frontage > 0:
                road_lots = int(road_frontage / frontage_required)
                st.metric("Lots", road_lots)
                if road_lots > 0 and acreage > 0:
                    road_lot_size = acreage / road_lots
                    st.metric("Acres/Lot", f"{road_lot_size:.2f}")
        
        # Admin Split
        st.subheader("📋 Administrative Split")
        
        col1, col2 = st.columns(2)
        with col1:
            st.write("**Admin - Sold Comp**")
            admin_sold_link = st.text_input("Link", key="admin_sold_link", placeholder="Link")
            admin_sold_price = st.number_input("Price ($)", min_value=0, step=1000, key="admin_sold_price")
            admin_sold_acres = st.number_input("Acres", min_value=0.0, step=0.1, key="admin_sold_acres")
            if admin_sold_acres > 0:
                admin_sold_ppa = admin_sold_price / admin_sold_acres
                st.metric("PPA", f"${admin_sold_ppa:,.0f}")
            else:
                admin_sold_ppa = 0
        
        with col2:
            st.write("**Admin - Active Comp**")
            admin_active_link = st.text_input("Link", key="admin_active_link", placeholder="Link")
            admin_active_price = st.number_input("Price ($)", min_value=0, step=1000, key="admin_active_price")
            admin_active_acres = st.number_input("Acres", min_value=0.0, step=0.1, key="admin_active_acres")
            if admin_active_acres > 0:
                admin_active_ppa = admin_active_price / admin_active_acres
                st.metric("PPA", f"${admin_active_ppa:,.0f}")
            else:
                admin_active_ppa = 0
        
        # Admin calculation
        col1, col2, col3 = st.columns(3)
        with col1:
            admin_lots = st.number_input("Admin Lots", min_value=0, value=0, step=1, key="admin_lots_num")
        with col2:
            if admin_lots > 0 and acreage > 0:
                admin_lot_size = acreage / admin_lots
                st.markdown(f"<div style='font-size: 14px;'>Acres/Lot: {admin_lot_size:.2f}</div>", unsafe_allow_html=True)
            else:
                admin_lot_size = 0
        with col3:
            admin_use_ppa = st.number_input("Use PPA ($)", 
                                           value=int(admin_sold_ppa),
                                           min_value=0, step=100, key="admin_use_ppa")
            
            # Always show the calculated value
            if admin_lots > 0 and admin_lot_size > 0 and admin_use_ppa > 0:
                admin_total_value = admin_use_ppa * admin_lot_size * admin_lots
                admin_purchase = calculate_subdivision_purchase(admin_total_value, config)
                admin_profit = calculate_subdivision_profit(admin_total_value, admin_purchase)
                
                # Visual display of calculations
                st.markdown(f"<div style='background: #f0f9ff; padding: 10px; border-radius: 8px; margin: 10px 0;'>", unsafe_allow_html=True)
                st.markdown(f"<div style='font-size: 16px; font-weight: bold; color: #0369a1;'>Admin Total: ${admin_total_value:,.0f}</div>", unsafe_allow_html=True)
                st.markdown(f"<div style='font-size: 14px; color: #0c4a6e;'>Purchase: ${admin_purchase:,.0f}</div>", unsafe_allow_html=True)
                st.markdown(f"<div style='font-size: 14px; color: #0c4a6e;'>Expected Profit: ${admin_profit:,.0f}</div>", unsafe_allow_html=True)
                st.markdown(f"</div>", unsafe_allow_html=True)
                
                if st.button("✓ Set Admin Value", key="set_admin", use_container_width=True, type="primary"):
                    st.session_state.subdiv_data['admin_value'] = admin_total_value
                    # Auto-save when setting admin value
                    if deal_id:
                        auto_save_subdivision_data(deal_id, st.session_state)
                    st.success("Admin value set!")
            else:
                st.info("Enter lots and PPA to see calculations")
        
        # Minor Split
        st.subheader("📋 Minor Split")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            minor_lots = st.number_input("Minor Lots", min_value=0, value=0, step=1, key="minor_lots_num")
        with col2:
            if minor_lots > 0 and acreage > 0:
                minor_lot_size = acreage / minor_lots
                st.markdown(f"<div style='font-size: 14px;'>Acres/Lot: {minor_lot_size:.2f}</div>", unsafe_allow_html=True)
            else:
                minor_lot_size = 0
        with col3:
            minor_ppa = st.number_input("PPA ($)", min_value=0, step=100, key="minor_ppa")
            
            # Always show the calculated value
            if minor_lots > 0 and minor_lot_size > 0 and minor_ppa > 0:
                minor_total_value = minor_ppa * minor_lot_size * minor_lots
                minor_purchase = calculate_subdivision_purchase(minor_total_value, config)
                minor_profit = calculate_subdivision_profit(minor_total_value, minor_purchase)
                
                # Visual display of calculations
                st.markdown(f"<div style='background: #fef3c7; padding: 10px; border-radius: 8px; margin: 10px 0;'>", unsafe_allow_html=True)
                st.markdown(f"<div style='font-size: 16px; font-weight: bold; color: #92400e;'>Minor Total: ${minor_total_value:,.0f}</div>", unsafe_allow_html=True)
                st.markdown(f"<div style='font-size: 14px; color: #78350f;'>Purchase: ${minor_purchase:,.0f}</div>", unsafe_allow_html=True)
                st.markdown(f"<div style='font-size: 14px; color: #78350f;'>Expected Profit: ${minor_profit:,.0f}</div>", unsafe_allow_html=True)
                st.markdown(f"</div>", unsafe_allow_html=True)
                
                if st.button("✓ Set Minor Value", key="set_minor", use_container_width=True, type="primary"):
                    st.session_state.subdiv_data['minor_value'] = minor_total_value
                    # Auto-save when setting minor value
                    if deal_id:
                        auto_save_subdivision_data(deal_id, st.session_state)
                    st.success("Minor value set!")
            else:
                st.info("Enter lots and PPA to see calculations")
        
        # Show both values summary
        if 'admin_value' in st.session_state.subdiv_data or 'minor_value' in st.session_state.subdiv_data:
            st.markdown('<div class="section-header">Subdivision Summary</div>', unsafe_allow_html=True)
            col1, col2, col3 = st.columns(3)
            with col1:
                if 'admin_value' in st.session_state.subdiv_data:
                    admin_v = st.session_state.subdiv_data['admin_value']
                    admin_p = calculate_subdivision_purchase(admin_v, config)
                    st.metric("Admin Split", f"${admin_v:,.0f}")
                    st.caption(f"Purchase: ${admin_p:,.0f}")
            with col2:
                if 'minor_value' in st.session_state.subdiv_data:
                    minor_v = st.session_state.subdiv_data['minor_value']
                    minor_p = calculate_subdivision_purchase(minor_v, config)
                    st.metric("Minor Split", f"${minor_v:,.0f}")
                    st.caption(f"Purchase: ${minor_p:,.0f}")
            with col3:
                if st.button("Clear All Subdivision Values"):
                    st.session_state.subdiv_data = {}
                    st.rerun()
    
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
            
            st.caption(f"Margin = NSP Purchase - (Purchase × 1.0525)")
            st.caption(f"NSP Purchase = ${offers.get('nsp_purchase', adjusted_fmv * 0.94 - 3500):,.0f}")
        
        with col2:
            st.write("**Test Wholesale Price**")
            test_wholesale = st.number_input(
                "What if we wholesaled at ($):",
                min_value=0,
                value=int(offers['wholesale']),
                step=1000,
                key="test_wholesale"
            )
            
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
            
            st.caption(f"Margin = NSP Wholesale - Wholesale Price")
            st.caption(f"NSP Wholesale = ${offers.get('nsp_wholesale', adjusted_fmv * 0.94 - 2500):,.0f}")
    
    with tab5:
        st.markdown('<div class="section-header">Custom Profit Calculator</div>', unsafe_allow_html=True)
        
        st.subheader("💡 Calculate Custom Deal Profit")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.write("**Deal Inputs**")
            custom_sale_value = st.number_input(
                "Expected Total Sale Value ($)",
                min_value=0,
                step=1000,
                key="custom_sale_value",
                help="Total expected sale price"
            )
            
            custom_purchase = st.number_input(
                "Purchase Price ($)",
                min_value=0,
                step=1000,
                key="custom_purchase",
                help="What you're paying for the property"
            )
            
            custom_closing = st.number_input(
                "Expected Closing Costs ($)",
                min_value=0,
                value=2500,
                step=100,
                key="custom_closing"
            )
        
        with col2:
            st.write("**Percentage Costs**")
            broker_percent = st.slider(
                "Broker Costs (%)",
                min_value=0.0,
                max_value=10.0,
                value=6.0,
                step=0.5,
                key="broker_percent",
                help="Percentage of sale price for broker"
            )
            
            funding_percent = st.slider(
                "Funding/Lender Costs (%)",
                min_value=0.0,
                max_value=20.0,
                value=5.0,
                step=0.5,
                key="funding_percent",
                help="Percentage added to purchase price for funding"
            )
        
        # Calculate custom profit
        if custom_sale_value > 0 and custom_purchase > 0:
            st.markdown('<div class="section-header">Profit Calculation</div>', unsafe_allow_html=True)
            
            # Calculate components
            broker_costs = custom_sale_value * (broker_percent / 100)
            funding_costs = custom_purchase * (funding_percent / 100)
            total_purchase_with_funding = custom_purchase * (1 + funding_percent / 100)
            
            # Net sale proceeds = Sale Value - Broker Costs - Closing Costs
            net_proceeds = custom_sale_value - broker_costs - custom_closing
            
            # Total costs = Purchase with funding
            total_costs = total_purchase_with_funding
            
            # Profit = Net proceeds - Total costs
            custom_profit = net_proceeds - total_costs
            
            # Display breakdown
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.markdown("**Revenue Side**")
                st.metric("Sale Value", f"${custom_sale_value:,.0f}")
                st.caption(f"- Broker ({broker_percent}%): ${broker_costs:,.0f}")
                st.caption(f"- Closing: ${custom_closing:,.0f}")
                st.metric("Net Proceeds", f"${net_proceeds:,.0f}")
            
            with col2:
                st.markdown("**Cost Side**")
                st.metric("Purchase Price", f"${custom_purchase:,.0f}")
                st.caption(f"+ Funding ({funding_percent}%): ${funding_costs:,.0f}")
                st.metric("Total Cost", f"${total_costs:,.0f}")
            
            with col3:
                st.markdown("**Profit Analysis**")
                if custom_profit > 0:
                    st.markdown(f"""
                        <div style="background: linear-gradient(135deg, #10b981 0%, #059669 100%); 
                                color: white; padding: 20px; border-radius: 10px; text-align: center;">
                            <div style="font-size: 14px;">Net Profit</div>
                            <div style="font-size: 32px; font-weight: bold;">${custom_profit:,.0f}</div>
                            <div style="font-size: 14px;">ROI: {(custom_profit/custom_purchase*100):.1f}%</div>
                        </div>
                    """, unsafe_allow_html=True)
                else:
                    st.markdown(f"""
                        <div style="background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%); 
                                color: white; padding: 20px; border-radius: 10px; text-align: center;">
                            <div style="font-size: 14px;">Net Loss</div>
                            <div style="font-size: 32px; font-weight: bold;">-${abs(custom_profit):,.0f}</div>
                        </div>
                    """, unsafe_allow_html=True)
            
            # Show formula
            st.markdown("---")
            st.caption("**Formula Used:**")
            st.caption(f"Net Proceeds = Sale Value × (1 - Broker %) - Closing Costs")
            st.caption(f"Total Cost = Purchase Price × (1 + Funding %)")
            st.caption(f"Profit = Net Proceeds - Total Cost")

if __name__ == "__main__":
    main()
