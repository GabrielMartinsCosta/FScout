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

Fases 0, 1 e 1b concluídas: domínio, schema, ingestão da StatsBomb, ligação com o
Transfermarkt e clima por partida. No banco: 662 mil eventos de 182 partidas de quatro
competições, com 96,8% dos atletas ligados à ficha biográfica.

| Camada | Estado |
|---|---|
| `domain/` — vocabulário e geometria do campo | pronto |
| `db/` — schema com 22 tabelas e identidade entre fontes | pronto |
| `ingestion/` — StatsBomb | pronto, validado |
| `ingestion/` — Transfermarkt (ficha, mercado) | pronto, validado |
| `ingestion/` — Open-Meteo (clima por partida) | pronto, validado |
| `linking/` — ligação de registros entre fontes | pronto, 96,8% |
| `ingestion/` — API-Football (lesões, Brasileirão) | a fazer |
| `metrics/` — catálogo e motor (108 definições) | pronto |
| `api/` — FastAPI | pronto |
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
# Temporadas disponíveis na StatsBomb Open Data (com filtro opcional)
fscout competitions
fscout competitions "copa america"

# Carrega uma temporada: competição e temporada, na ordem da listagem acima
fscout ingest 223 282              # Copa América 2024
fscout ingest 43 106 --limit 5     # só as 5 primeiras partidas da Copa de 2022
fscout ingest 223 282 --refresh    # recarrega o que já está no banco

# Liga os atletas ao Transfermarkt e preenche ficha, valor de mercado e contrato
fscout transfermarkt

# Localiza os estádios e busca o clima de cada partida no horário do jogo
fscout weather

# Preenche o código ISO de cada país, que é o que posiciona o mapa-múndi
fscout paises

# Sonda o que o plano do API-Football cobre (exige FSCOUT_API_FOOTBALL_KEY no .env).
# Gasta 3 das 100 requisições diárias do plano gratuito e diz se o item compensa.
fscout api-football

# Catálogo de métricas (a tabela de definições operacionais do projeto)
fscout catalogo
fscout catalogo finalizacao
fscout catalogo --csv data/processed/catalogo_metricas.csv

# Quantidade de registros por tabela
fscout status

# Sobe a API; a documentação interativa fica em http://127.0.0.1:8000/docs
fscout api

# Sobe o painel, em OUTRO terminal e com a API no ar: http://127.0.0.1:8050
fscout ui

# Verifica a paleta dos gráficos por cálculo (daltonismo, contraste, luminosidade).
# Três séries é o teto das formas em que qualquer marca encosta em qualquer outra.
python scripts/validate_palette.py "#2a78d6,#eb6834,#1baf7a" --mode light --pairs all

# Testes (o de integração baixa ~4 MB na primeira vez)
pytest
pytest -m "not integration"        # sem acesso à rede

# Lint e formatação
ruff check src tests
ruff format src tests
```

A carga é idempotente: rodar o mesmo comando duas vezes não duplica nada, e uma carga
interrompida retoma de onde parou.

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

## Fontes de dados

Primária e já integrada: [StatsBomb Open Data](https://github.com/statsbomb/open-data),
dados evento a evento.

Complementares, para o que a StatsBomb não tem — biografia, valor de mercado, lesões,
clima, Brasileirão: avaliadas e priorizadas em [`docs/FONTES.md`](docs/FONTES.md).

As limitações de cobertura e de granularidade estão declaradas na
[seção 8 da arquitetura](docs/ARQUITETURA.md#8-limitações--a-serem-declaradas-no-texto).
