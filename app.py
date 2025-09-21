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

# Prevent form submission on Enter key
st.markdown("""
<script>
document.addEventListener('DOMContentLoaded', function() {
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        form.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                return false;
            }
        });
    });
});
</script>
""", unsafe_allow_html=True)

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
    form {
        border: none !important;
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
def calculate_offers(fmv, config):
    """Calculate the offer prices based on NSP formulas"""
    purchase_return = get_expected_return(fmv, config, 'purchase')
    wholesale_return = get_expected_return(fmv, config, 'wholesale')
    
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

# ============= PIPEDRIVE FUNCTIONS =============
def push_to_pipedrive(deal_id, data):
    """Push calculated values to Pipedrive"""
    if not PIPEDRIVE_API_TOKEN or not PIPEDRIVE_DOMAIN:
        st.warning("Pipedrive credentials not configured")
        return False
    
    try:
        url = f"https://{PIPEDRIVE_DOMAIN}.pipedrive.com/api/v1/deals/{deal_id}?api_token={PIPEDRIVE_API_TOKEN}"
        payload = {
            PIPEDRIVE_FIELDS['purchase_price']: data['purchase_price'],
            PIPEDRIVE_FIELDS['wholesale_price']: data['wholesale_price'],
            PIPEDRIVE_FIELDS['seller_finance']: data.get('seller_finance', 0),
            PIPEDRIVE_FIELDS['calculator_link']: st._get_session_id() + f"?deal_id={deal_id}"
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
    
    # Initialize session state for adjustments
    if 'adjustments' not in st.session_state:
        st.session_state.adjustments = []
    if 'subdiv_data' not in st.session_state:
        st.session_state.subdiv_data = {}
    
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
    
    # Get deal_id from URL
    query_params = st.query_params
    deal_id = query_params.get('deal_id', '')
    
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
    
    if 'data' not in st.session_state:
        st.session_state.data = {}
    
    # Store acreage in session state for cross-tab access
    if 'acreage' not in st.session_state:
        st.session_state.acreage = 5.0
    
    # Main tabs
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
                help="Enter the estimated fair market value"
            )
            
            acreage = st.number_input(
                "Acreage",
                min_value=0.0,
                value=float(st.session_state.data.get('acreage', 5.0)),
                step=0.1,
                format="%.2f",
                help="Total acres of the property"
            )
            st.session_state.acreage = acreage
        
        with col2:
            st.subheader("Property Adjustments")
            
            # Add new adjustment
            with st.expander("Add Adjustment"):
                adj_desc = st.text_input("Description", key="adj_desc")
                adj_amount = st.number_input("Amount ($)", step=500, key="adj_amount")
                if st.button("Add", key="add_adj"):
                    if adj_desc and adj_amount != 0:
                        st.session_state.adjustments.append({
                            'description': adj_desc,
                            'amount': adj_amount
                        })
            
            # Show existing adjustments
            if st.session_state.adjustments:
                st.write("**Current Adjustments:**")
                total_adjustments = 0
                for i, adj in enumerate(st.session_state.adjustments):
                    col_desc, col_amt, col_del = st.columns([3, 2, 1])
                    with col_desc:
                        st.caption(adj['description'])
                    with col_amt:
                        st.caption(f"${adj['amount']:,}")
                    with col_del:
                        if st.button("❌", key=f"del_{i}"):
                            st.session_state.adjustments.pop(i)
                            st.rerun()
                    total_adjustments += adj['amount']
                
                st.metric("Total Adjustments", f"${total_adjustments:,}")
            else:
                total_adjustments = 0
                st.info("No adjustments added")
        
        with col3:
            st.subheader("Subdivision Potential")
            
            can_subdivide = st.checkbox(
                "Can Subdivide",
                value=st.session_state.data.get('can_subdivide', False),
                help="Check if property can be subdivided"
            )
            
            if can_subdivide and 'subdiv_value' in st.session_state.subdiv_data:
                st.metric("Expected Subdiv Value", 
                         f"${st.session_state.subdiv_data.get('subdiv_value', 0):,.0f}")
        
        # Calculate adjusted FMV
        adjusted_fmv = fmv_input + total_adjustments
        
        # Calculate offers
        offers = calculate_offers(adjusted_fmv, config)
        purchase_return = offers['purchase_return']
        wholesale_return = offers['wholesale_return']
        
        # Get comp values from session state
        sold_comp_value = st.session_state.get('sold_comp_value', 0)
        active_comp_value = st.session_state.get('active_comp_value', 0)
        
        # Show comp-based values if available
        if sold_comp_value > 0 or active_comp_value > 0:
            st.markdown('<div class="section-header">Subject Property Values (from Comps)</div>', unsafe_allow_html=True)
            col1, col2 = st.columns(2)
            with col1:
                if sold_comp_value > 0:
                    st.metric("Based on Sold Comp", f"${sold_comp_value:,.0f}")
            with col2:
                if active_comp_value > 0:
                    st.metric("Based on Active Comp", f"${active_comp_value:,.0f}")
        
        st.markdown('<div class="section-header">Calculated Offers</div>', unsafe_allow_html=True)
        
        # Display offers
        if can_subdivide and 'subdiv_value' in st.session_state.subdiv_data:
            # Show 4 columns when subdivision is available
            col1, col2, col3, col4 = st.columns(4)
        else:
            # Show 3 columns normally
            col1, col2, col3 = st.columns(3)
            col4 = None
        
        with col1:
            st.markdown(f"""
                <div class="offer-card purchase-offer">
                    <div style="font-size: 18px;">Purchase Price</div>
                    <div class="big-number">${offers['purchase']:,.0f}</div>
                    <div style="font-size: 14px;">Direct Purchase</div>
                </div>
            """, unsafe_allow_html=True)
            st.markdown(f'<div class="profit-positive">Target Return: ${purchase_return:,.0f}</div>', unsafe_allow_html=True)
        
        with col2:
            st.markdown(f"""
                <div class="offer-card wholesale-offer">
                    <div style="font-size: 18px;">Wholesale Price</div>
                    <div class="big-number">${offers['wholesale']:,.0f}</div>
                    <div style="font-size: 14px;">With Margin</div>
                </div>
            """, unsafe_allow_html=True)
            st.markdown(f'<div class="profit-positive">Target Return: ${wholesale_return:,.0f}</div>', unsafe_allow_html=True)
        
        with col3:
            # Always show seller finance if conditions met
            show_seller_finance = (can_subdivide or fmv_input >= 400000)
            if show_seller_finance:
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
                st.info("💡 Seller Finance: $400k+ properties")
        
        # Show subdivision card if applicable
        if col4 and can_subdivide and 'subdiv_value' in st.session_state.subdiv_data:
            with col4:
                subdiv_total = st.session_state.subdiv_data.get('subdiv_value', 0)
                subdiv_profit = calculate_subdivision_profit(subdiv_total, offers['purchase'])
                
                st.markdown(f"""
                    <div class="offer-card subdiv-card">
                        <div style="font-size: 18px;">Subdivision Value</div>
                        <div class="big-number">${subdiv_total:,.0f}</div>
                        <div style="font-size: 14px;">Expected Profit: ${subdiv_profit:,.0f}</div>
                    </div>
                """, unsafe_allow_html=True)
                st.caption("After purchase & subdivision costs")
        
        # Summary section
        st.markdown('<div class="section-header">Summary</div>', unsafe_allow_html=True)
        
        summary_col1, summary_col2 = st.columns(2)
        
        with summary_col1:
            st.markdown(f"""
                **Property Analysis:**
                - Fair Market Value: ${fmv_input:,.0f}
                - Adjustments: ${total_adjustments:,.0f}
                - Adjusted FMV: ${adjusted_fmv:,.0f}
                - Purchase Return: ${purchase_return:,.0f}
                - Wholesale Return: ${wholesale_return:,.0f}
                - Acreage: {acreage:.2f} acres
                - Price per Acre: ${(adjusted_fmv/acreage if acreage > 0 else 0):,.0f}
            """)
        
        with summary_col2:
            col_save, col_push = st.columns(2)
            
            with col_save:
                if st.button("💾 Save Calculations", use_container_width=True):
                    save_data = {
                        'fmv': fmv_input,
                        'acreage': acreage,
                        'adjustments': st.session_state.adjustments,
                        'adjusted_fmv': adjusted_fmv,
                        'purchase_return': purchase_return,
                        'wholesale_return': wholesale_return,
                        'purchase_price': offers['purchase'],
                        'wholesale_price': offers['wholesale'],
                        'can_subdivide': can_subdivide
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
        
        # Get acreage from session state
        acreage = st.session_state.acreage
        
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
                    st.metric("Subject Value (Sold)", f"${subject_value_sold:,.0f}")
                    st.session_state.sold_comp_value = subject_value_sold
        
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
                    st.session_state.active_comp_value = subject_value_active
    
    with tab3:
        st.markdown('<div class="section-header">Subdivision Analysis</div>', unsafe_allow_html=True)
        
        acreage = st.session_state.acreage
        
        # Road Frontage Subdivision
        st.subheader("🛣️ Road Frontage Subdivision")
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            road_frontage = st.number_input("Road Frontage (ft)", min_value=0, value=0, step=10)
        with col2:
            frontage_required = st.number_input("Frontage Required per Lot (ft)", min_value=0, value=100, step=10)
        with col3:
            if frontage_required > 0 and road_frontage > 0:
                road_lots = int(road_frontage / frontage_required)
                st.metric("Lots Possible", road_lots)
                
                if road_lots > 0 and acreage > 0:
                    road_lot_size = acreage / road_lots
                    st.metric("Acres per Lot", f"{road_lot_size:.2f}")
            else:
                road_lots = 0
                road_lot_size = 0
        with col4:
            road_ppa = st.number_input("Road Subdiv PPA ($)", min_value=0, step=100, key="road_ppa")
            if road_lots > 0 and road_lot_size > 0 and road_ppa > 0:
                road_total_value = road_ppa * road_lot_size * road_lots
                st.metric("Total Value", f"${road_total_value:,.0f}")
                st.session_state.subdiv_data['subdiv_value'] = road_total_value
        
        # Administrative Split
        st.subheader("📋 Administrative Split")
        
        # Admin split comps
        col1, col2 = st.columns(2)
        with col1:
            st.write("**Admin Split - Sold Comp**")
            admin_sold_link = st.text_input("Sold Link", key="admin_sold_link")
            admin_sold_price = st.number_input("Sale Price ($)", min_value=0, step=1000, key="admin_sold_price")
            admin_sold_acres = st.number_input("Acreage", min_value=0.0, step=0.1, key="admin_sold_acres")
            if admin_sold_acres > 0:
                admin_sold_ppa = admin_sold_price / admin_sold_acres
                st.metric("PPA (Sold)", f"${admin_sold_ppa:,.0f}")
        
        with col2:
            st.write("**Admin Split - Active Comp**")
            admin_active_link = st.text_input("Active Link", key="admin_active_link")
            admin_active_price = st.number_input("Listing Price ($)", min_value=0, step=1000, key="admin_active_price")
            admin_active_acres = st.number_input("Acreage", min_value=0.0, step=0.1, key="admin_active_acres")
            if admin_active_acres > 0:
                admin_active_ppa = admin_active_price / admin_active_acres
                st.metric("PPA (Active)", f"${admin_active_ppa:,.0f}")
        
        # Admin split calculation
        col1, col2, col3 = st.columns(3)
        with col1:
            admin_lots = st.number_input("Admin Lots Possible", min_value=0, value=0, step=1)
        with col2:
            if admin_lots > 0 and acreage > 0:
                admin_lot_size = acreage / admin_lots
                st.metric("Acres per Lot", f"{admin_lot_size:.2f}")
            else:
                admin_lot_size = 0
        with col3:
            admin_use_ppa = st.number_input("Use PPA for Calc ($)", 
                                           value=int((admin_sold_ppa if 'admin_sold_ppa' in locals() else 0)),
                                           min_value=0, step=100, key="admin_use_ppa")
            if admin_lots > 0 and admin_lot_size > 0 and admin_use_ppa > 0:
                admin_total_value = admin_use_ppa * admin_lot_size * admin_lots
                st.metric("Admin Split Total Value", f"${admin_total_value:,.0f}")
                if admin_total_value > st.session_state.subdiv_data.get('subdiv_value', 0):
                    st.session_state.subdiv_data['subdiv_value'] = admin_total_value
        
        # Minor Split
        st.subheader("📋 Minor Split")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            minor_lots = st.number_input("Minor Lots Possible", min_value=0, value=0, step=1)
        with col2:
            if minor_lots > 0 and acreage > 0:
                minor_lot_size = acreage / minor_lots
                st.metric("Acres per Lot", f"{minor_lot_size:.2f}")
            else:
                minor_lot_size = 0
        with col3:
            minor_ppa = st.number_input("Minor Split PPA ($)", min_value=0, step=100, key="minor_ppa")
            if minor_lots > 0 and minor_lot_size > 0 and minor_ppa > 0:
                minor_total_value = minor_ppa * minor_lot_size * minor_lots
                st.metric("Total Value", f"${minor_total_value:,.0f}")
                if minor_total_value > st.session_state.subdiv_data.get('subdiv_value', 0):
                    st.session_state.subdiv_data['subdiv_value'] = minor_total_value
    
    with tab4:
        st.markdown('<div class="section-header">Negotiation Tool</div>', unsafe_allow_html=True)
        
        st.subheader("🤝 Test Different Price Points")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.write("**Test Purchase Price**")
            with st.form(key="purchase_test_form"):
                test_purchase = st.number_input(
                    "What if we offered ($):",
                    min_value=0,
                    value=int(offers['purchase']),
                    step=1000,
                    key="test_purchase"
                )
                st.form_submit_button("Calculate", use_container_width=True)
            
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
            
            difference = test_purchase - offers['purchase']
            if abs(difference) > 1:
                if difference > 0:
                    st.warning(f"${difference:,.0f} above calculated")
                else:
                    st.info(f"${abs(difference):,.0f} below calculated")
        
        with col2:
            st.write("**Test Wholesale Price**")
            with st.form(key="wholesale_test_form"):
                test_wholesale = st.number_input(
                    "What if we wholesaled at ($):",
                    min_value=0,
                    value=int(offers['wholesale']),
                    step=1000,
                    key="test_wholesale"
                )
                st.form_submit_button("Calculate", use_container_width=True)
            
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
            
            difference_w = test_wholesale - offers['wholesale']
            if abs(difference_w) > 1:
                if difference_w > 0:
                    st.warning(f"${difference_w:,.0f} above calculated")
                else:
                    st.info(f"${abs(difference_w):,.0f} below calculated")
        
        # Quick adjustments
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
