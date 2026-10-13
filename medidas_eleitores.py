"""
Resume por SEÇÃO os arquivos de eleitores (eleitores_urna.py), para as análises da Parte 2 de
docs/analise-casos-atipicos.md. Lê dados/eleitores_<ano>_t<turno>_<UF>.parquet (uma linha por eleitor) e
grava dados/medidas_eleitores_<ano>_t<turno>.parquet (uma linha por seção), que gerar_site.py lê se existir.
Não muda nenhum critério: só acrescenta medidas.

    python medidas_eleitores.py                 # todas as UFs que tiverem eleitores_*.parquet
    python medidas_eleitores.py --ufs AC AL

Colunas (contagens de eleitores, salvo indicação):
    sd, sd_foto              sem digital cadastrada; destes, com foto no cadastro (a urna mostrou a foto)
    cad                      com digital cadastrada (digital reconhecida + liberados pelo mesário)
    man                      liberados pelo mesário
    man_isolada              liberações "no meio" de leituras que funcionaram: o eleitor com digital anterior E o seguinte
                             foram reconhecidos pela digital (o leitor estava funcionando)
    man_leitor_ok            liberações em janelas em que o leitor reconheceu a maioria: dos 10 eleitores com digital
                             mais próximos (5 antes, 5 depois), pelo menos 8 foram reconhecidos
    man_lidas4, man_esgotou  liberações em que o leitor capturou o dedo nas 4 tentativas; com alguma tentativa sem captura
    man_dado_nc              liberações em que o dado pessoal não conferiu na 1ª tentativa
    man_ate10s               liberações em até 10 s entre a urna pedir o dado e liberar
    cab6                     eleitores que votaram em 6 cargos, com horário de liberação e de voto
    cab6_med                 mediana do tempo de cabine deles (liberado -> voto computado), em segundos
    cab6_lt20, cab6_lt25, cab6_lt30   quantos ficaram menos de 20, 25 e 30 s na cabine
    cab6_seq25, cab6_seq25_ini        maior sequência de eleitores SEGUIDOS de 6 cargos com menos de 25 s; hora local do 1º
    transito                 eleitores de 1 cargo (voto em trânsito de outro estado)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PASTA = Path(__file__).parent / "dados"
CH = ["cd_municipio", "zona", "secao"]
PISO_CABINE = 25  # segundos: abaixo de 1 em cada 1.000 eleitores de 6 cargos no país (ver docs/analise-casos-atipicos.md)


def _maior_seq(flag: np.ndarray, grupo: np.ndarray, t: np.ndarray):
    """Maior sequência de True seguidos dentro de cada grupo (linhas já ordenadas por grupo e ordem).
    Devolve (grupo -> tamanho, grupo -> t do início) como Series."""
    n = len(flag)
    quebra = np.ones(n, dtype=bool)
    quebra[1:] = (grupo[1:] != grupo[:-1]) | (flag[1:] != flag[:-1])
    bloco = np.cumsum(quebra) - 1
    tam = np.bincount(bloco)
    ini = np.flatnonzero(quebra)
    ok = flag[ini]
    d = pd.DataFrame({"g": grupo[ini][ok], "tam": tam[ok], "t": t[ini][ok]})
    if d.empty:
        return pd.Series(dtype="int64"), pd.Series(dtype="float64")
    d = d.sort_values(["g", "tam"], ascending=[True, False]).drop_duplicates("g")
    return d.set_index("g")["tam"], d.set_index("g")["t"]


def medir(e: pd.DataFrame) -> pd.DataFrame:
    e = e.sort_values(CH + ["ordem"], kind="stable").reset_index(drop=True)
    g = (e["cd_municipio"].to_numpy(np.int64) * 10 ** 8 + e["zona"].to_numpy(np.int64) * 10 ** 4 + e["secao"].to_numpy(np.int64))
    tipo = e["tipo"].to_numpy()
    sd, man, dig = tipo == 1, tipo == 2, tipo == 0
    cad = man | dig
    out = pd.DataFrame({"g": g, "sd": sd, "sd_foto": sd & (e["foto"].to_numpy() > 0), "cad": cad, "man": man,
                        "transito": e["cargos"].to_numpy() == 1})

    # --- liberação pelo mesário com o leitor funcionando (só entre eleitores com digital cadastrada, na ordem do dia)
    ic = np.flatnonzero(cad)
    gc, mc = g[ic], man[ic]
    ant_ok = np.zeros(len(ic), bool)
    seg_ok = np.zeros(len(ic), bool)
    ant_ok[1:] = (gc[1:] == gc[:-1]) & ~mc[:-1]
    seg_ok[:-1] = (gc[:-1] == gc[1:]) & ~mc[1:]
    isolada = np.zeros(len(e), bool)
    isolada[ic] = mc & ant_ok & seg_ok
    # janela de 5 antes + 5 depois (dentro da seção): quantos foram reconhecidos pela digital
    d = (~mc).astype(np.int32)
    cs = np.concatenate([[0], np.cumsum(d)])
    pos = np.arange(len(ic))
    novo = np.ones(len(ic), bool)  # primeiro e último eleitor com digital de cada seção
    novo[1:] = gc[1:] != gc[:-1]
    ini_g = np.maximum.accumulate(np.where(novo, pos, 0))
    ult = np.ones(len(ic), bool)
    ult[:-1] = gc[:-1] != gc[1:]
    fim_g = np.minimum.accumulate(np.where(ult, pos, len(ic))[::-1])[::-1]
    a = np.maximum(pos - 5, ini_g)
    b = np.minimum(pos + 5, fim_g)
    viz = (b - a)  # vizinhos na janela (sem contar o próprio)
    rec = cs[b + 1] - cs[a] - d
    leitor_ok = np.zeros(len(e), bool)
    leitor_ok[ic] = mc & (viz >= 8) & (rec >= 0.8 * viz)
    out["man_isolada"], out["man_leitor_ok"] = isolada, leitor_ok
    out["man_lidas4"] = man & (e["lidas"].to_numpy() >= 4)
    out["man_esgotou"] = man & (e["tempo_esgotado"].to_numpy() > 0)
    out["man_dado_nc"] = man & (e["dado_nao_confere"].to_numpy() > 0)
    tl, tm, tv = e["t_lib"].to_numpy(), e["t_manual"].to_numpy(), e["t_voto"].to_numpy()
    out["man_ate10s"] = man & (tm >= 0) & (tl >= 0) & (tl - tm <= 10)

    # --- tempo de cabine dos eleitores de 6 cargos
    c6 = (e["cargos"].to_numpy() == 6) & (tl >= 0) & (tv >= tl)
    cab = np.where(c6, tv - tl, -1)
    out["cab6"] = c6
    for lim in (20, 25, 30):
        out[f"cab6_lt{lim}"] = c6 & (cab < lim)
    r = out.groupby("g", sort=False).sum().astype("int32")
    r["cab6_med"] = pd.Series(cab[c6]).groupby(g[c6], sort=False).median().reindex(r.index)
    seq, t0 = _maior_seq(c6 & (cab < PISO_CABINE), g, tl)
    r["cab6_seq25"] = seq.reindex(r.index).fillna(0).astype("int32")
    r["cab6_seq25_ini"] = t0.reindex(r.index)
    r = r.reset_index()
    r.insert(0, "secao", (r["g"] % 10 ** 4).astype("int32"))
    r.insert(0, "zona", (r["g"] // 10 ** 4 % 10 ** 4).astype("int32"))
    r.insert(0, "cd_municipio", (r["g"] // 10 ** 8).astype("int32"))
    return r.drop(columns="g")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ano", type=int, default=2026)
    p.add_argument("--turno", type=int, default=1)
    p.add_argument("--ufs", nargs="+", type=str.upper)
    a = p.parse_args()
    arqs = sorted(PASTA.glob(f"eleitores_{a.ano}_t{a.turno}_*.parquet"))
    if a.ufs:
        arqs = [x for x in arqs if x.stem.split("_")[-1] in a.ufs]
    if not arqs:
        raise SystemExit("Nenhum eleitores_*.parquet em dados/. Rode antes: python eleitores_urna.py")
    cols = CH + ["ordem", "t_voto", "t_lib", "t_manual", "tipo", "cargos", "lidas", "tempo_esgotado", "foto", "dado_nao_confere"]
    partes = []
    for arq in arqs:
        uf = arq.stem.split("_")[-1]
        r = medir(pd.read_parquet(arq, columns=cols))
        r.insert(0, "uf", uf)
        partes.append(r)
        print(f"  {uf}: {len(r):,} seções | sem digital com foto {int(r['sd_foto'].sum()):,} de {int(r['sd'].sum()):,}"
              f" | liberações com leitor funcionando {int(r['man_leitor_ok'].sum()):,} de {int(r['man'].sum()):,}"
              f" | 6 cargos em menos de {PISO_CABINE}s: {int(r['cab6_lt25'].sum()):,} de {int(r['cab6'].sum()):,}", flush=True)
    df = pd.concat(partes, ignore_index=True)
    saida = PASTA / f"medidas_eleitores_{a.ano}_t{a.turno}.parquet"
    df.to_parquet(saida, index=False)
    print(f"{len(df):,} seções -> {saida.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
