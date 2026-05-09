<img src="https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=2,8,15&height=180&section=header&text=BaseShot&fontSize=52&fontColor=000000&fontAlignY=38&desc=Base+chain+token+transfer+scanner+and+snapshot+tool&descAlignY=58&descSize=14&animation=fadeIn" width="100%"/>

<div align="center">

[![Live](https://img.shields.io/badge/Live%20App-bbf7d0?style=for-the-badge&logoColor=000)](https://baseshot.vercel.app)
[![License](https://img.shields.io/badge/MIT-bfdbfe?style=for-the-badge&logoColor=000)](LICENSE)
[![Platform](https://img.shields.io/badge/Python%20%2B%20Flask-fde68a?style=for-the-badge&logoColor=000)]()
[![Tech](https://img.shields.io/badge/Base%20RPC-fca5a5?style=for-the-badge&logoColor=000)]()

</div>

<div align="center">
<i>A Flask web app that scans Base chain ERC-20 transfer events across a block range, builds holder snapshots, and exports results as CSV with live progress tracking.</i>
</div>

---

## ✦ Features

<div align="center">

| | Feature | What it does |
|:---:|---|---|
| 🔍 | Transfer scanner | Scans ERC-20 Transfer events across any Base block range |
| 📸 | Holder snapshot | Builds a complete holder list with balances at any point in time |
| 📊 | Live progress | Real-time progress bar showing scan status and ETA |
| ⏹️ | Cancel support | Cancel a running scan at any time |
| 📄 | CSV export | Export the full holder list to CSV |
| ⚡ | Concurrent workers | Parallel RPC calls for faster scanning |

</div>

---

## ✦ Download & Run

**Step 1** .... Clone the repo

```bash
git clone https://github.com/0xnurrabby/BaseShot
cd BaseShot/BaseShotP
```

**Step 2** .... Install Python dependencies

```bash
pip install -r requirements.txt
# or on Windows
pip install flask requests python-dotenv
```

**Step 3** .... Configure and run

```bash
# Set your Base RPC URL
# On Windows:
set BASE_RPC_URL=https://mainnet.base.org
# On Mac/Linux:
export BASE_RPC_URL=https://mainnet.base.org

python app.py
# Open http://localhost:5000
```

---

## ✦ Setup

```
1. Clone the repo and cd into BaseShotP/
2. Install requirements: pip install -r requirements.txt
3. Set BASE_RPC_URL environment variable to your Base RPC endpoint
   (free options: https://mainnet.base.org or Alchemy/Infura Base)
4. Run: python app.py
5. Open http://localhost:5000 in your browser
6. Enter a token contract address and block range
7. Click Scan to start
8. Export results as CSV when done

For deployment on Render:
   - Use render.yaml in the repo
   - Set BASE_RPC_URL in Render environment variables
```

---

## ✦ Project Structure

```
BaseShot/
  BaseShotP/
    app.py             ->  Flask app, RPC scanning logic, progress tracking
    requirements.txt   ->  Python dependencies
    templates/         ->  HTML templates
    static/            ->  CSS and JS for the UI
    render.yaml        ->  Render deployment config
    run_windows.bat    ->  Windows quick-start script
    Procfile           ->  Render/Heroku process file
```

---

<img src="https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=2,8,15&height=100&section=footer&animation=fadeIn" width="100%"/>

<div align="center">MIT License .... built by <a href="https://github.com/0xnurrabby">0xnurrabby</a></div>
