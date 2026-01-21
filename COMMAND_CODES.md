## ⌨️ FORTRESS COMMAND CODES

### 1. ⚡ THE WAR ROOM (Dashboard)
* **Command:** `sudo systemctl restart fortress-dashboard`
* **URL:** `http://192.168.0.100:8503`
* **Use:** View Live Signals, Real Estate Heatmap, and Financials.

### 2. 💰 FINANCIAL AUDIT (Invoice Hunter)
* **Command:** `python ~/fortress-prime/src/analyze_spend.py`
* **Use:** Scans `/mnt/fortress_data/invoices` and calculates total vendor spend.

### 3. 👁️ OPERATION RETINA (Market Signals)
* **Command:** `python ~/fortress-prime/src/extract_trade_signals_v2.py`
* **Use:** Scrapes Market Club emails, downloads charts, and detects BUY/SELL signals.

### 4. 🗺️ PROPERTY MAPPER (Real Estate)
* **Command:** `python ~/fortress-prime/src/map_real_estate.py`
* **Use:** Scans Zillow/Competitor emails to find the most active territories.
