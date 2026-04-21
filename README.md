# 🧪 Toxic Ingredients Indicator

> **Scan a cosmetic label. Know what's in it. In plain English.**

Most people have no idea what's actually in their skincare, haircare, or makeup products. Ingredient lists are long, written in Latin chemical nomenclature, and deliberately opaque. Parabens, formaldehyde-releasing preservatives, PFAS compounds, phthalates, and benzophenones appear in everyday products - yet nothing on the label tells you they're there or why they matter.

The **Toxic Ingredients Indicator** bridges that gap. It lets anyone - regardless of scientific background — upload a label photo, paste an ingredient list, or type a chemical name, and instantly receive a structured safety report: every flagged ingredient ranked by severity, explained in plain English, and cited back to the actual regulation or study that flagged it.

---

## The Problem It Solves

Regulatory frameworks like the EU Cosmetics Regulation (EC No 1223/2009) have banned over 1,300 cosmetic substances. California's AB 2762 (Toxic-Free Cosmetics Act) prohibits 24 high-risk chemicals. The IARC has classified several common cosmetic ingredients as known or probable carcinogens. Yet none of this information reaches the consumer at the point of purchase in any usable form.

Existing tools like EWG Skin Deep require you to search one ingredient at a time. Think Dirty only works if the product exists in their database. CosDNA and INCI Decoder require you to already have the text — they provide no OCR, no AI explanation, and no severity ranking that a non-expert can act on.

This app is the first to combine:
- Multi-modal input (type, paste, photograph)
- Batch analysis of a full ingredient list in one pass
- Regulatory-grounded hazard tiering across EU, US, and California frameworks
- Chemical family clustering (so you can see when a product has three different parabens)
- AI-generated plain-English explanations for every flagged ingredient

---

## How It Works


https://github.com/user-attachments/assets/56d71239-87b0-4ea8-9b9d-9ed41e18d0a9


### Input Layer

The app accepts three input modes:

**Search text** — type an ingredient name, CAS number, or partial match. The FTS5 search engine returns all database matches instantly. Useful for quickly looking up a specific chemical.

**Paste text** — paste the full ingredient list from a product page, packaging photo, or anywhere else. The app tokenizes on commas, semicolons, and newlines, then runs each term through the search pipeline. Results for the whole product come back in one pass.

**Upload image** — photograph a product label and upload it. The app routes it through the OCR pipeline (described below), extracts the ingredient text, and hands it to the search layer. You can also upload a PDF ingredient sheet — up to 5 pages are processed automatically.

### OCR Pipeline

Label photography is one of the hardest real-world OCR problems. Labels are curved, reflective, small-font, densely packed, and photographed under uncontrolled lighting on smartphone cameras. Standard OCR engines fail badly on these inputs.

The app implements a **dual-path OCR pipeline** that detects image quality and routes accordingly:

**Fast path** — triggered when the image is high-resolution (height ≥ 600px), has a light background (mean pixel > 150), and has good contrast (std dev > 15). In this case minimal preprocessing is applied: the image is padded and submitted to Tesseract with a PSM sweep across modes 3, 4, and 6. The highest-confidence result is selected. Completes in under 2 seconds.

**Heavy path** — triggered for everything else: dark backgrounds, curved surfaces, compressed JPEGs, blurry smartphone photos. The image is first deskewed using OpenCV's minAreaRect angle detection. It is then scaled to a maximum height of 2,000 pixels using Lanczos interpolation. Six preprocessing variants are generated:

- Raw padded image
- Gamma correction at 0.4 (brightening dark labels)
- CLAHE with clip limit 3.0 and 8×8 tile grid (adaptive contrast enhancement)
- Contrast stretching (normalizes pixel range to 0–255)
- Gaussian sharpening (denoised then unsharp masked at 1.6 / -0.6 blend)
- Unsharp masking at sigma 2.5 (specifically targets soft-focus live captures)

Each variant is submitted to Tesseract with PSM modes 6 (uniform block) and 4 (single column), plus three variants with PSM 11 (sparse text) — giving 15 combinations total. Each returns a text string scored by a combined metric of Tesseract mean confidence and an INCI-specific token count heuristic (capitalized tokens ≥ 3 characters = likely ingredient name). The highest-scoring combination wins.

All output passes through a postprocessing layer that fixes common OCR character substitutions (0→O, 1→I/L, |→L), normalizes separators, removes noise-heavy lines, and applies a 25-entry dictionary of specific INCI name corrections built from real-world testing.

**Gemini Vision fallback** — when the user selects "Run OCR (Gemini Vision)", both Tesseract and Gemini Vision run in parallel on the same image. Gemini receives the image as base64-encoded PNG with a structured prompt asking for the ingredient list in comma-separated INCI format. The two outputs are compared by a word count heuristic (tokens ≥ 4 characters), and the higher-count output is selected. On dark and curved labels, Gemini Vision consistently outperforms Tesseract.

### Search and Retrieval

The search layer takes the ingredient text — whether typed, pasted, or OCR-extracted — and maps it to database records through a two-stage pipeline:

**Stage 1: FTS5 prefix search** — each candidate term is submitted to a SQLite FTS5 virtual table built on ingredient names and aliases with a unicode61 tokenizer and prefix indexing from 2 to 10 characters. This handles partial matches, abbreviated names, and prefix truncation from OCR errors.

**Stage 2: LIKE fallback** — if FTS5 returns no results for a term, a case-insensitive LIKE substring match runs against both the ingredient name column and the alias column. This catches OCR-corrupted tokens that don't align with the FTS tokenizer's expectations.

Results from both stages are deduplicated by ingredient ID and merged. The result set is capped at 30 ingredients per query.

**Domain expansion rules** — two special-case rules address the industry practice of hiding specific chemicals behind generic umbrella terms:
- Input containing `fragrance` or `parfum` automatically expands to six known high-prevalence fragrance allergens: linalool, limonene, citral, eugenol, benzyl salicylate, benzyl benzoate
- Input containing `paraben` expands to all six major paraben variants: methylparaben, propylparaben, butylparaben, ethylparaben, isobutylparaben, isopropylparaben

### Result Enrichment and Display

Each matched ingredient is enriched with:
- All associated hazard records, joined with hazard code, category, description, and severity score
- Chemical family assignment (via regex mapping against name and hazard fields, with notes-field override)
- Maximum severity across all linked hazard records (determines the displayed risk tier)
- Source citations with URLs linking back to the original regulatory document

Results are sorted high-to-low by severity. The risk summary bar shows the count of High, Medium, and Low ingredients at a glance. Each ingredient card shows the CAS number, family, one-line hazard description, and source links. An "Explain this to me" button fires a Gemini API call that returns a two-sentence plain-English explanation cached in session state.

The AI product summary generates automatically for the full result set: a 3–5 sentence paragraph naming the overall risk level, the worst ingredients explained simply, any repeat chemical families, and a practical tip. Both the summary and explanations use retry logic (up to 3 attempts) and only cache complete responses that end with sentence-terminating punctuation.

---

## Database

The `toxic.db` SQLite database is the analytical core of the app. It is organized across five normalized tables:

| Table | Purpose |
|---|---|
| `ingredients` | 736 flagged cosmetic ingredients with INCI names and CAS numbers |
| `hazards` | Hazard records with code, category, description, and severity tier (0–5) |
| `ingredient_hazards` | Junction table linking ingredients to hazards with source attribution |
| `ingredient_aliases` | Trade names, alternate spellings, and OCR-variant forms per ingredient |
| `sources` | Regulatory and scientific references with URLs |

**736 ingredients** are covered across **30 chemical families** including:

Parabens, Phthalates, PFAS / Fluorinated compounds, Benzophenones (UV filters), Formaldehyde donors, Cyclic siloxanes, Isothiazolinones, Fragrance allergens, Ethoxylated / PEG compounds, Hair dye precursors (aromatic amines / phenols)

**Severity tiers:**

| Tier | Label | Criteria |
|---|---|---|
| 4–5 | High risk | Known carcinogens (IARC Group 1/2A), endocrine disruptors, reproductive toxins, banned substances |
| 2–3 | Medium risk | Probable carcinogens (IARC Group 2B), confirmed sensitizers, persistent bioaccumulators, restricted substances |
| 0–1 | Low risk | Possible sensitizers, limited evidence of harm, generally safe at typical concentrations |

**Regulatory sources:** EU EC No 1223/2009 · California AB 2762 · IARC Monographs · FDA / MoCRA · CIR Expert Panel · California Proposition 65

The `ingredients_fts` virtual table is built at runtime from `ingredients` and `ingredient_aliases` using the FTS5 engine with unicode61 tokenizer and prefix indexing. It rebuilds automatically if absent or stale.

---

## Tech Stack

```
Frontend          Streamlit 1.x
Database          SQLite 3 + FTS5 virtual table
OCR (primary)     Tesseract 4 via pytesseract
OCR (secondary)   Gemini Vision (Google Generative Language API)
Image processing  OpenCV, Pillow
PDF support       pdf2image + Poppler
AI features       Gemini 2.5 Flash (REST API, x-goog-api-key auth)
HTTP client       Python requests
Language          Python 3.11+
```

---

## Getting Started

**1. Clone the repo**
```bash
git clone https://github.com/yourusername/toxic-ingredients-indicator.git
cd toxic-ingredients-indicator
```

**2. Create a virtual environment**
```bash
python3 -m venv venv
source venv/bin/activate
```

**3. Install Python dependencies**
```bash
pip install -r requirements.txt
```

**4. Install Tesseract** (system dependency, not pip)

macOS:
```bash
brew install tesseract
```
Ubuntu / Debian:
```bash
sudo apt-get install tesseract-ocr
```

**5. Install Poppler** (required for PDF support)

macOS:
```bash
brew install poppler
```
Ubuntu / Debian:
```bash
sudo apt-get install poppler-utils
```

**6. Add your Gemini API key** *(optional — all four AI features require it, core search and OCR work without it)*

Create the file `.streamlit/secrets.toml` in the project root:
```toml
GEMINI_API_KEY = "your-api-key-here"
```
Get a free key at [aistudio.google.com](https://aistudio.google.com) or via Google Cloud Console with the Generative Language API enabled.

**7. Run**
```bash
streamlit run app/app.py
```

The app opens at `http://localhost:8501`. Any device on the same WiFi network can access it at `http://your-machine-ip:8501` — no extra configuration needed.

---

## Project Structure

```
toxic-ingredients-indicator/
│
├── app/
│   └── app.py                  # Full Streamlit application (~1,000 lines)
│
├── data/
│   ├── toxic.db                # SQLite database (736 ingredients, 5 tables)
│   └── seed_kb.csv             # Source data used to populate the database
│
├── core/                       # Core utility modules
│
└── .streamlit/
    └── secrets.toml            # API key config (not committed to repo)
```

---

## AI Features

All four Gemini features are optional. The app detects whether a valid API key is present and enables or disables the relevant buttons accordingly. Without a key, the core ingredient search, OCR, risk tiering, and regulatory citations work fully.

| Feature | What it does | Max tokens |
|---|---|---|
| Gemini Vision OCR | Extracts ingredient list from a label photo | 600 |
| OCR error correction | Fixes garbled INCI names in Tesseract output | 600 |
| AI product summary | 3–5 sentence plain-English overview of the full product | 600 |
| Per-ingredient explanation | 2-sentence explanation of what an ingredient is and why it matters | 500 |

All calls use a structured prompting strategy: role assignment, factual context block from the database, explicit output format instruction. Responses are validated for completeness (must end with `.`, `!`, or `?`) and retried up to 3 times if incomplete. Complete responses are cached in Streamlit session state to avoid redundant API calls.

---

## Known Limitations

- The database covers 736 ingredients. Chemicals not in the database return no results and are not flagged. Absence of a result is not a safety guarantee.
- OCR on very low-resolution images (below 400px height) is unreliable even with heavy-path preprocessing. The app surfaces a warning in this case.
- Risk assessment is binary per ingredient — the app does not account for concentration. An ingredient restricted above 0.5% is flagged the same regardless of its actual concentration in the product.
- The Gemini free tier has a daily request quota. If you hit it, the AI features return 429 errors and the app falls back to database-only results automatically.

---

## Built By

**Samadrita Roy Chowdhury**
MS Business Analytics · California State University, East Bay · Spring 2026

Background in DevOps and Infrastructure (Capgemini) · Product Analytics (KNEX Technology) · Data Engineering and AI
