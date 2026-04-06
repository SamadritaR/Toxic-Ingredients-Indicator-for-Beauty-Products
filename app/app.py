import os, sys, io, re, sqlite3, textwrap, pathlib, requests, base64
from contextlib import closing

import streamlit as st

# Optional OCR deps
try:
    from PIL import Image
    import pytesseract
except Exception:
    Image = None
    pytesseract = None

try:
    from pdf2image import convert_from_bytes
except Exception:
    convert_from_bytes = None

# After: import pytesseract
import shutil
# Homebrew on Apple Silicon (M1/M2/M3) usually installs here:
DEFAULT_TESS = "/opt/homebrew/bin/tesseract"
if shutil.which("tesseract") is None and os.path.exists(DEFAULT_TESS):
    pytesseract.pytesseract.tesseract_cmd = DEFAULT_TESS


# -----------------------------
# SQLite helpers (self-contained)
# -----------------------------

DB_PATH = str(pathlib.Path(__file__).resolve().parents[1] / "toxic.db")

def connect():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con

CON = connect()


def ensure_fts_prefix():
    with closing(CON.cursor()) as cur:
        cur.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='ingredients_fts';
        """)
        exists = cur.fetchone() is not None

        need_rebuild = False
        if exists:
            try:
                cur.execute("SELECT count(*) FROM ingredients_fts LIMIT 1;")
            except sqlite3.OperationalError:
                need_rebuild = True
        else:
            need_rebuild = True

        if need_rebuild:
            cur.execute("DROP TABLE IF EXISTS ingredients_fts;")
            cur.execute("""
                CREATE VIRTUAL TABLE ingredients_fts USING fts5(
                  name, cas_number, aliases,
                  tokenize = 'unicode61 remove_diacritics 2',
                  prefix = '2 3 4 5 6 7 8 9 10'
                );
            """)
            cur.executescript("""
                DELETE FROM ingredients_fts;
                INSERT INTO ingredients_fts(rowid, name, cas_number, aliases)
                SELECT i.id, i.name, i.cas_number,
                       IFNULL(
                         (SELECT GROUP_CONCAT(alias,' ')
                            FROM ingredient_aliases a
                           WHERE a.ingredient_id = i.id),''
                       )
                FROM ingredients i;
            """)
            CON.commit()


def fts_candidates(term: str, limit: int):
    q = term.strip()
    if not q:
        return []
    qstar = q if q.endswith("*") else (q + "*")
    with closing(CON.cursor()) as cur:
        try:
            cur.execute(
                "SELECT rowid FROM ingredients_fts WHERE ingredients_fts MATCH ? LIMIT ?;",
                (qstar, limit)
            )
            return [r[0] for r in cur.fetchall()]
        except sqlite3.OperationalError:
            return []


def like_candidates(term: str, limit: int):
    q = term.strip()
    if not q:
        return []
    with closing(CON.cursor()) as cur:
        ids = set()

        cur.execute(
            "SELECT id FROM ingredients WHERE LOWER(name) LIKE '%'||LOWER(?)||'%' LIMIT ?;",
            (q, limit)
        )
        ids.update([r[0] for r in cur.fetchall()])

        cur.execute(
            "SELECT ingredient_id FROM ingredient_aliases "
            "WHERE LOWER(alias) LIKE '%'||LOWER(?)||'%' LIMIT ?;",
            (q, limit)
        )
        ids.update([r[0] for r in cur.fetchall()])

        return list(ids)


def search_ingredients(term: str, limit: int = 30):
    ids = []
    seen = set()
    for source in (fts_candidates, like_candidates):
        for _id in source(term, limit * 3):
            if _id not in seen:
                ids.append(_id)
                seen.add(_id)
    if not ids:
        return []

    placeholders = ",".join(["?"] * len(ids))
    with closing(CON.cursor()) as cur:
        cur.execute(
            f"SELECT id, name, cas_number FROM ingredients "
            f"WHERE id IN ({placeholders}) ORDER BY name ASC LIMIT ?;",
            (*ids, limit)
        )
        return [dict(r) for r in cur.fetchall()]


def hazards_for(ingredient_id: int):
    with closing(CON.cursor()) as cur:
        cur.execute("""
            SELECT h.code, h.category, h.description, h.severity,
                   ih.notes,
                   s.name AS source_name, s.url AS source_url
            FROM ingredient_hazards ih
            JOIN hazards h ON h.id = ih.hazard_id
            LEFT JOIN sources s ON s.id = ih.source_id
            WHERE ih.ingredient_id = ?
            ORDER BY COALESCE(h.severity,0) DESC, h.category, h.code;
        """, (ingredient_id,))
        return [dict(r) for r in cur.fetchall()]


def family_for(name: str, hazards: list[dict]) -> str:
    def from_notes():
        for h in hazards:
            notes = (h.get("notes") or "").strip()
            if not notes:
                continue
            m = re.search(r"family:\s*([^\n;]+)", notes, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return None

    m = from_notes()
    if m:
        return m

    name_l = (name or "").lower()
    fields = " ".join([(h.get("description") or "") + " " + (h.get("category") or "") for h in hazards]).lower()

    def has(p): return re.search(p, name_l) or re.search(p, fields)

    mapping = [
        ("parabens", r"paraben"),
        ("phthalates", r"phthalate|bbp|dbp|dehp|dibp|dinp|didp|dnop"),
        ("benzophenones (UV filters)", r"benzophenone|oxybenzone|bp-?\d"),
        ("formaldehyde donors", r"dmdm|hydantoin|imidazolidinyl|diazolidinyl|quaternium-15|bronopol|hydroxymethyl"),
        ("isothiazolinones", r"isothiazolinone|(^|\W)mi($|\W)|(^|\W)mci($|\W)|(^|\W)bit($|\W)|(^|\W)oit($|\W)|dcoit"),
        ("cyclic siloxanes", r"\b(d4|d5|d6)\b|cyclotetra|cyclopenta|cyclohexa.*silox"),
        ("PFAS/fluorinated", r"\bpfas|perfluoro|ptfe|trifluoro|fluoro.*(ether|siloxane|acrylate)"),
        ("hair dyes (aromatic amines/phenols)", r"phenylenediamine|aminophenol|resorcinol"),
        ("fragrance allergens", r"linalool|limonene|citral|eugenol|coumarin|oakmoss|treemoss|benzyl"),
        ("ethoxylated/PEG", r"\bpeg[- ]?\d|\bpolysorbate|\bethoxylat|\blaureth|\bceteareth|\bsteareth|\bolet(h)?"),
    ]
    for fam, patt in mapping:
        if has(patt):
            return fam
    return "—"


def risk_label(max_sev: int | None):
    if max_sev is None: return ("Unknown", "bg-gray-200")
    if max_sev >= 4:    return ("High", "bg-red-200")
    if max_sev >= 2:    return ("Medium", "bg-yellow-200")
    return ("Low", "bg-green-200")


def harm_one_liner(name: str, hz: list[dict]) -> str:
    if not hz:
        return "No hazard records found for this ingredient in the current dataset."
    best = sorted(hz, key=lambda h: (-(h["severity"] or 0), -(len(h.get("description") or ""))))[0]
    cat = best.get("category") or best.get("code") or "hazard"
    desc = (best.get("description") or "").strip()
    base = f"{name} is associated with {cat.lower()}."
    if desc:
        desc = desc.rstrip(".")
        return f"{base} {desc}."
    return base


def sources_inline(hz: list[dict]) -> str:
    out = []
    seen = set()
    for h in hz:
        key = (h.get("source_name"), h.get("source_url"))
        if key in seen:
            continue
        seen.add(key)
        nm = h.get("source_name") or "source"
        url = h.get("source_url")
        if url:
            out.append(f"[{nm}]({url})")
        else:
            out.append(nm)
        if len(out) >= 3:
            break
    return " • ".join(out)

# --------------------------------
# Gemini API helpers
# --------------------------------

GEMINI_MODEL = "gemini-2.5-flash"

def _gemini_key() -> str:
    try:
        return st.secrets.get("GEMINI_API_KEY", "") or os.environ.get("GEMINI_API_KEY", "")
    except Exception:
        return os.environ.get("GEMINI_API_KEY", "")


def _gemini_call(prompt: str, max_tokens: int = 500, image_b64: str = None,
                 image_mime: str = "image/png") -> str:
    key = _gemini_key()
    if not key:
        return ""
    parts = []
    if image_b64:
        parts.append({"inline_data": {"mime_type": image_mime, "data": image_b64}})
    parts.append({"text": prompt})
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        + GEMINI_MODEL + ":generateContent"
    )
    headers = {"Content-Type": "application/json", "x-goog-api-key": key}
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": max_tokens},
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=20)
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        st.warning(f"⚠️ Gemini API error: {e} | Status: {getattr(resp, 'status_code', 'N/A')} | Response: {getattr(resp, 'text', 'N/A')[:300]}")
        return ""


def gemini_clean_ocr(raw_text: str) -> str:
    if not _gemini_key() or not raw_text.strip():
        return raw_text
    prompt = """You are an expert in cosmetic ingredient lists using INCI naming.
Fix ALL OCR errors in the text below.
COMMON ERRORS: 0->O, 1->I or L, 2->Z, 3->E, 4->A, 5->S, 6->G, 8->B
Broken words: "PHENOXY ETHANOL"->"PHENOXYETHANOL"
Missing letters: "NIACINMIDE"->"NIACINAMIDE"
Garbles: "CARB0MER"->"CARBOMER", "S0DIUM"->"SODIUM", "DIMETH1CONE"->"DIMETHICONE"
Join line-broken ingredient names. Fix repeated punctuation.
KNOWN INCI: Aqua, Glycerin, Niacinamide, Phenoxyethanol, Sodium Hyaluronate,
Dimethicone, Carbomer, Methylparaben, Propylparaben, Butylparaben, Ethylparaben,
Sodium Laureth Sulfate, Sodium Lauryl Sulfate, Cocamidopropyl Betaine,
Tocopheryl Acetate, Allantoin, Panthenol, Xanthan Gum, Disodium EDTA,
Cetearyl Alcohol, Butylene Glycol, Propylene Glycol, Ethylhexylglycerin,
Caprylyl Glycol, Sodium Benzoate, Potassium Sorbate, Salicylic Acid,
Hyaluronic Acid, Ceramide NP, Squalane, Titanium Dioxide, Zinc Oxide,
Oxybenzone, Octinoxate, Avobenzone, Caprylic/Capric Triglyceride
OUTPUT: corrected ingredient list only, no explanation, no preamble.
RAW TEXT:\n""" + raw_text
    corrected = _gemini_call(prompt, max_tokens=600)
    if not corrected or len(corrected) < len(raw_text) * 0.25:
        return raw_text
    return corrected


def gemini_vision_ocr(pil_image) -> str:
    if not _gemini_key() or Image is None:
        return ""
    buf = io.BytesIO()
    pil_image.save(buf, format="PNG")
    img_b64 = base64.b64encode(buf.getvalue()).decode()
    prompt = """This is a photo of a cosmetic product label.
Extract ONLY the ingredients list. Output ingredient names separated by commas.
Preserve INCI names and parenthetical translations like Aqua (Water).
No preamble, no explanation. If no ingredients list visible: NO_INGREDIENTS_FOUND"""
    result = _gemini_call(prompt, max_tokens=600, image_b64=img_b64)
    if not result or "NO_INGREDIENTS_FOUND" in result:
        return ""
    return result.strip()


def gemini_explain_ingredient(name: str, risk: str, family: str, why: str) -> str:
    cache_key = "_expl_" + re.sub(r"[^a-z0-9]", "_", name.lower())
    if st.session_state.get(cache_key):
        return st.session_state[cache_key]
    prompt = (
        f"You are a cosmetic safety expert talking to someone who knows nothing about chemistry.\n"
        f"Ingredient: {name}\nRisk: {risk}\nFamily: {family}\nConcern: {why}\n\n"
        f"Write exactly 2 sentences:\n"
        f"1. What this ingredient IS and what it does in a beauty product\n"
        f"2. Why someone should or shouldn't be concerned — be specific\n"
        f"Plain English only, no jargon. No bullet points, just 2 sentences. "
        f"IMPORTANT: Always write complete sentences. Never stop mid-sentence."
    )
    for _ in range(3):  # retry up to 3 times if response looks incomplete
        result = _gemini_call(prompt, max_tokens=500)
        if result and result[-1] in ".!?":
            break

    if result:
        st.session_state[cache_key] = result
    return result or ""


def gemini_product_summary(flagged: list[dict]) -> str:
    if not _gemini_key() or not flagged:
        return ""
    lines = [
        "- " + r["name"] + " | Risk: " + r["risk"] +
        " | Family: " + r["fam"] + " | Concern: " + r["why"]
        for r in flagged[:20]
    ]
    prompt = (
        "You are a cosmetic safety expert explaining ingredients to an everyday consumer.\n"
        "Flagged ingredients (high to low risk):\n" + "\n".join(lines) +
        "\n\nWrite 3-5 sentences: overall risk level, 1-2 worst ingredients explained simply, "
        "repeat families if any, one practical tip. "
        "Plain English, no bullet points, one paragraph. "
        "IMPORTANT: Always write complete sentences. Never stop mid-sentence."
    )
    for _ in range(3):  # retry up to 3 times if response looks incomplete
        result = _gemini_call(prompt, max_tokens=600)
        if result and result[-1] in ".!?":
            return result
    return result or ""


# --------------------------------
# OCR helpers
# --------------------------------

import cv2, numpy as np


def _gamma(img, g=0.4):
    lut = np.array([((i / 255.0) ** g) * 255 for i in range(256)], dtype=np.uint8)
    return lut[img]


def _contrast_stretch(img):
    mn, mx = img.min(), img.max()
    if mx <= mn:
        return img
    return ((img.astype(float) - mn) / (mx - mn) * 255).astype(np.uint8)


def _deskew(gray):
    try:
        thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
        coords = np.column_stack(np.where(thresh > 0))
        if len(coords) < 100:
            return gray
        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = 90 + angle
        if abs(angle) < 0.5:
            return gray
        h, w = gray.shape[:2]
        M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
        return cv2.warpAffine(gray, M, (w, h),
                              flags=cv2.INTER_CUBIC,
                              borderMode=cv2.BORDER_REPLICATE)
    except Exception:
        return gray


def _pad(img, size=40):
    return cv2.copyMakeBorder(img, size, size, size, size,
                              cv2.BORDER_CONSTANT, value=255)


def _is_clean(gray):
    """Light background, tall enough, good contrast → use fast path."""
    h = gray.shape[0]
    return h >= 600 and float(np.mean(gray)) > 150 and float(np.std(gray)) > 15


def _run_ocr(img, psm, conf_threshold=10):
    cfg = f"--oem 3 --psm {psm}"
    try:
        data = pytesseract.image_to_data(img, lang="eng", config=cfg,
                                         output_type=pytesseract.Output.DICT)
        confs = [c for c in data["conf"] if isinstance(c, (int, float)) and c >= 0]
        words = [w for w, c in zip(data["text"], data["conf"])
                 if isinstance(c, (int, float)) and c > conf_threshold and w.strip()]
        if not confs or not words:
            return "", 0.0
        mean_conf = float(np.mean(confs))
        score = mean_conf * (len(words) ** 0.5)
        return " ".join(words), score
    except Exception:
        return "", 0.0


def _ingredient_score(text):
    tokens = re.findall(r'[A-Z][A-Z\-\(\)/]{2,}', text)
    noise  = len(re.findall(r'[=\-_|~]{2,}|\b\w\b|\d{4,}', text))
    return len(tokens) * 10 - noise * 5


def _make_heavy_variants(base, h):
    scale  = min(max(2000 / max(h, 1), 1.0), 3.0)
    interp = cv2.INTER_LANCZOS4 if h < 800 else cv2.INTER_CUBIC
    scaled = cv2.resize(base, None, fx=scale, fy=scale, interpolation=interp)
    padded = _pad(scaled)

    clahe   = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    cl      = clahe.apply(padded)
    g_img   = _gamma(padded, 0.4)
    st      = _contrast_stretch(padded)
    dn      = cv2.fastNlMeansDenoising(padded, None, h=10,
                                       templateWindowSize=7, searchWindowSize=21)
    blur    = cv2.GaussianBlur(dn, (0, 0), 1.0)
    sharp   = cv2.addWeighted(dn, 1.6, blur, -0.6, 0)

    # Unsharp mask — specifically targets soft-focus / garbled chars from live captures
    blur2   = cv2.GaussianBlur(padded, (0, 0), 2.5)
    unsharp = cv2.addWeighted(padded, 2.0, blur2, -1.0, 0)

    variants = []
    for img_v in [padded, g_img, cl, st, sharp, unsharp]:
        for psm in [6, 4]:
            variants.append((img_v, psm))
    for img_v in [padded, g_img, unsharp]:
        variants.append((img_v, 11))

    return variants


def _postprocess(text: str) -> str:
    # Fix period or colon between ALL-CAPS words → comma
    text = re.sub(
        r'([A-Z\(\)/]{2,})[.:,]\s*([A-Z\(\)])',
        lambda m: m.group(1) + ', ' + m.group(2),
        text
    )
    # Remove noise-heavy lines
    clean_lines = []
    for line in text.split('\n'):
        s = line.strip()
        if not s:
            continue
        noise = len(re.findall(r'[=\-_|~]', s))
        if noise > len(s) * 0.35:
            continue
        if not re.search(r'[A-Za-z]', s):
            continue
        clean_lines.append(s)
    text = ' '.join(clean_lines)

    # Expanded OCR substitution fixes — covers common garbling from live/compressed captures
    fixes = [
        (r'\bOlL\b',            'OIL'),
        (r'\b0IL\b',            'OIL'),
        (r'\bOLL\b',            'OIL'),
        (r'\bCETEARY\|\b',      'CETEARYL'),
        (r'\bALCOHGL\b',        'ALCOHOL'),
        (r'\bALCOHO1\b',        'ALCOHOL'),
        (r'\bSOPROPYL\b',       'ISOPROPYL'),
        (r'\bNIACINAMIGE\b',    'NIACINAMIDE'),
        (r'\bNlACINAMIDE\b',    'NIACINAMIDE'),
        (r'\bPANTHENQL\b',      'PANTHENOL'),
        (r'\bPANTHEN0L\b',      'PANTHENOL'),
        (r'\bGLYCERlN\b',       'GLYCERIN'),
        (r'\bGLYCER1N\b',       'GLYCERIN'),
        (r'\bWATER\b',          'WATER'),   # sometimes reads as W4TER
        (r'\bW4TER\b',          'WATER'),
        (r'\bSODlUM\b',         'SODIUM'),
        (r'\bSOD1UM\b',         'SODIUM'),
        (r'\bPROPYLENE\b',      'PROPYLENE'),
        (r'\bPROPYL3NE\b',      'PROPYLENE'),
        (r'\bPHENOXYETHANOL\b', 'PHENOXYETHANOL'),
        (r'\bPHENOXYETHAN0L\b', 'PHENOXYETHANOL'),
        (r'\bBUTYLENE\b',       'BUTYLENE'),
        (r'\bBUTYL3NE\b',       'BUTYLENE'),
        (r'\bCARBOMER\b',       'CARBOMER'),
        (r'\bCARB0MER\b',       'CARBOMER'),
        (r'\bXANTHAN\b',        'XANTHAN'),
        (r'\bXANTH4N\b',        'XANTHAN'),
        (r'\b([A-Z]{3,})\|\b',  r'\1L'),   # trailing | → L
        (r'\b([A-Z]{3,})1\b',   r'\1I'),   # trailing 1 → I for caps words
        (r'\b([A-Z]{3,})0\b',   r'\1O'),   # trailing 0 → O for caps words
    ]
    for pat, repl in fixes:
        text = re.sub(pat, repl, text)

    text = re.sub(r'[ \t]+', ' ', text).strip()
    return text


def ocr_image(pil_image):
    """
    Returns (text, is_low_res).

    Strategy:
    ─ FAST PATH  (clean, high-res, light-bg): minimal preprocessing.
    ─ HEAVY PATH (dark/blurry/curved/low-res): 14 preprocessing × PSM combos
      including unsharp mask, scored by ingredient-token count.
    """
    if pytesseract is None or Image is None:
        return "", False

    is_low_res = pil_image.height < 400

    try:
        gray = cv2.cvtColor(np.array(pil_image.convert("RGB")), cv2.COLOR_RGB2GRAY)
    except Exception:
        try:
            return pytesseract.image_to_string(
                pil_image, lang="eng", config="--oem 3 --psm 6"), is_low_res
        except Exception:
            return "", is_low_res

    dark_bg = float(np.mean(gray)) < 127
    base    = cv2.bitwise_not(gray) if dark_bg else gray.copy()
    h       = base.shape[0]

    # ── FAST PATH ────────────────────────────────────────────────────────────
    if _is_clean(base):
        padded = _pad(base, size=30)
        best_t, best_sc = "", 0.0
        for psm in (6, 4, 3):
            t, sc = _run_ocr(padded, psm)
            if sc > best_sc and len(t) > 10:
                best_t, best_sc = t, sc
        if best_sc > 200 and len(best_t.split()) >= 5:
            return _postprocess(best_t), is_low_res

    # ── HEAVY PATH ───────────────────────────────────────────────────────────
    base    = _deskew(base)
    variants = _make_heavy_variants(base, h)

    best_t, best_sc = "", 0.0
    for img_v, psm in variants:
        t, conf_sc = _run_ocr(img_v, psm)
        ing_sc = _ingredient_score(t)
        combined = conf_sc * 0.5 + ing_sc * 2.0
        if combined > best_sc and len(t) > 10:
            best_t, best_sc = t, combined

    if not best_t.strip():
        try:
            best_t = pytesseract.image_to_string(
                pil_image, lang="eng", config="--oem 3 --psm 6")
        except Exception:
            best_t = ""

    return _postprocess(best_t), is_low_res

def ocr_pdf(pdf_bytes: bytes):
    if convert_from_bytes is None:
        return ""
    pages = convert_from_bytes(pdf_bytes, dpi=250)
    texts = []
    for p in pages[:5]:  # safety cap
        text, _ = ocr_image(p)
        texts.append(text)
    return "\n".join(texts)

def split_ingredientish(text: str):
    parts = re.split(r"[,;/\n\r]+", text)
    clean = []
    for p in parts:
        t = re.sub(r"\s+", " ", p).strip()
        if len(t) >= 3:
            clean.append(t)
    return clean

def search_from_text(text: str, per_term_limit: int = 6, overall_limit: int = 30):
    ids = {}
    for term in split_ingredientish(text.lower()):
        if term in ("ingredient", "ingredients"):
            continue
        for hit in search_ingredients(term, limit=per_term_limit):
            ids[hit["id"]] = hit
        if "fragrance" in term or "parfum" in term:
            for k in ("linalool", "limonene", "citral", "eugenol", "benzyl salicylate", "benzyl benzoate"):
                for hit in search_ingredients(k, limit=2):
                    ids[hit["id"]] = hit
        if "paraben" in term:
            for k in ("methylparaben","propylparaben","butylparaben","ethylparaben","isobutylparaben","isopropylparaben"):
                for hit in search_ingredients(k, limit=1):
                    ids[hit["id"]] = hit
    return list(ids.values())[:overall_limit]


# --------------------
# UI (single-box cards)
# --------------------

st.set_page_config(page_title="Toxic Ingredients Indicator", layout="wide")

st.markdown("""
<style>
.card { background:#ffffff; border:1px solid #ddd; border-radius:16px; padding:16px 18px; margin:12px 0; color:#111; }
.badge { display:inline-block; padding:4px 10px; border-radius:999px; font-size:0.85rem; font-weight:600; }
.bg-red-200 {background:#fecaca;} .bg-yellow-200 {background:#fde68a;}
.bg-green-200 {background:#bbf7d0;} .bg-gray-200 {background:#e5e7eb;}
.meta { color:#333; font-size:0.92rem; }
.h1 { font-size:2.2rem; font-weight:800; }
.summary-card {
    background: linear-gradient(135deg, #1e1e2e 0%, #2a1a3e 100%);
    border: 1px solid #7c3aed; border-radius: 16px;
    padding: 20px 24px; margin: 16px 0 24px 0; color: #f0e6ff;
}
.summary-card .summary-title {
    font-size: 1rem; font-weight: 700; color: #a78bfa;
    text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 10px;
}
.summary-card .summary-text { font-size: 1.05rem; line-height: 1.7; color: #ede9fe; }
.explain-box {
    background: #f5f3ff; border-left: 3px solid #7c3aed;
    border-radius: 0 8px 8px 0; padding: 10px 14px;
    margin: 4px 0 12px 0; color: #3b0764; font-size: 0.95rem; line-height: 1.6;
}
.risk-bar {
    display: flex; gap: 8px; margin: 16px 0 8px 0;
    align-items: center; flex-wrap: wrap; font-size: 0.85rem; color: #888;
}
</style>
""", unsafe_allow_html=True)

st.markdown("<div class='h1'>🧪 Toxic Ingredients Indicator</div>", unsafe_allow_html=True)

ensure_fts_prefix()

with st.sidebar:
    st.header("Input")
    mode = st.radio("Choose input type:", ["Search text", "Upload image"], index=0)
    if pytesseract is None or Image is None:
        st.caption("For OCR: install `pytesseract` and `Pillow` in your venv.")
    if convert_from_bytes is None:
        st.caption("For PDFs: install `pdf2image` and Poppler.")

results = st.session_state.get("results", [])

if mode == "Search text":
    q = st.text_input("Ingredient / CAS / alias", help="Type and press Enter (partial words OK, e.g., 'paraben').")
    if q:
        results = search_ingredients(q)
        st.session_state["results"] = results

elif mode == "Paste text":
    txt = st.text_area("Paste any text (ingredients list, label, etc.)", height=160, key="paste_txt")
    go = st.button("Analyze text", type="primary", key="analyze_paste")
    if go and txt.strip():
        try:
            results = search_from_text(txt)
            st.session_state["results"] = results
        except Exception as e:
            st.error(f"Search failed: {e}")

elif mode == "Upload image":
    import base64

    st.caption("📸 **Tips:** Get close so ingredients fill the frame. Good lighting, no shadows, hold steady.")

    f = st.file_uploader("Upload a label photo (PNG/JPG)", type=["png","jpg","jpeg"])

    if f is not None and Image is not None:
        file_key = f"{f.name}_{f.size}"

        if st.session_state.get("raw_file_key") != file_key:
            raw_bytes  = f.read()
            image_full = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
            st.session_state.update({
                "raw_file_key":         file_key,
                "full_image":           image_full,
                "rotation":             0,
                "crop_coords":          None,
                "pending_crop_coords":  None,
                "ocr_extracted":        None,
                "ocr_low_res":          False,
                "results":              [],
            })

        col1, col2, _ = st.columns([1, 1, 5])
        with col1:
            if st.button("↺ Rotate Left", key="rot_left"):
                st.session_state["rotation"]      = (st.session_state.get("rotation", 0) - 90) % 360
                st.session_state["crop_coords"]   = None
                st.session_state["ocr_extracted"] = None
        with col2:
            if st.button("Rotate Right ↻", key="rot_right"):
                st.session_state["rotation"]      = (st.session_state.get("rotation", 0) + 90) % 360
                st.session_state["crop_coords"]   = None
                st.session_state["ocr_extracted"] = None

        rotation   = st.session_state.get("rotation", 0)
        full_image = st.session_state["full_image"]
        rot_map    = {90: -90, 180: 180, 270: 90}
        working    = full_image.rotate(rot_map[rotation], expand=True) if rotation else full_image

        img_w, img_h = working.size

        st.markdown("**Step 1 — Draw a box around the ingredients, then click Confirm Crop:**")

        max_w      = 560
        disp_scale = min(1.0, max_w / img_w)
        disp_w     = int(img_w * disp_scale)
        disp_h     = int(img_h * disp_scale)
        disp_img   = working.resize((disp_w, disp_h), Image.LANCZOS)
        buf        = io.BytesIO()
        disp_img.save(buf, format="PNG")
        b64        = base64.b64encode(buf.getvalue()).decode()
        inv_scale  = round(1.0 / disp_scale, 8)

        qp = st.query_params
        qp_crop = qp.get("crop", "")
        if qp_crop and qp_crop.count(",") == 3:
            try:
                vals = [int(v) for v in qp_crop.split(",")]
                if vals[2]-vals[0] > 20 and vals[3]-vals[1] > 20:
                    st.session_state["pending_crop_coords"] = tuple(vals)
            except Exception:
                pass

        pending_crop = st.session_state.get("pending_crop_coords")
        crop_coords  = st.session_state.get("crop_coords")

        crop_html = f"""
<div style="position:relative;display:inline-block;user-select:none;touch-action:none;max-width:100%;">
  <img id="cImg" src="data:image/png;base64,{b64}"
       style="display:block;max-width:100%;border:2px solid #555;border-radius:8px;"
       draggable="false"/>
  <canvas id="cCvs" style="position:absolute;top:0;left:0;pointer-events:all;cursor:crosshair;border-radius:8px;"></canvas>
</div>
<br>
<button onclick="doConfirm()" style="background:#e53935;color:#fff;border:none;padding:10px 24px;border-radius:8px;font-size:1rem;font-weight:700;cursor:pointer;">
  ✂️ Confirm Crop
</button>
<span id="cStatus" style="color:#aaa;font-size:0.85rem;margin-left:10px;">Draw a box over the ingredients</span>
<div id="cResult" style="margin-top:6px;font-size:0.9rem;color:#4ade80;font-weight:600;min-height:1.2em;"></div>
<script>
(function(){{
  const img=document.getElementById('cImg'),cvs=document.getElementById('cCvs');
  const ctx=cvs.getContext('2d'),status=document.getElementById('cStatus'),result=document.getElementById('cResult');
  let sx,sy,ex,ey,drawing=false;
  function sync(){{cvs.width=img.offsetWidth;cvs.height=img.offsetHeight;}}
  img.onload=sync; setTimeout(sync,200); setTimeout(sync,700);
  window.addEventListener('resize',sync);
  function pos(e){{const r=cvs.getBoundingClientRect(),s=e.touches?e.touches[0]:e;return{{x:s.clientX-r.left,y:s.clientY-r.top}};}}
  function redraw(){{
    ctx.clearRect(0,0,cvs.width,cvs.height); if(sx==null) return;
    const x=Math.min(sx,ex),y=Math.min(sy,ey),w=Math.abs(ex-sx),h=Math.abs(ey-sy);
    ctx.fillStyle='rgba(0,0,0,0.45)'; ctx.fillRect(0,0,cvs.width,cvs.height);
    ctx.clearRect(x,y,w,h); ctx.strokeStyle='#e53935'; ctx.lineWidth=2.5; ctx.strokeRect(x,y,w,h);
  }}
  cvs.addEventListener('mousedown',e=>{{const p=pos(e);sx=ex=p.x;sy=ey=p.y;drawing=true;redraw();}});
  cvs.addEventListener('mousemove',e=>{{if(!drawing)return;const p=pos(e);ex=p.x;ey=p.y;redraw();}});
  cvs.addEventListener('mouseup',()=>{{drawing=false;status.textContent='Box drawn — click Confirm Crop';}});
  cvs.addEventListener('touchstart',e=>{{e.preventDefault();const p=pos(e);sx=ex=p.x;sy=ey=p.y;drawing=true;redraw();}},{{passive:false}});
  cvs.addEventListener('touchmove',e=>{{e.preventDefault();if(!drawing)return;const p=pos(e);ex=p.x;ey=p.y;redraw();}},{{passive:false}});
  cvs.addEventListener('touchend',()=>{{drawing=false;status.textContent='Box drawn — click Confirm Crop';}});
  window.doConfirm=function(){{
    if(sx==null){{status.textContent='⚠️ Draw a box first!';return;}}
    const actualW=img.offsetWidth, actualH=img.offsetHeight;
    const scaleX={img_w}/actualW, scaleY={img_h}/actualH;
    const x1=Math.round(Math.min(sx,ex)*scaleX),y1=Math.round(Math.min(sy,ey)*scaleY);
    const x2=Math.round(Math.max(sx,ex)*scaleX),y2=Math.round(Math.max(sy,ey)*scaleY);
    const val=x1+','+y1+','+x2+','+y2;
    try {{ localStorage.setItem('st_crop_coords', val); }} catch(e) {{}}
    try {{ window.parent.postMessage({{type:'st_crop',val:val}}, '*'); }} catch(e) {{}}
    try {{
      const url=new URL(window.parent.location.href);
      url.searchParams.set('crop', val);
      window.parent.history.replaceState(null,'',url.toString());
    }} catch(e) {{}}
    result.textContent='✅ ('+x1+','+y1+') → ('+x2+','+y2+') — click Apply Crop below ↓';
    status.textContent='Coordinates saved! ✓';
  }};
}})();
</script>
"""
        st.components.v1.html(crop_html, height=disp_h + 110, scrolling=False)

        bridge_html = """
<script>
(function(){
  var last = null;
  function tryWrite(val) {
    if (!val || val === last) return;
    last = val;
    try {
      var pdoc = window.parent.document;
      var setter = Object.getOwnPropertyDescriptor(window.parent.HTMLInputElement.prototype, 'value').set;
      var inputs = pdoc.querySelectorAll('input[type="text"]');
      if (inputs.length > 0) {
        var inp = inputs[inputs.length - 1];
        setter.call(inp, val);
        inp.dispatchEvent(new Event('input', {bubbles: true}));
      }
    } catch(e) {}
    try {
      var url = new URL(window.parent.location.href);
      url.searchParams.set('crop', val);
      window.parent.history.replaceState(null, '', url.toString());
    } catch(e) {}
  }
  setInterval(function() {
    try {
      var v = localStorage.getItem('st_crop_coords');
      if (v) tryWrite(v);
    } catch(e) {}
  }, 500);
})();
</script>
"""
        st.components.v1.html(bridge_html, height=0, scrolling=False)
        coord_str = st.text_input("coords", value="", key="crop_str",
                                  label_visibility="collapsed")
        if coord_str and coord_str.count(",") == 3:
            try:
                vals = [int(v) for v in coord_str.split(",")]
                if vals[2]-vals[0] > 20 and vals[3]-vals[1] > 20:
                    st.session_state["pending_crop_coords"] = tuple(vals)
            except Exception:
                pass

        col_a, col_b = st.columns([1, 3])
        with col_a:
            if st.button("✅ Apply Crop", key="apply_crop", type="primary"):
                fresh_crop = st.query_params.get("crop", "") or coord_str
                pending = st.session_state.get("pending_crop_coords")
                if pending:
                    st.session_state["crop_coords"]   = pending
                    st.session_state["ocr_extracted"] = None
                    st.rerun()
                elif fresh_crop and fresh_crop.count(",") == 3:
                    try:
                        vals = [int(v) for v in fresh_crop.split(",")]
                        if vals[2]-vals[0] > 20 and vals[3]-vals[1] > 20:
                            st.session_state["crop_coords"]         = tuple(vals)
                            st.session_state["pending_crop_coords"] = tuple(vals)
                            st.session_state["ocr_extracted"]       = None
                            st.rerun()
                    except Exception:
                        pass
                st.warning("Draw a box on the image above, click Confirm Crop, then Apply Crop.")
        with col_b:
            if st.button("✖ Clear / use full image", key="clear_crop"):
                st.session_state["crop_coords"]         = None
                st.session_state["pending_crop_coords"] = None
                st.session_state["ocr_extracted"]       = None
                st.query_params.clear()
                st.rerun()

        crop_coords = st.session_state.get("crop_coords")
        if crop_coords:
            st.success(f"✅ Crop applied: {crop_coords}")
            st.image(working.crop(crop_coords), width=400)
        elif pending_crop:
            st.info("👁 Preview ready — click Apply Crop to confirm")
            st.image(working.crop(pending_crop), width=400)
        else:
            st.caption("No crop — full image will be used for OCR.")

        st.markdown("**Step 2 — Run OCR:**")
        ocr_col1, ocr_col2 = st.columns([1, 1])
        with ocr_col1:
            run_tesseract = st.button("▶ Run OCR (Tesseract)", type="primary", key="run_ocr_btn")
        with ocr_col2:
            run_vision = st.button(
                "🤖 Run OCR (Gemini Vision)", key="run_vision_btn",
                disabled=not bool(_gemini_key()),
                help="Uses Gemini AI — better on dark or curved labels"
                     if _gemini_key() else "Add GEMINI_API_KEY to secrets.toml to enable"
            )

        if run_tesseract:
            ocr_input = working.crop(crop_coords) if crop_coords else working
            with st.spinner("Running Tesseract OCR…"):
                extracted, is_low_res = ocr_image(ocr_input)
            st.session_state.update({
                "ocr_extracted": extracted,
                "ocr_low_res": is_low_res,
                "ocr_source": "tesseract"
            })
            st.rerun()

        if run_vision:
            ocr_input = working.crop(crop_coords) if crop_coords else working
            with st.spinner("Asking Gemini to read the label…"):
                vision_text = gemini_vision_ocr(ocr_input)
                tess_text, is_low_res = ocr_image(ocr_input)
                def _wc(t): return len([w for w in t.split() if len(w) >= 4])
                if vision_text and _wc(vision_text) >= _wc(tess_text):
                    best, source = vision_text, "gemini"
                else:
                    best, source = tess_text, "tesseract"
                    if not vision_text:
                        st.warning("Gemini Vision couldn't find an ingredients list — using Tesseract.")
            st.session_state.update({
                "ocr_extracted": best,
                "ocr_low_res": False,
                "ocr_source": source
            })
            st.rerun()

        extracted  = st.session_state.get("ocr_extracted") or ""
        is_low_res = st.session_state.get("ocr_low_res", False)
        ocr_source = st.session_state.get("ocr_source", "tesseract")

        if extracted:
            if is_low_res:
                st.warning("⚠️ Low resolution — results may be imperfect.")
            src_label = "🤖 Gemini Vision" if ocr_source == "gemini" else "📄 Tesseract"
            st.caption(f"OCR source: {src_label}")
            st.markdown("**Step 3 — Review text, edit if needed, then Analyze:**")
            if _gemini_key():
                if st.button("✨ Fix OCR errors with AI", key="fix_ocr_btn",
                             help="Gemini corrects garbled INCI names and letter/number swaps"):
                    with st.spinner("Fixing OCR errors…"):
                        cleaned = gemini_clean_ocr(extracted)
                    if cleaned != extracted:
                        st.session_state["ocr_extracted"] = cleaned
                        st.success("✅ OCR text corrected by Gemini")
                        st.rerun()
                    else:
                        st.info("No corrections needed — text looks clean.")
            txt = st.text_area("OCR text (edit if needed)", extracted, height=160, key="ocr_img_txt")
            if st.button("🔍 Analyze", type="primary", key="analyze_img"):
                try:
                    results = search_from_text(txt)
                    st.session_state["results"] = results
                    st.rerun()
                except Exception as e:
                    st.error(f"Search failed: {e}")


# --------- render results ---------
if results:

    # Enrich and sort high → low
    enriched = []
    for r in results:
        ing_id   = r["id"]
        name     = r["name"]
        cas      = r.get("cas_number") or "—"
        hz       = hazards_for(ing_id)
        fam      = family_for(name, hz)
        sev_vals = [h["severity"] for h in hz if h.get("severity") is not None]
        max_sev  = max(sev_vals) if sev_vals else 0
        risk_txt, risk_cls = risk_label(max_sev if sev_vals else None)
        enriched.append({
            "id": ing_id, "name": name, "cas": cas,
            "hz": hz, "fam": fam, "max_sev": max_sev,
            "risk": risk_txt, "risk_cls": risk_cls,
            "why": harm_one_liner(name, hz),
            "srcs": sources_inline(hz),
        })
    enriched.sort(key=lambda x: x["max_sev"], reverse=True)

    # Product summary — cached per result set
    current_hash = str(sorted([r["name"] for r in enriched]))
    if st.session_state.get("_results_hash") != current_hash:
        st.session_state["_results_hash"]   = current_hash
        st.session_state["_gemini_summary"] = None
    if _gemini_key() and st.session_state.get("_gemini_summary") is None:
        with st.spinner("Generating AI product summary…"):
            _summary = gemini_product_summary(enriched) or ""
            # Only cache complete responses — incomplete ones stay None and retry on next render
            if _summary and _summary[-1] in ".!?":
                st.session_state["_gemini_summary"] = _summary
            else:
                st.session_state["_gemini_summary"] = None
    summary_text = st.session_state.get("_gemini_summary", "")

    # Stats
    high_ct   = sum(1 for r in enriched if r["max_sev"] >= 4)
    medium_ct = sum(1 for r in enriched if 2 <= r["max_sev"] < 4)
    low_ct    = sum(1 for r in enriched if r["max_sev"] < 2)
    total     = len(enriched)
    top_sev   = enriched[0]["max_sev"] if enriched else 0
    overall_risk, _ = risk_label(top_sev if top_sev else None)

    st.subheader(f"Results — {total} ingredient{'s' if total != 1 else ''} flagged")

    st.markdown(f"""
    <div class="risk-bar">
        <span style="background:#fecaca;padding:3px 10px;border-radius:999px;color:#111;font-weight:600;">⛔ {high_ct} High</span>
        <span style="background:#fde68a;padding:3px 10px;border-radius:999px;color:#111;font-weight:600;">⚠️ {medium_ct} Medium</span>
        <span style="background:#bbf7d0;padding:3px 10px;border-radius:999px;color:#111;font-weight:600;">✅ {low_ct} Low</span>
        <span style="margin-left:auto;">Overall: <b>{overall_risk} risk</b></span>
    </div>
    """, unsafe_allow_html=True)

    # Summary card
    if summary_text:
        st.markdown(f"""
        <div class="summary-card">
            <div class="summary-title">🤖 AI Product Summary</div>
            <div class="summary-text">{summary_text}</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        top_name = enriched[0]["name"] if enriched else ""
        st.markdown(f"""
        <div class="summary-card">
            <div class="summary-title">📋 Product Summary</div>
            <div class="summary-text">
                Found <b>{total} flagged ingredient{'s' if total != 1 else ''}</b>.
                {f'Most concerning: <b>{top_name}</b> ({enriched[0]["risk"]} risk).' if enriched else ''}
                {f'{high_ct} high-risk, {medium_ct} medium-risk, {low_ct} low-risk.' if total > 1 else ''}
                Sorted highest to lowest concern below.
            </div>
        </div>
        """, unsafe_allow_html=True)

    # Ingredient cards with explainer
    for i, r in enumerate(enriched):
        cache_key = "_expl_" + re.sub(r"[^a-z0-9]", "_", r["name"].lower())

        st.markdown(f"""
        <div class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <div style="font-weight:700;font-size:1.25rem;">{r['name']}</div>
            <span class="badge {r['risk_cls']}">{r['risk']} risk</span>
          </div>
          <div class="meta" style="margin-top:6px;">
            <b>CAS:</b> {r['cas']} &nbsp;•&nbsp; <b>Family:</b> {r['fam']}
          </div>
          <div style="margin-top:10px;">{r['why']}</div>
          <div class="meta" style="margin-top:8px;">{('Sources: ' + r['srcs']) if r['srcs'] else ''}</div>
        </div>
        """, unsafe_allow_html=True)

        if _gemini_key():
            existing = st.session_state.get(cache_key)
            if st.button("💬 Explain this to me", key=f"explain_{i}"):
                if not existing:
                    with st.spinner(f"Explaining {r['name']}…"):
                        existing = gemini_explain_ingredient(
                            r["name"], r["risk"], r["fam"], r["why"]
                        )
            if existing:
                st.markdown(f"""
                <div class="explain-box">💡 {existing}</div>
                """, unsafe_allow_html=True)

else:
    st.info("Enter a query, paste text, or upload an image/PDF to see results.")