"""
Uma linha por ELEITOR a partir dos logs das urnas: como foi liberado, quantos cargos votou e os
horários de cada passo. Complementa logs_urna.py (que resume cada seção) sem mudar o que ele calcula:
as medidas novas (liberações pelo mesário hora a hora, por que a digital falhou, foto sem digital,
tempo de cabine) saem deste arquivo, e assim não é preciso baixar os logs de novo para cada ideia.

Uso:
    python eleitores_urna.py --ufs AC                 # baixa só os logs (como baixar_logs.py) e grava
    python eleitores_urna.py --ufs AC --apagar-brutos # apaga dados/logs_brutos_* depois de gravar
    python eleitores_urna.py --zip dados/logs_brutos_2026_1t_AC.zip
    python eleitores_urna.py --conferir               # só confere os arquivos já gravados com logs_<...>.parquet

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
    t_manual, t_mesario                   liberação pelo mesário: a urna pediu o dado pessoal; o mesário pôs a digital dele
    mesario_cod                           código EMBARALHADO do mesário que liberou (0 = não se aplica ou não associado).
                                          O mesmo mesário tem o mesmo código em qualquer seção; o número do título não é
                                          guardado e não dá para voltar do código para ele sem dados/.sal_mesario
                                          (chave sorteada nesta máquina; nunca publicar nem a chave nem o código)
    urna                                  número da urna (coluna "id urna" do log) que registrou o voto

Grava também dados/urnas_<ano>_t<turno>_<UF>.parquet: uma linha por seção × arquivo de log × urna com votos no dia
da eleição (votos, primeiro e último voto, primeira e última linha do log naquele dia; hora LOCAL em segundos).
"""
from __future__ import annotations

import argparse
import hashlib
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
           "ano_errado", "dado_nao_confere", "mesario_id", "inativo", "corrigiu", "t_manual", "t_mesario", "urna"]
NUMERICAS = [c for c in COLUNAS if c not in ("mesario_id", "urna")]
ARQ_SAL = PASTA / ".sal_mesario"
_SAL = None


def _sal() -> bytes:
    """Chave local (sorteada uma vez) para embaralhar o número do mesário. Fica só em dados/ (fora do git)."""
    global _SAL
    if _SAL is None:
        if not ARQ_SAL.exists():
            PASTA.mkdir(exist_ok=True)
            ARQ_SAL.write_bytes(os.urandom(32))
        _SAL = ARQ_SAL.read_bytes()
    return _SAL


def _embaralhar(numero: str) -> int:
    return int.from_bytes(hashlib.blake2b(numero.encode(), digest_size=8, key=_sal()).digest(), "little", signed=True) or 1


def _seg(hora: str) -> int:
    return int(hora[0:2]) * 3600 + int(hora[3:5]) * 60 + int(hora[6:8])


def _novo():
    return {"t_ident": -1, "t_lib": -1, "hab": HAB_OUTRO, "cargos": 0, "tent": 0, "lidas": 0, "esg": 0,
            "foto": 0, "ano": 0, "dado": 0, "mes": "", "ina": 0, "cor": 0, "t_man": -1, "t_mes": -1}


def ler_eleitores(texto: str) -> tuple[list[tuple], list[tuple]]:
    """Log (texto do logd.dat) -> (uma tupla por voto computado no dia da eleição, na ordem de COLUNAS;
    uma tupla por urna com votos: id, votos, 1º voto, último voto, 1ª linha, última linha do dia).
    mesario_id é o número do mesário no log (só usado para numerar e embaralhar, nunca gravado)."""
    linhas, dias = [], Counter()
    for linha in texto.splitlines():
        p = linha.split("\t")
        if len(p) < 5 or p[3] != "VOTA":
            continue
        dia = p[0][:10]
        if p[4] == MSG_VOTO:
            dias[dia] += 1
        linhas.append((dia, p[0][11:19], p[4], p[2]))
    if not dias:
        return [], []
    dia_eleicao = dias.most_common(1)[0][0]
    saida, ev, urnas = [], None, {}
    for dia, hora, msg, id_urna in linhas:
        if dia != dia_eleicao:
            continue
        u = urnas.get(id_urna)
        if u is None:
            u = urnas[id_urna] = [0, -1, -1, _seg(hora), -1]  # votos, 1º voto, último voto, 1ª linha, última linha
        u[4] = _seg(hora)
        if msg in MSG_PRONTA:
            ev = _novo()
            continue
        if ev is None:  # voto antes da primeira "urna pronta" (não deveria acontecer): classifica como outro
            ev = _novo()
        # mesma regra de habilitação de logs_urna.ler_eventos
        if msg == MSG_BIO:
            ev["hab"] = HAB_DIGITAL
        elif msg == MSG_SEM_CADASTRO:
            ev["hab"] = HAB_SEM_CADASTRO
        elif msg == MSG_ANO_NASCIMENTO and ev["hab"] == HAB_OUTRO:
            ev["hab"] = HAB_SEM_CADASTRO
        elif msg == MSG_MANUAL:
            ev["hab"] = HAB_MANUAL
            if ev["t_man"] < 0:
                ev["t_man"] = _seg(hora)
        elif msg == MSG_VOTO:
            t = _seg(hora)
            saida.append((t, ev["t_ident"], ev["t_lib"], ev["hab"], ev["cargos"], ev["tent"], ev["lidas"],
                          ev["esg"], ev["foto"], ev["ano"], ev["dado"], ev["mes"], ev["ina"], ev["cor"],
                          ev["t_man"], ev["t_mes"], id_urna))
            u[0] += 1
            if u[1] < 0:
                u[1] = t
            u[2] = t
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
            ev["t_mes"] = _seg(hora)
        elif SEM_MESARIO in msg:
            if not ev["mes"]:
                ev["mes"] = "?"
                ev["t_mes"] = _seg(hora)
        elif msg.startswith("Eleitor sem atividade"):
            ev["ina"] = 1
        elif msg.startswith("Eleitor corrigiu"):
            ev["cor"] = 1
    return saida, [(k, *v) for k, v in urnas.items() if v[0]]


def _urna_num(id_urna: str) -> int:
    return int(id_urna) if id_urna.isdigit() else -1


def _processar(item):
    """Um log -> (chave da seção, matriz int32 das colunas numéricas, código embaralhado do mesário (int64),
    marca do mesário (int8: 0 real, -1 não se aplica, -2 não associado), urna de cada voto (int64), urnas do log).
    Matrizes compactas já no processo filho: listas de tuplas de 26 milhões de eleitores (SP) não cabem na memória.
    O número do mesário é embaralhado aqui e não sai do processo filho."""
    nome, conteudo = item
    try:
        votos, urnas = ler_eleitores(extrair_logd(conteudo))
    except Exception as e:
        return nome, None, f"{type(e).__name__}: {e}"
    m = RE_NOME.search(nome)
    if not m:
        return nome, None, "não foi possível identificar a seção pelo nome"
    i_mes, i_urna = COLUNAS.index("mesario_id"), COLUNAS.index("urna")
    fora = (i_mes, i_urna)
    num = np.array([[v for j, v in enumerate(r) if j not in fora] for r in votos], dtype=np.int32).reshape(len(votos), len(NUMERICAS))
    cod = np.array([_embaralhar(r[i_mes]) if r[i_mes] not in ("", "?") else 0 for r in votos], dtype=np.int64)
    marca = np.array([-2 if r[i_mes] == "?" else -1 if r[i_mes] == "" else 0 for r in votos], dtype=np.int8)
    urna = np.array([_urna_num(r[i_urna]) for r in votos], dtype=np.int64)
    return nome, (tuple(int(x) for x in m.groups()), num, cod, marca, urna, urnas), None


def _lote(itens):
    return [_processar(i) for i in itens]


def processar_zip(caminho: Path, uf: str, processos: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Devolve (eleitores, urnas)."""
    from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
    por_secao = defaultdict(list)
    erros, linhas_urna = [], []
    _sal()  # cria a chave antes de abrir os processos filhos
    with zipfile.ZipFile(caminho) as zf:
        infos = sorted((i for i in zf.infolist() if i.filename.lower().endswith(EXT_LOG)), key=lambda i: i.filename)
        print(f"  {len(infos):,} logs a processar", flush=True)
        t0 = time.time()
        feitos = 0

        def guardar(res):
            nonlocal feitos
            for nome, r, erro in res:
                if erro:
                    erros.append((nome, erro))
                    continue
                chave, num, cod, marca, urna, urnas = r
                if len(num):
                    por_secao[chave].append((num, cod, marca, urna))
                for u in urnas:
                    linhas_urna.append((*chave, nome.rsplit("/", 1)[-1], *u))
            feitos += len(res)
            if feitos % 2000 < 32:
                print(f"\r  {feitos:,}/{len(infos):,} logs  ({feitos / (time.time() - t0):,.0f}/s)   ", end="", flush=True)

        # janela de lotes: ler o zip inteiro de uma vez (ex.map) guardava todos os logs da UF na memória
        with ProcessPoolExecutor(max_workers=max(1, processos)) as ex:
            pendentes = set()
            for k in range(0, len(infos), 32):
                pendentes.add(ex.submit(_lote, [(i.filename, zf.read(i)) for i in infos[k:k + 32]]))
                if len(pendentes) >= max(1, processos) * 4:
                    prontos, pendentes = wait(pendentes, return_when=FIRST_COMPLETED)
                    for f in prontos:
                        guardar(f.result())
            for f in pendentes:
                guardar(f.result())
    print(f"\r  {sum(len(a[0]) for v in por_secao.values() for a in v):,} eleitores em {len(por_secao):,} seções, {len(erros)} logs com erro")
    for nome, erro in erros[:10]:
        print(f"    ! {nome}: {erro}")
    tipos = {"t_voto": "int32", "t_ident": "int32", "t_lib": "int32", "tipo": "int8", "cargos": "int8",
             "tentativas": "int8", "lidas": "int8", "tempo_esgotado": "int8", "foto": "int8", "ano_errado": "int8",
             "dado_nao_confere": "int8", "inativo": "int8", "corrigiu": "int8", "t_manual": "int32", "t_mesario": "int32"}
    blocos, chaves, mesarios, codigos, urnas_v = [], [], [], [], []
    for (mun, zona, secao), logs in sorted(por_secao.items()):
        num = np.concatenate([a[0] for a in logs])
        cod = np.concatenate([a[1] for a in logs])
        marca = np.concatenate([a[2] for a in logs])
        urna = np.concatenate([a[3] for a in logs])
        ordem = np.argsort(num[:, 0], kind="stable")
        num, cod, marca, urna = num[ordem], cod[ordem], marca[ordem], urna[ordem]
        # mesário: 0, 1, 2… na ordem em que aparece na seção (o número do título não é guardado)
        rot = marca.copy()
        reais = marca == 0
        if reais.any():
            _, primeira, inv = np.unique(cod[reais], return_index=True, return_inverse=True)
            ordem_aparicao = np.argsort(np.argsort(primeira))
            rot[reais] = np.minimum(ordem_aparicao[inv], 127)
        blocos.append(pd.DataFrame({c: num[:, k].astype(tipos[c]) for k, c in enumerate(NUMERICAS)}))
        mesarios.append(rot)
        codigos.append(cod)
        urnas_v.append(urna)
        chaves.append((mun, zona, secao, len(num)))
    if not blocos:
        return pd.DataFrame(), pd.DataFrame()
    df = pd.concat(blocos, ignore_index=True)
    df["mesario"] = np.concatenate(mesarios)
    df["mesario_cod"] = np.concatenate(codigos)
    df["urna"] = np.concatenate(urnas_v)
    n = np.array([c[3] for c in chaves])
    df.insert(0, "ordem", np.concatenate([np.arange(1, k + 1) for k in n]).astype("int16"))
    df.insert(0, "secao", np.repeat([c[2] for c in chaves], n).astype("int16"))
    df.insert(0, "zona", np.repeat([c[1] for c in chaves], n).astype("int16"))
    df.insert(0, "cd_municipio", np.repeat([c[0] for c in chaves], n).astype("int32"))
    urnas = pd.DataFrame(linhas_urna, columns=["cd_municipio", "zona", "secao", "arquivo", "urna", "votos", "t_primeiro_voto",
                                               "t_ultimo_voto", "t_primeira_linha", "t_ultima_linha"])
    urnas = urnas.sort_values(["cd_municipio", "zona", "secao", "t_primeiro_voto"], ignore_index=True)
    return df, urnas


def conferir(uf: str, ano: int, turno: int) -> bool:
    """Compara eleitores_<...> e urnas_<...> com logs_<...>.parquet, seção por seção. True se tudo bate."""
    arq_e, arq_l = PASTA / f"eleitores_{ano}_t{turno}_{uf}.parquet", PASTA / f"logs_{ano}_t{turno}_{uf}.parquet"
    arq_u = PASTA / f"urnas_{ano}_t{turno}_{uf}.parquet"
    if not (arq_e.exists() and arq_l.exists()):
        print(f"  {uf}: sem conferência (falta {arq_l.name if arq_e.exists() else arq_e.name})")
        return False
    e = pd.read_parquet(arq_e, columns=["cd_municipio", "zona", "secao", "tipo"])
    ch = ["cd_municipio", "zona", "secao"]
    g = e.groupby(ch + ["tipo"], observed=True).size().unstack("tipo", fill_value=0).reindex(columns=range(4), fill_value=0)
    g.columns = ["e_digital", "e_sem_cad", "e_manual", "e_outro"]
    g["e_votos"] = g.sum(axis=1)
    l = pd.read_parquet(arq_l, columns=ch + ["votos_log", "votos_digital", "votos_sem_cadastro", "votos_manual"])
    l = l.fillna(0).astype({c: "int64" for c in ["votos_log", "votos_digital", "votos_sem_cadastro", "votos_manual"]})
    j = l.merge(g.reset_index(), on=ch, how="outer").fillna(0)
    pares = [("votos_log", "e_votos"), ("votos_digital", "e_digital"), ("votos_sem_cadastro", "e_sem_cad"), ("votos_manual", "e_manual")]
    dif = {a: int((j[a] != j[b]).sum()) for a, b in pares}
    ok = not any(dif.values())
    txt = (f"  {uf}: {len(j):,} seções, {int(j['e_votos'].sum()):,} votos (digital {int(j['e_digital'].sum()):,}, "
           f"sem digital cadastrada {int(j['e_sem_cad'].sum()):,}, mesário {int(j['e_manual'].sum()):,})")
    if arq_u.exists():
        u = pd.read_parquet(arq_u)
        vu = u.groupby(ch)["votos"].sum().rename("u_votos").reset_index()
        ju = j.merge(vu, on=ch, how="left").fillna(0)
        dif["urnas"] = int((ju["u_votos"] != ju["e_votos"]).sum())
        ok = ok and not dif["urnas"]
        txt += f" | {u['urna'].nunique():,} urnas com voto"
    print(txt + (" | CONFERE com logs_urna" if ok else f" | !!! NÃO CONFERE: seções diferentes por medida {dif}"))
    return ok


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
    p.add_argument("--conferir", action="store_true", help="Só conferir os arquivos já gravados com logs_<...>.parquet")
    a = p.parse_args()
    PASTA.mkdir(exist_ok=True)
    if a.conferir:
        return 0 if all([conferir(uf, a.ano, a.turno) for uf in a.ufs]) else 1
    if a.zip:
        m = re.search(r"_(\d{4})_(\d)t_([A-Z]{2})\.zip$", a.zip.name, re.I)
        tarefas = [(m.group(3).upper(), int(m.group(1)), int(m.group(2)), a.zip)] if m else [(input("UF: ").upper(), a.ano, a.turno, a.zip)]
    else:
        tarefas = [(uf, a.ano, a.turno, None) for uf in a.ufs]
    for uf, ano, turno, zip_local in tarefas:
        saida = PASTA / f"eleitores_{ano}_t{turno}_{uf}.parquet"
        saida_urnas = PASTA / f"urnas_{ano}_t{turno}_{uf}.parquet"
        if saida.exists() and saida_urnas.exists() and not a.refazer:
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
        df, urnas = processar_zip(caminho, uf, a.processos)
        if df.empty:
            print("  ! nenhum eleitor encontrado")
            continue
        df.insert(0, "uf", uf)
        df["uf"] = df["uf"].astype("category")
        df.to_parquet(saida, index=False)
        urnas.insert(0, "uf", uf)
        urnas.to_parquet(saida_urnas, index=False)
        t = df["tipo"].value_counts().reindex(range(4), fill_value=0)
        print(f"  {len(df):,} eleitores: digital {t[0]:,}, sem digital cadastrada {t[1]:,}, pelo mesário {t[2]:,}, outro {t[3]:,}"
              f" | {saida.stat().st_size / 1e6:,.0f} MB")
        conferir(uf, ano, turno)
        if a.apagar_brutos and zip_local is None and brutos.exists():
            brutos.unlink()
    return 0


if __name__ == "__main__":
    sys.exit(main())
