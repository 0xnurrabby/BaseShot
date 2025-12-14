# Deploy to Render (Flask)

## Requirements
- A Render account
- GitHub repo containing this project

## Environment Variables (Render Dashboard)
Set:
- BASE_RPC_URL = https://mainnet.base.org
(Optional) You do NOT need PORT; Render provides it automatically.

## Deploy steps
1. Push this folder to a GitHub repository.
2. In Render: New + -> Blueprint (recommended) OR Web Service.
   - If using Blueprint: select the repo; Render will read `render.yaml`.
   - If using Web Service manually:
     - Build Command: `pip install -r requirements.txt`
     - Start Command: `gunicorn -w 1 -b 0.0.0.0:$PORT app:app`
3. Add env var `BASE_RPC_URL`.
4. Deploy.

## Notes
- `-w 1` is intentional to keep progress/cancel and latest-download state consistent (in-memory).
- For very large scans, consider increasing Render plan/timeouts, or narrowing ranges in PRO mode.
