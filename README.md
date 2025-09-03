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

### Seeding de cartas
Importe sets e cartas da distribuição TCGdex clonada localmente:
```bash
python seed_tcgdex_cards.py --sets base1
python seed_tcgdex_cards.py --sets "rivais predestinados"
```

### Importação offline via cards-database
Também é possível carregar os dados diretamente do repositório
[`tcgdex/cards-database`](https://github.com/tcgdex/cards-database)
utilizando o script `load_tcgdex.py`:

```bash
# Importa todos os sets disponíveis em Português
python load_tcgdex.py --repo-path ../cards-database --lang pt

# Executa uma atualização incremental desde 2024-01-01 sem gravar no banco
DATABASE_URL=sqlite:///meu.db python load_tcgdex.py --repo-path ../cards-database \
    --since 2024-01-01 --dry-run
```

## Licença
Distribuído sob a licença [MIT](LICENSE).

---
Marcas e imagens de Pokémon são propriedade de Nintendo / Creatures /
GAME FREAK / The Pokémon Company. Este projeto é comunitário e
educacional, sem afiliação oficial.
