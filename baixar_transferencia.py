"""
Baixa o arquivo do TSE "Transferência temporária do eleitorado por seção" e gera
dados/transferencia_<ano>.parquet com, por seção, quantos eleitores foram
transferidos temporariamente PARA ela (recebidos) e DELA para outra seção (enviados).

Transferência temporária é o "voto em trânsito" e o voto de presos provisórios,
mesários, policiais e outros que votam fora da própria seção. Seções que recebem
muita gente assim têm comparecimento diferente das vizinhas, o que explica parte
dos destaques de abstenção.

Uso:
    python baixar_transferencia.py
    python baixar_transferencia.py --zip transf_temporaria_secao_2026.zip

O endereço do arquivo no CDN do TSE foi presumido. Se der "não publicado (404)",
baixe pelo portal dadosabertos.tse.jus.br (conjunto "Eleitorado 2026") e use --zip.
"""
from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

import pandas as pd

import leitura_tse as L
from download_tse import baixar_completo

URL = "https://cdn.tse.jus.br/estatistica/sead/odsele/transferencia_temporaria/transf_temporaria_secao_{ano}.zip"
PASTA = Path(__file__).parent / "dados"
CHAVE = ["uf", "cd_municipio", "zona", "secao"]

# Dois formatos possíveis: (1) uma linha por seção com a quantidade; (2) uma linha por
# transferência, com seção de origem e de destino. As colunas são procuradas nessa ordem.
COLUNAS = {
    "turno": ["NR_TURNO"],
    "uf": ["SG_UF", "SG_UF_DESTINO", "SG_UF_TRANSFERENCIA"],
    "cd_municipio": ["CD_MUNICIPIO", "CD_MUNICIPIO_DESTINO", "CD_MUNICIPIO_TRANSFERENCIA"],
    "zona": ["NR_ZONA", "NR_ZONA_DESTINO", "NR_ZONA_TRANSFERENCIA"],
    "secao": ["NR_SECAO", "NR_SECAO_DESTINO", "NR_SECAO_TRANSFERENCIA"],
    "uf_o": ["SG_UF_ORIGEM"],
    "cd_municipio_o": ["CD_MUNICIPIO_ORIGEM"],
    "zona_o": ["NR_ZONA_ORIGEM"],
    "secao_o": ["NR_SECAO_ORIGEM"],
    "tipo": ["DS_TIPO_TRANSFERENCIA", "DS_CATEGORIA", "DS_TIPO_ELEITOR", "DS_MOTIVO_TRANSFERENCIA"],
}
OBRIGATORIAS = ["uf", "cd_municipio", "zona", "secao"]


def coluna_qtd(cab: list[str]) -> str | None:
    """A coluna de quantidade: a primeira QT_ que fala de eleitor; senão a primeira QT_."""
    qts = [c for c in cab if c.upper().startswith("QT_")]
    return next((c for c in qts if "ELEITOR" in c.upper()), qts[0] if qts else None)


def ler(caminho: Path, turno: int) -> pd.DataFrame:
    rec, env, tipos = [], [], []
    with zipfile.ZipFile(caminho) as z:
        for nome in L.csvs(z):
            cab = L.cabecalho(z, nome)
            qtd = coluna_qtd(cab)
            cols = dict(COLUNAS)
            if qtd:
                cols["qtd"] = [qtd]
            print(f"  {nome}: quantidade em {qtd or '(uma linha por eleitor)'}")
            for d in L.ler(z, nome, cols, OBRIGATORIAS):
                if "turno" in d and d["turno"].isin([str(turno)]).any():
                    d = d[d["turno"] == str(turno)]
                q = L.inteiro(d["qtd"], "Int64").fillna(0) if "qtd" in d else pd.Series(1, index=d.index)
                dest = pd.DataFrame({"uf": d["uf"].str.strip(), "cd_municipio": L.inteiro(d["cd_municipio"]),
                                     "zona": L.inteiro(d["zona"]), "secao": L.inteiro(d["secao"]), "q": q})
                rec.append(dest.groupby(CHAVE, as_index=False)["q"].sum())
                if {"cd_municipio_o", "zona_o", "secao_o"} <= set(d.columns):
                    o = pd.DataFrame({"uf": d.get("uf_o", d["uf"]).str.strip(),
                                      "cd_municipio": L.inteiro(d["cd_municipio_o"]),
                                      "zona": L.inteiro(d["zona_o"]), "secao": L.inteiro(d["secao_o"]), "q": q})
                    env.append(o.groupby(CHAVE, as_index=False)["q"].sum())
                if "tipo" in d:
                    tipos.append(pd.DataFrame({"tipo": d["tipo"], "q": q}).groupby("tipo")["q"].sum())
    if not rec:
        return pd.DataFrame()
    out = pd.concat(rec).groupby(CHAVE)["q"].sum().rename("transf_recebidos").to_frame()
    if env:
        out = out.join(pd.concat(env).groupby(CHAVE)["q"].sum().rename("transf_enviados"), how="outer")
    if tipos:
        t = pd.concat(tipos).groupby(level=0).sum().sort_values(ascending=False)
        print("  por tipo:")
        for k, v in t.head(12).items():
            print(f"    {k:<50} {v:>10,}")
    out = out.fillna(0).astype("int32").reset_index()
    return out[out["cd_municipio"].notna()]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ano", type=int, default=2026)
    p.add_argument("--turno", type=int, default=1)
    p.add_argument("--zip", type=Path)
    p.add_argument("--url", help="Endereço alternativo do zip no TSE")
    a = p.parse_args()
    PASTA.mkdir(exist_ok=True)
    try:
        caminho = a.zip or baixar_completo((a.url or URL).format(ano=a.ano),
                                           PASTA / f"transf_temporaria_secao_{a.ano}.zip")
    except FileNotFoundError as e:
        raise SystemExit(f"{e}\nBaixe o arquivo pelo portal dadosabertos.tse.jus.br e rode com --zip.")
    df = ler(caminho, a.turno)
    if df.empty:
        raise SystemExit("Nenhuma linha lida.")
    saida = PASTA / f"transferencia_{a.ano}.parquet"
    df.to_parquet(saida, index=False)
    env = f", {df['transf_enviados'].sum():,} enviados" if "transf_enviados" in df else ""
    print(f"\n{len(df):,} seções com transferência temporária: {df['transf_recebidos'].sum():,} eleitores "
          f"recebidos{env} | salvo em {saida.name}")


if __name__ == "__main__":
    main()
