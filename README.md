# ZoomAtCheck

Приложение для проверки посещаемости в Zoom через скрипт нормализации и токенизацию

Simple Streamlit app to compare Zoom webinar attendance with signups.

## Run locally

1. Create and activate a Python virtual environment.

Windows (PowerShell):

```powershell
python -m venv venv; .\venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

2. Upload the two CSV files (signups and attendance) to the web UI and view the analysis.

## Files
- `app.py` - Streamlit app
- `requirements.txt` - Python packages

## Notes
- The app expects the signups file with one column of names, and the Zoom attendance file with at least name and duration columns.
- If you need help connecting to GitHub or pushing, make sure to configure your credentials or SSH key for the remote repository: https://github.com/ChKosmidis/ZoomAtCheck

---

If you prefer a single-language README or different content, update this file and commit again.
