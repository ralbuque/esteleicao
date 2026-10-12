"""
Uma linha por ELEITOR a partir dos logs das urnas: como foi liberado, quantos cargos votou e os
horários de cada passo. Complementa logs_urna.py (que resume cada seção) sem mudar o que ele calcula:
as medidas novas (liberações pelo mesário hora a hora, por que a digital falhou, foto sem digital,
tempo de cabine) saem deste arquivo, e assim não é preciso baixar os logs de novo para cada ideia.

Uso:
    python eleitores_urna.py --ufs AC                 # baixa só os logs (como baixar_logs.py) e grava
    python eleitores_urna.py --ufs AC --apagar-brutos # apaga dados/logs_brutos_* depois de gravar
    python eleitores_urna.py --zip dados/logs_brutos_2026_1t_AC.zip

Saída: dados/eleitores_<ano>_t<turno>_<UF>.parquet, com (horários em segundos desde a meia-noite,
HORA LOCAL da urna; o fuso de cada seção está em logs_<ano>_t<turno>_<UF>.parquet):

    cd_municipio, zona, secao, ordem      seção e posição do eleitor no dia (pela hora do voto)
    t_voto, t_ident, t_lib                voto computado; mesário digitou o título/CPF; eleitor liberado
    tipo                                  0 digital, 1 sem digital cadastrada, 2 liberado pelo mesário, 3 outro
                                          (a mesma regra de logs_urna.ler_eventos)
    cargos                                quantos cargos o eleitor confirmou (6 normal; 1 = trânsito de outro estado)
    tentativas, lidas, tempo_esgotado     pedidos de digital, dedo capturado, tempo esgotado sem capturar
    foto                                  a urna mostrou a foto do eleitor (há foto no cadastro)
    ano_errado, dado_nao_confere          ano de nascimento ou dado pessoal digitado diferente do cadastro
    mesario                               liberação pelo mesário: 0, 1, 2… = qual mesário da seção liberou
                                          (ordem em que aparecem; o número do título NÃO é guardado);
                                          -2 = a urna não conseguiu associar a um mesário; -1 = não se aplica
    inativo, corrigiu                     eleitor ficou parado na cabine; corrigiu algum voto
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from download_tse import SemDownloadParcial, baixar_so_logs
from logs_urna import (EXT_LOG, HAB_DIGITAL, HAB_MANUAL, HAB_OUTRO, HAB_SEM_CADASTRO, MSG_ANO_NASCIMENTO, MSG_BIO,
                       MSG_MANUAL, MSG_PRONTA, MSG_SEM_CADASTRO, MSG_VOTO, RE_NOME, extrair_logd)

PASTA = Path(__file__).parent / "dados"
URL = ("https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes{ano}/arqurnatot/"
       "bu_imgbu_logjez_rdv_vscmr_{ano}_{turno}t_{uf}.zip")
UFS = ["AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA",
       "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO", "ZZ"]
RE_MESARIO = re.compile(r"^Mesário (\d+) habilitou o eleitor")
SEM_MESARIO = "Não é possível associar a habilitação a um mesário"
COLUNAS = ["t_voto", "t_ident", "t_lib", "tipo", "cargos", "tentativas", "lidas", "tempo_esgotado", "foto",
           "ano_errado", "dado_nao_confere", "mesario_id", "inativo", "corrigiu"]


def _seg(hora: str) -> int:
    return int(hora[0:2]) * 3600 + int(hora[3:5]) * 60 + int(hora[6:8])


def ler_eleitores(texto: str) -> list[tuple]:
    """Log (texto do logd.dat) -> uma tupla por voto computado no dia da eleição, na ordem de COLUNAS.
    mesario_id é o número do mesário no log (só usado para numerar, nunca gravado)."""
    linhas, dias = [], Counter()
    for linha in texto.splitlines():
        p = linha.split("\t")
        if len(p) < 5 or p[3] != "VOTA":
            continue
        dia = p[0][:10]
        if p[4] == MSG_VOTO:
            dias[dia] += 1
        linhas.append((dia, p[0][11:19], p[4]))
    if not dias:
        return []
    dia_eleicao = dias.most_common(1)[0][0]
    saida, ev = [], None
    for dia, hora, msg in linhas:
        if dia != dia_eleicao:
            continue
        if msg in MSG_PRONTA:
            ev = {"t_ident": -1, "t_lib": -1, "hab": HAB_OUTRO, "cargos": 0, "tent": 0, "lidas": 0, "esg": 0,
                  "foto": 0, "ano": 0, "dado": 0, "mes": "", "ina": 0, "cor": 0}
            continue
        if ev is None:  # voto antes da primeira "urna pronta" (não deveria acontecer): classifica como outro
            ev = {"t_ident": -1, "t_lib": -1, "hab": HAB_OUTRO, "cargos": 0, "tent": 0, "lidas": 0, "esg": 0,
                  "foto": 0, "ano": 0, "dado": 0, "mes": "", "ina": 0, "cor": 0}
        # mesma regra de habilitação de logs_urna.ler_eventos
        if msg == MSG_BIO:
            ev["hab"] = HAB_DIGITAL
        elif msg == MSG_SEM_CADASTRO:
            ev["hab"] = HAB_SEM_CADASTRO
        elif msg == MSG_ANO_NASCIMENTO and ev["hab"] == HAB_OUTRO:
            ev["hab"] = HAB_SEM_CADASTRO
        elif msg == MSG_MANUAL:
            ev["hab"] = HAB_MANUAL
        elif msg == MSG_VOTO:
            saida.append((_seg(hora), ev["t_ident"], ev["t_lib"], ev["hab"], ev["cargos"], ev["tent"], ev["lidas"],
                          ev["esg"], ev["foto"], ev["ano"], ev["dado"], ev["mes"], ev["ina"], ev["cor"]))
            ev = None
        # detalhes (não mudam a classificação)
        elif msg.startswith("Identificador do eleitor digitado"):
            if ev["t_ident"] < 0:
                ev["t_ident"] = _seg(hora)
        elif msg == "Eleitor foi habilitado":
            ev["t_lib"] = _seg(hora)
        elif msg.startswith("Voto confirmado para"):
            ev["cargos"] += 1
        elif msg.startswith("Solicita digital. Tentativa"):
            ev["tent"] += 1
        elif msg.startswith("Capturada a digital. Tentativa"):
            ev["lidas"] += 1
        elif msg.startswith("Timeout de reconhecimento"):
            ev["esg"] += 1
        elif msg == "Foto do eleitor apresentada":
            ev["foto"] = 1
        elif msg.startswith("Ano de nascimento digitado é diferente"):
            ev["ano"] = 1
        elif msg.startswith("Dado digitado não confere"):
            ev["dado"] = 1
        elif m := RE_MESARIO.match(msg):
            ev["mes"] = m.group(1)
        elif SEM_MESARIO in msg:
            if not ev["mes"]:
                ev["mes"] = "?"
        elif msg.startswith("Eleitor sem atividade"):
            ev["ina"] = 1
        elif msg.startswith("Eleitor corrigiu"):
            ev["cor"] = 1
    return saida


def _processar(item):
    """Um log -> (chave da seção, matriz int32 com as colunas numéricas, vetor int64 do mesário).
    Matrizes compactas já no processo filho: listas de tuplas de 26 milhões de eleitores (SP) não cabem na memória."""
    nome, conteudo = item
    try:
        votos = ler_eleitores(extrair_logd(conteudo))
    except Exception as e:
        return nome, None, f"{type(e).__name__}: {e}"
    m = RE_NOME.search(nome)
    if not m:
        return nome, None, "não foi possível identificar a seção pelo nome"
    i_mes = COLUNAS.index("mesario_id")
    num = np.array([[v for j, v in enumerate(r) if j != i_mes] for r in votos], dtype=np.int32).reshape(len(votos), len(COLUNAS) - 1)
    mes = np.array([-2 if r[i_mes] == "?" else -1 if r[i_mes] == "" else int(r[i_mes]) for r in votos], dtype=np.int64)
    return nome, (tuple(int(x) for x in m.groups()), num, mes), None


def _lote(itens):
    return [_processar(i) for i in itens]


def processar_zip(caminho: Path, uf: str, processos: int) -> pd.DataFrame:
    from concurrent.futures import ProcessPoolExecutor
    por_secao = defaultdict(list)
    erros = []
    with zipfile.ZipFile(caminho) as zf:
        infos = [i for i in zf.infolist() if i.filename.lower().endswith(EXT_LOG)]
        print(f"  {len(infos):,} logs a processar", flush=True)
        t0 = time.time()

        def lotes():
            for k in range(0, len(infos), 32):
                yield [(i.filename, zf.read(i)) for i in infos[k:k + 32]]

        feitos = 0
        with ProcessPoolExecutor(max_workers=max(1, processos)) as ex:
            for res in ex.map(_lote, lotes(), chunksize=1):
                for nome, r, erro in res:
                    if erro:
                        erros.append((nome, erro))
                    elif len(r[1]):
                        por_secao[r[0]].append((r[1], r[2]))
                feitos += len(res)
                if feitos % 2000 < 32:
                    print(f"\r  {feitos:,}/{len(infos):,} logs  ({feitos / (time.time() - t0):,.0f}/s)   ", end="", flush=True)
    print(f"\r  {sum(len(a) for v in por_secao.values() for a, _ in v):,} eleitores em {len(por_secao):,} seções, {len(erros)} logs com erro")
    for nome, erro in erros[:10]:
        print(f"    ! {nome}: {erro}")
    cols = [c for c in COLUNAS if c != "mesario_id"]
    tipos = {"t_voto": "int32", "t_ident": "int32", "t_lib": "int32", "tipo": "int8", "cargos": "int8",
             "tentativas": "int8", "lidas": "int8", "tempo_esgotado": "int8", "foto": "int8", "ano_errado": "int8",
             "dado_nao_confere": "int8", "inativo": "int8", "corrigiu": "int8"}
    blocos, chaves, mesarios = [], [], []
    for (mun, zona, secao), logs in por_secao.items():
        num = np.concatenate([a for a, _ in logs])
        mes = np.concatenate([b for _, b in logs])
        ordem = np.argsort(num[:, 0], kind="stable")
        num, mes = num[ordem], mes[ordem]
        # mesário: 0, 1, 2… na ordem em que aparece na seção (o número do título não é guardado)
        rot = np.full(len(mes), -1, dtype=np.int8)
        rot[mes == -2] = -2
        reais = mes >= 0
        if reais.any():
            _, primeira, inv = np.unique(mes[reais], return_index=True, return_inverse=True)
            ordem_aparicao = np.argsort(np.argsort(primeira))
            rot[reais] = np.minimum(ordem_aparicao[inv], 127)
        blocos.append(pd.DataFrame({c: num[:, k].astype(tipos[c]) for k, c in enumerate(cols)}))
        mesarios.append(rot)
        chaves.append((mun, zona, secao, len(num)))
    if not blocos:
        return pd.DataFrame()
    df = pd.concat(blocos, ignore_index=True)
    df["mesario"] = np.concatenate(mesarios)
    n = np.array([c[3] for c in chaves])
    df.insert(0, "ordem", np.concatenate([np.arange(1, k + 1) for k in n]).astype("int16"))
    df.insert(0, "secao", np.repeat([c[2] for c in chaves], n).astype("int16"))
    df.insert(0, "zona", np.repeat([c[1] for c in chaves], n).astype("int16"))
    df.insert(0, "cd_municipio", np.repeat([c[0] for c in chaves], n).astype("int32"))
    return df


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ano", type=int, default=2026)
    p.add_argument("--turno", type=int, default=1)
    p.add_argument("--ufs", nargs="+", default=UFS, type=str.upper)
    p.add_argument("--zip", type=Path, help="Processar um zip de logs já baixado (a UF é lida do nome)")
    p.add_argument("--apagar-brutos", action="store_true", help="Apagar dados/logs_brutos_* depois de gravar")
    p.add_argument("--conexoes", type=int, default=8)
    p.add_argument("--refazer", action="store_true")
    p.add_argument("--processos", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    a = p.parse_args()
    PASTA.mkdir(exist_ok=True)
    if a.zip:
        m = re.search(r"_(\d{4})_(\d)t_([A-Z]{2})\.zip$", a.zip.name, re.I)
        tarefas = [(m.group(3).upper(), int(m.group(1)), int(m.group(2)), a.zip)] if m else [(input("UF: ").upper(), a.ano, a.turno, a.zip)]
    else:
        tarefas = [(uf, a.ano, a.turno, None) for uf in a.ufs]
    for uf, ano, turno, zip_local in tarefas:
        saida = PASTA / f"eleitores_{ano}_t{turno}_{uf}.parquet"
        if saida.exists() and not a.refazer:
            print(f"{uf}: já processado ({saida.name})")
            continue
        print(f"\n=== {uf} ({ano}, {turno}º turno): eleitores ===", flush=True)
        brutos = PASTA / f"logs_brutos_{ano}_{turno}t_{uf}.zip"
        caminho = zip_local
        if caminho is None:
            try:
                caminho, n_total, n_falhas = baixar_so_logs(URL.format(ano=ano, turno=turno, uf=uf), brutos, EXT_LOG, a.conexoes)
            except SemDownloadParcial:
                print("  ! o servidor não aceitou baixar só os logs")
                continue
            except Exception as e:
                print(f"  ! falha no download: {e}. Rode de novo: continua de onde parou.")
                continue
            if n_falhas:
                print(f"  ! {n_falhas} de {n_total:,} logs não vieram. Rode de novo para buscar só os que faltam.")
                continue
        df = processar_zip(caminho, uf, a.processos)
        if df.empty:
            print("  ! nenhum eleitor encontrado")
            continue
        df.insert(0, "uf", uf)
        df["uf"] = df["uf"].astype("category")
        df.to_parquet(saida, index=False)
        t = df["tipo"].value_counts().reindex(range(4), fill_value=0)
        print(f"  {len(df):,} eleitores: digital {t[0]:,}, sem digital cadastrada {t[1]:,}, pelo mesário {t[2]:,}, outro {t[3]:,}"
              f" | {saida.stat().st_size / 1e6:,.0f} MB")
        if a.apagar_brutos and zip_local is None and brutos.exists():
            brutos.unlink()
    return 0


if __name__ == "__main__":
    sys.exit(main())
