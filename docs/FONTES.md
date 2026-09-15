# Fontes de dados e como combiná-las

## 1. Por que mais de uma fonte

Nenhuma fonte aberta atende sozinha à especificação do FScout. A StatsBomb tem o nível de
detalhe que sustenta a análise (cada chute com pé, técnica, coordenada e xG), mas não traz
data de nascimento, altura, valor de mercado, lesões nem clima. As fontes que têm esses
dados não têm eventos.

O desenho do projeto parte disso: **cada fonte cobre uma lacuna, e o banco guarda uma
entidade canônica por atleta, clube e partida**, ligada ao identificador que ela tem em
cada fonte.

---

## 2. Do requisito à fonte

| Requisito da especificação | Fonte | Situação |
|---|---|---|
| Estatísticas de chute, passe, drible, defesa, goleiro, disciplina | StatsBomb Open Data | **Integrada** |
| Histórico de partidas, recortes por competição e data | StatsBomb Open Data | **Integrada** |
| Duelos contra adversário específico, casa/fora | StatsBomb Open Data | **Integrada** |
| Nome, nacionalidade | StatsBomb Open Data | **Integrada** |
| Idade (data de nascimento), altura, pé preferencial | transfermarkt-datasets | Planejada |
| Dupla nacionalidade (país de nascimento e de cidadania) | transfermarkt-datasets | Planejada |
| Valor de mercado e sua evolução, fim de contrato | transfermarkt-datasets | Planejada |
| Histórico de clubes com transferências e empréstimos | transfermarkt-datasets | Planejada |
| Condição climática da partida | Open-Meteo (histórico) | Planejada |
| Histórico de lesões | API-Football | Planejada |
| Dados do Brasileirão | API-Football (agregado, sem eventos) | Planejada |
| Distância percorrida, sprints, velocidade | Metrica Sports, SkillCorner (amostras) | Opcional |
| Peso | — | Sem fonte aberta confiável |
| Salário | — | Sem fonte aberta confiável |

---

## 3. Fontes avaliadas

### StatsBomb Open Data — eventos · integrada

- **Granularidade:** evento a evento, com coordenadas, qualificadores e xG.
- **Cobertura relevante:** Copa do Mundo 2022, Eurocopa 2020 e 2024, **Copa América 2024**
  (única com a seleção brasileira), La Liga da era Messi, Champions League.
- **Acesso:** JSON no GitHub. Os termos de uso estão no `LICENSE.pdf` do repositório.
- **Lacunas:** sem biografia, sem lesões, sem clima, sem Brasileirão.

### Wyscout (Pappalardo et al., 2019) — eventos · candidata

- **Granularidade:** evento a evento, com taxonomia de tags própria.
- **Cobertura:** temporada 2017/18 das cinco grandes ligas europeias, Copa do Mundo 2018 e
  Eurocopa 2016.
- **Licença:** CC BY 4.0, publicada no figshare junto com artigo na *Scientific Data*, o que
  a torna citável no texto.
- **Custo de integração:** alto. Exige um segundo mapeador de eventos, porque a taxonomia
  não coincide com a da StatsBomb. Só compensa se sobrar prazo.

### transfermarkt-datasets — biografia e mercado · próxima a integrar

- **Formato:** CSV em 12 tabelas: competições, clubes, atletas, partidas, participações,
  valorizações, jogos por clube, eventos de partida, escalações, transferências, países e
  seleções.
- **Colunas de atleta, conferidas no modelo do repositório:** `date_of_birth`,
  `height_in_cm`, `foot`, `country_of_citizenship`, `country_of_birth`, `position`,
  `sub_position`, `contract_expiration_date`, `agent_name`, `current_club_id`. Valor de
  mercado vem da tabela de valorizações.
- **Licença:** CC0.
- **Atenção:** a atualização automática **está pausada**. Os dados vão até 06/07/2026, e as
  valorizações até 12/06/2026. Para um TCC com recorte histórico isso não impede o uso, mas
  precisa constar como limitação.
- **Não tem:** peso, lesões.

### API-Football — lesões e Brasileirão · planejada

- **Formato:** API REST.
- **Plano gratuito:** 100 requisições por dia, com acesso a todos os endpoints, incluindo o
  de lesões.
- **Cobertura:** inclui o Campeonato Brasileiro Série A.
- **Limite importante:** estatística agregada por partida, não evento a evento. Serve para
  lesões, escalações e totais do Brasileirão, não para a análise granular.
- **Consequência de projeto:** com 100 requisições diárias, a ingestão tem de ser
  incremental e cachear tudo em disco, como o cliente da StatsBomb já faz.

### Open-Meteo Historical Weather — clima · planejada

- **Dado:** reanálise meteorológica (ERA5) desde 1940, por coordenada e hora.
- **Acesso:** sem chave de API; gratuito para uso não comercial até 10 mil chamadas por dia.
- **Licença dos dados:** CC BY 4.0, com atribuição.
- **Uso no FScout:** temperatura, chuva e vento no horário de cada partida, a partir da
  coordenada do estádio. Com isso o recorte "desempenho sob chuva ou calor" deixa de ser
  trabalho futuro.

### Metrica Sports e SkillCorner — tracking · opcional

- **Metrica Sports:** três partidas anonimizadas com tracking e eventos.
- **SkillCorner:** dez partidas de tracking extraído da transmissão, da A-League australiana
  2024/25.
- **Uso possível:** demonstrar o cálculo de distância percorrida, sprints e velocidade.
- **Limite:** as partidas não são das competições com eventos da StatsBomb, então essas
  métricas não aparecem no perfil dos mesmos atletas. Entram, se entrarem, como capítulo de
  demonstração metodológica.

### Descartadas: raspagem de SofaScore, FotMob e FBref

APIs não oficiais, termos de uso que restringem coleta automatizada e estrutura que muda
sem aviso. Um TCC não deve depender de uma coleta que pode quebrar na semana da defesa nem
de dado cuja licença não se consegue declarar.

---

## 4. Como combinar: ligação de registros

### O modelo

Atleta, clube, competição e partida existem **uma vez** no banco. A tabela `external_ids`
guarda, para cada entidade, o identificador em cada fonte e **como a ligação foi feita**:

| `matched_by` | Significado |
|---|---|
| `created` | A fonte criou o registro canônico |
| `exact_id` | As fontes compartilham um identificador |
| `name_birthdate` | Ligação inferida por nome e data de nascimento |
| `name_team_season` | Ligação inferida por nome e clube na mesma temporada |
| `manual` | Revisada e confirmada manualmente |

A coluna `confidence` quantifica ligações inferidas. Para qualquer número exibido é possível
responder de que fonte veio e por que dois registros foram considerados a mesma pessoa.

### O problema do atleta

StatsBomb e Transfermarkt não compartilham identificador, e a StatsBomb não informa data de
nascimento — então a chave mais óbvia não existe. A ligação usa três sinais:

1. **Nome normalizado:** sem acento, minúsculo, comparado por tokens. "Lionel Andrés Messi
   Cuccittini" e "Lionel Messi" compartilham os tokens relevantes.
2. **Nacionalidade:** elimina homônimos de países diferentes.
3. **Clube ou seleção na mesma temporada:** o sinal mais forte. Dois registros com nome
   parecido que jogaram pela mesma equipe no mesmo ano são, na prática, a mesma pessoa.

A combinação vira uma pontuação. Acima de um limiar, liga automaticamente; numa faixa
intermediária, vai para uma fila de revisão manual; abaixo, não liga.

### Quem prevalece quando as fontes discordam

- A fonte que **criou** o registro pode atualizá-lo.
- Uma fonte **ligada depois** só preenche campos vazios.

Isso já está implementado no carregador. Quando houver conflito real — duas fontes com
datas de nascimento diferentes —, a regra evolui para precedência por campo (data de
nascimento do Transfermarkt, nome de exibição da StatsBomb).

### Como validar — e transformar em resultado do TCC

Sortear uma amostra de ligações automáticas, conferir manualmente e reportar **precisão**
(quantas ligações estavam certas) e **cobertura** (quantos atletas da StatsBomb foram
ligados). É uma avaliação quantitativa simples e defensável da etapa de integração.

---

## 5. Ordem sugerida dentro do prazo

1. **transfermarkt-datasets.** Preenche a ficha básica — nome, idade, altura, posição,
   nacionalidade —, que a especificação trata como fundamental. É também onde a ligação de
   registros é construída e validada.
2. **Open-Meteo.** Barato: uma requisição por partida. Reinclui o recorte climático.
3. **API-Football.** Lesões e Brasileirão, respeitando a cota diária.
4. **Tracking amostral.** Só se houver folga.
5. **Wyscout.** Só se houver folga depois do item 4.

---

## Referências

- StatsBomb Open Data: <https://github.com/statsbomb/open-data>
- Pappalardo, L. et al. *A public data set of spatio-temporal match events in soccer
  competitions.* Scientific Data 6, 236 (2019): <https://www.nature.com/articles/s41597-019-0247-7>
- Dataset Wyscout no figshare: <https://figshare.com/collections/Soccer_match_event_dataset/4415000>
- transfermarkt-datasets: <https://github.com/dcaribou/transfermarkt-datasets>
- API-Football, planos: <https://www.api-football.com/pricing>
- API-Football, endpoint de lesões: <https://www.api-football.com/news/post/new-endpoint-injuries>
- Open-Meteo Historical Weather API: <https://open-meteo.com/en/docs/historical-weather-api>
- Metrica Sports sample data: <https://github.com/metrica-sports/sample-data>
- SkillCorner open data: <https://github.com/SkillCorner/opendata>
