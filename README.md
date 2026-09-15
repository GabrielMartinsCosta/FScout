# FScout

Ferramenta de scouting para análise granular de atletas de futebol a partir de dados
evento a evento.

Trabalho de Conclusão de Curso.

## O que é

A maioria das ferramentas de estatística de futebol entrega números agregados: total de
gols, total de passes, percentual de acerto. O FScout parte de um nível abaixo — cada ação
registrada em campo, com suas coordenadas e qualificadores — e calcula a estatística no
momento da pergunta.

A diferença prática é que perguntas como

> *gols de canhota, de fora da área, vindos de escanteio, entre junho e julho de 2024,
> contra adversários específicos*

não precisam ter sido previstas. São um filtro sobre a tabela de eventos, não uma coluna
que alguém lembrou de criar.

Ver [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md) para o raciocínio completo e
[`docs/ROADMAP.md`](docs/ROADMAP.md) para o plano de execução.

## Estado atual

Fase 0 concluída: domínio, schema e fundação de testes.

| Camada | Estado |
|---|---|
| `domain/` — vocabulário e geometria do campo | pronto, 33 testes |
| `db/` — schema com 19 tabelas | pronto |
| `ingestion/` — StatsBomb e CSV | próximo |
| `metrics/` — catálogo e motor | a fazer |
| `api/` — FastAPI | a fazer |
| `viz/` — Dash e Plotly | a fazer |

## Requisitos

Python 3.11 ou superior. Nenhuma outra dependência de sistema — sem Node, sem servidor de
banco, sem Docker.

## Instalação

```powershell
git clone https://github.com/GabrielMartinsCosta/FScout
cd FScout

python -m venv .venv
.venv\Scripts\Activate.ps1      # PowerShell
# .venv\Scripts\activate.bat    # cmd
# source .venv/bin/activate     # Linux e macOS

pip install -e ".[dev]"
```

O arquivo `.env` é opcional: `config.py` traz padrão para toda configuração, e o banco
é criado em `data/db/fscout.db`. Copie de `.env.example` só se precisar alterar algo
(apontar para Postgres, mudar o diretório de cache).

Nada que o repositório não traz precisa ser transportado entre máquinas: o ambiente
virtual é recriado pelo comando acima, e os dados brutos são recarregados da fonte pela
ingestão.

## Uso

```bash
# Cria o banco
python -c "from fscout.db.session import create_all; create_all()"

# Testes
pytest

# Lint e formatação
ruff check src tests
ruff format src tests
```

## Estrutura

```
src/fscout/
├── domain/      Vocabulário e geometria do futebol. Sem I/O, sem dependências.
├── db/          Schema e sessão.
├── ingestion/   Adaptadores por fonte de dados.
├── metrics/     Catálogo declarativo e motor de avaliação.
├── api/         Contrato HTTP.
└── viz/         Interface.
```

## Fonte de dados

Primária: [StatsBomb Open Data](https://github.com/statsbomb/open-data), dados evento a
evento sob licença de uso acadêmico e não comercial.

Secundária: adaptador CSV, para dados fornecidos por clube e para informações que nenhum
provedor aberto registra (lesões, valor de mercado).

As limitações de cobertura e de granularidade de cada fonte estão declaradas na
[seção 8 da arquitetura](docs/ARQUITETURA.md#8-limitações--a-serem-declaradas-no-texto).
