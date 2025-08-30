-- Esquema PostgreSQL para o Pokémon TCG (PT-BR)
-- Define tabelas, relacionamentos e índices para um banco de dados completo.

CREATE TABLE series (
    id SERIAL PRIMARY KEY,
    nome VARCHAR(100) NOT NULL UNIQUE,
    codigo VARCHAR(50),
    data_lancamento DATE,
    criado_em TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    atualizado_em TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

CREATE TABLE colecoes (
    id SERIAL PRIMARY KEY,
    serie_id INTEGER NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    nome VARCHAR(120) NOT NULL,
    codigo VARCHAR(50),
    data_lancamento DATE,
    total_cartas INTEGER,
    simbolo_url TEXT,
    logo_url TEXT,
    criado_em TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    atualizado_em TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    UNIQUE (serie_id, codigo)
);

CREATE INDEX idx_colecoes_nome ON colecoes (nome);

CREATE TABLE raridades (
    id SERIAL PRIMARY KEY,
    nome VARCHAR(50) NOT NULL UNIQUE
);

CREATE TABLE artistas (
    id SERIAL PRIMARY KEY,
    nome VARCHAR(100) NOT NULL UNIQUE
);

CREATE TABLE tipos_energia (
    id SERIAL PRIMARY KEY,
    nome VARCHAR(50) NOT NULL UNIQUE,
    simbolo VARCHAR(20)
);

CREATE TABLE cartas (
    id SERIAL PRIMARY KEY,
    colecao_id INTEGER NOT NULL REFERENCES colecoes(id) ON DELETE CASCADE,
    nome VARCHAR(200) NOT NULL,
    numero VARCHAR(20) NOT NULL,
    hp INTEGER,
    classe VARCHAR(50),
    subclasse VARCHAR(50),
    raridade_id INTEGER REFERENCES raridades(id),
    artista_id INTEGER REFERENCES artistas(id),
    regra VARCHAR(255),
    texto_rodape TEXT,
    publicado BOOLEAN DEFAULT TRUE,
    criado_em TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    atualizado_em TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    UNIQUE (colecao_id, numero)
);

CREATE INDEX idx_cartas_nome ON cartas (nome);
CREATE INDEX idx_cartas_colecao ON cartas (colecao_id);

CREATE TABLE habilidades (
    id SERIAL PRIMARY KEY,
    carta_id INTEGER NOT NULL REFERENCES cartas(id) ON DELETE CASCADE,
    nome VARCHAR(100) NOT NULL,
    texto TEXT NOT NULL,
    ordem SMALLINT DEFAULT 0,
    UNIQUE (carta_id, nome)
);

CREATE TABLE ataques (
    id SERIAL PRIMARY KEY,
    carta_id INTEGER NOT NULL REFERENCES cartas(id) ON DELETE CASCADE,
    nome VARCHAR(100) NOT NULL,
    texto TEXT,
    dano VARCHAR(20),
    ordem SMALLINT DEFAULT 0
);

CREATE TABLE ataques_custos (
    ataque_id INTEGER REFERENCES ataques(id) ON DELETE CASCADE,
    tipo_energia_id INTEGER REFERENCES tipos_energia(id),
    quantidade SMALLINT NOT NULL CHECK (quantidade > 0),
    PRIMARY KEY (ataque_id, tipo_energia_id)
);

CREATE TABLE fraquezas (
    id SERIAL PRIMARY KEY,
    carta_id INTEGER NOT NULL REFERENCES cartas(id) ON DELETE CASCADE,
    tipo_energia_id INTEGER NOT NULL REFERENCES tipos_energia(id),
    multiplicador VARCHAR(10) NOT NULL
);

CREATE TABLE resistencias (
    id SERIAL PRIMARY KEY,
    carta_id INTEGER NOT NULL REFERENCES cartas(id) ON DELETE CASCADE,
    tipo_energia_id INTEGER NOT NULL REFERENCES tipos_energia(id),
    modificador VARCHAR(10) NOT NULL
);

CREATE TABLE formatos_torneio (
    id SERIAL PRIMARY KEY,
    nome VARCHAR(50) NOT NULL UNIQUE
);

CREATE TABLE legalidades (
    carta_id INTEGER REFERENCES cartas(id) ON DELETE CASCADE,
    formato_id INTEGER REFERENCES formatos_torneio(id),
    status VARCHAR(20) NOT NULL DEFAULT 'legal',
    PRIMARY KEY (carta_id, formato_id)
);

CREATE TABLE variantes (
    id SERIAL PRIMARY KEY,
    carta_id INTEGER NOT NULL REFERENCES cartas(id) ON DELETE CASCADE,
    tipo VARCHAR(50) NOT NULL,
    descricao VARCHAR(100),
    UNIQUE (carta_id, tipo)
);

CREATE TABLE imagens (
    id SERIAL PRIMARY KEY,
    carta_id INTEGER NOT NULL REFERENCES cartas(id) ON DELETE CASCADE,
    variante_id INTEGER REFERENCES variantes(id),
    url_pequena TEXT,
    url_grande TEXT,
    tipo VARCHAR(20)
);

CREATE TABLE precos (
    id SERIAL PRIMARY KEY,
    carta_id INTEGER NOT NULL REFERENCES cartas(id) ON DELETE CASCADE,
    fonte VARCHAR(50) NOT NULL,
    data_coleta DATE NOT NULL DEFAULT CURRENT_DATE,
    preco_baixo NUMERIC(10,2),
    preco_medio NUMERIC(10,2),
    preco_alto NUMERIC(10,2),
    preco_mercado NUMERIC(10,2)
);

CREATE INDEX idx_precos_carta_data ON precos (carta_id, data_coleta);
