# app.py
# -----------------------------------------------------------------------------
# Aplicativo Flask estilo "Collectr" — versão sem precificação automática
# - Buscar cartas (com auto-import por número X/Y)
# - Coleção: adicionar (merge por atributos), editar, remover 1 a 1, mesclar duplicados
# - Wishlist
# - Exportações CSV
# - Seed de exemplo
# - Endpoints manuais de histórico de preços (para registrar valores que você inserir)
# - Usa banco em `instance/` e, se existir, PRIORIZA `collectr.db`
# -----------------------------------------------------------------------------

from __future__ import annotations

import os
import re
from datetime import datetime
from io import StringIO
import csv
from typing import Optional, Iterable, Dict, Any, List, Tuple

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
    abort,
    Response,
)
from sqlalchemy import func, distinct, or_

from config import Config
from db import (
    db,
    Set,
    Card,
    CollectionItem,
    WishlistItem,
    PriceHistory,
    kpi_total_items,
    kpi_unique_cards,
    kpi_wishlist_count,
    kpi_total_estimated_value,
)
from pokemontcg_import import (
    import_by_print_number,
    import_by_name,
    import_hybrid,
    import_set,
    ensure_single_by_number,
)
from services.pricing import scrape_and_price
from services.search import search_cards

_NUMBER_RE = re.compile(r'^\s*\d+(?:\s*/\s*\d+)?\s*$')


def _normalize_print_number(raw: str) -> str:
    if not raw:
        return ""
    text = raw.strip()
    return re.sub(r"\s*/\s*", "/", text)



# ---------- Busca: normalização e parsing ----------
_WORD_RE = re.compile(r"[A-Za-zÀ-ÿ0-9]+")
_SET_CODE_RE = re.compile(r"^(?:[a-z]{2}\d{1,2}|base\d+)$", re.I)

def _strip_accents(s: str) -> str:
    import unicodedata
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')

def _tokenize(s: str):
    s = (s or '').strip()
    raw = [t for t in _WORD_RE.findall(s)]
    norm = [_strip_accents(t).lower() for t in raw]
    return raw, norm

def _parse_search_query(q: str):
    """Decompõe a pesquisa em (number, set_code, name_tokens)"""
    q = (q or '').strip()
    if not q:
        return None, None, []
    number = None; set_code = None
    # detecta número X/Y ou X
    if _NUMBER_RE.match(q):
        number = re.sub(r"\s*/\s*", "/", q).strip()
    # tenta detectar set code
    parts = q.split()
    for p in parts:
        if _SET_CODE_RE.match(p):
            set_code = p.lower()
            break
    return number, set_code, parts



def _get_float(value: Optional[str]) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _set_release_key(s: Optional[Set]) -> Tuple[int, int, int]:
    d = getattr(s, "release_date", None)
    if not d:
        return (1900, 1, 1)
    return (d.year, d.month, d.day)


def _resolve_db_uri_for_instance(app: Flask) -> Tuple[str, Optional[str]]:
    """
    Resolve a URI de banco priorizando a pasta `instance/`.

    Ordem:
      1) Se DB_URL/DATABASE_URL/SQLALCHEMY_DATABASE_URI vier com esquema (ex.: sqlite:///C:/..., postgres://),
         usa como está.
      2) Se vier um caminho simples/relativo (ex.: 'collectr.db' ou 'poke_market.db'), coloca dentro de `instance/`.
      3) Se nada vier:
           - se existir `instance/collectr.db`, usa ELE (compatibilidade com seu banco antigo);
           - senão, usa `instance/poke_market.db`.

    Retorna (db_uri, db_file) — db_file só vem preenchido quando for sqlite local.
    """
    env_db = (
        os.getenv("DB_URL")
        or os.getenv("DATABASE_URL")
        or os.getenv("SQLALCHEMY_DATABASE_URI")
        or ""
    ).strip()

    # Caso 1: já é URI com esquema
    if env_db and "://" in env_db:
        uri = env_db.replace("\\", "/") if env_db.lower().startswith("sqlite:") else env_db
        db_file = None
        if uri.lower().startswith("sqlite:///"):
            # tenta extrair caminho local para debug/exists
            db_file = uri.replace("sqlite:///", "")
        return uri, db_file

    # Garante pasta instance/
    os.makedirs(app.instance_path, exist_ok=True)

    # Caso 2: veio um caminho simples?
    if env_db:
        db_file = os.path.join(app.instance_path, env_db)
        return "sqlite:///" + db_file.replace("\\", "/"), db_file

    # Caso 3: nada no ambiente → preferir collectr.db se existir
    collectr = os.path.join(app.instance_path, "collectr.db")
    poke = os.path.join(app.instance_path, "poke_market.db")
    chosen = collectr if os.path.exists(collectr) else poke
    return "sqlite:///" + chosen.replace("\\", "/"), chosen


def create_app() -> Flask:
    # Importante: habilita pasta `instance/`
    app = Flask(__name__, instance_relative_config=True)

    # Carrega config base
    app.config.from_object(Config)

    # Força DB dentro da pasta `instance/` (ou respeita URL absoluta)
    db_uri, db_file = _resolve_db_uri_for_instance(app)
    app.config["SQLALCHEMY_DATABASE_URI"] = db_uri
    # Ajustes de engine para sqlite local
    if db_uri.lower().startswith("sqlite:"):
        app.config.setdefault("SQLALCHEMY_ENGINE_OPTIONS", {})
        app.config["SQLALCHEMY_ENGINE_OPTIONS"].setdefault(
            "connect_args", {"check_same_thread": False, "timeout": 15}
        )

    # Inicializa DB
    db.init_app(app)

    with app.app_context():
        # Garante que a pasta do arquivo sqlite exista
        if db_file:
            os.makedirs(os.path.dirname(db_file), exist_ok=True)
        db.create_all()
        from services.search import ensure_card_tokens
        ensure_card_tokens()

    # -------------------------------------------------------------------------
    # Debug do banco
    # -------------------------------------------------------------------------
    @app.get("/debug/dbinfo")
    def debug_dbinfo():
        try:
            sets_ct = Set.query.count()
            cards_ct = Card.query.count()
            coll_ct = CollectionItem.query.count()
        except Exception as e:
            return jsonify({"ok": False, "error": str(e), "db_uri": app.config.get("SQLALCHEMY_DATABASE_URI"), "instance_path": app.instance_path}), 500

        return jsonify({
            "ok": True,
            "db_uri": app.config.get("SQLALCHEMY_DATABASE_URI"),
            "instance_path": app.instance_path,
            "db_exists": bool(db_file and os.path.exists(db_file)),
            "db_file": db_file,
            "counts": {"sets": sets_ct, "cards": cards_ct, "collection_items": coll_ct},
        })

    # -------------------------------------------------------------------------
    # Dashboard
    # -------------------------------------------------------------------------
    @app.route("/")
    def index():
        total_items = kpi_total_items()
        unique_cards = kpi_unique_cards()
        wishlist_count = kpi_wishlist_count()
        total_value = kpi_total_estimated_value()

        sets = Set.query.order_by(Set.release_date.desc()).all()
        progress = []
        for s in sets:
            set_total = (
                db.session.query(func.count(Card.id)).filter(Card.set_id == s.id).scalar()
                or 0
            )
            owned_distinct = (
                db.session.query(func.count(distinct(CollectionItem.card_id)))
                .join(Card, Card.id == CollectionItem.card_id)
                .filter(Card.set_id == s.id)
                .scalar()
                or 0
            )
            pct = int((owned_distinct / set_total) * 100) if set_total else 0
            progress.append({"set": s, "owned": owned_distinct, "total": set_total, "pct": pct})

        recent = (
            CollectionItem.query.order_by(CollectionItem.created_at.desc())
            .limit(8)
            .all()
        )

        return render_template(
            "index.html",
            total_itens=total_items,
            unique_cards=unique_cards,
            wishlist_count=wishlist_count,
            total_value=total_value,
            progress=progress,
            recent=recent,
        )

    # -------------------------------------------------------------------------
    # Buscar cartas (catálogo local + auto-import por número/nome)
    # -------------------------------------------------------------------------
    @app.route("/cards")
    def cards():
        q = (request.args.get("q") or "").strip()
        set_id = (request.args.get("set_id") or "").strip()
        rarity = (request.args.get("rarity") or "").strip()
        only_missing = (request.args.get("only_missing") == "on")
        results = search_cards(q, set_id=set_id, rarity=rarity)

        # -------------------------
        # Auto-import quando vazio
        # -------------------------
        if (not results) and q:
            if _NUMBER_RE.match(q):
                # Importa por número (suporta "X/Y" e "X")
                number = _normalize_print_number(q)

                # Se o usuário já escolheu um set na UI, tente restringir
                chosen_set_code = None
                if set_id:
                    try:
                        s = db.session.get(Set, int(set_id))
                        chosen_set_code = getattr(s, "code", None)
                    except Exception:
                        pass

                imported = import_by_print_number(number, set_code=chosen_set_code)
                if imported:
                    flash(f"Importadas {len(imported)} carta(s) pelo número {number}.", "info")
                    results = search_cards(q, set_id=set_id, rarity=rarity)
                else:
                    flash(f"Nenhuma carta oficial encontrada para o número {number}.", "warning")

            else:
                # Importa por nome (com suporte a "set_code" embutido no texto, ex.: "Psyduck sm9")
                _number, set_code_hint, _parts = _parse_search_query(q)

                # Se o usuário escolheu set no seletor, isso tem prioridade sobre o hint do texto
                chosen_set_code = None
                if set_id:
                    try:
                        s = db.session.get(Set, int(set_id))
                        chosen_set_code = getattr(s, "code", None)
                    except Exception:
                        pass
                if not chosen_set_code:
                    chosen_set_code = set_code_hint

                imported = import_by_name(q, set_code=chosen_set_code, limit=60)
                if imported:
                    flash(f"Importadas {len(imported)} carta(s) pelo nome '{q}'.", "info")
                    results = search_cards(q, set_id=set_id, rarity=rarity)
                else:
                    flash(f"Nenhuma carta oficial encontrada pelo nome '{q}'.", "warning")

        # Apenas não possuídas (aplica no final, para funcionar tanto com local quanto após import)
        if only_missing and results:
            owned_ids = {
                cid for (cid,) in db.session.query(distinct(CollectionItem.card_id)).all()
            }
            results = [c for c in results if c.id not in owned_ids]

        # Dados para os selects de filtro
        sets = Set.query.order_by(Set.release_date.desc()).all()
        rarities = [
            r[0]
            for r in db.session.query(distinct(Card.rarity)).filter(Card.rarity.isnot(None)).all()
        ]

        return render_template(
            "fontes.html",
            results=results,
            sets=sets,
            rarities=rarities,
            q=q,
            set_id=set_id,
            rarity=rarity,
            only_missing=only_missing,
        )


    # -------------------------------------------------------------------------
    # Coleção
    # -------------------------------------------------------------------------
    def _merge_add_collection_item(
        *,
        card_id: int,
        qty: int,
        condition: str,
        purchase_price: Optional[float],
        last_price: Optional[float],
        grade: Optional[str] = None,
        location: Optional[str] = None,
    ) -> CollectionItem:
        """
        Se já existir um CollectionItem com (card_id, condition, grade, location),
        soma a quantidade e atualiza preços:
        - purchase_price: média ponderada (se informado agora)
        - last_price: substitui se informado agora
        """
        condition = (condition or "NM").strip() or "NM"
        grade = (grade or None)
        location = (location or None)

        existing = (
            CollectionItem.query.filter_by(
                card_id=card_id,
                condition=condition,
                grade=grade,
                location=location,
            )
            .order_by(CollectionItem.created_at.asc())
            .first()
        )

        if existing:
            before_qty = existing.quantity or 0
            add_qty = max(1, qty)
            after_qty = before_qty + add_qty
            if purchase_price is not None:
                if existing.purchase_price is None:
                    new_avg = purchase_price
                else:
                    new_avg = (
                        (existing.purchase_price * before_qty) + (purchase_price * add_qty)
                    ) / max(1, after_qty)
                existing.purchase_price = round(new_avg, 2)
            if last_price is not None:
                existing.last_price = last_price

            existing.quantity = after_qty
            db.session.flush()
            return existing

        item = CollectionItem(
            card_id=card_id,
            quantity=max(1, qty),
            condition=condition,
            grade=grade,
            location=location,
            purchase_price=purchase_price,
            last_price=last_price,
        )
        db.session.add(item)
        db.session.flush()
        return item

    @app.post("/collection/add")
    def collection_add():
        data = request.get_json(silent=True) or request.form

        card_id_raw = data.get("card_id")
        number_raw = data.get("number") or data.get("print_number")
        set_code = (data.get("set_code") or "").strip() or None

        target_card: Optional[Card] = None

        if card_id_raw not in (None, ""):
            try:
                cid = int(card_id_raw)
            except (TypeError, ValueError):
                abort(400, "card_id inválido.")
            target_card = db.session.get(Card, cid)
            if not target_card:
                abort(404, "Carta não encontrada pelo card_id informado.")
        else:
            if not number_raw:
                abort(400, "Informe 'card_id' ou 'number' (ex.: 65/82).")
            number = _normalize_print_number(number_raw)

            if set_code:
                # join correto entre Card e Set
                target_card = (
                    Card.query.join(Set, Card.set_id == Set.id)
                    .filter(
                        Card.number == (number.split("/")[0] if "/" in number else number),
                        Set.code == set_code,
                    )
                    .first()
                )
                if not target_card:
                    import_by_print_number(number, set_code=set_code)
                    target_card = (
                        Card.query.join(Set, Card.set_id == Set.id)
                        .filter(
                            Card.number == (number.split("/")[0] if "/" in number else number),
                            Set.code == set_code,
                        )
                        .first()
                    )
                    if not target_card:
                        import_set(set_code)
                        target_card = (
                            Card.query.join(Set, Card.set_id == Set.id)
                            .filter(
                                Card.number == (number.split("/")[0] if "/" in number else number),
                                Set.code == set_code,
                            )
                            .first()
                        )
                if not target_card:
                    abort(404, f"Carta {number} não encontrada no set {set_code}.")
            else:
                target_card = ensure_single_by_number(number)
                if not target_card:
                    abort(404, f"Nenhuma carta encontrada para o número {number}.")

        qty = int(data.get("quantity", 1) or 1)
        qty = max(1, qty)
        condition = (data.get("condition") or "NM").strip() or "NM"
        purchase_price = _get_float(data.get("purchase_price"))
        last_price = _get_float(data.get("last_price"))

        item = _merge_add_collection_item(
            card_id=target_card.id,
            qty=qty,
            condition=condition,
            purchase_price=purchase_price,
            last_price=last_price,
            grade=None,
            location=None,
        )
        db.session.commit()

        if request.is_json:
            return jsonify({"ok": True, "item": item.as_dict()})
        flash("Carta adicionada à coleção!", "success")
        return redirect(request.referrer or url_for("cards"))

    @app.post("/collection/add-by-number")
    def collection_add_by_number():
        return collection_add()

    @app.get("/collection")
    def collection_list():
        items = CollectionItem.query.order_by(CollectionItem.created_at.desc()).all()
        return render_template("collection.html", items=items)

    @app.post("/collection/update/<int:item_id>")
    def collection_update(item_id: int):
        item = CollectionItem.query.get_or_404(item_id)
        item.quantity = max(0, int(request.form.get("quantity", item.quantity) or item.quantity))
        item.condition = (request.form.get("condition") or item.condition or "NM").strip() or "NM"
        item.grade = (request.form.get("grade") or item.grade or "").strip() or None
        item.location = (request.form.get("location") or item.location or "").strip() or None
        item.last_price = _get_float(request.form.get("last_price"))
        item.purchase_price = _get_float(request.form.get("purchase_price"))

        db.session.commit()
        flash("Item atualizado!", "success")
        return redirect(request.referrer or url_for("collection_list"))

    @app.post("/collection/delete/<int:item_id>")
    def collection_delete(item_id: int):
        """
        Remove por padrão **1 unidade** do item;
        - Envie 'decrement' (ou 'step') para remover outra quantidade.
        - Envie 'all=1' para remover o item inteiro de uma vez.
        """
        item = CollectionItem.query.get_or_404(item_id)
        data = request.get_json(silent=True) or request.form

        remove_all = str(data.get("all", "")).lower() in {"1", "true", "on", "yes"}
        if remove_all:
            db.session.delete(item)
            db.session.commit()
            if request.is_json:
                return jsonify({"ok": True, "deleted": True})
            flash("Item removido da coleção.", "info")
            return redirect(request.referrer or url_for("collection_list"))

        dec_raw = data.get("decrement") or data.get("step") or "1"
        try:
            dec = int(dec_raw)
        except ValueError:
            dec = 1
        dec = max(1, dec)

        if (item.quantity or 0) > dec:
            item.quantity = item.quantity - dec
            db.session.commit()
            if request.is_json:
                return jsonify({"ok": True, "deleted": False, "quantity": item.quantity})
            flash(f"Removidas {dec} unidade(s).", "success")
        else:
            db.session.delete(item)
            db.session.commit()
            if request.is_json:
                return jsonify({"ok": True, "deleted": True})
            flash("Item removido da coleção.", "info")

        return redirect(request.referrer or url_for("collection_list"))

    @app.post("/collection/merge-duplicates")
    def collection_merge_duplicates():
        groups = (
            db.session.query(
                CollectionItem.card_id,
                CollectionItem.condition,
                CollectionItem.grade,
                CollectionItem.location,
                func.count(CollectionItem.id),
                func.sum(CollectionItem.quantity),
            )
            .group_by(
                CollectionItem.card_id,
                CollectionItem.condition,
                CollectionItem.grade,
                CollectionItem.location,
            )
            .having(func.count(CollectionItem.id) > 1)
            .all()
        )

        merged = 0
        for card_id, condition, grade, location, _cnt, _sum_qty in groups:
            base = (
                CollectionItem.query.filter_by(
                    card_id=card_id,
                    condition=condition,
                    grade=grade,
                    location=location,
                )
                .order_by(CollectionItem.created_at.asc())
                .first()
            )
            if not base:
                continue

            others = (
                CollectionItem.query.filter(
                    CollectionItem.id != base.id,
                    CollectionItem.card_id == card_id,
                    CollectionItem.condition == condition,
                    CollectionItem.grade.is_(grade),
                    CollectionItem.location.is_(location),
                ).all()
            )
            if not others:
                continue

            base.quantity = max(0, base.quantity + sum(o.quantity for o in others))
            for o in others:
                db.session.delete(o)
            merged += 1

        db.session.commit()
        if request.is_json:
            return jsonify({"ok": True, "merged_groups": merged})
        flash(f"Mesclagem concluída: {merged} grupo(s) de duplicados unificados.", "success")
        return redirect(request.referrer or url_for("collection_list"))

    # -------------------------------------------------------------------------
    # Wishlist
    # -------------------------------------------------------------------------
    @app.post("/wishlist/add")
    def wishlist_add():
        try:
            card_id = int(request.form["card_id"])
        except (KeyError, ValueError):
            abort(400, "card_id inválido")

        target_price = request.form.get("target_price")
        wi = WishlistItem(card_id=card_id)
        if target_price not in (None, ""):
            try:
                wi.target_price = float(target_price)
            except ValueError:
                pass

        db.session.add(wi)
        db.session.commit()
        flash("Carta adicionada à wishlist!", "success")
        return redirect(request.referrer or url_for("cards"))

    @app.get("/wishlist")
    def wishlist():
        items = WishlistItem.query.order_by(WishlistItem.added_at.desc()).all()
        return render_template("wishlist.html", items=items)

    @app.post("/wishlist/delete/<int:item_id>")
    def wishlist_delete(item_id: int):
        item = WishlistItem.query.get_or_404(item_id)
        db.session.delete(item)
        db.session.commit()
        flash("Removido da wishlist.", "info")
        return redirect(request.referrer or url_for("wishlist"))

    # -------------------------------------------------------------------------
    # Sets e cartas
    # -------------------------------------------------------------------------
    
    # -------------------------------------------------------------------------
    # Detalhe de Set: lista todas as cartas do set com seleção/bulk actions
    # -------------------------------------------------------------------------
    @app.get("/set/<int:set_id>")
    def set_view(set_id: int):
        s = Set.query.get_or_404(set_id)
        cards = Card.query.filter(Card.set_id == set_id).order_by(Card.number.asc()).all()

        owned_ids = {cid for (cid,) in db.session.query(distinct(CollectionItem.card_id)).all()}
        wish_ids = {cid for (cid,) in db.session.query(distinct(WishlistItem.card_id)).all()}

        return render_template(
            "set_detail.html",
            set=s,
            cards=cards,
            owned_ids=owned_ids,
            wish_ids=wish_ids,
        )
    @app.get("/sets")
    def sets_page():
        sets = Set.query.order_by(Set.release_date.desc()).all()
        return render_template("sets.html", sets=sets)

    @app.post("/sets/new")
    def sets_new():
        name = (request.form.get("name") or "").strip()
        if not name:
            abort(400, "Nome do set é obrigatório")

        code = (request.form.get("code") or "").strip() or None
        icon_url = (request.form.get("icon_url") or "").strip() or None

        s = Set(name=name, code=code, icon_url=icon_url)
        db.session.add(s)
        db.session.commit()
        flash("Set criado!", "success")
        return redirect(url_for("sets_page"))

    @app.post("/cards/new")
    def cards_new():
        name = (request.form.get("name") or "").strip()
        if not name:
            abort(400, "Nome da carta é obrigatório")

        try:
            set_id = int(request.form.get("set_id"))
        except (TypeError, ValueError):
            abort(400, "set_id inválido")

        number = (request.form.get("number") or "").strip() or None
        rarity = (request.form.get("rarity") or "").strip() or None
        ctype = (request.form.get("type") or "").strip() or None
        image_url = (request.form.get("image_url") or "").strip() or None

        c = Card(
            name=name,
            set_id=set_id,
            number=number,
            rarity=rarity,
            type=ctype,
            image_url=image_url,
        )

        try:
            db.session.add(c)
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            flash(
                "Não foi possível criar a carta (talvez duplicidade de número no set). "
                f"Detalhe: {exc}",
                "error",
            )
            return redirect(url_for("cards", set_id=set_id))

        flash("Carta criada!", "success")
        return redirect(url_for("cards", set_id=set_id))

    # -------------------------------------------------------------------------
    # API leve (auto-complete / integrações) + Histórico de preços (manual)
    # -------------------------------------------------------------------------
    @app.get("/api/cards")
    def api_cards():
        q = (request.args.get("q") or "").strip()
        query = Card.query
        if q:
            if _NUMBER_RE.match(q):
                number = _normalize_print_number(q)
                query = query.filter(Card.number == (number.split("/")[0] if "/" in number else number))
            else:
                query = query.filter(or_(
                    Card.name.ilike(f"%{q}%"),
                    Card.name_pt.ilike(f"%{q}%"),
                ))
        cards = query.order_by(Card.name.asc()).limit(50).all()
        if (not cards) and q:
            if _NUMBER_RE.match(q):
                number = _normalize_print_number(q)
                query = Card.query.filter(Card.number == (number.split("/")[0] if "/" in number else number))
                cards = query.order_by(Card.name.asc()).limit(50).all()
            else:
                # tenta importar por nome quando não há resultados
                _, set_code, _ = _parse_search_query(q)
                imported = import_by_name(q, set_code=set_code, limit=30)
                if imported:
                    query = Card.query
                    raw, _ = _tokenize(q)
                    for t in raw:
                        query = query.filter(or_(
                            Card.name.ilike(f"%{t}%"),
                            Card.name_pt.ilike(f"%{t}%"),
                        ))
                    cards = query.order_by(Card.name.asc()).limit(50).all()
        
        return jsonify([c.as_dict() for c in cards])

    @app.get("/api/price_history")
    def api_price_history():
        try:
            card_id = int(request.args.get("card_id"))
        except (TypeError, ValueError):
            abort(400, "card_id inválido")

        hist = (
            PriceHistory.query.filter(PriceHistory.card_id == card_id)
            .order_by(PriceHistory.captured_at.desc())
            .limit(100)
            .all()
        )
        return jsonify([h.as_dict() for h in hist])

    @app.get("/api/price_search")
    def api_price_search():
        q = (request.args.get("q") or "").strip()
        if not q:
            abort(400, "parâmetro q obrigatório")
        return jsonify(scrape_and_price(q))

    @app.post("/price/record")
    def price_record():
        """
        Registro manual de histórico de preço.
        Form/JSON:
          - card_id (int), price (float), source (opcional), captured_at (ISO-8601 opcional)
        """
        data = request.get_json(silent=True) or request.form

        try:
            card_id = int(data.get("card_id"))
        except (TypeError, ValueError):
            abort(400, "card_id inválido")

        try:
            price = float(data.get("price"))
        except (TypeError, ValueError):
            abort(400, "price inválido")

        source = (data.get("source") or "").strip() or None
        captured_at_raw: Optional[str] = data.get("captured_at")
        if captured_at_raw:
            try:
                captured_at = datetime.fromisoformat(captured_at_raw)
            except ValueError:
                abort(400, "captured_at deve estar em ISO-8601 (ex.: 2025-08-10T13:45:00)")
        else:
            captured_at = datetime.utcnow()

        card = db.session.get(Card, card_id)
        if not card:
            abort(404, "Carta não encontrada")

        ph = PriceHistory(card_id=card_id, price=price, source=source, captured_at=captured_at)
        db.session.add(ph)
        db.session.commit()

        return jsonify({"ok": True, "price_history": ph.as_dict()})

    @app.post("/price/bulk_record")
    def price_bulk_record():
        """
        Registro manual em lote.
        JSON:
          { "items": [ { "card_id": 1, "price": 12.50, "source": "manual", "captured_at": "2025-08-10T12:00:00" }, ... ] }
        """
        payload = request.get_json(silent=True)
        if not payload or "items" not in payload or not isinstance(payload["items"], list):
            abort(400, "Envie JSON com a lista 'items'.")

        created: List[Dict[str, Any]] = []
        for row in payload["items"]:
            try:
                card_id = int(row.get("card_id"))
                price = float(row.get("price"))
            except Exception:
                continue

            source = (row.get("source") or "").strip() or None
            cat = row.get("captured_at")
            if cat:
                try:
                    captured_at = datetime.fromisoformat(cat)
                except ValueError:
                    captured_at = datetime.utcnow()
            else:
                captured_at = datetime.utcnow()

            if not db.session.get(Card, card_id):
                continue

            ph = PriceHistory(card_id=card_id, price=price, source=source, captured_at=captured_at)
            db.session.add(ph)
            created.append(ph)

        db.session.commit()
        return jsonify({"ok": True, "count": len(created), "items": [c.as_dict() for c in created]})

    # -------------------------------------------------------------------------
    # Export CSV
    # -------------------------------------------------------------------------
    def _csv_response(rows: Iterable[List[Any]], filename: str) -> Response:
        sio = StringIO()
        sio.write("\ufeff")
        writer = csv.writer(sio, lineterminator="\n")
        for r in rows:
            writer.writerow(r)
        data = sio.getvalue()
        return Response(
            data,
            mimetype="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
            },
        )

    
    @app.post("/collection/bulk_add")
    def collection_bulk_add():
        card_ids = request.form.getlist("card_ids")
        if not card_ids:
            flash("Nenhuma carta selecionada.", "warning")
            return redirect(request.referrer or url_for("sets_page"))

        try:
            qty = max(1, int(request.form.get("quantity", "1")))
        except ValueError:
            qty = 1
        condition = (request.form.get("condition") or "NM").strip() or "NM"
        purchase_price = request.form.get("purchase_price")
        last_price = request.form.get("last_price")

        def _f(v):
            try:
                return float(v) if v not in (None, "") else None
            except ValueError:
                return None

        added = 0
        for cid in card_ids:
            try:
                cid_int = int(cid)
            except ValueError:
                continue
            _merge_add_collection_item(
                card_id=cid_int,
                qty=qty,
                condition=condition,
                purchase_price=_f(purchase_price),
                last_price=_f(last_price),
                grade=None,
                location=None,
            )
            added += 1

        db.session.commit()
        flash(f"Adicionadas {added} carta(s) à coleção.", "success")
        return redirect(request.referrer or url_for("collection_list"))

    @app.post("/wishlist/bulk_add")
    def wishlist_bulk_add():
        card_ids = request.form.getlist("card_ids")
        if not card_ids:
            flash("Nenhuma carta selecionada.", "warning")
            return redirect(request.referrer or url_for("sets_page"))

        target_price = request.form.get("target_price")
        try:
            target_price_val = float(target_price) if target_price not in (None, "") else None
        except ValueError:
            target_price_val = None

        added = 0
        for cid in card_ids:
            try:
                cid_int = int(cid)
            except ValueError:
                continue
            wi = WishlistItem(card_id=cid_int)
            if target_price_val is not None:
                wi.target_price = target_price_val
            db.session.add(wi)
            added += 1

        db.session.commit()
        flash(f"Adicionadas {added} carta(s) à wishlist.", "success")
        return redirect(request.referrer or url_for("wishlist"))
    @app.get("/export/sets.csv")
    def export_sets():
        rows = [["id", "name", "code", "release_date", "icon_url", "created_at", "updated_at"]]
        for s in Set.query.order_by(Set.id.asc()).all():
            rows.append([
                s.id, s.name, s.code or "", s.release_date.isoformat() if s.release_date else "",
                s.icon_url or "", s.created_at.isoformat(), s.updated_at.isoformat()
            ])
        return _csv_response(rows, "sets.csv")

    @app.get("/export/cards.csv")
    def export_cards():
        rows = [["id", "set_id", "set_name", "name", "number", "rarity", "type", "image_url", "created_at", "updated_at"]]
        for c in Card.query.order_by(Card.id.asc()).all():
            rows.append([
                c.id, c.set_id, c.set.name if c.set else "", c.name, c.number or "",
                c.rarity or "", c.type or "", c.image_url or "", c.created_at.isoformat(), c.updated_at.isoformat()
            ])
        return _csv_response(rows, "cards.csv")

    @app.get("/export/collection.csv")
    def export_collection():
        rows = [["item_id", "card_id", "card_name", "set_name", "number", "quantity", "condition",
                 "grade", "purchase_price", "last_price", "unit_estimated_value",
                 "total_estimated_value", "location", "notes", "created_at", "updated_at"]]
        items = CollectionItem.query.order_by(CollectionItem.id.asc()).all()
        for i in items:
            rows.append([
                i.id, i.card_id, i.card.name if i.card else "", i.card.set.name if i.card and i.card.set else "",
                i.card.number if i.card and i.card.number else "",
                i.quantity, i.condition, i.grade or "", i.purchase_price if i.purchase_price is not None else "",
                i.last_price if i.last_price is not None else "",
                f"{i.unit_estimated_value:.2f}", f"{i.total_estimated_value:.2f}",
                i.location or "", (i.notes or "").replace("\n", " "),
                i.created_at.isoformat(), i.updated_at.isoformat()
            ])
        return _csv_response(rows, "collection.csv")

    @app.get("/export/wishlist.csv")
    def export_wishlist():
        rows = [["wishlist_id", "card_id", "card_name", "set_name", "number", "target_price", "added_at", "latest_price"]]
        for w in WishlistItem.query.order_by(WishlistItem.id.asc()).all():
            latest = w.card.latest_price() if w.card else None
            rows.append([
                w.id, w.card_id, w.card.name if w.card else "", w.card.set.name if w.card and w.card.set else "",
                w.card.number if w.card and w.card.number else "",
                w.target_price if w.target_price is not None else "",
                w.added_at.isoformat(),
                "" if latest is None else f"{latest:.2f}"
            ])
        return _csv_response(rows, "wishlist.csv")

    # -------------------------------------------------------------------------
    # Seed demo
    # -------------------------------------------------------------------------
    @app.post("/seed/minimal")
    def seed_minimal():
        if Set.query.count() > 0:
            flash("Seed ignorado: já existem dados.", "warning")
            return redirect(url_for("index"))

        base = Set(
            name="Base Set (Demo)",
            code="BASE",
            icon_url="https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/items/poke-ball.png",
        )
        db.session.add(base)
        db.session.flush()

        cards = [
            Card(
                name="Pikachu",
                number="58/102",
                rarity="Common",
                type="Electric",
                image_url="https://images.pokemontcg.io/base1/58_hires.png",
                set_id=base.id,
            ),
            Card(
                name="Charizard",
                number="4/102",
                rarity="Holo Rare",
                type="Fire",
                image_url="https://images.pokemontcg.io/base1/4_hires.png",
                set_id=base.id,
            ),
            Card(
                name="Blastoise",
                number="2/102",
                rarity="Holo Rare",
                type="Water",
                image_url="https://images.pokemontcg.io/base1/2_hires.png",
                set_id=base.id,
            ),
            Card(
                name="Bulbasaur",
                number="44/102",
                rarity="Common",
                type="Grass",
                image_url="https://images.pokemontcg.io/base1/44_hires.png",
                set_id=base.id,
            ),
        ]
        db.session.add_all(cards)
        db.session.flush()

        prices = [
            (cards[0].id, 25.00, "stub"),
            (cards[1].id, 1200.00, "stub"),
            (cards[2].id, 800.00, "stub"),
            (cards[3].id, 15.00, "stub"),
        ]
        for cid, p, src in prices:
            db.session.add(PriceHistory(card_id=cid, price=p, source=src))

        db.session.commit()
        flash("Seed criado! Vá em 'Buscar Cartas' e adicione à coleção.", "success")
        return redirect(url_for("cards"))

    return app


if __name__ == "__main__":
    app = create_app()
    # Mostra no console onde está o banco
    print("[collectr] Using DB:", app.config.get("SQLALCHEMY_DATABASE_URI"))
    print("[collectr] Instance path:", app.instance_path)
    app.run(debug=True)
