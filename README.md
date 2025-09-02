# poke-market-br — Gestor de Coleção Pokémon TCG (PT-BR)

Aplicativo estilo **Collectr** voltado para colecionadores do Pokémon TCG
que utilizam cartas impressas oficialmente em Português do Brasil.
O backend é escrito em Flask + SQLAlchemy com banco SQLite e foco em
simplicidade para uso local.

## Recursos
- Catálogo PT-BR de cartas, sets e séries
- Busca por nome, número (ex: `65/82`), set e raridade
- Coleção e wishlist com possibilidade de exportação em CSV
- Histórico de preços manual
- Seeding de cartas em PT-BR utilizando a API do [TCGdex](https://www.tcgdex.net/)

## Arquitetura
- Python 3.10+
- Flask (templates Jinja)
- SQLAlchemy como ORM
- SQLite para desenvolvimento local

## Instalação e execução
```bash
# Clonar o repositório
git clone https://github.com/LincolnRick/poke-market-br.git
cd poke-market-br

# Ambiente virtual
python -m venv .venv
source .venv/bin/activate

# Dependências
python -m pip install --upgrade pip
pip install -r requirements.txt

# Executar a aplicação
flask --app app run  # ou `python app.py`
```

### Configuração opcional
Crie um arquivo `.env` na raiz com variáveis de ambiente como
`DB_URL` e `SECRET_KEY`. O banco SQLite local fica em `instance/`.

### Seeding de cartas
Scripts de exemplo:
```bash
python seed_demo.py
python seed_ligapokemon_cards.py --edids 706 707
python seed_tcgdex_cards.py --sets base1
```

## Licença
Distribuído sob a licença [MIT](LICENSE).

---
Marcas e imagens de Pokémon são propriedade de Nintendo / Creatures /
GAME FREAK / The Pokémon Company. Este projeto é comunitário e
educacional, sem afiliação oficial.
