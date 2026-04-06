import sqlite3
from contextlib import closing

DB_PATH = "toxic.db"

def _connect():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con

_con = _connect()

def search_fts(query: str, limit: int = 30):
    import sqlite3
    raw = (query or "").strip()
    if not raw:
        return []

    qstar = raw if raw.endswith("*") else raw + "*"
    with closing(_con.cursor()) as cur:
        ids = set()

        # 1) FTS candidates (safe: query only the FTS table)
        try:
            cur.execute(
                "SELECT rowid FROM ingredients_fts WHERE ingredients_fts MATCH ? LIMIT ?;",
                (qstar, limit * 3),
            )
            ids.update([r[0] for r in cur.fetchall()])
        except sqlite3.OperationalError:
            # If user types special chars that FTS dislikes, just skip FTS
            pass

        # 2) Substring fallback on names
        cur.execute(
            "SELECT id FROM ingredients WHERE LOWER(name) LIKE '%'||LOWER(?)||'%' LIMIT ?;",
            (raw, limit * 3),
        )
        ids.update([r[0] for r in cur.fetchall()])

        # 3) Substring fallback on aliases
        cur.execute(
            "SELECT ingredient_id FROM ingredient_aliases "
            "WHERE LOWER(alias) LIKE '%'||LOWER(?)||'%' LIMIT ?;",
            (raw, limit * 3),
        )
        ids.update([r[0] for r in cur.fetchall()])

        if not ids:
            return []

        # Fetch details for the unique ids we found
        id_list = list(ids)[:limit]
        placeholders = ",".join(["?"] * len(id_list))
        cur.execute(
            f"SELECT id, name, cas_number FROM ingredients "
            f"WHERE id IN ({placeholders}) ORDER BY name;",
            id_list,
        )
        return [dict(r) for r in cur.fetchall()]


def ingredient_by_id(ingredient_id: int):
    with closing(_con.cursor()) as cur:
        cur.execute("SELECT id, name, cas_number FROM ingredients WHERE id=?;", (ingredient_id,))
        r = cur.fetchone()
        return dict(r) if r else None

def hazards_for(ingredient_id: int):
    with closing(_con.cursor()) as cur:
        cur.execute("""
            SELECT h.code, h.category, h.description, h.severity,
                   s.name AS source_name, s.url
            FROM ingredient_hazards ih
            JOIN hazards h ON h.id = ih.hazard_id
            LEFT JOIN sources s ON s.id = ih.source_id
            WHERE ih.ingredient_id = ?
            ORDER BY COALESCE(h.severity, 0) DESC, h.category, h.code;
        """, (ingredient_id,))
        return [dict(r) for r in cur.fetchall()]

def all_names_and_aliases():
    # used for text/OCR matching
    with closing(_con.cursor()) as cur:
        cur.execute("""
            SELECT i.id, i.name, i.cas_number,
                   IFNULL((SELECT GROUP_CONCAT(alias, '|||')
                           FROM ingredient_aliases a
                           WHERE a.ingredient_id = i.id),'') AS aliases
            FROM ingredients i;
        """)
        items = []
        for r in cur.fetchall():
            aliases = [a.strip() for a in (r["aliases"] or "").split("|||") if a.strip()]
            items.append({"id": r["id"], "name": r["name"], "cas": r["cas_number"], "aliases": aliases})
        return items

