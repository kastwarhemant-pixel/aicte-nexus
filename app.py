
"""AICTE NEXUS — Premium institutional complaint intelligence platform."""

import streamlit as st
import ui

st.set_page_config(
    page_title="AICTE NEXUS | Intelligence Command Center",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "About": """
        **AICTE NEXUS**

        Unified institutional complaint intelligence,
        cross-bureau case matching and risk monitoring.

        Prototype demonstration using synthetic data only.
        """
    },
)

ui.bootstrap()

# Sidebar brand and compact command-center identity.
with st.sidebar:
    st.markdown(
        """
        <div style="
            padding: 14px 12px 18px;
            margin: 0 0 18px;
            border-bottom: 1px solid #2c3d5c;
        ">
            <div style="
                font-size: 10px;
                letter-spacing: 2px;
                font-weight: 800;
                color: #67e8f9;
                margin-bottom: 8px;
            ">INSTITUTIONAL INTELLIGENCE</div>
            <div style="
                font-size: 25px;
                font-weight: 800;
                letter-spacing: -1px;
                color: #f8fafc;
            ">NEXUS<span style="color:#22d3ee">.</span></div>
            <div style="
                font-size: 12px;
                color: #94a3b8;
                margin-top: 4px;
            ">Unified Complaint Command Center</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.caption("WORKSPACE  /  OPERATIONS")

navigation = st.navigation(
    [
        st.Page(
            "pages/0_Overview.py",
            title="Command Center",
            icon="📊",
            default=True,
        ),
        st.Page(
            "pages/1_Institution_Directory.py",
            title="Institution Directory",
            icon="🏛️",
        ),
        st.Page(
            "pages/2_Complaint_Management.py",
            title="Complaint Management",
            icon="📁",
        ),
        st.Page(
            "pages/3_Cross_Bureau_Intelligence.py",
            title="Cross-Bureau Intelligence",
            icon="🔗",
        ),
        st.Page(
            "pages/4_Risk_Monitoring.py",
            title="Risk Monitoring",
            icon="🛡️",
        ),
        st.Page(
            "pages/5_Analytics_Reports.py",
            title="Analytics & Reports",
            icon="📈",
        ),
        st.Page(
            "pages/6_Audit_Trail.py",
            title="Audit Trail",
            icon="🧾",
        ),
        st.Page(
            "pages/7_Settings.py",
            title="Settings",
            icon="⚙️",
        ),
        st.Page(
            "pages/8_AI_Assistant.py",
            title="NEXUS AI Assistant",
            icon="🤖",
        ),
    ],
)

ui.sidebar_footer()
navigation.run()
