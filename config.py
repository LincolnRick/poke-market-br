# config.py
# -----------------------------------------------------------------------------
# Lê .env e expõe Config com SQLALCHEMY_DATABASE_URI correto.
# Aceita DB_URL / DATABASE_URL / SQLALCHEMY_DATABASE_URI.
# Normaliza caminho Windows -> sqlite:///C:/... quando necessário.
# -----------------------------------------------------------------------------

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path
from typing import Optional


# --------------------- carregamento do .env ---------------------
def _load_dotenv_safe() -> None:
    """
    Carrega .env da raiz do projeto. Usa python-dotenv se presente;
    senão, faz um parser manual simples (KEY=VALUE).
    """
    root = Path(__file__).resolve().parent
    env_path = root / ".env"
    if not env_path.exists():
        return

    # Tenta com python-dotenv
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv(env_path.as_posix())
        return
    except Exception:
        pass

    # Fallback manual
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            # não sobrescreve variáveis já definidas no ambiente
            os.environ.setdefault(k, v)
    except Exception:
        # se falhar, segue sem .env
        return


_load_dotenv_safe()


# --------------------- helpers ---------------------
def _get_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return str(v).strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def _get_int(name: str, default: int) -> int:
    v = os.environ.get(name)
    if v is None or str(v).strip() == "":
        return default
    try:
        return int(v)
    except ValueError:
        return default


def _resolve_db_uri() -> str:
    """
    Escolhe a URI do banco a partir das variáveis conhecidas:
    1) DB_URL
    2) DATABASE_URL
    3) SQLALCHEMY_DATABASE_URI
    Se nada vier, usa sqlite local ./poke_market.db
    Também normaliza caminhos Windows sem esquema para sqlite:///C:/...
    """
    raw = (
        os.environ.get("DB_URL")
        or os.environ.get("DATABASE_URL")
        or os.environ.get("SQLALCHEMY_DATABASE_URI")
        or ""
    ).strip()

    if not raw:
        # padrão: arquivo local na pasta do projeto
        here = Path(__file__).resolve().parent
        return f"sqlite:///{(here / 'poke_market.db').as_posix()}"

    # se já parece uma URI (tem "://"), retorna como está (mas normaliza barras do sqlite no Windows)
    if "://" in raw:
        if raw.lower().startswith("sqlite:"):
            # troca backslash por slash (URI)
            raw = raw.replace("\\", "/")
        return raw

    # Se veio um caminho puro do SO (ex.: C:\... ou /home/...):
    p = Path(raw)
    try:
        # no Windows, Path("C:\\...").drive não-vazio indica caminho absoluto
        is_abs = p.is_absolute() or bool(p.drive)
    except Exception:
        is_abs = False

    if is_abs:
        return f"sqlite:///{p.as_posix()}"

    # caminho relativo → resolvido a partir do diretório do config.py
    base = Path(__file__).resolve().parent / raw
    return f"sqlite:///{base.as_posix()}"


# --------------------- Config ---------------------
class Config:
    # Segurança básica Flask
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-collectr-key")

    # Token “simples” opcional para rotas protegidas internas
    SECRET_TOKEN = os.environ.get("SECRET_TOKEN", "super-seguro-4391")

    # Banco de dados
    SQLALCHEMY_DATABASE_URI = _resolve_db_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 280,
    }

    # Ajustes úteis para SQLite local
    if str(SQLALCHEMY_DATABASE_URI).lower().startswith("sqlite:"):
        SQLALCHEMY_ENGINE_OPTIONS["connect_args"] = {
            "check_same_thread": False,
            "timeout": 15,
        }

    # Cookies / Sessão
    PREFERRED_URL_SCHEME = os.environ.get("PREFERRED_URL_SCHEME", "http")
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _get_bool("SESSION_COOKIE_SECURE", False)
    PERMANENT_SESSION_LIFETIME = timedelta(days=_get_int("SESSION_DAYS", 30))

    # Extras (futuras integrações)
    DEFAULT_CURRENCY = os.environ.get("DEFAULT_CURRENCY", "BRL")

    # eBay / TCG (deixamos disponíveis para quem usa)
    EBAY_CLIENT_ID = os.environ.get("EBAY_CLIENT_ID", "")
    EBAY_CLIENT_SECRET = os.environ.get("EBAY_CLIENT_SECRET", "")
    EBAY_MP_ID = os.environ.get("EBAY_MP_ID", "EBAY_US")
    EBAY_SCOPE = os.environ.get("EBAY_SCOPE", "https://api.ebay.com/oauth/api_scope")
    POKEMONTCG_API_KEY = os.environ.get("POKEMONTCG_API_KEY") or os.environ.get("POKEMON_TCG_API_KEY")
