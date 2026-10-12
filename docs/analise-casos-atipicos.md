# Análises de out/2026: liberação pelo mesário, tempo de voto e casos extremamente atípicos

Resumo das amostragens feitas com os dados reais do 1º turno de 2026 (sessão na nuvem de 12/out),
para continuar a implementação. Nada aqui muda os 3 critérios do site. Tudo que virar tela entra
como **tag** (fora da contagem dos critérios), com filtro em "Seções em atenção", e é mostrado ao
usuário com os números nacionais **antes de publicar**.

## 1. Já implementado e publicado (Parte 1)

Tags de liberação pelo mesário (`extras.liberacoes`, bits em `flags_lib`):

| Tag | Regra | Brasil (rigor padrão) |
|---|---|---|
| Mesário após 17h | liberações pelo mesário depois das 17h ≥ 20 / 10 / 5 (rigoroso/padrão/amplo) | 1.087 seções, 16.003 liberações |
| Salto às 17h | ≥ 10 liberações depois das 17h; taxa depois das 17h − taxa do dia ≥ 50 / 40 / 30 p.p. e ≥ 2× a do dia; a taxa das 14h–16h não pode ter subido mais que 15 p.p. sobre a das 8h–13h (senão começou antes = leitor quebrado) | 3 (Trindade-GO z49 s132, Içara-SC z79 s294, Cariacica-ES z54 s509); amplo: 7 |
| Leitor com defeito provável | ≥ 80% de quem tem digital liberado pelo mesário o dia todo, ou a partir de uma hora até as 16h (com ≤ 30% antes e ≥ 20 eleitores no período ruim) | 107 (92 o dia todo) |

Brasil: 194.295 liberações pelo mesário depois das 17h (5,6% de quem tinha digital nesse horário),
contra 7,1% antes das 17h. Em todos os 27 estados a taxa é menor depois das 17h (de manhã votam mais idosos).

## 2. O que o log da urna permite saber de cada eleitor (2026)

- A urna **só pede a digital de quem tem digital cadastrada** ("Solicita digital. Tentativa N de 4").
  Quem não tem é liberado só pelo ano de nascimento ("Ano de nascimento digitado é igual ao do cadastro"),
  sem nenhum pedido de digital. Conferido com o perfil do eleitorado (cadastro de biometria do TSE): onde o
  cadastro diz que todos têm digital, só 0,3% dos votos aparecem como "sem digital cadastrada"; correlação 0,87 por seção.
- **Liberação pelo mesário** sempre vem depois das 4 tentativas (amostra de 3.648 em AL: 100%). Motivo da falha:
  93,6% "dedo lido e não reconhecido", 5,8% parte tempo esgotado, 0,6% leitor não leu nenhuma vez.
- "Batimento de digitais retornou o score N" é da **conferência da digital do mesário**, não do eleitor.
- "Mesário N habilitou o eleitor" identifica o mesário que liberou (~60% dos casos; senão "não é possível associar").
  É normal um único mesário fazer todas; concentração sozinha não diferencia. Nunca publicar o número.
- "Foto do eleitor apresentada": há foto no cadastro (coletada junto com a biometria).
- Cargos confirmados por eleitor: 6 normal; **1 = voto em trânsito de outro estado** (só Presidente).

`eleitores_urna.py` grava uma linha por eleitor (`dados/eleitores_<ano>_t<turno>_<UF>.parquet`) com tudo isso;
conferido com `logs_urna` (mesma classificação, seção por seção). Já gerados na nuvem para 19 UFs; faltam
SP, RJ, MG, MT, MS, DF, SE, BA (no Mac: rodar sem `--apagar-brutos` para nunca mais baixar).

## 3. Tempo de voto (amostra de 20.059 eleitores em 69 seções)

- Cabine (liberado → voto computado), eleitores de 6 cargos: mínimo observado 18 s; p0,1 23 s; p1 29 s; mediana 55 s.
  Menor intervalo entre dois cargos: 2 s. Identificação (mesário digita → liberado): mediana 15 s. Espera entre eleitores: mediana 20 s.
- As seções "mais rápidas do país" pelo intervalo entre votos eram **seções de voto em trânsito** (eleitores de 1 cargo,
  ~11 s na cabine). A métrica atual "votos rápidos em sequência" se confunde com trânsito e fila e nunca disparou
  (máximo 5 seguidos). Proposta aprovada: trocar por "eleitores de 6 cargos abaixo do piso nacional (~25 s), vários seguidos",
  como sinal no detalhe (não critério).
- Nenhum grupo suspeito teve cabine mais rápida que as seções sorteadas.

## 4. Fraudes de identidade e compra de votos: o que separou e o que não separou

Não separou (comum/explicado): votos a mais vindos sem digital (nas 25.360 seções com 20+ votos acima do esperado, só 10%
do excesso foi sem digital, abaixo da média 12,2%); voto em trânsito (77–98% dos transferidos de outro estado votam;
origem nunca concentrada: no máximo 7 de uma mesma seção); rajadas de votos em 10 minutos.

Separou (Parte 2; resultado com os dados reais na seção 7):
- **Leitor com defeito × liberação seletiva**: as campeãs de liberação pelo mesário (Trindade-GO z49 s123, Dias d'Ávila,
  Simões Filho, S. Francisco do Conde, Angélica-MS, Serra-ES) têm 0 digitais reconhecidas desde as 8h = leitor quebrado.
  "Liberação seletiva" = leitor reconhecendo a maioria na mesma hora, mas alguns eleitores liberados pelo mesário
  (marca de impostor). Nhamundá-AM z43 s47: leitor bom até 15h, falhas crescentes no fim do dia.
- **Sem digital mas com foto**: em Ulianópolis-PA z84 (10 seções), Maracajá e Balneário Arroio do Silva (SC), 54% dos
  "sem digital cadastrada" tiveram foto (seções sorteadas: 7%). E nelas votaram mais "sem digital" do que o cadastro
  de julho tem (27 seções no país; usar só seções em que o perfil de julho bate com os aptos ±3%).
- Comparecimento de quem tem digital 83,5% × de quem não tem 41,4% (Brasil).

## 5. Casos extremamente atípicos de horário (IMPLEMENTADO e publicado em 12/out/2026)

Origem: o usuário apontou Lauro de Freitas-BA z180 s529 (nenhum voto até 16h59) e s232 (votos até 20h19).

- s529: comparecimento oficial 270, **26 votos no log**, urna "abriu" às 17h32 → 244 votos fora do log (urna trocada sem o
  1º log publicado, ou cédula).
- s232: 23–30 votos por hora o dia todo e também 17h–20h; leitor falhou com 97% (tags "leitor com defeito" e "mesário após 17h").
  A **zona 180 inteira** votou até 19–20h (dezenas de seções, 42 locais): congestionamento da zona.

Testado no país e **descartado** (comum, congestionamento): "ritmo não cai depois das 17h" (17.380 seções; zonas inteiras como
Maceió z54 com 174), "pico depois das 18h" (5.955), "terminou depois das outras da escola" sem filtros (736, dos quais 201 com seção
agregada e 79 bem maiores que as vizinhas: mais eleitores na mesma urna).

**Proposta (3 tags + lista "Casos extremamente atípicos" + contexto de zona):**

| Tag | Regra | Brasil |
|---|---|---|
| Votos fora do log | comparecimento oficial − votos no log ≥ 50 | 1.281 seções, 169.230 votos (639 com < metade no log; 26 com log vazio). Ex.: Grajaú-MA z15 s321 (7 no log, 320 oficiais) |
| Urna começou tarde | 1ª vez pronta (Brasília) ≥ 15h | 358 (73 depois das 17h) |
| Terminou sozinha | último voto ≥ 60 min depois da última OUTRA seção do mesmo local; local com ≥ 3 seções; outras seções do local com média ≤ 5 votos após 17h; ≥ 20 votos após 17h; sem seção agregada; aptos < 1,3 × média das outras seções do local | 456. Ex.: Cícero Dantas-BA z82 s155 (301 aptos como as vizinhas; 79 votos após 17h até 19h30; vizinhas 0,5) |
| (já existe) Salto às 17h | ver seção 1 | 3 |

União: 1.716 seções; 370 com 2+ padrões (as mais extremas). Por UF: SP 274, BA 160, RJ 153, MG 144.
Contexto: "zona inteira votou até tarde" (fração de seções da zona com último voto depois das 19h) para ler essas seções como congestionamento.

Notas de dados: `secao_principal` em `dados/locais_2026.parquet` identifica as seções agregadas; `abertura`, `ultimo_voto`,
`ociosa_antes_17_min` e os histogramas `h00..h23` (hora LOCAL; converter pelo `fuso`) estão em `dados/logs_*.parquet`.

### 5.1 Como ficou (dados reais, `extras.atipicos`)

- Contagens confirmadas: votos fora do log 1.281 seções (169.230 votos; 637 com menos da metade no log; 26 com log vazio); urna começou
  tarde 358 (73 depois das 17h); terminou sozinha 456 (20.682 votos após 17h); salto às 17h 3; união 1.718.
- **Toda seção com "urna começou tarde" também tem "votos fora do log"** (358 de 358), e em todas as 1.255 seções com votos fora do log
  e algum log a urna do log ficou pronta depois das 9h. É um evento só (troca de urna): a dupla conta como UM padrão. Com isso, 21 seções
  reúnem 2+ padrões diferentes (fora do log + terminou sozinha: 21, das quais 9 também com urna tarde; Trindade-GO z49 s132 tem fora do
  log, terminou sozinha e salto às 17h).
- Contexto de zona: seções da zona com último voto depois das 19h. Metade das zonas do país não tem nenhuma (4.418 de 6.106); p90 = 6,8%,
  p95 = 11,4%. "Zona votou até tarde" = 5% ou mais (826 zonas). Lauro de Freitas z180: 24 de 413 (6%); Maceió z54: 102 de 338 (30%).

## 6. Amostragens de 12/out/2026 (país inteiro; nada virou tag)

Base: 124.746.009 votos, 8.319.736 liberações pelo mesário. Arquivos: `dados/eleitores_*`, `dados/urnas_*`.

a) **Mesmo mesário em seções diferentes** (código embaralhado, 61% das liberações têm mesário identificado; 695.124 mesários): 117 em 2+
   seções (1.387 liberações); 106 no mesmo local (mediana de 2 liberações na 2ª seção); 8 em locais diferentes do mesmo município; 3 em
   municípios diferentes (Mauá/Birigui-SP, Itanhaém/Peruíbe-SP, Palmas/Porto Nacional-TO; em Itanhaém/Peruíbe os horários se sobrepõem,
   o que sugere erro de reconhecimento da digital do mesário, não verificado).
b) **Dado do eleitor não conferiu antes da liberação**: 113.473 liberações (1,36%). No log, a urna pede o dado de novo e só libera quando
   confere ("Dado digitado não confere" → nova solicitação → "Dado digitado confere"). 53 seções com 10+ casos e 50%+ das liberações
   (Coronel José Dias-PI z13 s199: 60 de 60); só 4 delas têm o critério de liberação manual. Hábito de digitação do mesário.
c) **Liberação rápida** (urna pede o dado → eleitor liberado): mediana 24 s, p1 10 s, mínimo 4 s. 118 seções com 20+ liberações em até 10 s
   e 50%+ do total; 450 de 45.585 mesários (com 20+ liberações) têm mediana ≤ 10 s. Nada fisicamente impossível.
d) **BU e RDV** (arquivos `-bu.dat` e `-rdv.dat` do zip do TSE, ASN.1; lidos por HTTP Range só para a amostra): 3.216 seções (1.716 com
   tag atípica + 1.500 sorteadas). Comparecimento do BU = oficial, votos para presidente do BU = votação por seção, RDV = BU em todos os
   cargos: 3.216 de 3.216. O BU traz a contagem digital / sem digital / mesário, que bate com a nossa classificação do log nas 1.926
   seções com log completo. Nas 1.281 com votos fora do log, o BU tem TODOS os votos (323.717), registra a abertura às 8h e foi emitido
   pela mesma urna do log publicado: troca de urna, com o log da primeira não publicado (não é cédula de papel).
e) **Mesma urna em mais de uma seção**: nenhuma. 497.869 seções com voto, 497.869 urnas distintas; cada seção tem um único arquivo de log
   e uma única urna (o sinal "urna substituída", `n_urnas > 1`, nunca dispara em 2026).

## 7. Parte 2 com os dados reais (12/out/2026; implementada)

Medidas por seção em `medidas_eleitores.py` (país inteiro, sem o exterior).

1. **Liberação seletiva × leitor com defeito**: "leitor funcionando em volta" = pelo menos 8 dos 10 eleitores com digital mais próximos
   (5 antes, 5 depois) reconhecidos. Brasil: 7.380.452 de 8.319.736 liberações (88,7%); nas 107 seções com leitor com defeito, ~0%.
   Das 7.515 seções com o critério de liberação manual, 651 têm 30+ liberações assim (80%+ do total), mas com 17% de eleitores de 70+
   (Brasil: 9%) e taxa de 13–18%: perfil de idosos, não um grupo suspeito. Decisão: sem tag; só a frase com os números no detalhe.
2. **Sem digital cadastrada, mas com foto** ("Foto do eleitor apresentada" em quem foi liberado só pelo ano de nascimento): 327.175 de
   6.931.133 (4,7%; PR 36,8%, MT 12,9%, SP 9,0%). Tag: 20+ e 50%+ dos sem digital → 116 seções em 36 municípios (Ulianópolis-PA 23,
   Maracajá-SC 15, Balneário Arroio do Silva-SC 14, Nazaré Paulista-SP 12, Indaiatuba-SP 9).
3. **Sem digital > cadastro** (perfil de julho bate com os aptos ±3% em 475.134 seções): 46 seções com 20+ votos "sem digital" além dos
   eleitores sem biometria do cadastro; 44 delas estão entre as 116 do item 2. Ex.: Indaiatuba-SP z211 s438, 337 eleitores todos com
   biometria no cadastro, 59 votaram como sem digital, 53 com foto. Hipótese NÃO verificada: biometria coletada/importada depois da
   preparação das urnas. Entrou como parte da tag do item 2 (comparação no detalhe da seção).
4. **Tempo de cabine** (liberado → voto computado, eleitores de 6 cargos: 124.538.798): mediana por seção 55 s; menos de 25 s: 169.994
   (0,14%); menos de 20 s: 12.451 (0,01%). 3+ seguidos abaixo de 25 s: 8 seções; sinal (3+ seguidos ou 10+ no dia): 10 seções.
   São Paulo de Olivença-AM z22 s97 (13 seguidos às 19h03, 47 no dia), São Gabriel da Cachoeira-AM z19 s33 (9 seguidos às 16h52),
   Bom Lugar-MA z66 (s41: 5 seguidos; s121 e s312 com 12 e 13 no dia).

## 8. Aba "Simule o 2º turno" (12/out/2026; implementada)

Não é análise de seções atípicas nem previsão: soma os votos oficiais do 1º turno e deixa a pessoa escolher a divisão dos votos em jogo.

Presidente, 1º → 2º turno (TSE, `detalhe_votacao_munzona_<ano>.zip`, linha BRASIL; conferido em 12/out/2026):

| Ano | Dois finalistas no 1º turno | Abstenção | Brancos | Nulos | Votos válidos |
|---|---|---|---|---|---|
| 2010 | 79,5% | 24.610.296 → 29.197.152 | 3.479.340 → 2.452.597 | 6.124.254 → 4.689.428 | 101.590.153 → 99.463.917 (−2.126.236) |
| 2014 | 75,1% | 27.698.475 → 30.137.479 | 4.420.489 → 1.921.819 | 6.678.592 → 5.219.787 | 104.023.802 → 105.542.273 (+1.518.471) |
| 2018 | 75,3% | 29.941.171 → 31.372.373 | 3.106.937 → 2.486.593 | 7.206.222 → 8.608.105 | 107.050.749 → 104.838.753 (−2.211.996) |
| 2022 | 91,6% | 32.770.982 → 32.200.558 | 1.964.779 → 1.769.678 | 3.487.874 → 3.930.765 | 118.229.719 → 118.552.353 (+322.634) |
| 2026 | 92,2% | 33.469.244 → ? | 2.300.798 → ? | 3.669.003 → ? | 119.306.034 → ? |

A fatia dos dois finalistas (2010 a 2022) é o resultado oficial divulgado, não recalculado dos arquivos por candidato.

Fórmula do cenário de presidente (`simulador.ajuste_referencia`), com f = eleitorado 2026 ÷ eleitorado 2022 = 158.745.502 ÷ 156.454.011:
voltam = 570.424 × f = 578.779; anulam = 442.891 × f = 449.378; saldo = 322.634 × f = 327.359; brancos que escolhem = saldo + anulam −
voltam = 197.958 (195.101 × f daria 197.959; a diferença de 1 voto é arredondamento). Grupo 1 = 9.321.993 − 449.378 = 8.872.615;
Grupo 2 = 776.737. Ponto de virada: o 2º colocado precisa de mais de (Grupo 1 + Grupo 2 + diferença) ÷ 2 = 5.937.159 dos 9.649.352 (61,5%).

Limites declarados na tela: uma eleição só de referência; não considera quem votou num finalista e muda de lado ou não volta; a origem
dos nulos a mais (eleitores de quem ficou de fora) é suposição. Governadores não usam a referência de 2022.
