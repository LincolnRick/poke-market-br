# poke-market-br — Gestor de Coleção Pokémon TCG (PT-BR)

Aplicativo  voltado para colecionadores do Pokémon TCG
que utilizam cartas impressas oficialmente em Português do Brasil.
O backend é escrito em Flask + SQLAlchemy com banco SQLite e foco em
simplicidade para uso local.

## Recursos
- Catálogo PT-BR de cartas, sets e séries
- Busca por nome, número (ex: `65/82`), set e raridade
- Coleção e wishlist
- Histórico de preços
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

### Seeder offline via cards-database
Os dados oficiais de cartas são lidos da pasta local `cards-database` (mesma
estrutura do repositório [`tcgdex/cards-database`](https://github.com/tcgdex/cards-database)).

```bash
# instala dependências
pip install -r requirements.txt

# popula o banco (SQLite local por padrão)
python seed_tcgdex_cards.py --cards-db-dir ./cards-database --clean

# usando outro banco (aceita DB_URL, DATABASE_URL ou SQLALCHEMY_DATABASE_URI)
DB_URL=sqlite:///meu.db python seed_tcgdex_cards.py --cards-db-dir ./cards-database
```

O comando acima cria/atualiza a tabela `cards` com os dados dos arquivos
TypeScript. Para um banco Postgres, defina `DATABASE_URL` e instale
`psycopg2-binary`.

### Página `/cards`
Depois de rodar o seeder, execute a aplicação normalmente:

```bash
python app.py
```

Visite `http://localhost:5000/cards` para navegar pelas cartas utilizando os
filtros de série, set ou busca textual. Também há o endpoint JSON em
`/api/cards` com os mesmos parâmetros (`series`, `set`, `q`).

## Licença
Distribuído sob a licença [MIT](LICENSE).

---
Marcas e imagens de Pokémon são propriedade de Nintendo / Creatures /
GAME FREAK / The Pokémon Company. Este projeto é comunitário e
educacional, sem afiliação oficial.
