"""Local single-user UI package for the Shorts Pipeline.

The Streamlit entry point lives in ``app.py``. All pipeline orchestration lives
in ``controller.py``, which does not import Streamlit so it can be unit-tested
without the optional ``ui`` extra installed.
"""
