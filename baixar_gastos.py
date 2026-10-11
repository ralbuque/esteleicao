"""
Baixa a prestação de contas eleitorais dos candidatos (TSE) e gera
dados/gastos_<ano>.parquet com as despesas contratadas por município do
FORNECEDOR, separadas em transporte, combustível, locação de veículos e pessoal.

Gasto muito alto por eleitor nessas categorias, num município com várias
seções em atenção, é um sinal adicional (transporte de eleitores, cabos
eleitorais). Sozinho não quer dizer nada: campanha gasta em todo lugar.

Uso:
    python baixar_gastos.py
    python baixar_gastos.py --zip prestacao_de_contas_eleitorais_candidatos_2026.zip

O zip é grande; o download retoma de onde parou. O script lista os tipos de
despesa encontrados e em qual categoria cada um entrou, para conferir.
Fonte: https://dadosabertos.tse.jus.br/dataset/prestacao-de-contas-eleitorais-2026
"""
from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

import pandas as pd

import leitura_tse as L
from download_tse import baixar_completo

URL = "https://cdn.tse.jus.br/estatistica/sead/odsele/prestacao_contas/prestacao_de_contas_eleitorais_candidatos_{ano}.zip"
PASTA = Path(__file__).parent / "dados"
REF = Path(__file__).parent / "referencia" / "municipios.csv"

COLUNAS = {
    "valor": ["VR_DESPESA_CONTRATADA", "VR_DESPESA"],
    "origem": ["DS_ORIGEM_DESPESA", "DS_DESPESA"],
    "cd_mun_forn": ["CD_MUNICIPIO_FORNECEDOR"],
    "nm_mun_forn": ["NM_MUNICIPIO_FORNECEDOR"],
    "uf_forn": ["SG_UF_FORNECEDOR"],
    "uf_cand": ["SG_UF", "SG_UE"],
    "cargo": ["DS_CARGO"],
    "tipo_forn": ["DS_TIPO_FORNECEDOR"],
}
OBRIGATORIAS = ["valor", "origem", "uf_forn"]

# palavras (sem acento, minúsculas) no tipo de despesa -> categoria
CATEGORIAS = [
    ("combustivel", ["combust"]),
    ("veiculos", ["veicul"]),
    ("transporte", ["transporte", "deslocamento"]),
    ("pessoal", ["pessoal", "militancia", "mobilizacao"]),
]


def categoria(origem: pd.Series) -> pd.Series:
    t = origem.fillna("").map(L.sem_acento).str.lower()
    out = pd.Series("outras", index=origem.index)
    for cat, palavras in reversed(CATEGORIAS):  # a primeira da lista prevalece
        m = t.str.contains("|".join(palavras), regex=True)
        out = out.where(~m, cat)
    return out


def codigo_tse(d: pd.DataFrame) -> pd.Series:
    """Município do fornecedor em código do TSE. Aceita código TSE, código IBGE (7 dígitos)
    ou, se faltar, o nome do município + UF."""
    ref = pd.read_csv(REF, dtype={"cd_ibge": str}).dropna(subset=["cd_tse"])
    cod = L.inteiro(d["cd_mun_forn"], "Int64") if "cd_mun_forn" in d else pd.Series(pd.NA, index=d.index, dtype="Int64")
    validos = cod[cod > 0]
    if len(validos) and (validos >= 1_000_000).mean() > 0.5:
        print("  códigos de município do fornecedor são do IBGE: convertendo para o código do TSE")
        cod = cod.astype("string").map(ref.set_index("cd_ibge")["cd_tse"].astype(int).to_dict()).astype("Int64")
    falta = cod.isna() | (cod <= 0)
    if falta.any() and "nm_mun_forn" in d:
        k = d["uf_forn"].str.strip() + "|" + d["nm_mun_forn"].fillna("").map(L.sem_acento).str.upper().str.strip()
        ref_k = (ref["uf"] + "|" + ref["nome"].map(L.sem_acento).str.upper()).to_frame("k").assign(cd=ref["cd_tse"].astype(int))
        cod = cod.where(~falta, k.map(ref_k.set_index("k")["cd"].to_dict()).astype("Int64"))
    return cod


def ler(caminho: Path, ano: int) -> pd.DataFrame:
    partes, origens = [], []
    with zipfile.ZipFile(caminho) as z:
        alvos = L.csvs(z, contem="despesas_contratadas")
        if not alvos:
            raise SystemExit("Não achei despesas_contratadas_*.csv no zip. Arquivos: "
                             + ", ".join(z.namelist()[:20]))
        for nome in alvos:
            for d in L.ler(z, nome, COLUNAS, OBRIGATORIAS):
                d["valor"] = L.decimal_br(d["valor"]).fillna(0)
                d["categoria"] = categoria(d["origem"])
                origens.append(d.groupby(["origem", "categoria"])["valor"].agg(["sum", "size"]))
                d = d[d["categoria"] != "outras"].copy()
                d["cd_municipio"] = codigo_tse(d)
                d["uf"] = d["uf_forn"].str.strip()
                partes.append(d.groupby(["uf", "cd_municipio", "categoria"], dropna=False)["valor"]
                              .agg(valor="sum", despesas="size").reset_index())
            print(f"  ok {nome}")
    o = pd.concat(origens).groupby(level=[0, 1]).sum().sort_values("sum", ascending=False)
    print("\n  Tipos de despesa (conferir a categoria):")
    for (orig, cat), r in o.head(40).iterrows():
        print(f"    {cat:<12} R$ {r['sum']:>16,.2f}  {int(r['size']):>9,}  {orig}")
    df = pd.concat(partes).groupby(["uf", "cd_municipio", "categoria"], dropna=False)[["valor", "despesas"]].sum()
    return df.reset_index()


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ano", type=int, default=2026)
    p.add_argument("--zip", type=Path)
    a = p.parse_args()
    PASTA.mkdir(exist_ok=True)
    caminho = a.zip or baixar_completo(URL.format(ano=a.ano),
                                       PASTA / f"prestacao_de_contas_eleitorais_candidatos_{a.ano}.zip")
    df = ler(caminho, a.ano)
    saida = PASTA / f"gastos_{a.ano}.parquet"
    df.to_parquet(saida, index=False)
    sem = df["cd_municipio"].isna()
    print(f"\nR$ {df['valor'].sum():,.2f} em {df['despesas'].sum():,} despesas das 4 categorias; "
          f"R$ {df.loc[sem, 'valor'].sum():,.2f} sem município identificado | salvo em {saida.name}")
    print(df.groupby("categoria")["valor"].sum().map("R$ {:,.2f}".format).to_string())


if __name__ == "__main__":
    main()
