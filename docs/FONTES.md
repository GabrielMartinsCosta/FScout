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
| Idade (data de nascimento), altura, pé preferencial | transfermarkt-datasets | **Integrada** |
| Dupla nacionalidade (país de nascimento e de cidadania) | transfermarkt-datasets | **Integrada** |
| Valor de mercado e sua evolução, fim de contrato | transfermarkt-datasets | **Integrada** |
| Histórico de clubes com transferências e empréstimos | transfermarkt-datasets | Planejada |
| Condição climática da partida | Open-Meteo (histórico) | **Integrada** |
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

### transfermarkt-datasets — biografia e mercado · integrada

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

### Open-Meteo Historical Weather — clima · integrada

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
| `date_teams` | Partida ligada por data e pelos nomes das duas equipes |
| `match_side` | Equipe ligada pelo lado que ocupou nas partidas já ligadas |
| `game_lineup` | Atleta ligado dentro da escalação de uma partida, por nome e camisa |
| `name_nationality` | Atleta ligado por nome dentro do país |
| `exact_name_unique` | Atleta ligado por nome idêntico e único no dataset inteiro |
| `manual` | Revisada e confirmada manualmente |

A coluna `confidence` quantifica ligações inferidas. Para qualquer número exibido é possível
responder de que fonte veio e por que dois registros foram considerados a mesma pessoa.

### O problema do atleta

StatsBomb e Transfermarkt não compartilham identificador, e a StatsBomb não informa data de
nascimento — a chave mais óbvia simplesmente não existe. Sobram três sinais:

1. **Nome normalizado:** sem acento, minúsculo, comparado palavra a palavra. "Lionel Andrés
   Messi Cuccittini" e "Lionel Messi" compartilham as palavras que importam.
2. **Partida em comum:** se as duas fontes descrevem o mesmo jogo, o atleta está entre os
   ~25 inscritos daquela equipe, e o número da camisa confirma. É o sinal mais forte.
3. **Nacionalidade:** quando não há escalação, reduz o universo de 50 mil nomes para os
   milhares de um país.

Os sinais não viram uma pontuação única: são aplicados em níveis, do mais forte ao mais
fraco, e cada nível pode **recusar** em vez de arriscar. O que ninguém decide vai para um
CSV de revisão manual, nunca para uma ligação duvidosa.

### Quem prevalece quando as fontes discordam

- A fonte que **criou** o registro pode atualizá-lo.
- Uma fonte **ligada depois** só preenche campos vazios.

Isso já está implementado no carregador. Quando houver conflito real — duas fontes com
datas de nascimento diferentes —, a regra evolui para precedência por campo (data de
nascimento do Transfermarkt, nome de exibição da StatsBomb).

### Os três níveis de decisão, em ordem de evidência

1. **Escalação da partida.** Entre os inscritos de uma equipe numa partida, nome parecido
   mais número de camisa. É o nível mais forte e o único disponível para a Copa América
   2024 e a La Liga — Copa do Mundo e Euro não têm escalação no Transfermarkt.
2. **Nome e nacionalidade.** Nome idêntico e único dentro do país, ou nome aproximado com
   folga sobre o segundo colocado. Homônimos exatos são desempatados por jogos de seleção.
3. **Nome único no dataset inteiro.** Último recurso, para atletas que a fonte registra sem
   cidadania nem país de nascimento.

### Onde o método falha, e por que ele desiste

Os 51 casos não ligados não são falhas silenciosas: são recusas deliberadas, registradas no
CSV de revisão. Os padrões:

- **Sobrenome composto espanhol.** "Daniel Olmo Carvajal" contém as palavras de "Daniel
  Carvajal", outro atleta da mesma seleção, que pontua mais que o "Dani Olmo" correto.
- **Apelido comum.** "Fabinho" tem oito registros no Transfermarkt, "Ederson" tem três.
- **Apelido contra nome de registro.** O "Sávio" da seleção brasileira de 2024 é o "Savinho"
  do Transfermarkt; o método por nome escolheria outro Sávio, e foi a escalação que acertou.

### Como validar — e transformar em resultado do TCC

Sortear uma amostra de ligações automáticas, conferir manualmente e reportar **precisão**
(quantas ligações estavam certas) e **cobertura** (quantos atletas da StatsBomb foram
ligados). É uma avaliação quantitativa simples e defensável da etapa de integração.

---

## 4b. Resultado medido da integração

Sobre 182 partidas de quatro competições (Copa América 2024, Copa do Mundo 2022, Euro 2024
e La Liga 2020/21):

| Etapa | Resultado |
|---|---|
| Partidas ligadas | 182 de 182 |
| Equipes ligadas | 71 |
| Atletas ligados | **1.532 de 1.583 (96,8%)** |
| — por escalação da partida | 703 |
| — por nome e nacionalidade | 827 |
| — por nome único no dataset | 2 |
| Precisão do método por nome | **98,6%** (633 de 642) |
| Cobertura do método por nome | 90,0% |
| Casos para revisão manual | 51 (3,2%) |
| Biografia preenchida | 1.511 datas de nascimento, 1.512 alturas e pés preferenciais |
| Valor de mercado | 41.781 registros de valorização, 1.239 fins de contrato |
| Clima | 182 de 182 partidas, 51 estádios localizados (7 por coordenada manual) |

A precisão do método por nome é medida **contra as ligações por escalação**, que servem de
gabarito: o método é aplicado como se aqueles atletas não estivessem ligados, e a resposta é
comparada com a ligação conhecida.

---

## 5. Ordem sugerida dentro do prazo

1. ~~**transfermarkt-datasets.**~~ **Feito.** Ficha básica, valor de mercado e contrato.
2. ~~**Open-Meteo.**~~ **Feito.** Uma requisição por estádio cobre todas as suas partidas.
   Exigiu geocodificar os estádios, que nenhuma das fontes de partida traz.
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
- Nominatim (OpenStreetMap), usado para geocodificar estádios: <https://nominatim.org/>
- Wikidata, usada nas coordenadas que o Nominatim não resolve: <https://www.wikidata.org/>
- Metrica Sports sample data: <https://github.com/metrica-sports/sample-data>
- SkillCorner open data: <https://github.com/SkillCorner/opendata>
