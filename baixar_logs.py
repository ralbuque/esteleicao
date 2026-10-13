"""
Baixa os "Arquivos transmitidos para totalização" do TSE (um zip por UF com
.bu, .imgbu, .logjez, .rdv e .vscmr de cada seção), lê os logs das urnas e
gera, por seção, métricas do horário dos votos.

Os arquivos do TSE são GRANDES (de centenas de MB a vários GB por UF). Por isso,
por padrão, o script baixa SÓ os logs de dentro do zip (cerca de metade do
tamanho), em várias conexões, com novas tentativas automáticas. Se cair ou for
interrompido, rode de novo: ele continua de onde parou.

    python baixar_logs.py --ufs AC
    python baixar_logs.py --ufs CE BA
    python baixar_logs.py --ufs BA --conexoes 4
    python baixar_logs.py --ufs CE --completo
    python baixar_logs.py --zip ~/Downloads/bu_imgbu_logjez_rdv_vscmr_2026_1t_CE.zip

--conexoes   número de downloads simultâneos (padrão 8; reduza se der muitos erros)
--completo   baixa o zip inteiro em vez de só os logs (retoma sozinho se cair)
--zip        processa um zip que você já baixou (pelo navegador, curl etc.)
--refazer    reprocessa UFs já processadas; usa os logs_brutos já baixados, sem baixar de novo
Resultado: dados/logs_<ano>_t<turno>_<UF>.parquet  (gerar_site.py lê automaticamente)

Fonte: https://dadosabertos.tse.jus.br/dataset/resultados-2026-arquivos-transmitidos-para-totalizacao
"""
from __future__ import annotations

import argparse
import io
import os
import re
import sys
import time
import zipfile
from collections import Counter, defaultdict
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, as_completed, wait
from pathlib import Path

import numpy as np
import pandas as pd
from download_tse import SemDownloadParcial, baixar_completo, baixar_so_logs
from logs_urna import ABERTURA, EXT_LOG, estimar_fuso, metricas, processar_logjez

URL = ("https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes{ano}/arqurnatot/"
       "bu_imgbu_logjez_rdv_vscmr_{ano}_{turno}t_{uf}.zip")
UFS = ["AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA",
       "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO", "ZZ"]
PASTA = Path(__file__).parent / "dados"


# ------------------------------------------------------------------ leitura do zip
def iterar_logjez(zf: zipfile.ZipFile, prefixo: str = ""):
    """Percorre o zip (e zips dentro dele) devolvendo (nome, bytes) de cada log de urna."""
    for info in zf.infolist():
        nome = info.filename.lower()
        if nome.endswith(EXT_LOG):
            yield prefixo + info.filename, zf.read(info)
        elif nome.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(zf.read(info))) as interno:
                yield from iterar_logjez(interno, prefixo + info.filename + "/")


def _tarefa(lote):
    return [processar_logjez(nome, dados) for nome, dados in lote]


def _em_paralelo(itens, processos: int, tam_lote: int = 32):
    """Processa em paralelo com memória limitada (no máximo ~4 lotes por processo em voo)."""
    def lotes():
        lote = []
        for item in itens:
            lote.append(item)
            if len(lote) == tam_lote:
                yield lote
                lote = []
        if lote:
            yield lote

    if processos <= 1:
        for lote in lotes():
            yield from _tarefa(lote)
        return
    with ProcessPoolExecutor(max_workers=processos) as ex:
        pendentes = set()
        for lote in lotes():
            pendentes.add(ex.submit(_tarefa, lote))
            if len(pendentes) >= processos * 4:
                prontos, pendentes = wait(pendentes, return_when=FIRST_COMPLETED)
                for f in prontos:
                    yield from f.result()
        for f in as_completed(pendentes):
            yield from f.result()


def processar_zip(caminho: Path, uf: str, processos: int) -> pd.DataFrame:
    por_secao = defaultdict(list)
    erros = []
    with zipfile.ZipFile(caminho) as zf:
        n_log = sum(1 for i in zf.infolist() if i.filename.lower().endswith(EXT_LOG))
        n_zip = sum(1 for i in zf.infolist() if i.filename.lower().endswith(".zip"))
        total = n_log if not n_zip else None
        print(f"  {n_log:,} logs" + (f" e {n_zip:,} zips internos" if n_zip else "") + " a processar")
        t0 = time.time()
        for i, r in enumerate(_em_paralelo(iterar_logjez(zf), processos), 1):
            if "erro" in r:
                erros.append((r["nome"], r["erro"]))
            else:
                por_secao[r["chave"]].append(r)
            if i % 500 == 0:
                de = f"/{total:,}" if total else ""
                print(f"\r  {i:,}{de} logs lidos  ({i / (time.time() - t0):,.0f}/s)   ", end="", flush=True)
    print(f"\r  {sum(len(v) for v in por_secao.values()):,} logs lidos, {len(por_secao):,} seções, "
          f"{len(erros)} com erro")
    for nome, erro in erros[:10]:
        print(f"    ! {nome}: {erro}")

    # fuso de cada seção e harmonização pelo fuso mais comum do município
    linhas = []
    for (mun, zona, secao), logs in por_secao.items():
        votos = np.concatenate([l["votos_s"] for l in logs])
        hab = np.concatenate([l["hab"] for l in logs])
        ordem = np.argsort(votos, kind="stable")
        votos, hab = votos[ordem], hab[ordem]
        aberturas = [l["abertura_s"] for l in logs if l["abertura_s"] is not None]
        abertura = min(aberturas) if aberturas else None
        linhas.append({"cd_municipio": mun, "zona": zona, "secao": secao,
                       "_votos": votos, "_hab": hab, "_abertura": abertura,
                       "_fuso": estimar_fuso(abertura, int(votos[0]) if len(votos) else None, uf),
                       "n_logs": len(logs), "n_urnas": len(set().union(*[l["urnas"] for l in logs])),
                       "dia": next((l["dia"] for l in logs if l["dia"]), None)})
    fuso_mun = defaultdict(Counter)
    for l in linhas:
        fuso_mun[l["cd_municipio"]][l["_fuso"]] += 1
    saida = []
    for l in linhas:
        fuso = fuso_mun[l["cd_municipio"]].most_common(1)[0][0]
        m = metricas(l["_votos"], l["_hab"], fuso)
        m["abertura"] = (l["_abertura"] / 3600 - fuso) if l["_abertura"] is not None else np.nan
        m["abertura_atrasada_min"] = max(0.0, (m["abertura"] - ABERTURA) * 60) if l["_abertura"] else np.nan
        saida.append({"uf": uf, **{k: v for k, v in l.items() if not k.startswith("_")}, **m})
    if not saida:
        with zipfile.ZipFile(caminho) as zf:
            exemplos = [i.filename for i in zf.infolist()][:8]
        print("  ! nenhum log de urna reconhecido neste zip. Primeiros arquivos encontrados:")
        for n in exemplos:
            print(f"      {n}")
        print("    O formato pode ter mudado; envie esta lista para ajustar o script.")
        return pd.DataFrame()
    df = pd.DataFrame(saida)
    hcols = [f"{p}{h:02d}" for p in "hsm" for h in range(24)]
    df[hcols] = df[hcols].astype("int16")
    return df


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ano", type=int, default=2026)
    p.add_argument("--turno", type=int, default=1)
    p.add_argument("--ufs", nargs="+", default=UFS, type=str.upper)
    p.add_argument("--zip", type=Path, help="Processar um zip já baixado (a UF é lida do nome)")
    p.add_argument("--apagar-zip", action="store_true", help="Apagar o zip após processar")
    p.add_argument("--completo", action="store_true",
                   help="Baixar o zip inteiro do TSE (padrão: baixar só os logs de dentro dele)")
    p.add_argument("--conexoes", type=int, default=8, help="Downloads simultâneos no modo só-logs")
    p.add_argument("--url", help=argparse.SUPPRESS)  # para testes: modelo de URL alternativo
    p.add_argument("--refazer", action="store_true", help="Reprocessar UFs já processadas")
    p.add_argument("--processos", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    a = p.parse_args()
    PASTA.mkdir(exist_ok=True)

    if a.zip:
        m = re.search(r"_(\d{4})_(\d)t_([A-Z]{2})\.zip$", a.zip.name, re.I)
        uf = m.group(3).upper() if m else input("UF deste zip: ").strip().upper()
        ano, turno = (int(m.group(1)), int(m.group(2))) if m else (a.ano, a.turno)
        tarefas = [(uf, ano, turno, a.zip)]
    else:
        tarefas = [(uf, a.ano, a.turno, None) for uf in a.ufs]

    for uf, ano, turno, zip_local in tarefas:
        saida = PASTA / f"logs_{ano}_t{turno}_{uf}.parquet"
        if saida.exists() and not a.refazer:
            print(f"{uf}: já processado ({saida.name}); use --refazer para refazer")
            continue
        print(f"\n=== {uf} ({ano}, {turno}º turno) ===")
        url = (a.url or URL).format(ano=ano, turno=turno, uf=uf)
        completo = PASTA / f"arqurna_{ano}_{turno}t_{uf}.zip"
        brutos = PASTA / f"logs_brutos_{ano}_{turno}t_{uf}.zip"
        try:
            if zip_local:
                caminho = zip_local
            elif a.refazer and saida.exists() and brutos.exists():
                # o .parquet só é gravado quando todos os logs vieram: os brutos estão completos
                print(f"  reprocessando os logs já baixados ({brutos.name}), sem acessar o TSE")
                caminho = brutos
            elif completo.exists():  # zip inteiro já baixado antes
                print(f"  usando o zip completo já baixado: {completo.name}")
                caminho = completo
            elif a.completo:
                caminho = baixar_completo(url, completo)
            else:
                try:
                    caminho, n_total, n_falhas = baixar_so_logs(url, brutos, EXT_LOG, a.conexoes)
                except SemDownloadParcial:
                    print("  servidor não aceitou baixar só os logs; baixando o zip completo")
                    caminho = baixar_completo(url, completo)
                else:
                    if n_falhas:
                        print(f"  ! {n_falhas} de {n_total:,} logs não vieram. Rode o mesmo comando de novo "
                              "para buscar só os que faltam (o resto já está salvo).")
                        continue
        except KeyboardInterrupt:
            print("\nInterrompido. Rode o mesmo comando para continuar de onde parou.")
            return 1
        except Exception as e:
            print(f"  ! falha no download: {e}")
            print("    Rode o mesmo comando de novo: ele continua de onde parou.")
            continue
        df = processar_zip(caminho, uf, a.processos)
        if df.empty:
            print("  ! nenhum log válido encontrado")
            continue
        df.to_parquet(saida, index=False)
        print(f"  sem digital {1 - df['votos_digital'].sum() / df['votos_log'].sum():.1%} "
              f"(sem cadastro {df['votos_sem_cadastro'].sum() / df['votos_log'].sum():.1%}, "
              f"manual {df['votos_manual'].sum() / df['votos_log'].sum():.1%})")
        print(f"  hora média {df['hora_media'].mean():.2f}h | "
              f"{df['votos_apos_17'].sum():,} votos após 17h "
              f"({df['votos_apos_17'].sum() / df['votos_log'].sum():.2%}) | salvo em {saida.name}")
        if a.apagar_zip and not zip_local and caminho == completo:
            caminho.unlink()
            print("  zip apagado")
    print("\nPronto. Rode:  python gerar_site.py --servir")


if __name__ == "__main__":
    sys.exit(main())
