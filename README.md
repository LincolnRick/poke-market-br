poke-market-br — Gestor de Coleção Pokémon TCG (PT-BR)

App estilo Collectr para colecionadores do Pokémon Estampas Ilustradas com foco no mercado brasileiro (cartas oficialmente impressas em Português do Brasil).
Backend em Flask + SQLAlchemy, banco SQLite, busca/coleção/wishlist, exportações e seeding em PT-BR via TCGdex.

Sumário

Recursos

Arquitetura

Instalação (dev)

Configuração

Como rodar

Seeding de Cartas (PT-BR)

Opção A — API TCGdex (recomendada)

Opção B — Carga inicial offline (cards-database)

Rotas principais (MVP)

Estrutura de pastas

Roadmap

Boas práticas e notas legais

Agradecimentos

Licença

Recursos

Catálogo PT-BR: cartas, sets e séries, com nome/descrição em português quando oficialmente impressas no Brasil.

Busca: por nome, número (ex: 65/82), set, raridade, filtros úteis.

Coleção: adicionar/editar/mesclar duplicados, totais e KPIs básicos.

Wishlist: lista de desejos com possível conversão para coleção.

Exportações: CSV (coleção, wishlist).

Histórico de preços (manual): endpoints para registrar valores informados por você.

Seeding PT-BR: popula o banco local com TCGdex.

Banco local: instance/collectr.db por padrão (SQLite).

Foco deste repositório: funcional e estável primeiro; UI pode ser evoluída (tema “retro/Game Boy”, mascote lontra etc.) no roadmap.

Arquitetura

Python 3.10+

Flask (views/templates Jinja)

SQLAlchemy (ORM)

SQLite (dev/local) — pode apontar para Postgres em produção

Seeding via TCGdex (PT-BR)

Instalação (dev)
git clone https://github.com/LincolnRick/poke-market-br.git
cd poke-market-br

# Ambiente virtual
python -m venv .venv
# Windows
.\.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate

# Dependências
python -m pip install --upgrade pip
pip install -r requirements.txt

Configuração

Crie um arquivo .env na raiz (opcional) ou exporte variáveis no seu shell:

# Banco (padrão: sqlite:///instance/collectr.db)
DB_URL=sqlite:///instance/collectr.db

# Conversão opcional de preços (se quiser exibir BRL a partir de USD)
FX_USD_BRL=5.20

# Flask (opcional)
FLASK_ENV=development
FLASK_DEBUG=1
SECRET_KEY=troque-esta-chave

# Outras integrações futuras (placeholders)
# POKEMONTCG_API_KEY=xxxxx


Diretório instance/: certifique-se de que existe (Flask/SQLite o usam para dados locais).
Na primeira execução, o banco é criado automaticamente pelos scripts de seeding ou pelo app.

Como rodar
# Se o projeto tiver um app.py/cli
flask --app app run
# ou
python app.py


A aplicação iniciará em http://127.0.0.1:5000/ (ou porta configurada).

Seeding de Cartas (PT-BR)
Opção A — API TCGdex (recomendada)

Use o script de seeding por API (cartas oficiais em PT-BR):

# Executar na raiz do projeto
python seed_tcgdex_ptbr.py

# Exemplos úteis
python seed_tcgdex_ptbr.py --max-sets 3
python seed_tcgdex_ptbr.py --only-sets base1,swsh3 --update
python seed_tcgdex_ptbr.py --sleep 0.25
python seed_tcgdex_ptbr.py --dry-run


O que o script faz

Lista sets PT-BR → detalha cada set → busca todas as cartas do set → upsert no banco.

Preenche campos-chave: id, local_id, nome (PT-BR), raridade, categoria, tipos, set_id, set_nome, ilustrador, imagem_url.

Se disponível, grava preços internacionais (USD/EUR; tendência/médias) expostos pela TCGdex.

É idempotente (pode rodar várias vezes).

Dica: defina DB_URL e FX_USD_BRL no .env se quiser preço em BRL calculado em views/queries.

Opção B — Carga inicial offline (cards-database)

Para populações massivas iniciais, você pode clonar o repositório público com os JSONs PT e rodar um importador offline (sem depender de milhares de chamadas HTTP).
Workflow sugerido:

Clonar o repositório tcgdex/cards-database (dados puros por carta/set/idioma).

Rodar um importador que percorre **/*/pt.json e faz upsert no banco com o mesmo esquema da opção A.

Manter sincronização depois via API (opção A) apenas para novos sets/cartas.

Se desejar, mantemos um script import_tcgdex_repo_pt.py no mesmo padrão (idempotente, logs, upsert).

Opção C — Liga Pokémon (scraper)

Quando precisar importar cartas diretamente do site da Liga Pokémon, use o
script de seeding dedicado:

```
python seed_ligapokemon_cards.py --edids 706 707
```

Basta informar os `edids` das edições que deseja carregar. O script cria
os sets automaticamente (quando ausentes) e realiza *upsert* das cartas
com base na constraint de unicidade `(set_id, number)`, permitindo
execuções idempotentes.

Rotas principais (MVP)

Podem variar conforme sua versão; abaixo, o intento do MVP.

GET / — dashboard/resumo (KPI simples da coleção)

GET /cards — buscar cartas (nome, número X/Y, set, raridade, filtros)

POST /collection — adicionar item à coleção

GET /collection — listar coleção (com filtros/ordenação)

POST /collection/merge — mesclar duplicados

GET /wishlist — listar wishlist

POST /wishlist — adicionar à wishlist

POST /wishlist/move-to-collection — mover item da wishlist para coleção

GET /export/collection.csv — exportar coleção

GET /export/wishlist.csv — exportar wishlist

POST /prices/manual — registrar preço manual (histórico)

Estrutura de pastas
poke-market-br/
├── app.py
├── config.py
├── db.py
├── seed_tcgdex_ptbr.py          # seeding por API (PT-BR)
├── requirements.txt
├── instance/
│   └── collectr.db              # banco local (após criar)
├── templates/
│   ├── index.html
│   ├── cards.html
│   ├── collection.html
│   └── wishlist.html
├── static/
│   ├── css/
│   └── img/
└── README.md


Alguns nomes/arquivos podem variar — ajuste conforme seu estado atual do repo.

Roadmap

Dados & Catálogo

 Importador offline (cards-database PT) + diffs por set

 Validação de cobertura: total local vs. cardCount.official

Preços

 Conversão BRL com FX_USD_BRL (view/materialização)

 Integração “sold items” (eBay/Mercado Livre) para preço realizado

Coleção/Wishlist

 Regras de mescla inteligente (pelas características/foil/raridade)

 “Wishlist → Coleção” com log de aquisição

UI/UX

 Tema retro/Game Boy + mascote “lontra” em botões (CSV, PDF, etc.)

 KPIs (total por raridade, sets completos, valor estimado)

Observabilidade

 etl_log com métricas de seeding/sync

 Testes de fumaça diários (novos sets/cartas)

Boas práticas e notas legais

Cartas PT-BR: mantenha o foco em cartas oficialmente impressas no Brasil (PT-BR).

Créditos de dados: ao usar TCGdex, referencie a fonte.

Imagens: use URLs oficiais/expostas pelos provedores; cache local é opcional e deve respeitar termos de uso.

Marcas: Pokémon, Pokémon TCG, logotipos e imagens são propriedade de Nintendo / Creatures / GAME FREAK / The Pokémon Company. Este projeto é comunitário/educacional, sem afiliação oficial.

Agradecimentos

TCGdex e comunidade — dados multilíngues e APIs/SDKs que viabilizam PT-BR.

Comunidade de colecionadores e devs que mantêm projetos auxiliares (documentação, scraping responsável, validação).
