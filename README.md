# 🧪 Toxic Ingredients Indicator

**Scan a cosmetic label. Know what's in it. In plain English.**

Toxic Ingredients Indicator is a Streamlit web app that analyzes cosmetic product ingredient lists and flags harmful chemicals using a curated toxicological database, dual-engine OCR, and AI-powered plain-English explanations.

---

## What It Does

Upload a label photo, paste an ingredient list, or type a single ingredient name. The app parses the input, matches it against 736 flagged cosmetic chemicals across 30 chemical families, and returns a severity-ranked safety report — no chemistry background required.

Every flagged ingredient shows its risk tier, chemical family, CAS number, one-line hazard description, regulatory source citation, and an on-demand AI explanation written in plain English.

---

## Features

| Feature | Details |
|---|---|
| 🔍 Ingredient search | FTS5 full-text search with prefix matching and alias lookup |
| 📋 Paste-from-label | Paste a raw ingredient list and analyze the full product |
| 📸 Image upload | Upload a label photo and extract ingredients via OCR |
| 🤖 Dual OCR engine | Tesseract (fast + heavy path) with Gemini Vision fallback |
| ⚠️ Risk tiering | High / Medium / Low severity badges sorted by concern |
| 🧬 Chemical families | 30 families including parabens, PFAS, formaldehyde donors, phthalates |
| 📖 AI explanations | Per-ingredient plain-English explanations via Gemini 2.5 Flash |
| 📝 AI product summary | One-paragraph safety overview of the full ingredient list |
| ✨ OCR error correction | AI fixes garbled INCI names before analysis |
| 🌿 Regulatory sources | EU EC 1223/2009, California AB 2762, IARC, FDA, CIR Expert Panel |

---

## Tech Stack

```
Frontend       Streamlit
Database       SQLite 3 + FTS5
OCR            Tesseract 4 (pytesseract) + OpenCV + Gemini Vision
AI             Gemini 2.5 Flash (Google Generative Language API)
Image          Pillow, pdf2image
Language       Python 3.11+
```

---

## Getting Started

**1. Clone the repo**
```bash
git clone https://github.com/yourusername/toxic-ingredients-indicator.git
cd toxic-ingredients-indicator
```

**2. Install dependencies**
```bash
pip install -r requirements.txt
```

**3. Install Tesseract**

On macOS:
```bash
brew install tesseract
```
On Ubuntu/Debian:
```bash
sudo apt-get install tesseract-ocr
```

**4. Add your Gemini API key** *(optional — app works without it)*

Create `.streamlit/secrets.toml`:
```toml
GEMINI_API_KEY = "your-key-here"
```
Get a free key at [aistudio.google.com](https://aistudio.google.com)

**5. Run the app**
```bash
streamlit run app/app.py
```

Open `http://localhost:8501` in your browser. On the same WiFi network, any device can access it at `http://your-ip:8501`.

---

## Project Structure

```
toxic-ingredients-indicator/
│
├── app/
│   └── app.py               # Main Streamlit application
│
├── data/
│   ├── toxic.db             # SQLite database (736 ingredients)
│   └── seed_kb.csv          # Source data for database population
│
└── core/                    # Core modules
```

---

## Database

The `toxic.db` SQLite database contains:

- **736 flagged cosmetic ingredients** with CAS numbers and INCI names
- **30 chemical families** including parabens, phthalates, PFAS, benzophenones, cyclic siloxanes, isothiazolinones, fragrance allergens, formaldehyde donors, ethoxylated compounds, and hair dye precursors
- **5 hazard severity tiers** from 0 (low concern) to 5 (known carcinogen / banned)
- **Regulatory citations** from EU, FDA, IARC, California AB 2762, and the CIR Expert Panel
- **Alias table** with trade names, alternate spellings, and OCR-variant forms per ingredient

---

## How the OCR Pipeline Works

Images are routed through one of two processing paths based on detected quality:

**Fast path** — clean, high-resolution, light-background images. Minimal preprocessing, PSM sweep, result in under 2 seconds.

**Heavy path** — dark, blurry, curved, or compressed label photos. Applies 6 preprocessing variants (CLAHE, gamma correction, unsharp masking, contrast stretching, denoising, sharpening) across multiple Tesseract page segmentation modes. Selects the highest-scoring output using a confidence and INCI token heuristic.

When Gemini Vision OCR is selected, both engines run in parallel and the higher word-count output wins.

---

## Regulatory Coverage

| Source | Jurisdiction | Scope |
|---|---|---|
| EC No 1223/2009 | European Union | 1,300+ banned and restricted substances |
| AB 2762 Toxic-Free Cosmetics Act | California, USA | 24 prohibited chemicals |
| IARC Monographs | International | Carcinogenicity classifications Group 1 / 2A / 2B |
| FDA Cosmetic Guidance + MoCRA | United States | Prohibited ingredients and labeling |
| CIR Expert Panel | USA | Peer-reviewed ingredient safety assessments |

---

## Requirements

```
streamlit
pytesseract
Pillow
opencv-python
pdf2image
requests
numpy
```

Tesseract must be installed separately as a system dependency (see Getting Started above).

---

## Notes

- The Gemini API key is optional. Without it, all four AI features are disabled but the core ingredient search, OCR, risk tiering, and source citations work fully.
- The app is accessible on mobile browsers via local network sharing at `http://your-local-ip:8501`.
- The database does not cover every harmful cosmetic ingredient. Ingredients not in the database return no results.

---

## Built By

**Samadrita Roy Chowdhury**
MS Business Analytics — California State University, East Bay
Capstone Project, Spring 2026
