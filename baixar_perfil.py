"""
Baixa o "Perfil do eleitorado por seção eleitoral" do TSE (um zip por UF) e gera
dados/perfil_<ano>_<UF>.parquet com, para cada seção:

    eleitores, de 16 e 17 anos, de 60 a 69, de 70 anos ou mais, com biometria

Eleitores de 16–17 e de 70+ têm voto facultativo e faltam mais; idosos também
têm mais falha de digital. O site usa isso para mostrar quando o perfil da
seção explica o destaque (abstenção baixa ou muitas liberações manuais).

Uso:
    python baixar_perfil.py --ufs AC
    python baixar_perfil.py
    python baixar_perfil.py --zip perfil_eleitor_secao_2026_AC.zip

Fonte: https://dadosabertos.tse.jus.br/dataset/eleitorado-2026 ("Perfil do eleitorado por seção eleitoral")
"""
from __future__ import annotations

import argparse
import re
import zipfile
from pathlib import Path

import pandas as pd

import leitura_tse as L
from download_tse import baixar_completo

URL = "https://cdn.tse.jus.br/estatistica/sead/odsele/perfil_eleitor_secao/perfil_eleitor_secao_{ano}_{uf}.zip"
PASTA = Path(__file__).parent / "dados"
UFS = ["AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA",
       "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO", "ZZ"]

COLUNAS = {
    "uf": ["SG_UF"],
    "cd_municipio": ["CD_MUNICIPIO"],
    "zona": ["NR_ZONA"],
    "secao": ["NR_SECAO"],
    "ds_faixa": ["DS_FAIXA_ETARIA"],
    "cd_faixa": ["CD_FAIXA_ETARIA"],
    "eleitores": ["QT_ELEITORES_PERFIL", "QT_ELEITORES"],
    "biometria": ["QT_ELEITORES_BIOMETRIA"],
}
OBRIGATORIAS = ["uf", "cd_municipio", "zona", "secao", "eleitores"]


def idade_minima(ds: pd.Series | None, cd: pd.Series | None) -> pd.Series:
    """Menor idade da faixa: '16 anos' -> 16, '70 a 74 anos' -> 70, '100 anos ou mais' -> 100.
    Sem descrição, usa o código (ex.: 1600, 7074 -> os dois primeiros dígitos)."""
    if ds is not None:
        v = pd.to_numeric(ds.str.extract(r"(\d+)", expand=False), errors="coerce")
        if v.notna().any():
            return v
    if cd is not None:
        c = cd.astype(str).str.strip()
        return pd.to_numeric(c.where(c.str.len() == 4).str[:2], errors="coerce")
    return pd.Series(float("nan"), index=(ds if ds is not None else cd).index)


def ler(caminho: Path) -> pd.DataFrame:
    partes = []
    with zipfile.ZipFile(caminho) as z:
        for nome in L.csvs(z, preferir_brasil=False):
            for d in L.ler(z, nome, COLUNAS, OBRIGATORIAS):
                if "ds_faixa" not in d and "cd_faixa" not in d:
                    print("  ! sem coluna de faixa etária (DS_FAIXA_ETARIA / CD_FAIXA_ETARIA)")
                    return pd.DataFrame()
                idade = idade_minima(d.get("ds_faixa"), d.get("cd_faixa"))
                q = L.inteiro(d["eleitores"], "Int64").fillna(0)
                out = pd.DataFrame({
                    "uf": d["uf"].str.strip(), "cd_municipio": L.inteiro(d["cd_municipio"]),
                    "zona": L.inteiro(d["zona"]), "secao": L.inteiro(d["secao"]),
                    "eleitores": q,
                    "el_16_17": q.where(idade.isin([16, 17]), 0),
                    "el_60_69": q.where((idade >= 60) & (idade < 70), 0),
                    "el_70_mais": q.where(idade >= 70, 0),
                    "el_idade_invalida": q.where(idade.isna(), 0),
                })
                if "biometria" in d:
                    out["el_biometria"] = L.inteiro(d["biometria"], "Int64").fillna(0)
                # soma já no pedaço para não guardar milhões de linhas de perfil
                partes.append(out.groupby(["uf", "cd_municipio", "zona", "secao"], as_index=False).sum())
            print(f"  ok {nome}")
    if not partes:
        return pd.DataFrame()
    df = pd.concat(partes).groupby(["uf", "cd_municipio", "zona", "secao"], as_index=False).sum()
    for c in df.columns[4:]:
        df[c] = df[c].astype("int32")
    return df


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ano", type=int, default=2026)
    p.add_argument("--ufs", nargs="+", default=UFS, type=str.upper)
    p.add_argument("--zip", type=Path, nargs="+", help="Usar zips já baixados (a UF é lida do nome)")
    p.add_argument("--refazer", action="store_true")
    a = p.parse_args()
    PASTA.mkdir(exist_ok=True)
    if a.zip:
        tarefas = []
        for z in a.zip:
            m = re.search(r"_(\d{4})_([A-Z]{2})\.zip$", z.name, re.I)
            tarefas.append((m.group(2).upper() if m else input(f"UF de {z.name}: ").strip().upper(), z))
    else:
        tarefas = [(uf, None) for uf in a.ufs]
    for uf, zip_local in tarefas:
        saida = PASTA / f"perfil_{a.ano}_{uf}.parquet"
        if saida.exists() and not a.refazer:
            print(f"{uf}: já processado ({saida.name}); use --refazer para refazer")
            continue
        print(f"\n=== {uf} ===")
        try:
            caminho = zip_local or baixar_completo(URL.format(ano=a.ano, uf=uf),
                                                   PASTA / f"perfil_eleitor_secao_{a.ano}_{uf}.zip")
        except Exception as e:
            print(f"  ! falha no download: {e}\n    Rode o mesmo comando de novo.")
            continue
        df = ler(caminho)
        if df.empty:
            continue
        df.to_parquet(saida, index=False)
        t = df["eleitores"].sum()
        bio = f", {df['el_biometria'].sum() / t:.1%} com biometria" if "el_biometria" in df else ""
        print(f"  {len(df):,} seções, {t:,} eleitores: {df['el_16_17'].sum() / t:.1%} com 16–17 anos, "
              f"{df['el_70_mais'].sum() / t:.1%} com 70+{bio} | salvo em {saida.name}")
        sec_arq = sorted(PASTA.glob(f"secoes_{a.ano}_t*.parquet"))
        if sec_arq:  # conferência: eleitores do perfil vs aptos da seção
            s = pd.read_parquet(sec_arq[0], columns=["uf", "cd_municipio", "zona", "secao", "aptos"])
            s = s[s["uf"].astype(str) == uf]
            for c in ["cd_municipio", "zona", "secao"]:
                s[c] = s[c].astype("Int32")
            j = s.merge(df, on=["cd_municipio", "zona", "secao"], how="inner")
            if len(j):
                print(f"  conferência: {len(j) / len(s):.1%} das seções do resultado têm perfil; "
                      f"eleitores do perfil = aptos em {(j['eleitores'] == j['aptos']).mean():.1%} delas "
                      f"(perfil {j['eleitores'].sum():,} vs aptos {j['aptos'].sum():,})")
    print("\nPronto. Rode:  python gerar_site.py")


if __name__ == "__main__":
    main()
