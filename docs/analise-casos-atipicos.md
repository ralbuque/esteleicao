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

Separou (a implementar, Parte 2):
- **Leitor com defeito × liberação seletiva**: as campeãs de liberação pelo mesário (Trindade-GO z49 s123, Dias d'Ávila,
  Simões Filho, S. Francisco do Conde, Angélica-MS, Serra-ES) têm 0 digitais reconhecidas desde as 8h = leitor quebrado.
  "Liberação seletiva" = leitor reconhecendo a maioria na mesma hora, mas alguns eleitores liberados pelo mesário
  (marca de impostor). Nhamundá-AM z43 s47: leitor bom até 15h, falhas crescentes no fim do dia.
- **Sem digital mas com foto**: em Ulianópolis-PA z84 (10 seções), Maracajá e Balneário Arroio do Silva (SC), 54% dos
  "sem digital cadastrada" tiveram foto (seções sorteadas: 7%). E nelas votaram mais "sem digital" do que o cadastro
  de julho tem (27 seções no país; usar só seções em que o perfil de julho bate com os aptos ±3%).
- Comparecimento de quem tem digital 83,5% × de quem não tem 41,4% (Brasil).

## 5. Casos extremamente atípicos de horário (proposta, ainda não implementada)

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
