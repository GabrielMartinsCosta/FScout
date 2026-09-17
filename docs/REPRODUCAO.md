# Roteiro de reprodução

Do clone à primeira tela, com os números que você deve obter em cada passo.

Este roteiro existe para que o trabalho possa ser **verificado por terceiros**. Cada
etapa termina com um resultado conferível: se o seu número bater com o daqui, a etapa
funcionou; se não bater, o desvio está localizado.

---

## 1. O que é preciso ter

| | |
|---|---|
| Python | 3.11 ou mais novo |
| Espaço em disco | ~2 GB (banco de 400 MB, cache das fontes ~1 GB) |
| Internet | sim, na ingestão; depois o cache local basta |
| Conta em serviço pago | nenhuma |

A camada de dado agregado (passo 6) usa uma conta **gratuita** do API-Football. Ela é
opcional: os passos 1 a 5 produzem uma ferramenta completa sem ela.

## 2. Ambiente

```bash
git clone https://github.com/GabrielMartinsCosta/FScout
cd FScout
python -m venv .venv
.venv\Scripts\activate        # Windows;  no Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
```

Confira a instalação rodando a suíte de testes. Nenhum deles depende de rede, exceto os
marcados como integração:

```bash
pytest -m "not integration"
```

**Esperado:** todos passam, em torno de dez segundos.

## 3. Banco

```bash
fscout init-db
```

Cria as tabelas que faltarem e acrescenta colunas novas a um banco já existente. É
idempotente: rodar de novo não faz nada.

## 4. Camada de evento — a base do trabalho

Quatro competições da StatsBomb Open Data. Os dois números de cada comando são os
identificadores de competição e temporada na fonte; `fscout competitions` lista todos.

```bash
fscout ingest 43 106      # Copa do Mundo 2022        —  64 partidas
fscout ingest 55 282      # Eurocopa 2024             —  51 partidas
fscout ingest 223 282     # Copa América 2024         —  32 partidas
fscout ingest 11 90       # La Liga 2020/21           —  35 partidas
```

Cada carga leva de vinte segundos a um minuto. A primeira baixa os arquivos da fonte;
as seguintes reaproveitam o cache em `data/raw/`.

**Esperado ao fim de cada uma:** `Placares divergentes: 0` e `Valores não mapeados: 0`.
O primeiro é o teste de sanidade mais barato da ingestão — se os gols reconstruídos a
partir das finalizações não batem com o placar oficial, algo no mapeamento está errado.

**Conferência acumulada:**

```bash
fscout status
```

| Tabela | Esperado |
|---|---|
| `matches` | 182 |
| `events` | 661.915 |
| `players` | 1.984 |
| `passes` | 190.585 |
| `shots` | 4.463 |

## 5. Enriquecimento

```bash
fscout transfermarkt     # biografia, valor de mercado e contrato (baixa ~190 MB na 1ª vez)
fscout weather           # localiza estádios e busca o clima de cada partida
fscout paises            # código ISO de cada país, que posiciona o mapa-múndi
```

**Esperado no `transfermarkt`:** 1.532 de 1.583 atletas ligados (96,8%), com **precisão
de 98,6%** medida contra as ligações por escalação, e 51 casos recusados e listados em
`data/processed/`. A recusa é deliberada: preferir não ligar a ligar errado.

**Esperado no `weather`:** 182 de 182 partidas com clima, 51 estádios localizados, sete
deles por coordenada manual em `data/reference/venues.csv`.

**Esperado no `paises`:** 86 códigos gravados e 5 países sem código — Tchecoslováquia,
URSS, Iugoslávia, Sérvia e Montenegro e a Iugoslávia republicana. São Estados extintos
de sucessão ambígua, e escolher um sucessor plantaria um marcador onde ninguém jogou.

## 6. Camada agregada — opcional, e é o que traz o futebol brasileiro

Não existe dado de evento aberto para o futebol de clubes sul-americano. A cobertura do
Brasileirão e da Libertadores vem de estatística já agregada, com granularidade menor.

**6.1. Crie a conta gratuita** em `dashboard.api-football.com` e escreva a chave no
arquivo `.env`, na raiz do projeto:

```
FSCOUT_API_FOOTBALL_KEY=sua_chave
```

O `.env` está no `.gitignore`. Não coloque a chave no `.env.example`, que é versionado.

**6.2. Confira o que o seu plano cobre** — gasta 7 das 100 requisições diárias:

```bash
fscout api-football sondar
```

**Esperado no plano gratuito:** Brasileirão e Libertadores com as temporadas de **2022 a
2024** acessíveis, e **33 estatísticas por jogador e por partida**. Não vêm coordenadas,
xG, pé utilizado nem comprimento de passe — é essa a fronteira entre as duas camadas.

**6.3. Baixe.** O plano gratuito dá 100 requisições por dia e uma temporada tem 380
partidas, então a carga leva alguns dias. O comando para sozinho ao fim da cota; rodá-lo
de novo no dia seguinte continua de onde parou, sem regastar nada.

```bash
fscout api-football baixar --competicao 9  --temporada 2024   # Copa América — 33 requisições
fscout api-football baixar --competicao 71 --temporada 2024   # Brasileirão — 4 dias
```

**Comece pela Copa América.** Ela existe nas duas fontes, e é essa coincidência que
permite ligar os atletas do Brasileirão ao elenco canônico — veja o passo 6.5.

**6.4. Carregue** (lê só o cache, não vai à rede, pode rodar com a carga pela metade):

```bash
fscout api-football carregar --competicao 9  --temporada 2024
fscout api-football carregar --competicao 71 --temporada 2024
```

**Esperado na Copa América:** 32 partidas, 338 atletas, 1.009 linhas de estatística,
`Placares divergentes: 0` e **um defeito da fonte declarado** — o identificador 65657
aparece duas vezes na mesma partida, como "Jesús Sagredo" e "José Sagredo".

**6.5. Ligue as fontes:**

```bash
fscout api-football ligar
```

**Esperado:** 32 partidas em comum, 338 atletas na sobreposição, **338 ligados (100%)**,
zero ambíguos, além de 16 equipes e 1 temporada fundidas. A ligação usa a partida como
âncora e o número de camisa como desempate — o mesmo método medido no passo 5.

O efeito vai além: os identificadores ligados aqui reaparecem nas partidas do
Brasileirão, onde não há âncora nenhuma, e o carregador reaproveita o atleta canônico
sozinho. Com a Copa América ligada, **Sergio Rochet** passa a ser um registro só com
Copa do Mundo e Copa América na camada de evento e Brasileirão na agregada.

## 7. Rodar

Dois processos, em dois terminais:

```bash
fscout api      # http://127.0.0.1:8000/docs
fscout ui       # http://127.0.0.1:8050
```

## 8. O que você deve ver

Na tela, o seletor **Granularidade do dado** troca entre as duas camadas e muda tudo
abaixo dele: atletas, métricas e percentis.

Estes são os fatos independentes que confirmam que a carga saiu certa. Nenhum deles foi
conferido contra o próprio sistema:

| Verificação | Esperado | Fonte externa |
|---|---|---|
| Placar reconstruído dos eventos | 182 de 182 conferem | placares oficiais |
| Artilheiro da Copa América | Lautaro Martínez, 5 gols | artilharia oficial |
| Líder de assistências da Copa América | James Rodríguez, 6 | recorde do torneio |
| Gols de Messi na La Liga 2020/21 | 30 | Pichichi daquela temporada |
| Artilharia pela camada **agregada** | Lautaro 5, Rondón 3, Álvarez 2 | mesma ordem da camada de evento |

A última linha é a verificação mais forte do trabalho: **duas fontes independentes,
calculadas por caminhos completamente diferentes** — uma somando finalizações evento a
evento, outra lendo totais já agregados —, chegando à mesma ordem.

## 9. Exportar a tabela de definições

O catálogo de métricas, exportado, é a tabela de definições operacionais da metodologia:

```bash
fscout catalogo --csv data/processed/catalogo_metricas.csv
```

**Esperado:** 144 métricas — 108 calculadas sobre eventos e 36 sobre dado agregado, sem
nenhuma chave em comum.

## 10. Conferir a acessibilidade dos gráficos

As cores do painel não foram escolhidas no olho: a segurança para daltonismo é calculada.

```bash
python scripts/validate_palette.py "#2a78d6,#eb6834,#1baf7a" --mode light --pairs all
```

**Esperado:** todas as checagens passam, com ΔE 9.2 sob daltonismo e 24.0 na visão
normal. Acrescentar um quarto matiz faz a verificação reprovar — e é por isso que o mapa
de chutes tem três classes de desfecho e o radar aceita no máximo três séries.

---

## Se algo não bater

- **Placares divergentes na ingestão** indicam problema de mapeamento, não de rede. O
  comando lista quais partidas divergiram.
- **`FSCOUT_API_FOOTBALL_KEY não está configurada`** é erro esperado quando a chave não
  foi posta no `.env`. A mensagem diz o que fazer.
- **A cota do dia acabou** não é falha: o que já veio está em cache, e rodar amanhã
  continua. O comando avisa quantos dias ainda faltam.
- **O painel diz que a API não responde**: ela roda em outro processo. Suba `fscout api`
  num segundo terminal e recarregue a página.
