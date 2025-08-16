# scrapers/ligapokemon.py
import re
import json
import time
from typing import List, Optional, Any, Dict, Iterable
import requests

from .base import BaseScraper, PriceResult

# Observação:
# A Liga Pokémon publica, por edição (edid), um arquivo JS com um array de objetos.
# Exemplos de padrões observados:
#   - new_ed_assoc_tcg_2_ed_{edid} = [{...}, {...}, ...];
#   - var data = [{...}]
# Nem sempre é JSON estrito (pode ter aspas simples e chaves sem aspas).
# O parser abaixo tenta "normalizar" para JSON antes de carregar.

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
    "Accept": "text/javascript, application/javascript, application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Referer": "https://www.ligapokemon.com.br/",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Connection": "keep-alive",
}

BASE_JS = "https://www.lmcorp.com.br/arquivos/up/prod_js/new_ed_assoc_tcg_2_ed_{edid}.js"
SEARCH_HTML = "https://www.ligapokemon.com.br/?view=cards/search&edid={edid}"


def _to_float_brl(value: Any) -> Optional[float]:
    """
    Converte string/number em float (BRL).
    Aceita formatos como 'R$ 1.234,56', '1234,56', 1234.56, '1 234,56'.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        x = float(value)
        return x if x > 0 else None
    s = str(value)
    if not s.strip():
        return None
    # remove tudo exceto dígitos, ponto e vírgula
    s = re.sub(r"[^\d,\.]", "", s)
    # se tiver vírgula e ponto, assume vírgula como decimal e remove pontos de milhar
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        x = float(s)
        return x if x > 0 else None
    except Exception:
        return None


def _looks_like_price_key(k: str) -> bool:
    k = k.lower()
    return any(p in k for p in [
        "preco", "preço", "price", "valor", "min", "max", "low", "high", "sale"
    ])


def _normalize_js_to_json(text: str) -> Optional[str]:
    """
    Extrai o primeiro array de objetos de um JS e tenta normalizar para JSON.
    Estratégia:
      - encontra o bloco que começa com '[' e termina no '];' correspondente
      - acrescenta aspas em chaves não-aspadas
      - troca aspas simples por duplas, preservando números
      - remove vírgulas finais antes de '}' e ']'
    Retorna o JSON string ou None.
    """
    if not text:
        return None

    # pegue o maior bloco [ ... ];
    m_all = list(re.finditer(r"\[(?:.|\s)*?\]", text))
    if not m_all:
        return None

    # escolha o MAIOR bloco (mais segurança contra arrays internos)
    m = max(m_all, key=lambda m_: (m_.end() - m_.start()))
    raw = text[m.start(): m.end()]

    # uniformiza quebras de linha
    s = raw.replace("\r", "\n")

    # troca aspas simples por duplas quando não parecem parte de JSON válido
    s = re.sub(r"'", '"', s)

    # coloca aspas em chaves não-aspadas: { key: -> { "key":
    s = re.sub(r'([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)', r'\1"\2"\3', s)

    # remove vírgulas finais antes de fecha-chaves/colchetes
    s = re.sub(r",\s*([}\]])", r"\1", s)

    # tentativa de JSON
    return s


def _load_rows_from_js(text: str) -> List[Dict[str, Any]]:
    js = _normalize_js_to_json(text)
    if not js:
        return []
    try:
        data = json.loads(js)
        if isinstance(data, list):
            # mantém apenas objetos
            return [x for x in data if isinstance(x, dict)]
        return []
    except Exception:
        return []


def _extract_name(row: Dict[str, Any]) -> Optional[str]:
    for k in ["name", "nome", "title", "card", "nm", "descricao", "description"]:
        if k in row:
            v = str(row[k]).strip()
            if v:
                return v
    # heurística: primeiro campo string "longa"
    for k, v in row.items():
        if isinstance(v, str) and len(v.strip()) >= 3 and not _looks_like_price_key(k):
            return v.strip()
    return None


def _collect_prices(row: Dict[str, Any]) -> List[float]:
    prices: List[float] = []
    # pega por chaves "de preço"
    for k, v in row.items():
        if _looks_like_price_key(k):
            val = _to_float_brl(v)
            if val:
                prices.append(val)
    # se não encontrou nada, procura strings que pareçam preço
    if not prices:
        for v in row.values():
            if isinstance(v, str) and ("R$" in v or re.search(r"\d[,\.]\d{2}\b", v)):
                val = _to_float_brl(v)
                if val:
                    prices.append(val)
    # saneamento
    prices = [p for p in prices if 0 < p < 500_000]
    return prices


class LigaPokemonScraper(BaseScraper):
    """
    Scraper que varre um ou mais edids (edições) da Liga Pokémon.
    Por padrão usa um edid mais recente conhecido.
    Dica: passe uma lista de edids relevantes para o seu uso.
    """
    source_name = "ligapokemon"

    def __init__(self, edids: Optional[Iterable[str]] = None, delay_s: float = 0.9):
        # Você pode ajustar a lista default conforme seu caso.
        self.edids: List[str] = [str(x) for x in (edids or ["706"])]
        self.delay_s = float(delay_s)

    def _fetch_js_text(self, edid: str) -> Optional[str]:
        url = BASE_JS.format(edid=edid)
        try:
            r = requests.get(url, headers=HEADERS, timeout=25)
            r.raise_for_status()
            return r.text
        except Exception:
            return None

    def _rows_for_edid(self, edid: str) -> List[Dict[str, Any]]:
        text = self._fetch_js_text(edid)
        if not text:
            return []
        rows = _load_rows_from_js(text)
        return rows

    def search(self, query: str) -> List[PriceResult]:
        if not query or len(query.strip()) < 2:
            return []

        q = query.strip()
        rx = re.compile(re.escape(q), re.IGNORECASE)

        results: List[PriceResult] = []

        for edid in self.edids:
            rows = self._rows_for_edid(edid)
            if not rows:
                time.sleep(self.delay_s)
                continue

            for row in rows:
                name = _extract_name(row) or ""
                if not name or not rx.search(name):
                    # tenta alguns campos extras comuns para o filtro
                    joined = " ".join(str(v) for v in row.values() if isinstance(v, (str, int, float)))
                    if not rx.search(joined):
                        continue

                prices = _collect_prices(row)
                if not prices:
                    continue

                pmin, pmax = min(prices), max(prices)
                ref_url = SEARCH_HTML.format(edid=edid)

                results.append(
                    PriceResult(
                        query=q,
                        source=self.source_name,
                        title=str(name)[:512] if name else f"Resultado ({edid})",
                        url=ref_url,
                        price_min_brl=round(float(pmin), 2),
                        price_max_brl=round(float(pmax), 2),
                    ).clamp()
                )

            # Respeita o servidor
            time.sleep(self.delay_s)

        # Dedup por (title, url) mantendo menor preço médio
        def mid(r: PriceResult) -> float:
            return (float(r.price_min_brl) + float(r.price_max_brl)) / 2.0

        dedup: Dict[tuple, PriceResult] = {}
        for r in results:
            key = (r.title, r.url)
            if key not in dedup or mid(r) < mid(dedup[key]):
                dedup[key] = r

        final = sorted(dedup.values(), key=mid)
        return final[:40]
