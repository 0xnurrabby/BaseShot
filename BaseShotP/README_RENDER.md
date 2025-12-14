# Deploy to Render (Web Service)

## 1) Put files in repo root
Your repository root must contain:
- app.py
- requirements.txt
- render.yaml
- Procfile
- static/
- templates/

If `requirements.txt` is inside a subfolder, Render will fail with: "Could not open requirements file".

## 2) Create on Render (Blueprint)
Render Dashboard → New + → Blueprint → select your GitHub repo.

## 3) Set environment variable
In Render → Service → Environment:
- BASE_RPC_URL = https://mainnet.base.org

## 4) Deploy
Click "Deploy latest commit".

Notes:
- We use 1 gunicorn worker because this app keeps in-memory state for progress/cancel and latest download.
