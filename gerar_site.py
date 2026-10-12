"""
Gera os dados do site (pasta web/dados) a partir dos arquivos já processados.

Todo o cálculo pesado (z-scores, cruzamentos, agregações por município e escola)
é feito UMA VEZ aqui, e não a cada visita. O site em web/ é estático: o servidor
só entrega arquivos prontos (Caddy file_server), então abre em ~1 segundo e
aguenta qualquer número de visitantes sem gastar memória.

    python gerar_site.py                      # eleição/turno mais recente em dados/
    python gerar_site.py --ano 2026 --turno 1
    python gerar_site.py --servir             # gera e abre em http://localhost:8000

Entradas (em dados/):
    secoes_<ano>_t<turno>.parquet        baixar_dados.py   (obrigatório)
    logs_<ano>_t<turno>_<UF>.parquet     baixar_logs.py    (horário e digital)
    locais_<ano>.parquet                 baixar_locais.py  (endereço e coordenadas da escola)
Opcionais, para a aba "Mais análises" (veja extras.py): votacao_*, perfil_*, populacao_*,
    secoes_<ano-4>_t1 (eleição anterior), secoes_<ano>_t<outro turno>, transferencia_*, gastos_*.
Saída (em web/dados/): brasil.json, municipios.json, apos17.json, plano.json, extras.json,
    uf/<UF>.json (seções sinalizadas) e mun/<código>.json (todas as seções do município).
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import re
import shutil
import time
import unicodedata
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import extras
from analise import corrigir_fuso, juntar_horario, pontuar_secoes

RAIZ = Path(__file__).parent
DADOS = RAIZ / "dados"
SAIDA = RAIZ / "web" / "dados"
REF_MUNICIPIOS = RAIZ / "referencia" / "municipios.csv"

# Três níveis de exigência. "padrao" é o usado no plano de fiscalização.
NIVEIS = {
    "rigoroso": dict(abst_z=4.0, p17=0.20, dest17=45, man_z=4.0, man_min=8),
    "padrao": dict(abst_z=3.0, p17=0.15, dest17=30, man_z=3.0, man_min=5),
    "amplo": dict(abst_z=2.5, p17=0.10, dest17=20, man_z=2.5, man_min=5),
}
MIN_APTOS_ABST = 50
MIN_VOTOS_17 = 10
BIT = {"abst": 1, "17h": 2, "manual": 4}
# faixas de horário (Brasília) usadas nos gráficos: 8h (inclui antes das 8h), 9h ... 16h, 17h, 18h ou mais
FAIXAS = list(range(8, 19))


# ------------------------------------------------------------------ utilidades
def _num(x, casas):
    if x is None:
        return None
    try:
        if isinstance(x, (float, np.floating)) and not math.isfinite(x):
            return None
    except TypeError:
        return None
    if pd.isna(x):
        return None
    if casas == 0:
        return int(round(float(x)))
    return round(float(x), casas)


def tabela(df: pd.DataFrame, colunas: dict[str, int | None]) -> dict:
    """DataFrame -> {"cols": [...], "rows": [[...], ...]} com arredondamento por coluna
    (None = texto). Formato compacto: o nome de cada campo aparece uma vez só."""
    nomes = list(colunas)
    vals = []
    for c, casas in colunas.items():
        s = df[c] if c in df else pd.Series([None] * len(df), index=df.index)
        if casas is None:
            vals.append([None if (v is None or (isinstance(v, float) and math.isnan(v))) else str(v)
                         for v in s.astype(object).where(s.notna(), None)])
        else:
            arr = pd.to_numeric(s, errors="coerce").to_numpy(dtype=float)
            if casas == 0:
                vals.append([None if not math.isfinite(v) else int(round(v)) for v in arr])
            else:
                vals.append([None if not math.isfinite(v) else round(v, casas) for v in arr])
    return {"cols": nomes, "rows": [list(r) for r in zip(*vals)] if vals else []}


def gravar(caminho: Path, obj) -> int:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    caminho.write_bytes(txt)
    # versão pré-compactada: o Caddy entrega direto (file_server precompressed)
    with gzip.open(caminho.with_suffix(caminho.suffix + ".gz"), "wb", compresslevel=9) as f:
        f.write(txt)
    return len(txt)


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").upper().strip()


def titulo(s: str) -> str:
    """'SÃO JOÃO DO RIO' -> 'São João do Rio' (para textos vindos em maiúsculas)."""
    if not isinstance(s, str):
        return s
    minus = {"de", "da", "do", "das", "dos", "e", "d'", "em", "na", "no"}
    partes = re.split(r"(\s+)", s.strip().lower())
    out = []
    for i, p in enumerate(partes):
        if p.isspace() or not p:
            out.append(p)
        elif i > 0 and p in minus:
            out.append(p)
        else:
            out.append(p[:1].upper() + p[1:])
    return "".join(out)


# ------------------------------------------------------------------ carga
def escolher_arquivo(ano: int | None, turno: int | None) -> Path:
    if ano:
        p = DADOS / f"secoes_{ano}_t{turno or 1}.parquet"
        if not p.exists():
            raise SystemExit(f"Não encontrei {p}. Rode antes: python baixar_dados.py --ano {ano}")
        return p
    arqs = sorted(DADOS.glob("secoes_*.parquet"), key=lambda p: (p.stem.split("_")[1], p.stem.split("_")[2]),
                  reverse=True)
    if not arqs:
        raise SystemExit("Nenhum dado em dados/. Rode antes: python baixar_dados.py")
    return arqs[0]


def carregar_logs(ano, turno) -> pd.DataFrame | None:
    arqs = sorted(DADOS.glob(f"logs_{ano}_t{turno}_*.parquet"))
    logs = pd.concat([pd.read_parquet(a) for a in arqs], ignore_index=True) if arqs else None
    if logs is not None:
        logs = logs[logs["uf"].astype(str) != "ZZ"]
    return logs


def carregar_logs_corrigidos(ano, turno) -> pd.DataFrame | None:
    logs = carregar_logs(ano, turno)
    return corrigir_fuso(logs) if logs is not None else None


def carregar(caminho: Path) -> tuple[pd.DataFrame, dict]:
    ano, turno = re.match(r"secoes_(\d{4})_t(\d)", caminho.stem).groups()
    sec = pd.read_parquet(caminho)
    sec = sec[sec["uf"].astype(str) != "ZZ"].reset_index(drop=True)  # exterior fica fora do site
    df = pontuar_secoes(sec)
    logs = carregar_logs(ano, turno)
    df = juntar_horario(df, logs)  # já corrige o fuso (analise.corrigir_fuso)
    ufs_log = sorted(logs["uf"].astype(str).unique()) if logs is not None else []

    # endereço e coordenadas do local de votação
    loc_arq = DADOS / f"locais_{ano}.parquet"
    if loc_arq.exists():
        loc = pd.read_parquet(loc_arq)
        loc = loc.drop(columns=[c for c in ["local"] if c in loc and "local" in df])
        for c in ["cd_municipio", "zona", "secao"]:
            loc[c] = loc[c].astype("Int32")
            df[c] = df[c].astype("Int32")
        loc["uf"] = loc["uf"].astype(str)
        df["uf"] = df["uf"].astype(str)
        df = df.merge(loc.rename(columns={"nome_local": "nome_local_tse"}),
                      on=["uf", "cd_municipio", "zona", "secao"], how="left")
        if "nome_local" in df:
            df["nome_local"] = df["nome_local_tse"].fillna(df["nome_local"])
        else:
            df["nome_local"] = df["nome_local_tse"]
        df = df.drop(columns=["nome_local_tse"])
    if "endereco" not in df and "endereco_local" in df:
        df["endereco"] = df["endereco_local"]
    for c in ["endereco", "bairro", "cep", "tipo_local", "lat", "lon"]:
        if c not in df:
            df[c] = np.nan
    if "local" not in df:
        df["local"] = pd.NA

    # municípios: código IBGE, nome bem escrito e centro (para o mapa)
    ref = pd.read_csv(REF_MUNICIPIOS, dtype={"cd_ibge": str})
    ref_cod = ref.dropna(subset=["cd_tse"]).astype({"cd_tse": int})
    df["uf"] = df["uf"].astype(str)
    df["cd_municipio"] = df["cd_municipio"].astype(int)
    df = df.merge(ref_cod[["cd_tse", "cd_ibge", "nome", "lat", "lon"]].rename(
        columns={"cd_tse": "cd_municipio", "nome": "mun_nome", "lat": "mun_lat", "lon": "mun_lon"}),
        on="cd_municipio", how="left")
    # municípios novos sem código TSE na tabela: casa por UF + nome
    falta = df["cd_ibge"].isna()
    if falta.any():
        ref["_k"] = ref["uf"] + "|" + ref["nome"].map(_sem_acento)
        k = df.loc[falta, "uf"] + "|" + df.loc[falta, "municipio"].astype(str).map(_sem_acento)
        m = k.map(ref.set_index("_k")[["cd_ibge"]].to_dict()["cd_ibge"])
        df.loc[falta, "cd_ibge"] = m
        for a, b in [("mun_nome", "nome"), ("mun_lat", "lat"), ("mun_lon", "lon")]:
            df.loc[falta, a] = k.map(ref.set_index("_k")[b].to_dict())
    df["mun_nome"] = df["mun_nome"].fillna(df["municipio"].astype(str).map(titulo))

    meta = {"ano": int(ano), "turno": int(turno), "ufs_com_log": ufs_log,
            "tem_locais": bool(loc_arq.exists())}
    return df, meta


# ------------------------------------------------------------------ critérios
def marcar(df: pd.DataFrame) -> pd.DataFrame:
    """Bits por nível: bits 0-2 = rigoroso, 3-5 = padrão, 6-8 = amplo (abst=1, 17h=2, manual=4)."""
    mask = np.zeros(len(df), dtype=np.int32)
    tem = lambda c: c in df
    for i, (nome, p) in enumerate(NIVEIS.items()):
        f_abst = (df["z_ajustado"] <= -p["abst_z"]) & (df["aptos"] >= MIN_APTOS_ABST)
        f17 = pd.Series(False, index=df.index)
        if tem("votos_apos_17"):
            f17 = (df["pct_apos_17"] >= p["p17"]) & (df["votos_apos_17"] >= MIN_VOTOS_17)
            if tem("dif_local_min"):
                f17 &= (df["dif_local_min"] >= p["dest17"]) | df["dif_local_min"].isna()
        fman = pd.Series(False, index=df.index)
        if tem("z_manual"):
            fman = (df["z_manual"] >= p["man_z"]) & (df["votos_manual"] >= p["man_min"])
        b = (f_abst.fillna(False).astype(int) * 1 + f17.fillna(False).astype(int) * 2
             + fman.fillna(False).astype(int) * 4).to_numpy()
        mask |= (b << (3 * i)).astype(np.int32)
    df["flags"] = mask
    for i, nome in enumerate(NIVEIS):
        df[f"f_{nome}"] = (mask >> (3 * i)) & 7
    return df


def sinais(df: pd.DataFrame) -> pd.Series:
    """Códigos curtos de padrões objetivos encontrados no log (o site transforma em frases)."""
    regras = []
    if "votos_apos_17" in df:
        tarde = df["votos_apos_17"].fillna(0) >= 5
        regras += [
            ("ociosa", tarde & (df["ociosa_antes_17_min"] >= 20)),
            ("sem_bio_17h", tarde & (df["pct_sem_bio_apos_17"] >= 0.5)),
            ("ritmo_17h", tarde & (df["intervalo_med_apos_17_s"] <= 45)),
            ("tarde_escola", df.get("dif_local_min", pd.Series(np.nan, index=df.index)) >= 60),
            ("seq_manual", df.get("maior_seq_manual", pd.Series(np.nan, index=df.index)) >= 8),
            ("log_dif", df["dif_log_comparecimento"].abs() >= 1),
            ("urna_trocada", df["n_urnas"] > 1),
            ("abertura", df["abertura_atrasada_min"] >= 30),
            ("sem_digital_escola", df.get("dif_local_sem_digital_pp", pd.Series(np.nan, index=df.index)) >= 25),
        ]
    out = pd.Series("", index=df.index, dtype=object)
    for cod, m in regras:
        m = m.fillna(False).astype(bool)
        out = out.where(~m, out + np.where(out == "", "", ",") + cod)
    return out


def faixas_brasilia(df: pd.DataFrame, prefixo: str = "h") -> np.ndarray:
    """Votos por faixa de horário de Brasília (8h, 9h ... 17h, 18h+) para cada seção."""
    cols = [f"{prefixo}{h:02d}" for h in range(24)]
    out = np.zeros((len(df), len(FAIXAS)), dtype=np.int32)
    if cols[0] not in df:
        return out
    H = df[cols].fillna(0).to_numpy(dtype=np.int32)
    fuso = df["fuso"].fillna(0).astype(int).to_numpy()
    for f in np.unique(fuso):
        linhas = fuso == f
        for hl in range(24):
            hb = hl - f  # hora de Brasília
            j = min(max(hb, 8), 18) - 8
            out[linhas, j] += H[linhas, hl]
    return out


# ------------------------------------------------------------------ agregações
SOMAS = ["aptos", "comparecimento", "abstencoes", "votos_log", "votos_apos_17", "votos_manual",
         "votos_sem_cadastro", "votos_digital", "com_log", "com_17h"]
# somas que só existem quando a fonte opcional foi baixada (Mais análises)
SOMAS_OPC = ["eleitores_perfil", "el_70_mais", "el_16_17", "el_biometria", "transf_recebidos",
             "votos_antes_8", "manual_16h", "man17", "cad17", "sd_foto", "man_leitor_ok", "cab6", "cab6_lt25"]


def preparar(df: pd.DataFrame) -> pd.DataFrame:
    df["com_log"] = df["tem_log"].astype(int)
    for c in ["votos_log", "votos_apos_17", "votos_manual", "votos_sem_cadastro", "votos_digital"]:
        if c not in df:
            df[c] = np.nan
    df["com_17h"] = (df["votos_apos_17"].fillna(0) > 0).astype(int)
    df["cadastrados"] = df["votos_log"] - df["votos_sem_cadastro"]
    df["sinais_cod"] = sinais(df)
    return df


def agregar(df: pd.DataFrame, por: list[str]) -> pd.DataFrame:
    g = df.groupby(por, observed=True, sort=False)
    a = g[SOMAS + [c for c in SOMAS_OPC if c in df]].sum(min_count=1)
    a["secoes"] = g.size()
    a["max_17h"] = g["votos_apos_17"].max()
    for nome in NIVEIS:
        f = df[f"f_{nome}"]
        a[f"{nome}_abst"] = (f & 1).astype(bool).groupby([df[c] for c in por], observed=True).sum()
        a[f"{nome}_17h"] = (f & 2).astype(bool).groupby([df[c] for c in por], observed=True).sum()
        a[f"{nome}_man"] = (f & 4).astype(bool).groupby([df[c] for c in por], observed=True).sum()
        a[f"{nome}_sec"] = (f > 0).groupby([df[c] for c in por], observed=True).sum()
        a[f"{nome}_mult"] = ((f & 1).astype(bool).astype(int) + (f & 2).astype(bool).astype(int)
                             + (f & 4).astype(bool).astype(int) >= 2).groupby([df[c] for c in por], observed=True).sum()
        a[f"{nome}_v17"] = (df["votos_apos_17"].where(f > 0, 0)).groupby([df[c] for c in por], observed=True).sum()
        if "flags_conc" in df:
            i = list(NIVEIS).index(nome)
            a[f"{nome}_conc"] = extras.bit(df["flags_conc"], i).groupby([df[c] for c in por], observed=True).sum()
        if "flags_lib" in df:
            i = list(NIVEIS).index(nome)
            chaves = [df[c] for c in por]
            a[f"{nome}_lib17"] = extras.bit(df["flags_lib"], i).groupby(chaves, observed=True).sum()
            a[f"{nome}_salto"] = extras.bit(df["flags_lib"], 3 + i).groupby(chaves, observed=True).sum()
    if "flags_lib" in df:
        a["defeito"] = extras.bit(df["flags_lib"], extras.BIT_DEFEITO).groupby([df[c] for c in por], observed=True).sum()
    if "flags_p2" in df:  # Parte 2: tag "sem digital, com foto" e sinal "cabine muito rápida"
        chaves = [df[c] for c in por]
        a["p2_foto"] = extras.bit(df["flags_p2"], extras.BIT_FOTO).groupby(chaves, observed=True).sum()
        a["p2_cabine"] = extras.bit(df["flags_p2"], extras.BIT_CABINE).groupby(chaves, observed=True).sum()
    if "flags_atip" in df:  # casos extremamente atípicos (tags)
        chaves = [df[c] for c in por]
        for nome_bit, b in [("fora", extras.BIT_FORA), ("tarde", extras.BIT_TARDE), ("soz", extras.BIT_SOZINHA)]:
            a[f"atip_{nome_bit}"] = extras.bit(df["flags_atip"], b).groupby(chaves, observed=True).sum()
        a["fora_votos"] = df["fora_log"].where(extras.bit(df["flags_atip"], extras.BIT_FORA) > 0, 0).groupby(chaves, observed=True).sum()
        for i, nome in enumerate(NIVEIS):
            q = extras.n_atipicos(df, i)
            a[f"{nome}_atip"] = (q > 0).groupby(chaves, observed=True).sum()
            a[f"{nome}_atip2"] = (q >= 2).groupby(chaves, observed=True).sum()
    return a.reset_index()


def cols_agg(df: pd.DataFrame) -> dict:
    """Colunas dos arquivos agregados: as de sempre + as das fontes opcionais que existirem."""
    c = dict(COLS_AGG)
    c.update({k: 0 for k in SOMAS_OPC if k in df})
    if "flags_conc" in df:
        c.update({f"{n}_conc": 0 for n in NIVEIS})
    if "flags_lib" in df:
        c.update({f"{n}_{k}": 0 for n in NIVEIS for k in ["lib17", "salto"]})
        c["defeito"] = 0
    if "flags_p2" in df:
        c.update({"p2_foto": 0, "p2_cabine": 0})
    if "flags_atip" in df:
        c.update({k: 0 for k in ["atip_fora", "atip_tarde", "atip_soz", "fora_votos"]})
        c.update({f"{n}_{k}": 0 for n in NIVEIS for k in ["atip", "atip2"]})
    return c


COLS_AGG = {"secoes": 0, "aptos": 0, "comparecimento": 0, "abstencoes": 0, "com_log": 0, "votos_log": 0,
            "votos_apos_17": 0, "com_17h": 0, "max_17h": 0, "votos_manual": 0, "votos_sem_cadastro": 0,
            "votos_digital": 0,
            **{f"{n}_{k}": 0 for n in NIVEIS for k in ["abst", "17h", "man", "sec", "mult", "v17"]}}


def perfil(df: pd.DataFrame, faixas: np.ndarray, mask=None) -> list[int]:
    f = faixas if mask is None else faixas[np.asarray(mask)]
    return [int(x) for x in f.sum(0)]


# ------------------------------------------------------------------ escolas (plano de fiscalização)
def prioridade(g: pd.DataFrame) -> pd.Series:
    """Prioridade da escola para receber fiscal, em regras simples que dá para explicar:
    ALTA  = alguma seção cumpre 2+ critérios, OU 3+ seções sinalizadas na escola,
            OU desvio muito forte (abstenção z ≤ −5, liberação manual z ≥ 5, ou 30%+ e 30+ votos após 17h)
    MÉDIA = 2 seções sinalizadas, OU seção sinalizada com sinal no log (urna ociosa e depois rajada, etc.)
    BAIXA = demais escolas com pelo menos 1 seção sinalizada."""
    f = g["f_padrao"]
    ncrit = (f & 1).astype(bool).astype(int) + (f & 2).astype(bool).astype(int) + (f & 4).astype(bool).astype(int)
    forte = (g["z_ajustado"] <= -5) | (g["z_manual"].fillna(0) >= 5) | \
            ((g["pct_apos_17"].fillna(0) >= 0.30) & (g["votos_apos_17"].fillna(0) >= 30))
    sinal = g["sinais_cod"].str.contains("ociosa|sem_bio_17h|seq_manual|ritmo_17h|salto_17h", regex=True)
    return pd.Series({
        "multi": int((ncrit >= 2).sum()),
        "forte": int((forte & (f > 0)).sum()),
        "com_sinal": int((sinal & (f > 0)).sum()),
    })


def plano(df: pd.DataFrame) -> pd.DataFrame:
    chave = ["uf", "cd_municipio", "zona", "local"]
    d = df.copy()
    d["local"] = d["local"].fillna(-1)
    esc = d.groupby(chave, observed=True, dropna=False)
    base = esc.agg(secoes_total=("secao", "size"), aptos_total=("aptos", "sum"),
                   nome_local=("nome_local", "first"), endereco=("endereco", "first"),
                   bairro=("bairro", "first"), cep=("cep", "first"), lat=("lat", "first"), lon=("lon", "first"),
                   tipo_local=("tipo_local", "first"),
                   mun_nome=("mun_nome", "first"), mun_lat=("mun_lat", "first"), mun_lon=("mun_lon", "first"),
                   cd_ibge=("cd_ibge", "first"))
    s = d[d["f_padrao"] > 0]
    if s.empty:
        return pd.DataFrame()
    gs = s.groupby(chave, observed=True, dropna=False)
    sin = gs.agg(sinalizadas=("secao", "size"), aptos_sinalizadas=("aptos", "sum"),
                 v17=("votos_apos_17", "sum"), vman=("votos_manual", "sum"),
                 n_abst=("f_padrao", lambda x: int((x & 1).astype(bool).sum())),
                 n_17h=("f_padrao", lambda x: int((x & 2).astype(bool).sum())),
                 n_man=("f_padrao", lambda x: int((x & 4).astype(bool).sum())),
                 secoes=("secao", lambda x: " ".join(str(int(v)) for v in sorted(x))))
    pr = s.groupby(chave, observed=True, dropna=False)[["f_padrao", "z_ajustado", "z_manual", "pct_apos_17",
                                                        "votos_apos_17", "sinais_cod"]].apply(prioridade)
    out = base.join(sin, how="inner").join(pr).reset_index()
    alta = (out["multi"] > 0) | (out["sinalizadas"] >= 3) | (out["forte"] > 0)
    media = ~alta & ((out["sinalizadas"] >= 2) | (out["com_sinal"] > 0))
    out["prioridade"] = np.select([alta, media], [3, 2], 1)
    out = out.sort_values(["prioridade", "multi", "sinalizadas", "forte", "aptos_sinalizadas"],
                          ascending=False).reset_index(drop=True)
    return out


# ------------------------------------------------------------------ principal
COLS_SECAO_LISTA = {  # seções sinalizadas (arquivo da UF) e lista de votos após 17h
    "cd_municipio": 0, "zona": 0, "secao": 0, "local": 0, "flags": 0,
    "aptos": 0, "comparecimento": 0, "taxa_abstencao": 4, "taxa_esperada": 4, "z_ajustado": 2,
    "votos_log": 0, "votos_apos_17": 0, "pct_apos_17": 4, "dif_local_min": 0, "ultimo_voto": 3,
    "ociosa_antes_17_min": 0, "pct_sem_bio_apos_17": 3, "intervalo_med_apos_17_s": 0,
    "votos_manual": 0, "cadastrados": 0, "pct_manual_cadastrados": 4, "manual_esperado": 4, "z_manual": 2,
    "maior_seq_manual": 0, "votos_sem_cadastro": 0, "n_urnas": 0, "abertura_atrasada_min": 0,
    "dif_log_comparecimento": 0, "secoes_no_local": 0, "sinais_cod": None,
}
COLS_SECAO_MUN = {  # todas as seções de um município
    "zona": 0, "secao": 0, "local": 0, "flags": 0, "aptos": 0, "comparecimento": 0, "taxa_abstencao": 4,
    "taxa_esperada": 4, "z_ajustado": 2, "votos_log": 0, "votos_apos_17": 0, "pct_apos_17": 4,
    "dif_local_min": 0, "ultimo_voto": 3, "votos_manual": 0, "cadastrados": 0, "pct_manual_cadastrados": 4,
    "z_manual": 2, "maior_seq_manual": 0, "votos_sem_cadastro": 0, "sinais_cod": None,
}
# colunas das fontes opcionais (Mais análises): entram só se existirem
OPC_LISTA = {
    "flags_conc": 0, "conc_cargo": 0, "conc_nome": None, "conc_votos": 0, "conc_validos": 0, "conc_fatia": 4,
    "conc_esperada": 4, "conc_z": 2, "conc_z_bn": 2, "conc_pct_bn": 4, "conc_esp_bn": 4,
    "perfil_explica": 0, "pct_70": 3, "pct_16_17": 3, "tipo_secao_agregada": None, "n_agregadas": 0,
    "transf_recebidos": 0, "flags_ant": 0, "tem_ant": 0, "z_abst_ant": 2,
    "votos_antes_8": 0, "manual_16h": 0, "z_manual_tarde": 2, "maior_seq_rapida": 0, "seq_rapida_inicio": 3,
    "dif_comp_turnos": 4, "z_comp_turnos": 2, "comp_sobe_turno": 0, "taxa_comp_t1": 4, "taxa_comp_t2": 4,
    "apos17_so_t2": 0, "manual_tarde_esperado": 1,
    "flags_lib": 0, "man17": 0, "cad17": 0, "man_dia": 0, "cad_dia": 0, "defeito_desde": 0,
    "horas_man": None, "horas_cad": None,
    "flags_atip": 0, "fora_log": 0, "abertura": 3, "ult_outras": 3, "v17_outras": 1, "aptos_outras": 0,
    "local_com_log": 0, "zona_19": 0, "zona_log": 0,
    "flags_p2": 0, "sd_foto": 0, "sd_cadastro": 0, "sd_excesso": 0, "man_leitor_ok": 0,
    "cab6": 0, "cab6_med": 0, "cab6_lt20": 0, "cab6_lt25": 0, "cab6_seq25": 0, "cab6_seq25_ini": 3,
}
OPC_DETALHE = {
    **OPC_LISTA, "eleitores_perfil": 0, "el_70_mais": 0, "el_16_17": 0, "el_biometria": 0, "pct_biometria": 3,
    "abst_esperada_idade": 4, "z_abst_idade": 2, "manual_esperado_idade": 4, "z_manual_idade": 2,
    "transf_enviados": 0, "pct_transf": 3, "taxa_abst_ant": 4, "aptos_ant": 0, "pct_apos_17_ant": 4,
    "votos_apos_17_ant": 0, "z_manual_ant": 2, "votos_manual_ant": 0, "z_bn": 2, "pct_bn": 4, "esp_bn": 4,
    "comparecimento_t1": 0, "comparecimento_t2": 0, "votos_apos_17_t1": 0, "votos_apos_17_t2": 0,
    "manual_tarde_esperado": 1, "cadastrados_16h": 0, "intervalos_rapidos": 0, "votos_manual_apos_17": 0,
}


def com_opcionais(df: pd.DataFrame, base: dict, opc: dict) -> dict:
    return {**base, **{k: v for k, v in opc.items() if k in df}}


COLS_LOCAL = {"local": 0, "nome_local": None, "endereco": None, "bairro": None, "cep": None,
              "lat": 5, "lon": 5}


def locais_de(d: pd.DataFrame) -> dict:
    """Dicionário de locais de votação (escolas) usados num arquivo, chave = 'zona-local'."""
    l = d.drop_duplicates(["cd_municipio", "zona", "local"])
    out = {}
    for r in l.itertuples(index=False):
        if pd.isna(r.local):
            continue
        k = f"{int(r.cd_municipio)}-{int(r.zona)}-{int(r.local)}"
        out[k] = [titulo(r.nome_local) if isinstance(r.nome_local, str) else None,
                  titulo(r.endereco) if isinstance(r.endereco, str) else None,
                  titulo(r.bairro) if isinstance(r.bairro, str) else None,
                  None if pd.isna(r.cep) else str(r.cep),
                  _num(r.lat, 5), _num(r.lon, 5),
                  titulo(r.tipo_local) if isinstance(r.tipo_local, str) else None]
    return out


# ------------------------------------------------------------------ Mais análises (extras.py)
def enriquecer(df: pd.DataFrame, meta: dict) -> tuple[pd.DataFrame, dict]:
    """Acrescenta às seções as colunas das fontes opcionais. Cada etapa só roda se o arquivo existir."""
    ano, turno = meta["ano"], meta["turno"]
    rel = {}
    df = extras.sinais_extras(df)
    rel["sinais"] = extras.relatorio_sinais(df)
    df, rel["perfil"] = extras.perfil(df, DADOS, ano, NIVEIS, lambda d, nome: d[f"f_{nome}"])
    df, rel["contexto"] = extras.contexto(df, DADOS, ano)
    df, rel["anterior"] = extras.eleicao_anterior(df, DADOS, ano, marcar, carregar_logs)
    rel["repeticao"] = extras.resumo_repeticao(df, NIVEIS)
    df, rel["turnos"] = extras.outro_turno(df, DADOS, ano, turno, carregar_logs_corrigidos)
    df, vot, conc = extras.votacao(df, DADOS, ano, turno, NIVEIS)
    if vot:
        rel["materialidade"] = extras.materialidade(df, vot["materialidade_tot"], ano, NIVEIS)
        rel["concentracao"] = extras.resumo_concentracao(df, NIVEIS)
    meta["fontes_extras"] = sorted(k for k, v in rel.items() if v)
    print(f"  fontes extras: {', '.join(meta['fontes_extras']) or 'nenhuma'}")
    return df, rel


def listas_extras(df: pd.DataFrame, d: pd.DataFrame, CL: dict, faixas: np.ndarray, n: int) -> dict:
    """Listas de seções de cada análise extra (as n mais fortes de cada uma), para o recorte d."""
    def lista(mask, ordem, asc=False):
        x = d[mask.fillna(False).astype(bool)].sort_values(ordem, ascending=asc).head(n).copy()
        x["horas"] = [" ".join(map(str, r)) for r in faixas[df.index.get_indexer(x.index)]]
        return {"secoes": tabela(x, {"uf": None, **CL, "horas": None}), "locais": locais_de(x)}
    out = {}
    if "conc_z" in d:
        out["lista_conc"] = lista(extras.bit(d["flags_conc"], 2) > 0, "conc_z")
    if "perfil_explica" in d:
        out["lista_perfil"] = lista(d["perfil_explica"] > 0, "z_ajustado", asc=True)
    if "comp_sobe_turno" in d:
        out["lista_turnos"] = lista(d["z_comp_turnos"] >= 3, "z_comp_turnos")
    if "transf_recebidos" in d:
        out["lista_transf"] = lista(d["transf_recebidos"] >= 20, "transf_recebidos")
    if "votos_antes_8" in d:
        out["lista_antes_8"] = lista(d["votos_antes_8"] > 0, "votos_antes_8")
    if "z_manual_tarde" in d:
        out["lista_manual_tarde"] = lista(extras.manual_tarde(d), "z_manual_tarde")
    if "flags_p2" in d:
        out["lista_cabine"] = lista(extras.bit(d["flags_p2"], extras.BIT_CABINE) > 0, ["cab6_seq25", "cab6_lt25"])
        out["lista_foto"] = lista(extras.bit(d["flags_p2"], extras.BIT_FOTO) > 0, "sd_foto")
    elif "maior_seq_rapida" in d:
        out["lista_rapidos"] = lista(d["maior_seq_rapida"] >= 6, "maior_seq_rapida")
    return out


def relatorio_extras(df: pd.DataFrame, rel: dict, CL: dict, faixas: np.ndarray) -> dict:
    """extras.json: resumos e listas (Brasil) de cada análise extra. As listas completas de cada UF
    ficam em extras/<UF>.json."""
    out = {k: v for k, v in rel.items() if k not in ("cadastro", "gastos") and v}
    out["cadastro"], out["gastos"] = rel.get("cadastro") or {}, rel.get("gastos") or {}
    out.update(listas_extras(df, df, CL, faixas, 300))
    if "tipo_local" in df and df["tipo_local"].notna().any():
        t = df.assign(tipo=df["tipo_local"].fillna("Não informado").map(titulo))
        g = t.groupby("tipo")
        tl = pd.DataFrame({"secoes": g.size(), "aptos": g["aptos"].sum(),
                           **{f"{n}_sec": (t[f"f_{n}"] > 0).groupby(t["tipo"]).sum() for n in NIVEIS}})
        out["tipos_local"] = tabela(tl.reset_index().sort_values("secoes", ascending=False),
                                    {"tipo": None, "secoes": 0, "aptos": 0, **{f"{n}_sec": 0 for n in NIVEIS}})
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ano", type=int)
    p.add_argument("--turno", type=int)
    p.add_argument("--saida", type=Path, default=SAIDA)
    p.add_argument("--servir", action="store_true", help="Depois de gerar, abre o site em http://localhost:8000")
    a = p.parse_args()
    t0 = time.time()

    caminho = escolher_arquivo(a.ano, a.turno)
    print(f"Lendo {caminho.name} e logs…")
    df, meta = carregar(caminho)
    df = preparar(marcar(df))
    df, rel = enriquecer(df, meta)
    faixas = faixas_brasilia(df, "h")
    faixas_sd = faixas_brasilia(df, "s")
    faixas_man = faixas_brasilia(df, "m")
    # liberações pelo mesário hora a hora: tags "depois das 17h", "salto às 17h" e "leitor com defeito"
    df = extras.liberacoes(df, faixas_man, faixas - faixas_sd + faixas_man, NIVEIS)
    rel["liberacoes"] = extras.resumo_liberacoes(df, NIVEIS)
    for cod, b in [("salto_17h", None), ("leitor_defeito", extras.BIT_DEFEITO)]:
        m = (extras.bit(df["flags_lib"], b) > 0) if b is not None else (extras.bit(df["flags_lib"], 3 + list(NIVEIS).index("padrao")) > 0)
        df["sinais_cod"] = df["sinais_cod"].where(~m, df["sinais_cod"] + np.where(df["sinais_cod"] == "", "", ",") + cod)
    # casos extremamente atípicos: votos fora do log, urna começou tarde, terminou sozinha (tags)
    df = extras.atipicos(df)
    rel["atipicos"] = extras.resumo_atipicos(df, NIVEIS)
    # Parte 2 (medidas_eleitores.py, opcional): sem digital com foto, leitor funcionando em volta, tempo de cabine
    df, rel["parte2"] = extras.parte2(df, DADOS, meta["ano"], meta["turno"])
    if rel["parte2"]:
        rel["sinais"]["cabine"] = {k: rel["parte2"][k] for k in ("cab6", "cab6_lt25", "cab6_lt20", "cab6_med", "cabine_secoes", "cabine_seq")}
        rel["sinais"].pop("rapidos", None)
    print(f"  {len(df):,} seções, {int(df['tem_log'].sum()):,} com log ({time.time() - t0:.0f}s)")

    saida: Path = a.saida
    if saida.exists():
        shutil.rmtree(saida)
    (saida / "uf").mkdir(parents=True)
    (saida / "mun").mkdir(parents=True)
    tamanhos = {}

    # ---- municípios
    mun = agregar(df, ["uf", "cd_municipio"])
    info = df.drop_duplicates("cd_municipio").set_index("cd_municipio")[["cd_ibge", "mun_nome", "mun_lat", "mun_lon"]]
    mun = mun.join(info, on="cd_municipio")
    mun = mun.sort_values(["uf", "mun_nome"]).reset_index(drop=True)
    mun, rel["cadastro"] = extras.cadastro(mun, DADOS, meta["ano"])
    mun, rel["gastos"] = extras.gastos(mun, DADOS, meta["ano"])
    CA = cols_agg(df)
    opc_mun = {"pop_16_mais": 0, "razao_pop": 4, "aptos_mun_ant": 0, "cresc_eleitorado": 4, "gasto_total": 0,
               "gasto_eleitor": 3, "gasto_vs_uf": 2, "gasto_transporte": 0, "gasto_combustivel": 0,
               "gasto_veiculos": 0, "gasto_pessoal": 0}
    tamanhos["municipios.json"] = gravar(saida / "municipios.json", tabela(mun, {
        "cd_municipio": 0, "cd_ibge": None, "uf": None, "mun_nome": None, "mun_lat": 4, "mun_lon": 4,
        **CA, **{k: v for k, v in opc_mun.items() if k in mun}}))

    # ---- Brasil e UFs
    uf = agregar(df, ["uf"]).sort_values("uf")
    df["_br"] = "BR"
    br = agregar(df, ["_br"]).iloc[0]
    df.drop(columns="_br", inplace=True)
    perfis_uf = {u: {"votos": perfil(df, faixas, df["uf"] == u),
                     "sem_digital": perfil(df, faixas_sd, df["uf"] == u),
                     "manual": perfil(df, faixas_man, df["uf"] == u)} for u in uf["uf"]}
    brasil = {
        "meta": {**meta, "gerado_em": datetime.now().isoformat(timespec="minutes"),
                 "niveis": NIVEIS, "min_aptos_abst": MIN_APTOS_ABST, "min_votos_17": MIN_VOTOS_17,
                 "lib": {"limites": extras.LIB, "salto_min": extras.SALTO_MIN, "defeito_taxa": extras.DEFEITO_TAXA,
                         "defeito_antes": extras.DEFEITO_ANTES} if "flags_lib" in df else None,
                 "atip": {**extras.ATIP, **{k: rel["atipicos"][k] for k in ("zonas", "zonas_sem_19", "zonas_tarde")}}
                 if "flags_atip" in df else None,
                 "p2": rel["parte2"] or None,
                 "faixas": FAIXAS},
        "total": {k: _num(br[k], 0) for k in CA},
        "ufs": tabela(uf, {"uf": None, **CA}),
        "perfil": {"votos": perfil(df, faixas), "sem_digital": perfil(df, faixas_sd),
                   "manual": perfil(df, faixas_man)},
        "perfil_uf": perfis_uf,
        # distribuição das seções pela quantidade de votos após 17h (para o relatório)
        "faixas_17h": distribuicao_17h(df),
        "faixas_17h_uf": {u: distribuicao_17h(g) for u, g in df.groupby("uf", observed=True)},
    }
    tamanhos["brasil.json"] = gravar(saida / "brasil.json", brasil)

    # ---- seções sinalizadas por UF (no nível mais amplo; o site filtra pelos outros níveis)
    # (+ as de voto concentrado no nível amplo, o 4º critério opcional)
    conc_amplo = extras.bit(df["flags_conc"], 2).astype(bool) if "flags_conc" in df else False
    lib_amplo = ((df["flags_lib"].fillna(0).astype("int64") & ((1 << 2) | (1 << 5) | (1 << extras.BIT_DEFEITO))) > 0) \
        if "flags_lib" in df else False
    atip = (df["flags_atip"].fillna(0) > 0) if "flags_atip" in df else False
    p2 = (df["flags_p2"].fillna(0) > 0) if "flags_p2" in df else False
    cand = df[(df["f_amplo"] > 0) | conc_amplo | lib_amplo | atip | p2].copy()
    CL = com_opcionais(df, COLS_SECAO_LISTA, OPC_LISTA)
    hor = faixas[df.index.get_indexer(cand.index)] if len(cand) else np.zeros((0, len(FAIXAS)))
    cand["horas"] = [" ".join(map(str, r)) for r in hor]
    for u in uf["uf"]:
        g = cand[cand["uf"] == u]
        t17 = top_apos17(df[df["uf"] == u], faixas, df, 300)
        obj = {"uf": u, "secoes": tabela(g, {**CL, "horas": None}),
               "top17": tabela(t17, {**CL, "horas": None}),
               "locais": locais_de(pd.concat([g, t17]))}
        tamanhos[f"uf/{u}.json"] = gravar(saida / "uf" / f"{u}.json", obj)

    # ---- relatório "votos após 17h": as seções com MAIS votos depois das 17h (quantidade)
    if df["votos_apos_17"].notna().any():
        top = top_apos17(df, faixas, df, 1000)
        tamanhos["apos17.json"] = gravar(saida / "apos17.json", {
            "secoes": tabela(top, {"uf": None, **CL, "horas": None}),
            "locais": locais_de(top)})

    # ---- plano de fiscalização (escolas)
    esc = extras.rotas(plano(df))
    for c in ["nome_local", "endereco", "bairro", "tipo_local"]:
        if c in esc:
            esc[c] = esc[c].map(titulo)
    rel["rotas"] = {"rotas": int(esc["rota"].nunique()) if len(esc) else 0,
                    "locais": int(esc["rota"].notna().sum()) if len(esc) else 0, "raio_km": extras.RAIO_ROTA_KM}
    tamanhos["plano.json"] = gravar(saida / "plano.json", tabela(esc, {
        "prioridade": 0, "uf": None, "cd_municipio": 0, "mun_nome": None, "zona": 0, "local": 0,
        "nome_local": None, "endereco": None, "bairro": None, "cep": None, "lat": 5, "lon": 5,
        "mun_lat": 4, "mun_lon": 4, "secoes_total": 0, "aptos_total": 0, "sinalizadas": 0,
        "aptos_sinalizadas": 0, "n_abst": 0, "n_17h": 0, "n_man": 0, "multi": 0, "forte": 0,
        "com_sinal": 0, "v17": 0, "vman": 0, "secoes": None, "tipo_local": None,
        "rota": None, "rota_ordem": 0, "rota_km": 2}) if len(esc) else {"cols": [], "rows": []})

    # ---- Mais análises
    tamanhos["extras.json"] = gravar(saida / "extras.json", relatorio_extras(df, rel, CL, faixas))
    for u in uf["uf"]:
        lx = listas_extras(df, df[df["uf"] == u], CL, faixas, 1000)
        if lx:
            tamanhos[f"extras/{u}.json"] = gravar(saida / "extras" / f"{u}.json", lx)

    # ---- por município: resumo das zonas + perfil de horário;
    #      por zona: todas as seções (assim nenhum arquivo fica grande, nem na capital paulista)
    df["horas"] = [" ".join(map(str, r)) for r in faixas]
    (saida / "zona").mkdir(parents=True)
    zonas = agregar(df, ["cd_municipio", "zona"])
    CM = com_opcionais(df, COLS_SECAO_MUN, OPC_DETALHE)
    n = 0
    for cd, g in df.groupby("cd_municipio", observed=True, sort=False):
        idx = df.index.get_indexer(g.index)
        z = zonas[zonas["cd_municipio"] == cd].sort_values("zona")
        t17 = top_apos17(g, faixas, df, 100)
        gravar(saida / "mun" / f"{int(cd)}.json", {
            "cd": int(cd), "zonas": tabela(z, {"zona": 0, **CA}),
            "top17": tabela(t17, {**CL, "horas": None}), "locais": locais_de(t17),
            "perfil": [int(x) for x in faixas[idx].sum(0)],
            "perfil_sem_digital": [int(x) for x in faixas_sd[idx].sum(0)]})
        for zn, gz in g.groupby("zona", observed=True, sort=False):
            gravar(saida / "zona" / f"{int(cd)}-{int(zn)}.json", {
                "cd": int(cd), "zona": int(zn), "secoes": tabela(gz, CM | {"horas": None}),
                "locais": locais_de(gz)})
            n += 1
    print(f"  {df['cd_municipio'].nunique():,} municípios, {n:,} zonas")

    for k, v in sorted(tamanhos.items(), key=lambda kv: -kv[1])[:8]:
        print(f"  {k:<22} {v / 1e6:6.2f} MB")
    print(f"Pronto em {time.time() - t0:.0f}s -> {saida}")
    if a.servir:
        servir(saida.parent)


def top_apos17(d: pd.DataFrame, faixas: np.ndarray, df: pd.DataFrame, n: int) -> pd.DataFrame:
    """As n seções com MAIS votos depois das 17h (quantidade, não porcentagem)."""
    if "votos_apos_17" not in d or d["votos_apos_17"].isna().all():
        return d.head(0).assign(horas=pd.Series(dtype=object))
    top = d[d["votos_apos_17"].fillna(0) > 0].nlargest(n, ["votos_apos_17", "pct_apos_17"]).copy()
    hor = faixas[df.index.get_indexer(top.index)]
    top["horas"] = [" ".join(map(str, r)) for r in hor]
    return top


def distribuicao_17h(df: pd.DataFrame) -> list:
    """Quantas seções tiveram 0, 1–4, 5–9, 10–19, 20–49, 50+ votos após 17h (e quantos votos somam)."""
    if df["votos_apos_17"].isna().all():
        return []
    v = df["votos_apos_17"].dropna()
    cortes = [(0, 0, "nenhum"), (1, 4, "1 a 4"), (5, 9, "5 a 9"), (10, 19, "10 a 19"),
              (20, 49, "20 a 49"), (50, 10 ** 9, "50 ou mais")]
    return [{"faixa": rot, "secoes": int(((v >= a) & (v <= b)).sum()), "votos": int(v[(v >= a) & (v <= b)].sum())}
            for a, b, rot in cortes]


def servir(pasta: Path, porta: int = 8000):
    import functools
    import http.server

    class H(http.server.SimpleHTTPRequestHandler):
        def end_headers(self):
            self.send_header("Cache-Control", "no-cache")
            super().end_headers()

        def log_message(self, *a):
            pass
    print(f"Abra http://localhost:{porta}  (Ctrl+C para parar)")
    http.server.ThreadingHTTPServer(("", porta), functools.partial(H, directory=str(pasta))).serve_forever()


if __name__ == "__main__":
    main()
