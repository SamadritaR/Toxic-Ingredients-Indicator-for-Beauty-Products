#Toxic Ingredients Indicator for Beauty Products

A Streamlit app that scans beauty product labels — by photo, text, or paste — and tells you exactly what's in them, what the risks are, and where those risks are documented.

No more Googling ingredient names one by one. No more trusting that "dermatologist tested" means anything. You upload a photo of the back of your moisturiser, the app reads the label, cross-references every ingredient against a curated database of 700+ compounds, and flags anything worth knowing about — with the actual regulatory sources to back it up.

---

##  My Role  
I built this project end-to-end, focusing on:  
- Designing the **NLP pipeline** to parse ingredient lists.  
- Creating structured **product requirement documents (PRDs)** to guide development.  
- Defining **personas and prioritization (MoSCoW)** for roadmap planning.  
- Conducting **usability testing with peers** to validate the user experience.  
- Deploying the working prototype on **Streamlit** for easy accessibility.  

This started as a personal frustration — trying to decode ingredient lists on skincare products and realising there was no quick way to do it without a biochemistry degree or 45 minutes of searching. The app is my attempt to make that information accessible in under 30 seconds.

---

## What it actually does

**Three ways to scan a product:**

- **Search** — type any ingredient name, abbreviation, or CAS number. Partial matches work — type "paraben" and you'll see all of them.
- **Upload a photo** — take a picture of the ingredients list on your product. The app has a built-in crop tool so you can isolate just the ingredients panel, and a full OCR pipeline that handles dark backgrounds, curved labels, low resolution, and awkward angles.
- **Paste text** — copy an ingredients list from a brand website or anywhere else, paste it in, and get an analysis instantly.

**What you get back for each flagged ingredient:**

- A risk level — High, Medium, or Low — based on severity scores from regulatory bodies
- What the hazard actually is, explained in plain English (endocrine disruption, carcinogenicity, contact sensitisation, etc.)
- Which chemical family it belongs to (parabens, phthalates, cyclic siloxanes, fragrance allergens, PFAS, etc.)
- The specific regulatory sources that flagged it — EU Cosmetics Regulation, SCCS opinions, IARC classifications, FDA guidance, California AB 2762, ECHA dossiers — with links

---

## The database

This is the part I spent the most time on. The app is only as useful as what it knows about.

The database covers 1000+ cosmetic ingredients across 30+ categories:

| Category | Examples |
|---|---|
| Parabens | methylparaben, butylparaben, propylparaben |
| Phthalates | DBP, DEHP, DEP, BBP — all 10 common ones |
| PFAS | PFOA, PFOS, perfluorodecalin, 20+ fluorinated compounds |
| Cyclic siloxanes | D4, D5, D6 — EU-restricted in rinse-off products |
| Formaldehyde donors | DMDM hydantoin, quaternium-15, diazolidinyl urea, bronopol |
| Fragrance allergens | 82 EU-listed allergens including lilial (now banned), oakmoss, galaxolide |
| UV filters | oxybenzone, octinoxate, avobenzone, homosalate, octocrylene, and 15+ others |
| Hair dyes | PPD, resorcinol, disperse dyes, banned oxidative dyes |
| Heavy metals | lead, mercury, arsenic, cadmium, chromium VI, nickel |
| Preservatives | phenoxyethanol, isothiazolinones, IPBC, chlorphenesin, all parabens |
| Retinoids | retinol, retinyl palmitate, retinaldehyde (EU 2022 restrictions) |
| Exfoliants/AHAs | glycolic acid, lactic acid, malic acid, salicylic acid |
| Essential oils | 40+ oils flagged for allergens, phototoxicity, or EU restrictions |
| Surfactants | SLS, SLES, CAPB, ALS, cocamide DEA |
| Ethoxylated/PEG | 50+ PEG variants, all flagged for 1,4-dioxane contamination risk |
| Skin lighteners | hydroquinone (banned EU), kojic acid, arbutin, deoxyarbutin |
| Antioxidants | BHA (IARC 2B), BHT, TBHQ |
| Silicones | dimethicone, phenyl trimethicone, cyclomethicone |
| Nail care | MMA (banned), toluene sulfonamide resin, camphor |
| Oral care | fluoride limits, chlorhexidine, hydrogen peroxide concentrations |

Each entry has a severity score (1–5), a hazard category, an evidence level, and at least one regulatory source. The database draws from 20 sources including EU Annexes II/III/V/VI, SCCS opinions, IARC monographs, ECHA dossiers, FDA guidance, California AB 2762, OEHHA Prop 65, and the CSC Red List.

The search uses SQLite FTS5 with prefix indexing, so "SLES", "sodium laureth", and "laureth sulfate" all find the same thing. There's also a LIKE fallback for anything FTS misses.

---

## The OCR pipeline

Getting readable text out of a phone photo of a cosmetic label is harder than it sounds. Labels have:
- Tiny font, often 6–8pt
- Curved surfaces (tubes, bottles)
- Dark or metallic backgrounds
- Poor lighting or shadows
- Multiple text blocks at different angles

The app runs two OCR paths depending on the image:

**Fast path** — for clean, well-lit, high-resolution images. Skips preprocessing entirely and runs Tesseract directly. Heavy preprocessing on already-good images makes things worse, so this path avoids it.

**Heavy path** — for everything else. Steps: upscale to ~2000px tall, auto-deskew using minAreaRect rotation detection, CLAHE contrast normalisation, NLMeans denoising, Gaussian sharpening, then binarisation via three variants (Otsu, adaptive Gaussian at two block sizes, morphological cleanup). Each variant is run at multiple Tesseract PSM modes (4, 6, 11). The best result is picked by a scoring function that weighs both OCR confidence and word count.

There's also a crop tool built in canvas so you can draw a box around just the ingredients section before running OCR — this alone makes a big difference on cluttered labels.

---

## Tech stack

| Layer | What's used |
|---|---|
| App framework | Streamlit |
| Database | SQLite with FTS5 (full-text search with prefix indexing) |
| OCR | Tesseract via pytesseract |
| Image processing | OpenCV, Pillow |
| PDF support | pdf2image + Poppler |
| Language | Python 3.11+ |

No ML model. No API calls. No internet connection required once set up. Everything runs locally.

---

## Running it

**Requirements:**
- Python 3.11+
- Tesseract installed on your system (`brew install tesseract` on Mac, `apt install tesseract-ocr` on Linux)
- Poppler for PDF support (`brew install poppler` / `apt install poppler-utils`)

```bash
# Clone the repo
git clone https://github.com/SamadritaR/Toxic-Ingredients-Indicator-for-Beauty-Products.git
cd Toxic-Ingredients-Indicator-for-Beauty-Products

# Install Python dependencies
pip install streamlit pytesseract Pillow opencv-python pdf2image numpy

# Run
streamlit run app.py
```

The database file `toxic.db` needs to be in the parent directory of `app.py`, or update the `DB_PATH` variable at the top of the file to point to wherever you put it.

---

## What's next

A few things on the list:

- **Safer alternatives** — when something is flagged, suggest what to look for instead
- **Full product scoring** — aggregate all flagged ingredients into one overall safety score with breakdown
- **Mobile upload improvements** — better handling of portrait-orientation phone photos
- **Ingredient list parsing improvements** — smarter handling of parenthetical INCI names and manufacturer abbreviations
- **Cloud deployment** — hosted version so you don't need to run it locally

---

## Limitations

The database is built from publicly available regulatory sources and is not exhaustive. New ingredients enter the market faster than any database can track them. An ingredient not flagged by this app doesn't mean it's necessarily safe — it may just not be in the database yet.

This is a personal research tool, not a substitute for medical or dermatological advice. If you have a specific skin condition or allergy, talk to a doctor.

---

## Disclaimer

This tool is for educational purposes only.
It is not a substitute for medical or regulatory advice. Always consult dermatologists or official authorities for health-related guidance.
