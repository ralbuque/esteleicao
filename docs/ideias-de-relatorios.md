# Próximos relatórios e dados para orientar a fiscalização

> **Out/2026: todos os itens abaixo foram implementados** na aba "Mais análises"
> (`extras.py`, `gerar_site.py`, `web/app.js`), testados com dados sintéticos
> (`python testar_sem_internet.py`). Falta rodar com os dados reais e conferir os
> nomes das colunas dos arquivos novos do TSE. Exceção: o formulário de ocorrências
> que volta para o site (item 8) virou campos em branco na ficha impressa; registrar
> online exige um servidor, e o site é estático.

Ideias para ampliar o site, em ordem de prioridade. Todas usam dados abertos
(TSE, IBGE) e seguem o mesmo princípio do site: comparar cada seção com as
vizinhas, mostrar **quantidade** ao lado da porcentagem e tratar destaque como
motivo para olhar de perto, não como prova.

## 1. Materialidade: os votos em atenção mudariam o resultado?

**Pergunta:** quantos votos estão em seções em atenção, comparados com a
diferença entre o 1º e o 2º colocado em cada disputa?

- Por município (prefeito não está em disputa em 2026, mas vale para
  governador e senador por UF, e para presidente no Brasil): somar votos
  após 17h, liberações manuais e o "excesso de comparecimento" (comparecimento
  observado menos o esperado) das seções em atenção.
- Mostrar lado a lado com a margem de vitória. Ex.: "nas seções em atenção do
  Ceará houve 4.120 votos após 17h; a diferença para o 2º colocado ao Senado
  foi de 312 mil votos".
- É o relatório que mais ajuda a dimensionar a preocupação e evita que uma
  porcentagem alta numa seção pequena pareça maior do que é.
- Dado: "Votação por seção eleitoral" (TSE, resultados 2026), com votos por
  candidato em cada seção.

## 2. Concentração de votos num candidato por seção

**Pergunta:** em quais seções um candidato teve uma fatia de votos muito acima
da que teve no resto do município?

- Mesmo método do z ajustado da abstenção, aplicado à fatia de cada candidato
  (principalmente deputados, onde o voto é mais local).
- Cruzar com abstenção baixa: seção com comparecimento muito alto **e** voto
  muito concentrado é o padrão clássico de compra de votos ou de transporte de
  eleitores ("curral").
- Brancos e nulos muito abaixo do normal na mesma seção reforçam o sinal.
- Dado: "Votação por seção eleitoral" (TSE).

## 3. Perfil do eleitorado da seção (para explicar o que é normal)

**Pergunta:** a seção destoa mesmo depois de considerar quem vota nela?

- O TSE publica o "Perfil do eleitorado por seção eleitoral" (2026): faixa
  etária, escolaridade, gênero, biometria.
- Eleitores com 70 anos ou mais e de 16–17 anos têm voto facultativo e faltam
  mais; idosos têm mais falhas de digital. Usar esses dados no valor esperado
  reduz os falsos alarmes de abstenção e de liberação manual, e deixa na lista
  só o que o perfil não explica.
- Mostrar no detalhe da seção: "esta seção tem 31% de eleitores com 70+
  (município: 12%)".

## 4. Cadastro inflado e transferências de título

**Pergunta:** o município tem mais eleitores do que o esperado pela população?

- Razão eleitores ÷ população com 16 anos ou mais (IBGE). Acima de 1 indica
  cadastro com eleitores que não moram lá.
- Crescimento do eleitorado entre 2022 e 2026 por município e por seção,
  comparado com o crescimento da população. Transferências em massa para
  municípios pequenos antes da eleição são um vetor conhecido de fraude.
- Dados: "Eleitorado" (TSE, várias eleições) e estimativas de população (IBGE).

## 5. Repetição entre eleições e entre turnos

- **2022 × 2026:** a seção destoava em 2022 também? Se sim, quase sempre é
  causa estrutural (perfil do local). Se é novidade em 2026, sobe a prioridade.
  O projeto já baixa 2022 (`--ano 2022`); falta cruzar as duas bases.
- **1º × 2º turno (25/10/2026):** comparecimento que **sobe** muito numa seção
  entre os turnos, ou votos após 17h que aparecem só no 2º turno, onde havia
  fiscal designado a partir deste plano. Útil também para medir o efeito da
  presença de fiscais.

## 6. Contexto do local de votação

- Tipo do local (o cadastro de locais traz o tipo: zona rural, aldeia
  indígena, unidade prisional, seções agregadas). Explica abstenção e horário
  fora do padrão e deve aparecer no detalhe da seção.
- Voto em trânsito ("Transferência temporária do eleitorado por seção"):
  seções que recebem muitos eleitores em trânsito têm comparecimento diferente.

## 7. Gastos de campanha onde há seções em atenção

- Prestação de contas (TSE): despesas com transporte, combustível e
  pagamentos a pessoas físicas (cabos eleitorais) por município.
- Gasto muito alto por eleitor em municípios com várias seções em atenção é
  um sinal adicional de compra de votos ou transporte ilegal de eleitores.

## 8. Relatórios operacionais para o dia da eleição

- **Rota do fiscal:** agrupar os locais de prioridade alta por bairro e
  ordenar por proximidade (as coordenadas do TSE já estão no site), para um
  fiscal cobrir mais de um local quando eles ficam perto.
- **Ficha da escola para imprimir:** uma página por local com as seções a
  observar, os números do 1º turno e o checklist (abstenção, 17h, liberação
  manual).
- **Formulário de ocorrências:** o fiscal registra fila às 17h, horário do
  último voto, liberações manuais e troca de urna; os dados voltam para o
  site e permitem comparar o que foi visto com o log da urna depois.

## Já disponível nos logs e ainda não explorado

- **Votos antes da abertura:** listar seções com qualquer voto computado no
  dia da eleição antes das 8h (horário de Brasília), em quantidade. Hoje esses
  votos entram na faixa das 8h.
- **Intervalo entre votos:** sequências longas de votos muito rápidos (menos
  de 30 s entre um e outro) em qualquer horário, não só depois das 17h.
- **Liberações manuais por hora:** concentração de liberações manuais no fim
  do dia, quando a mesa já sabe quem faltou.
