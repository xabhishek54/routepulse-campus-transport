"""
Root entry point for Streamlit Community Cloud deployment.

Streamlit Cloud looks for streamlit_app.py at the repo root.
This file just re-executes the real app so the page structure is preserved.
"""
import os
import sys

# Add repo root to path so `routepulse` and `app` packages are found
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Execute the real main app
exec(open(os.path.join(os.path.dirname(__file__), "app", "main.py")).read())
