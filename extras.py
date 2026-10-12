"""
Análises da aba "Mais análises" (docs/ideias-de-relatorios.md).

Tudo aqui ACRESCENTA colunas e relatórios às seções; nenhum dos três critérios
de analise.py / gerar_site.py muda. Cada fonte é opcional: se o arquivo em
dados/ não existir, a função correspondente não faz nada e o site continua
funcionando sem aquela parte.

    a) materialidade       votacao_<ano>_t<turno>_<UF>.parquet  (baixar_votacao.py)
    b) voto concentrado    idem
    c) perfil do eleitorado perfil_<ano>_<UF>.parquet           (baixar_perfil.py)
    d) cadastro inflado    populacao_2022.parquet (baixar_ibge.py) + secoes_<ano-4>_t1.parquet
    e) repetição           secoes_<ano-4>_t1.parquet (+ logs) e secoes_<ano>_t<outro turno>.parquet
    f) contexto do local   locais_<ano>.parquet + transferencia_<ano>.parquet
    g) gastos de campanha  gastos_<ano>.parquet                 (baixar_gastos.py)
    h) rotas de fiscalização (coordenadas do plano)
    i) sinais extras do log (histogramas por hora e maior_seq_rapida dos logs)
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

from analise import MIN_SECOES_MUNICIPIO, juntar_horario, pontuar_secoes, z_proporcao

CHAVE = ["uf", "cd_municipio", "zona", "secao"]

# ---------------------------------------------------------------- limites (novos, ajustáveis)
# voto concentrado: z (mesma conta de analise.z_proporcao), fatia mínima dos votos válidos da
# seção e quantidade mínima de votos do candidato na seção
CONC = {
    "rigoroso": dict(z=5.0, fatia=0.50, votos=50),
    "padrao": dict(z=4.0, fatia=0.40, votos=40),
    "amplo": dict(z=3.0, fatia=0.30, votos=30),
}
CARGOS_CONC = {6: "Deputado federal", 7: "Deputado estadual", 8: "Deputado distrital"}
CARGOS_MAT = {1: "Presidente", 3: "Governador", 5: "Senador"}
BRANCO, NULO = 95, 96
Z_BN_BAIXO = -3.0          # brancos e nulos muito abaixo do município
Z_MANUAL_TARDE = 3.5       # liberações manuais concentradas das 16h em diante
MIN_MANUAL_TARDE = 5
RAZAO_MANUAL_TARDE = 2.0
SEQ_RAPIDA = 10            # 10+ votos seguidos com menos de 30 s entre eles
ANTES_8H_SINAL = 3         # votos antes das 8h que viram sinal
TURNOS_Z, TURNOS_DIF = 4.0, 0.10   # comparecimento que sobe muito entre os turnos
RAIO_ROTA_KM = 2.0
# liberações pelo mesário depois das 17h (tags: não entram na contagem dos critérios)
LIB = {  # min17 = liberações depois das 17h; salto = quanto a taxa depois das 17h passa a do dia
    "rigoroso": dict(min17=20, salto=0.50),
    "padrao": dict(min17=10, salto=0.40),
    "amplo": dict(min17=5, salto=0.30),
}
SALTO_MIN = 10              # salto às 17h: pelo menos 10 liberações depois das 17h
SALTO_ANTES_FOLGA = 0.15    # das 14h às 16h a taxa não pode já ter subido mais que isso (senão começou antes)
DEFEITO_TAXA = 0.80         # leitor com defeito provável: 80%+ de quem tem digital liberado pelo mesário
DEFEITO_ANTES = 0.30        # ... e, se começou no meio do dia, até 30% antes disso
DEFEITO_MIN = 20            # ... com pelo menos 20 eleitores com digital no período ruim
BIT_DEFEITO = 6             # flags_lib: bits 0-2 depois das 17h, 3-5 salto às 17h (por nível), 6 leitor com defeito
# casos extremamente atípicos (tags; não contam como critério). Regras em docs/analise-casos-atipicos.md, seção 5
ATIP = {"fora_min": 50,          # votos fora do log: comparecimento oficial − votos no log
        "tarde_hora": 15.0,      # urna começou tarde: 1ª vez pronta para o eleitor (Brasília)
        "soz_min": 60,           # terminou sozinha: minutos depois da última OUTRA seção do local
        "soz_secoes": 3,         # ... local com pelo menos 3 seções (com log)
        "soz_outras17": 5.0,     # ... as outras seções do local com até 5 votos após 17h em média
        "soz_votos17": 20,       # ... e esta com 20 ou mais
        "soz_aptos": 1.3,        # ... sem ser bem maior que as vizinhas (aptos < 1,3 × a média delas)
        "zona_hora": 19.0,       # contexto: seções da zona com último voto depois das 19h
        "zona_alta": 0.05}       # ... a zona "votou até tarde" quando são 5% ou mais (metade das zonas do país não tem nenhuma)
BIT_FORA, BIT_TARDE, BIT_SOZINHA = 0, 1, 2   # flags_atip
# Parte 2 (medidas_eleitores.py): identificação do eleitor e tempo de cabine. Tag e sinal, fora dos critérios.
P2 = {"foto_min": 20,       # tag "sem digital, com foto": eleitores sem digital cadastrada com foto no cadastro
      "foto_frac": 0.5,     # ... e pelo menos metade dos sem digital da seção
      "perfil_tol": 0.03,   # o cadastro (perfil de julho) só é comparado quando bate com os aptos em ±3%
      "cab_piso": 25,       # sinal "cabine muito rápida": eleitores de 6 cargos com menos de 25 s na cabine
      "cab_seq": 3,         # ... 3 ou mais SEGUIDOS
      "cab_dia": 10,        # ... ou 10 ou mais no dia
      "viz": 10, "viz_ok": 0.8}  # "leitor funcionando em volta": 8+ dos 10 eleitores com digital mais próximos reconhecidos
BIT_FOTO, BIT_CABINE = 0, 1   # flags_p2
COLS_P2 = ["sd_foto", "man_leitor_ok", "cab6", "cab6_med", "cab6_lt20", "cab6_lt25", "cab6_seq25", "cab6_seq25_ini"]


def bit(s: pd.Series, i: int) -> pd.Series:
    """Bit i de uma coluna de bits (pandas não tem >> em Series)."""
    return pd.Series((s.fillna(0).astype("int64").to_numpy() >> i) & 1, index=s.index)


def vagas_senado(ano: int) -> int:
    """Renovação de 2/3 do Senado (2 vagas por UF) em 2002, 2010, 2018, 2026..."""
    return 2 if ano % 8 == 2 else 1


def _chaves(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    d["uf"] = d["uf"].astype(str)
    for c in ["cd_municipio", "zona", "secao"]:
        d[c] = pd.to_numeric(d[c], errors="coerce").astype("int64")
    return d


def _juntar(df: pd.DataFrame, d: pd.DataFrame, colunas: list[str]) -> pd.DataFrame:
    """Junta colunas de d (por seção) ao df, sem duplicar nem reordenar as linhas."""
    d = _chaves(d)[CHAVE + colunas].drop_duplicates(CHAVE)
    k = _chaves(df[CHAVE])
    m = k.merge(d, on=CHAVE, how="left")
    for c in colunas:
        df[c] = m[c].to_numpy()
    return df


def _mad_tau2(resid: pd.Series, var_acaso: pd.Series, grupos, minimo: int = 20) -> pd.Series:
    """τ² (variação natural entre seções além do acaso), por grupo, de forma robusta (mediana/MAD),
    como em analise.z_proporcao, mas vetorizado (para milhões de linhas)."""
    ok = resid.notna()
    r = resid.where(ok)
    med = r.groupby(grupos, observed=True).transform("median")
    mad = (r - med).abs().groupby(grupos, observed=True).transform("median") * 1.4826
    va = var_acaso.where(ok).groupby(grupos, observed=True).transform("median")
    n = r.groupby(grupos, observed=True).transform("count")
    return ((mad ** 2 - va).clip(lower=0)).where(n >= minimo, 0.0).fillna(0.0)


# ================================================================ i) sinais extras do log
def sinais_extras(df: pd.DataFrame) -> pd.DataFrame:
    """Votos antes das 8h, liberações manuais das 16h em diante (comparadas com o município)
    e sequências longas de votos rápidos. Usa os histogramas por hora (h00..h23, m00..m23)."""
    if "h00" not in df:
        return df
    fuso = df["fuso"].fillna(0).astype(int).to_numpy()[:, None]
    hora_br = np.arange(24)[None, :] - fuso
    H = df[[f"h{h:02d}" for h in range(24)]].fillna(0).to_numpy()
    df["votos_antes_8"] = np.where(df["tem_log"], (H * (hora_br < 8)).sum(1), np.nan)
    if "m00" in df and "s00" in df:
        # taxa de liberação manual entre quem votou das 16h em diante e tem digital cadastrada,
        # comparada com a mesma taxa no município. Fila no fim do dia aumenta o número de
        # liberações tardias, mas não a taxa; por isso a comparação é pela taxa.
        M = df[[f"m{h:02d}" for h in range(24)]].fillna(0).to_numpy()
        S = df[[f"s{h:02d}" for h in range(24)]].fillna(0).to_numpy()
        tarde = hora_br >= 16
        m16, v16, s16 = (M * tarde).sum(1), (H * tarde).sum(1), (S * tarde).sum(1)
        cad16 = v16 - (s16 - m16)  # sem cadastro = sem digital - manual
        cad = df["cadastrados"].to_numpy(dtype=float)
        q = np.where(cad > 0, cad16 / np.maximum(cad, 1), np.nan)  # fatia dos eleitores com digital que votou das 16h em diante
        esperado = df["votos_manual"].to_numpy(dtype=float) * q   # liberações tardias se elas seguissem o horário dos votos
        z = (m16 - esperado) / np.sqrt(np.maximum(esperado * (1 - q), 0.25))
        df["manual_16h"] = np.where(df["tem_log"], m16, np.nan)
        df["cadastrados_16h"] = np.where(df["tem_log"], cad16, np.nan)
        df["manual_tarde_esperado"] = np.where(df["tem_log"], esperado, np.nan)
        df["z_manual_tarde"] = np.where(df["tem_log"] & (df["votos_manual"] >= MIN_MANUAL_TARDE), z, np.nan)
    novos = [("antes_8h", df["votos_antes_8"] >= ANTES_8H_SINAL)]
    if "z_manual_tarde" in df:
        novos.append(("manual_tarde", manual_tarde(df)))
    if "maior_seq_rapida" in df:
        novos.append(("rapidos", df["maior_seq_rapida"] >= SEQ_RAPIDA))
    s = df["sinais_cod"].copy()
    for cod, m in novos:
        m = m.fillna(False).astype(bool)
        s = s.where(~m, s + np.where(s == "", "", ",") + cod)
    df["sinais_cod"] = s
    return df


def manual_tarde(df: pd.DataFrame) -> pd.Series:
    """Liberações manuais concentradas das 16h em diante: pelo menos 5, o dobro do esperado pelo
    horário dos votos da própria seção, e bem acima do acaso (z ≥ 3,5)."""
    return ((df["z_manual_tarde"] >= Z_MANUAL_TARDE) & (df["manual_16h"] >= MIN_MANUAL_TARDE)
            & (df["manual_16h"] >= RAZAO_MANUAL_TARDE * df["manual_tarde_esperado"])).fillna(False)


def relatorio_sinais(df: pd.DataFrame) -> dict:
    out = {}
    if "votos_antes_8" in df:
        v = df["votos_antes_8"]
        out["antes_8"] = {"secoes": int((v > 0).sum()), "votos": int(v.fillna(0).sum()),
                          "secoes_sinal": int((v >= ANTES_8H_SINAL).sum())}
    if "manual_16h" in df:
        m = manual_tarde(df)
        out["manual_tarde"] = {"manual_16h": int(df["manual_16h"].fillna(0).sum()),
                               "cadastrados_16h": int(df["cadastrados_16h"].fillna(0).sum()),
                               "manual": int(df["votos_manual"].fillna(0).sum()),
                               "secoes_sinal": int(m.sum()), "z": Z_MANUAL_TARDE, "min": MIN_MANUAL_TARDE,
                               "razao": RAZAO_MANUAL_TARDE}
    if "maior_seq_rapida" in df:
        out["rapidos"] = {"secoes_sinal": int((df["maior_seq_rapida"] >= SEQ_RAPIDA).sum()),
                          "minimo": SEQ_RAPIDA, "com_metrica": int(df["maior_seq_rapida"].notna().sum())}
    return out


# ================================================================ c) perfil do eleitorado
def _referencia_loo(df: pd.DataFrame, num: pd.Series, den: pd.Series) -> pd.Series:
    """Proporção do município sem a própria seção (UF se o município tem < 5 seções),
    a mesma referência usada na abstenção esperada."""
    g = [df["uf"], df["cd_municipio"]]
    s_m, d_m = num.groupby(g).transform("sum"), den.groupby(g).transform("sum")
    s_u, d_u = num.groupby(df["uf"]).transform("sum"), den.groupby(df["uf"]).transform("sum")
    n_m = den.groupby(g).transform("count")
    p_m = (s_m - num) / (d_m - den).replace(0, np.nan)
    p_u = (s_u - num) / (d_u - den).replace(0, np.nan)
    return pd.Series(np.where(n_m >= MIN_SECOES_MUNICIPIO, p_m, p_u), index=df.index).fillna(p_u)


def _ajuste_idade(df, resid, peso, dx: pd.DataFrame, ok) -> tuple[pd.Series, dict]:
    """Quanto a diferença de idade em relação à referência explica do desvio da seção:
    regressão ponderada (peso = tamanho da seção) por UF, sem os casos extremos (|r| > 4 MAD).
    Devolve o ajuste a somar ao esperado e os coeficientes nacionais (para explicar no site)."""
    ajuste = pd.Series(0.0, index=df.index)
    coefs = {}

    def ajustar(idx):
        r = resid[idx]
        x = dx.loc[idx].to_numpy()
        w = peso[idx].to_numpy()
        med = np.median(r)
        mad = 1.4826 * np.median(np.abs(r - med)) or 1e-9
        bom = np.abs(r - med) <= 4 * mad
        X = np.column_stack([np.ones(bom.sum()), x[bom]])
        W = np.sqrt(w[bom])
        b, *_ = np.linalg.lstsq(X * W[:, None], r[bom].to_numpy() * W, rcond=None)
        return b[1:]

    base = ok & resid.notna() & dx.notna().all(axis=1)
    if base.sum() < 50:
        return ajuste, coefs
    b_br = ajustar(base)
    coefs = {c: round(float(v), 4) for c, v in zip(dx.columns, b_br)}
    for uf, idx in df[base].groupby("uf").groups.items():
        b = ajustar(pd.Index(idx)) if len(idx) >= 200 else b_br
        linhas = df.index[(df["uf"] == uf) & dx.notna().all(axis=1)]
        ajuste.loc[linhas] = dx.loc[linhas].to_numpy() @ b
    return ajuste, coefs


def perfil(df: pd.DataFrame, dados: Path, ano: int, niveis: dict, bit_niveis) -> tuple[pd.DataFrame, dict]:
    arqs = sorted(dados.glob(f"perfil_{ano}_*.parquet"))
    if not arqs:
        return df, {}
    p = pd.concat([pd.read_parquet(a) for a in arqs], ignore_index=True)
    cols = [c for c in ["eleitores", "el_16_17", "el_60_69", "el_70_mais", "el_biometria"] if c in p]
    df = _juntar(df, p, cols)
    df = df.rename(columns={"eleitores": "eleitores_perfil"})
    for c in ["eleitores_perfil"] + cols[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    tem = df["eleitores_perfil"].fillna(0) > 0
    den = df["eleitores_perfil"].where(tem)
    df["pct_70"] = df["el_70_mais"] / den
    df["pct_16_17"] = df["el_16_17"] / den
    if "el_biometria" in df:
        df["pct_biometria"] = df["el_biometria"] / den
    ref70 = _referencia_loo(df, df["el_70_mais"].where(tem), den)
    ref16 = _referencia_loo(df, df["el_16_17"].where(tem), den)
    dx = pd.DataFrame({"pct_70": df["pct_70"] - ref70, "pct_16_17": df["pct_16_17"] - ref16})

    # abstenção esperada considerando a idade
    resid = df["taxa_abstencao"] - df["taxa_esperada"]
    aj, coef_abst = _ajuste_idade(df, resid, df["aptos"].astype(float), dx, tem & (df["aptos"] >= 50))
    esp = (df["taxa_esperada"] + aj).clip(1e-3, 1 - 1e-3)
    df["abst_esperada_idade"] = esp.where(tem)
    r2 = df["taxa_abstencao"] - esp
    va = esp * (1 - esp) / df["aptos"]
    tau2 = _mad_tau2(r2.where(tem), va, df["uf"])
    df["z_abst_idade"] = (r2 / np.sqrt(va + tau2)).where(tem)

    # liberação manual esperada considerando a idade (idosos têm mais falha de digital)
    coef_man = {}
    if "z_manual" in df and df["z_manual"].notna().any():
        cad = df["cadastrados"]
        taxa_m = df["votos_manual"] / cad.where(cad >= 30)
        resid_m = taxa_m - df["manual_esperado"]
        aj_m, coef_man = _ajuste_idade(df, resid_m, cad.fillna(0).astype(float), dx[["pct_70"]], tem & (cad >= 30))
        esp_m = (df["manual_esperado"] + aj_m).clip(1e-3, 1 - 1e-3)
        df["manual_esperado_idade"] = esp_m.where(tem & cad.notna())
        r_m = taxa_m - esp_m
        va_m = esp_m * (1 - esp_m) / cad
        tau2_m = _mad_tau2(r_m.where(tem), va_m, df["uf"])
        df["z_manual_idade"] = (r_m / np.sqrt(va_m + tau2_m)).where(tem)

    # "o perfil explica": a seção cumpre o critério, mas com a idade considerada deixaria de cumprir.
    # bit i = nível i (rigoroso, padrão, amplo); 1º trio = abstenção, 2º trio = manual
    expl = np.zeros(len(df), dtype=np.int32)
    for i, (nome, lim) in enumerate(niveis.items()):
        f = bit_niveis(df, nome)
        e_abst = (f & 1).astype(bool) & (df["z_abst_idade"] > -lim["abst_z"])
        expl |= (e_abst.fillna(False).to_numpy().astype(np.int32) << i)
        if "z_manual_idade" in df:
            e_man = (f & 4).astype(bool) & (df["z_manual_idade"] < lim["man_z"])
            expl |= (e_man.fillna(False).to_numpy().astype(np.int32) << (3 + i))
    df["perfil_explica"] = np.where(tem.to_numpy(), expl, 0).astype(np.int32)

    rel = {"coef_abst": coef_abst, "coef_manual": coef_man,
           "secoes_com_perfil": int(tem.sum()), "eleitores": int(df["eleitores_perfil"].fillna(0).sum()),
           "el_70_mais": int(df["el_70_mais"].fillna(0).sum()), "el_16_17": int(df["el_16_17"].fillna(0).sum())}
    if "el_biometria" in df:
        rel["el_biometria"] = int(df["el_biometria"].fillna(0).sum())
    for i, nome in enumerate(niveis):
        f = bit_niveis(df, nome)
        rel[f"{nome}_abst"] = int((f & 1).astype(bool).sum())
        rel[f"{nome}_abst_explica"] = int(bit(df["perfil_explica"], i).sum())
        rel[f"{nome}_man"] = int((f & 4).astype(bool).sum())
        rel[f"{nome}_man_explica"] = int(bit(df["perfil_explica"], 3 + i).sum())
    return df, rel


# ================================================================ f) contexto do local
def contexto(df: pd.DataFrame, dados: Path, ano: int) -> tuple[pd.DataFrame, dict]:
    rel = {}
    loc_arq = dados / f"locais_{ano}.parquet"
    if loc_arq.exists():
        loc = pd.read_parquet(loc_arq)
        if "secao_principal" in loc:
            loc = _chaves(loc.dropna(subset=["cd_municipio", "zona", "secao"]))
            ag = loc[loc["secao_principal"].notna() & (loc["secao_principal"] != loc["secao"])]
            n = ag.groupby(["uf", "cd_municipio", "zona", "secao_principal"]).size().rename("n_agregadas")
            n = n.reset_index().rename(columns={"secao_principal": "secao"})
            if len(n):
                df = _juntar(df, n, ["n_agregadas"])
                rel["agregadas"] = {"secoes_principais": int((df["n_agregadas"] > 0).sum()),
                                    "secoes_agregadas": int(df["n_agregadas"].fillna(0).sum())}
    if "tipo_local" in df and df["tipo_local"].notna().any():
        rel["tipos_local"] = True
    tr_arq = dados / f"transferencia_{ano}.parquet"
    if tr_arq.exists():
        tr = pd.read_parquet(tr_arq)
        cols = [c for c in ["transf_recebidos", "transf_enviados"] if c in tr]
        df = _juntar(df, tr, cols)
        df["pct_transf"] = df["transf_recebidos"] / df["aptos"]
        rel["transferencia"] = {"secoes": int((df["transf_recebidos"] > 0).sum()),
                                "recebidos": int(df["transf_recebidos"].fillna(0).sum())}
    return df, rel


# ================================================================ e) repetição entre eleições e turnos
def eleicao_anterior(df: pd.DataFrame, dados: Path, ano: int, marcar, carregar_logs) -> tuple[pd.DataFrame, dict]:
    """Roda a MESMA análise (critérios e níveis) na eleição anterior e marca, seção a seção
    (mesmo município, zona e número), o que já destoava. Os números de seção podem mudar entre
    eleições (rezoneamento), então só vale para as seções que casam."""
    ant = ano - 4
    arq = dados / f"secoes_{ant}_t1.parquet"
    if not arq.exists():
        return df, {}
    s = pd.read_parquet(arq)
    s = s[s["uf"].astype(str) != "ZZ"].reset_index(drop=True)
    a = pontuar_secoes(s)
    logs = carregar_logs(ant, 1)
    a = marcar(juntar_horario(a, logs))
    cols = {"flags": "flags_ant", "z_ajustado": "z_abst_ant", "taxa_abstencao": "taxa_abst_ant", "aptos": "aptos_ant"}
    if "pct_apos_17" in a:
        cols |= {"pct_apos_17": "pct_apos_17_ant", "votos_apos_17": "votos_apos_17_ant"}
    if "z_manual" in a:
        cols |= {"z_manual": "z_manual_ant", "votos_manual": "votos_manual_ant"}
    a = a.rename(columns=cols)
    df = _juntar(df, a, list(cols.values()))
    df["tem_ant"] = df["aptos_ant"].notna()
    rel = {"ano": ant, "com_logs": logs is not None, "secoes_casadas": int(df["tem_ant"].sum()),
           "secoes": len(df)}
    return df, rel


def resumo_repeticao(df: pd.DataFrame, niveis) -> dict:
    out = {}
    if "flags_ant" not in df:
        return out
    fa = df["flags_ant"].fillna(0).astype(int)
    for i, nome in enumerate(niveis):
        f = df[f"f_{nome}"]
        fant = pd.Series((fa.to_numpy() >> (3 * i)) & 7, index=df.index)
        for k, b in [("abst", 1), ("17h", 2), ("man", 4)]:
            m = (f & b).astype(bool)
            out[f"{nome}_{k}"] = [int(m.sum()), int((m & df["tem_ant"]).sum()), int((m & ((fant & b) > 0)).sum())]
        m = f > 0
        out[f"{nome}_sec"] = [int(m.sum()), int((m & df["tem_ant"]).sum()), int((m & (fant > 0)).sum())]
    return out


def outro_turno(df: pd.DataFrame, dados: Path, ano: int, turno: int, carregar_logs) -> tuple[pd.DataFrame, dict]:
    """Compara o comparecimento seção a seção entre o 1º e o 2º turno do mesmo ano.
    Destaca a seção cujo comparecimento SOBE muito mais que o das outras seções do município."""
    outro = 2 if turno == 1 else 1
    arq = dados / f"secoes_{ano}_t{outro}.parquet"
    if not arq.exists():
        return df, {}
    o = pd.read_parquet(arq)
    o = o[o["uf"].astype(str) != "ZZ"]
    o["taxa_comp"] = o["comparecimento"] / o["aptos"]
    cols = ["taxa_comp", "comparecimento"]
    logs = carregar_logs(ano, outro)
    if logs is not None and "votos_apos_17" in logs:
        o = _juntar(o.reset_index(drop=True), logs, ["votos_apos_17"])
        cols.append("votos_apos_17")
    o = o.rename(columns={c: f"{c}_t{outro}" for c in cols})
    df = _juntar(df, o, [f"{c}_t{outro}" for c in cols])
    df[f"taxa_comp_t{turno}"] = df["comparecimento"] / df["aptos"]
    t1, t2 = df["taxa_comp_t1"], df["taxa_comp_t2"]
    dif = (t2 - t1).where(df["aptos"] >= 50)
    g = [df["uf"], df["cd_municipio"]]
    med = dif.groupby(g).transform("median")
    mad = ((dif - med).abs().groupby(g).transform("median") * 1.4826).clip(lower=0.02)
    df["dif_comp_turnos"] = dif
    df["z_comp_turnos"] = (dif - med) / mad
    sobe = (df["z_comp_turnos"] >= TURNOS_Z) & (dif >= TURNOS_DIF)
    df["comp_sobe_turno"] = sobe.fillna(False)
    rel = {"outro_turno": outro, "secoes_casadas": int(dif.notna().sum()),
           "comp_t1": int(df["comparecimento" if turno == 1 else "comparecimento_t1"].fillna(0).sum()),
           "comp_t2": int(df["comparecimento" if turno == 2 else "comparecimento_t2"].fillna(0).sum()),
           "secoes_sobe": int(sobe.sum()), "z": TURNOS_Z, "dif": TURNOS_DIF}
    if "votos_apos_17_t2" in df or turno == 2:
        v1 = df["votos_apos_17" if turno == 1 else "votos_apos_17_t1"]
        v2 = df["votos_apos_17" if turno == 2 else "votos_apos_17_t2"]
        so2 = (v1.fillna(0) == 0) & (v2 >= 10)
        df["apos17_so_t2"] = so2
        rel["apos17_so_t2"] = int(so2.sum())
    return df, rel


# ================================================================ d) cadastro inflado
def cadastro(mun: pd.DataFrame, dados: Path, ano: int) -> tuple[pd.DataFrame, dict]:
    """Por município: eleitores ÷ população com 16+ (IBGE) e crescimento do eleitorado
    desde a eleição anterior."""
    rel = {}
    pops = sorted(dados.glob("populacao_*.parquet"))
    if pops:
        p = pd.read_parquet(pops[-1])
        p["cd_ibge"] = p["cd_ibge"].astype(str)
        mun = mun.merge(p[["cd_ibge", "pop_total", "pop_16_mais"]], on="cd_ibge", how="left")
        mun["razao_pop"] = mun["aptos"] / mun["pop_16_mais"].where(mun["pop_16_mais"] > 0)
        rel["populacao"] = {"arquivo": pops[-1].stem, "municipios": int(mun["razao_pop"].notna().sum()),
                            "acima_1": int((mun["razao_pop"] > 1).sum()),
                            "acima_1_1": int((mun["razao_pop"] > 1.1).sum())}
    arq = dados / f"secoes_{ano - 4}_t1.parquet"
    if arq.exists():
        a = pd.read_parquet(arq, columns=["uf", "cd_municipio", "aptos"])
        a = a[a["uf"].astype(str) != "ZZ"]
        t = a.groupby(a["cd_municipio"].astype(int))["aptos"].sum().rename("aptos_mun_ant")
        mun = mun.join(t, on="cd_municipio")
        mun["cresc_eleitorado"] = mun["aptos"] / mun["aptos_mun_ant"] - 1
        rel["crescimento"] = {"ano_ant": ano - 4, "municipios": int(mun["cresc_eleitorado"].notna().sum()),
                              "aptos": int(mun["aptos"].sum()), "aptos_ant": int(t.sum()),
                              "acima_20": int((mun["cresc_eleitorado"] > 0.2).sum())}
    return mun, rel


# ================================================================ g) gastos de campanha
def gastos(mun: pd.DataFrame, dados: Path, ano: int) -> tuple[pd.DataFrame, dict]:
    arq = dados / f"gastos_{ano}.parquet"
    if not arq.exists():
        return mun, {}
    bruto = pd.read_parquet(arq)
    sem_mun = float(bruto.loc[bruto["cd_municipio"].isna(), "valor"].sum())
    total = float(bruto["valor"].sum())
    if total > 0 and sem_mun / total > 0.5:
        # 2026: o TSE publicou as despesas sem o município do fornecedor; não dá para dividir por município
        print(f"  gastos: {sem_mun / total:.1%} do valor sem município do fornecedor; relatório por município desligado")
        return mun, {"total": round(total, 2), "sem_municipio": round(sem_mun, 2), "sem_municipio_maioria": True}
    g = bruto.dropna(subset=["cd_municipio"])
    pv = g.pivot_table(index=g["cd_municipio"].astype(int), columns="categoria", values="valor", aggfunc="sum").fillna(0)
    pv.columns = [f"gasto_{c}" for c in pv.columns]
    pv["gasto_total"] = pv.sum(axis=1)
    mun = mun.join(pv, on="cd_municipio")
    mun["gasto_eleitor"] = mun["gasto_total"] / mun["aptos"]
    med_uf = mun.groupby("uf")["gasto_eleitor"].transform("median")
    mun["gasto_vs_uf"] = mun["gasto_eleitor"] / med_uf.where(med_uf > 0)
    rel = {"total": round(float(bruto["valor"].sum()), 2), "sem_municipio": round(float(bruto.loc[bruto["cd_municipio"].isna(), "valor"].sum()), 2),
           "por_categoria": {c: round(float(v), 2) for c, v in bruto.groupby("categoria")["valor"].sum().items()},
           "municipios": int(mun["gasto_total"].gt(0).sum())}
    return mun, rel


# ================================================================ a) e b) votação por seção
def _carregar_votacao(dados: Path, ano: int, turno: int):
    for a in sorted(dados.glob(f"votacao_{ano}_t{turno}_*.parquet")):
        yield a.stem.rsplit("_", 1)[1], pd.read_parquet(a)


def votacao(df: pd.DataFrame, dados: Path, ano: int, turno: int, niveis) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    """Materialidade (totais por candidato) e voto concentrado (por seção e candidato)."""
    totais, conc_secoes, bn = [], [], []
    for uf, v in _carregar_votacao(dados, ano, turno):
        v = v.copy()
        v["uf"] = v["uf"].astype(str)
        v["cargo"] = v["cargo"].astype(int)
        nomes = v.drop_duplicates(["cargo", "votavel"]).set_index(["cargo", "votavel"])["nome"].astype(str)
        t = v.groupby(["uf", "cargo", "votavel"], observed=True)["votos"].sum().reset_index()
        t["nome"] = [nomes.get((c, n)) for c, n in zip(t["cargo"], t["votavel"])]
        totais.append(t)
        if uf in ("ZZ", "BR"):  # exterior, ou o arquivo nacional de Presidente: só entram na materialidade
            continue
        c, b = _concentracao(v, df[df["uf"] == uf])
        conc_secoes.append(c)
        bn.append(b)
    if not totais:
        return df, {}, pd.DataFrame()
    tot = pd.concat(totais, ignore_index=True)
    rel = {"materialidade_tot": tot}

    # brancos e nulos por seção (deputado federal como referência; o cargo do voto concentrado se houver)
    if bn:
        b = pd.concat(bn, ignore_index=True)
        for cargo in sorted(b["cargo"].unique()):
            bc = b[b["cargo"] == cargo]
            df = _juntar(df, bc.rename(columns={"z_bn": f"z_bn_{cargo}", "pct_bn": f"pct_bn_{cargo}",
                                                "bn": f"bn_{cargo}", "esp_bn": f"esp_bn_{cargo}"}),
                         [f"z_bn_{cargo}", f"pct_bn_{cargo}", f"bn_{cargo}", f"esp_bn_{cargo}"])
    conc = pd.concat(conc_secoes, ignore_index=True) if conc_secoes else pd.DataFrame()
    if len(conc):
        cols = ["conc_cargo", "conc_votavel", "conc_nome", "conc_votos", "conc_validos", "conc_fatia",
                "conc_esperada", "conc_z", "flags_conc"]
        df = _juntar(df, conc, cols)
        df["flags_conc"] = df["flags_conc"].fillna(0).astype(int)
        # brancos e nulos do mesmo cargo do voto concentrado
        zb = pd.Series(np.nan, index=df.index)
        pb = pd.Series(np.nan, index=df.index)
        eb = pd.Series(np.nan, index=df.index)
        for cargo in CARGOS_CONC:
            if f"z_bn_{cargo}" in df:
                m = df["conc_cargo"] == cargo
                zb = zb.where(~m, df[f"z_bn_{cargo}"])
                pb = pb.where(~m, df[f"pct_bn_{cargo}"])
                eb = eb.where(~m, df[f"esp_bn_{cargo}"])
        df["conc_z_bn"], df["conc_pct_bn"], df["conc_esp_bn"] = zb, pb, eb
    else:
        df["flags_conc"] = 0
    # z_bn principal para o detalhe: deputado federal
    if "z_bn_6" in df:
        df["z_bn"], df["pct_bn"], df["esp_bn"] = df["z_bn_6"], df["pct_bn_6"], df["esp_bn_6"]
    return df, rel, conc


def _concentracao(v: pd.DataFrame, sec: pd.DataFrame):
    """Para cada seção e candidato a deputado: fatia dos votos válidos da seção vs a fatia do
    candidato no resto do município (UF se o município tem < 5 seções), com a mesma conta de
    analise.z_proporcao (acaso + variação natural τ², estimada por candidato de forma robusta).
    Devolve o candidato mais destacado de cada seção e os brancos e nulos por seção e cargo."""
    v = v[v["cargo"].isin(list(CARGOS_CONC))]
    if v.empty:
        return pd.DataFrame(), pd.DataFrame()
    v = _chaves(v)
    k = ["uf", "cd_municipio", "zona", "secao", "cargo"]
    tot = v.groupby(k)["votos"].sum().rename("total")
    eh_bn = v["votavel"].isin([BRANCO, NULO])
    bn = v[eh_bn].groupby(k)["votos"].sum().rename("bn")
    s = pd.concat([tot, bn], axis=1).fillna(0).reset_index()
    s["validos"] = s["total"] - s["bn"]
    # brancos e nulos por seção e cargo, comparados com o município (mesmo método)
    bn_out = []
    for cargo, g in s.groupby("cargo"):
        g = g.reset_index(drop=True)
        z, esp = z_proporcao(g, g["bn"], g["total"])
        bn_out.append(g[CHAVE].assign(cargo=cargo, bn=g["bn"], z_bn=z, esp_bn=esp,
                                      pct_bn=g["bn"] / g["total"].where(g["total"] > 0)))
    bn_df = pd.concat(bn_out, ignore_index=True)

    c = v[~eh_bn & (v["votavel"] >= 100)].merge(s[k + ["validos"]], on=k, how="left")
    c = c[c["validos"] > 0]
    gm = ["uf", "cd_municipio", "cargo"]
    s_m = s.groupby(gm)["validos"].transform("sum")
    d_mun = s.assign(d_mun=s_m).groupby(gm)["d_mun"].first()
    n_mun = s.groupby(gm).size().rename("n_mun")
    d_uf = s.groupby(["uf", "cargo"])["validos"].sum().rename("d_uf")
    v_mun = c.groupby(gm + ["votavel"])["votos"].sum().rename("v_mun")
    v_uf = c.groupby(["uf", "cargo", "votavel"])["votos"].sum().rename("v_uf")
    c = c.join(d_mun, on=gm).join(n_mun, on=gm).join(d_uf, on=["uf", "cargo"]) \
         .join(v_mun, on=gm + ["votavel"]).join(v_uf, on=["uf", "cargo", "votavel"])
    p_mun = (c["v_mun"] - c["votos"]) / (c["d_mun"] - c["validos"]).replace(0, np.nan)
    p_uf = (c["v_uf"] - c["votos"]) / (c["d_uf"] - c["validos"]).replace(0, np.nan)
    esp = pd.Series(np.where(c["n_mun"] >= MIN_SECOES_MUNICIPIO, p_mun, p_uf), index=c.index).fillna(p_uf)
    p = esp.clip(1e-3, 1 - 1e-3)
    fatia = c["votos"] / c["validos"]
    va = p * (1 - p) / c["validos"]
    resid = fatia - p
    tau2 = _mad_tau2(resid, va, [c["cargo"], c["votavel"]])
    c["conc_z"] = resid / np.sqrt(va + tau2)
    c["conc_fatia"], c["conc_esperada"] = fatia, esp
    flags = np.zeros(len(c), dtype=np.int32)
    for i, lim in enumerate(CONC.values()):
        m = (c["conc_z"] >= lim["z"]) & (fatia >= lim["fatia"]) & (c["votos"] >= lim["votos"])
        flags |= m.to_numpy().astype(np.int32) << i
    c["flags_conc"] = flags
    c = c[(c["votos"] >= min(l["votos"] for l in CONC.values()))]
    c = c.sort_values(["flags_conc", "conc_z"], ascending=False).drop_duplicates(CHAVE)
    c = c.rename(columns={"cargo": "conc_cargo", "votavel": "conc_votavel", "nome": "conc_nome",
                          "votos": "conc_votos", "validos": "conc_validos"})
    c["conc_nome"] = c["conc_nome"].astype(str)
    return c, bn_df


def materialidade(df: pd.DataFrame, tot: pd.DataFrame, ano: int, niveis) -> list[dict]:
    """Para presidente (Brasil) e governador e senador (cada UF): 1º e 2º colocados (e a última
    vaga, no Senado com 2 vagas) ao lado dos votos das seções em atenção."""
    d = df.copy()
    d["excesso_comp"] = (d["comparecimento"] - d["aptos"] * (1 - d["taxa_esperada"])).clip(lower=0)
    em_atencao = {}
    for nome in niveis:
        f = d[f"f_{nome}"] > 0
        g = d[f].groupby("uf")
        em_atencao[nome] = pd.DataFrame({
            "secoes": g.size(), "v17": g["votos_apos_17"].sum(), "manual": g["votos_manual"].sum(),
            "excesso": g["excesso_comp"].sum(), "aptos": g["aptos"].sum()}).fillna(0)
    out = []
    validos = tot[~tot["votavel"].isin([BRANCO, NULO])]
    for cargo, rot in CARGOS_MAT.items():
        tc = validos[validos["cargo"] == cargo]
        if tc.empty:
            continue
        escopos = [("BR", tc.groupby(["votavel"]).agg(votos=("votos", "sum"), nome=("nome", "first")))] if cargo == 1 else \
                  [(uf, g.groupby("votavel").agg(votos=("votos", "sum"), nome=("nome", "first")))
                   for uf, g in tc[tc["uf"] != "ZZ"].groupby("uf")]
        vagas = vagas_senado(ano) if cargo == 5 else 1
        for esc, t in escopos:
            t = t.sort_values("votos", ascending=False)
            if len(t) < 2:
                continue
            total_validos = int(t["votos"].sum())
            cand = [{"nome": str(r.nome), "numero": int(i), "votos": int(r.votos)} for i, r in t.head(vagas + 2).iterrows()]
            linha = {"cargo": cargo, "rotulo": rot, "escopo": esc, "vagas": vagas, "validos": total_validos,
                     "candidatos": cand, "dif_1_2": cand[0]["votos"] - cand[1]["votos"]}
            if vagas == 2 and len(cand) >= 3:
                linha["dif_ultima_vaga"] = cand[1]["votos"] - cand[2]["votos"]
            if cargo in (1, 3) and len(cand) >= 3:
                linha["dif_2_3"] = cand[1]["votos"] - cand[2]["votos"]
                linha["falta_maioria"] = int(total_validos // 2 + 1 - cand[0]["votos"])
            for nome, ea in em_atencao.items():
                e = ea.sum() if esc == "BR" else (ea.loc[esc] if esc in ea.index else pd.Series(0, index=ea.columns))
                linha[nome] = {k: int(round(float(e[k]))) for k in ["secoes", "v17", "manual", "excesso", "aptos"]}
            out.append(linha)
    return out


def resumo_concentracao(df: pd.DataFrame, niveis) -> dict:
    if "conc_z" not in df:
        return {}
    out = {"limites": CONC, "cargos": {str(k): v for k, v in CARGOS_CONC.items()}, "z_bn_baixo": Z_BN_BAIXO}
    for i, nome in enumerate(niveis):
        c = bit(df["flags_conc"], i).astype(bool)
        abst = (df[f"f_{nome}"] & 1).astype(bool)
        bnb = df["conc_z_bn"] <= Z_BN_BAIXO
        out[nome] = {"secoes": int(c.sum()), "com_abst": int((c & abst).sum()), "com_bn": int((c & bnb).sum()),
                     "tudo": int((c & abst & bnb).sum()), "votos": int(df.loc[c, "conc_votos"].sum())}
    return out


# ================================================================ h) rotas de fiscalização
def _km(lat1, lon1, lat2, lon2):
    r = math.pi / 180
    a = np.sin((lat2 - lat1) * r / 2) ** 2 + np.cos(lat1 * r) * np.cos(lat2 * r) * np.sin((lon2 - lon1) * r / 2) ** 2
    return 2 * 6371 * np.arcsin(np.sqrt(a))


def rotas(esc: pd.DataFrame, raio_km: float = RAIO_ROTA_KM) -> pd.DataFrame:
    """Agrupa os locais de prioridade ALTA a até `raio_km` uns dos outros (em cadeia), dentro do
    município, e ordena cada grupo pelo vizinho mais próximo, começando pelo local com mais
    seções em atenção. Um fiscal pode cobrir o grupo se o horário permitir."""
    esc = esc.copy()
    esc["rota"], esc["rota_ordem"], esc["rota_km"] = None, np.nan, np.nan
    if esc.empty:
        return esc
    alta = esc[(esc["prioridade"] == 3) & esc["lat"].notna() & esc["lon"].notna()]
    n_rota = 0
    for (uf, cd), g in alta.groupby(["uf", "cd_municipio"]):
        if len(g) < 2:
            continue
        lat, lon = g["lat"].to_numpy(float), g["lon"].to_numpy(float)
        d = _km(lat[:, None], lon[:, None], lat[None, :], lon[None, :])
        pai = list(range(len(g)))

        def raiz(i):
            while pai[i] != i:
                pai[i] = pai[pai[i]]
                i = pai[i]
            return i
        for i, j in zip(*np.nonzero(np.triu(d <= raio_km, 1))):
            pai[raiz(i)] = raiz(j)
        grupos = {}
        for i in range(len(g)):
            grupos.setdefault(raiz(i), []).append(i)
        for membros in grupos.values():
            if len(membros) < 2:
                continue
            n_rota += 1
            sinal = g["sinalizadas"].to_numpy()
            atual = max(membros, key=lambda i: sinal[i])
            ordem, resto, kms = [atual], set(membros) - {atual}, [0.0]
            while resto:
                prox = min(resto, key=lambda i: d[atual, i])
                kms.append(float(d[atual, prox]))
                ordem.append(prox)
                resto.discard(prox)
                atual = prox
            for pos, (i, km) in enumerate(zip(ordem, kms), 1):
                idx = g.index[i]
                esc.loc[idx, "rota"] = f"{uf}-{n_rota}"
                esc.loc[idx, "rota_ordem"] = pos
                esc.loc[idx, "rota_km"] = round(km, 2)
    return esc


# ================================================================ liberações pelo mesário por hora
def liberacoes(df: pd.DataFrame, manual: np.ndarray, cadastrados: np.ndarray, niveis) -> pd.DataFrame:
    """Tags sobre as liberações pelo mesário ao longo do dia (não mudam os 3 critérios).
    manual e cadastrados: por seção e faixa de horário de Brasília (8h ... 16h, 17h, 18h+), como
    gerar_site.faixas_brasilia. Grava em df:
      man17, cad17          liberações pelo mesário e eleitores com digital depois das 17h
      man_dia, cad_dia      o mesmo até as 17h
      defeito_desde         hora em que o leitor passou a falhar com quase todos (8 = o dia todo)
      flags_lib             bits 0-2: 'depois das 17h' por nível; 3-5: 'salto às 17h' por nível;
                            bit 6: leitor com defeito provável
      horas_man, horas_cad  as faixas, para o cartão hora a hora do detalhe da seção"""
    M = np.asarray(manual, dtype=float)
    C = np.asarray(cadastrados, dtype=float)
    tem = df["tem_log"].to_numpy(dtype=bool) if "tem_log" in df else C.sum(1) > 0
    m17, c17 = M[:, 9:].sum(1), C[:, 9:].sum(1)
    md, cd = M[:, :9].sum(1), C[:, :9].sum(1)
    with np.errstate(divide="ignore", invalid="ignore"):
        tx17 = np.where(c17 > 0, m17 / c17, np.nan)
        txd = np.where(cd > 0, md / cd, np.nan)
        tx_cedo = np.where(C[:, :6].sum(1) > 0, M[:, :6].sum(1) / C[:, :6].sum(1), np.nan)  # 8h às 13h
        tx_pre = np.where(C[:, 6:9].sum(1) > 0, M[:, 6:9].sum(1) / C[:, 6:9].sum(1), np.nan)  # 14h às 16h

    # leitor com defeito provável: o dia todo, ou a partir de uma hora até as 16h (depois disso é "salto")
    desde = np.full(len(df), np.nan)
    tot_m, tot_c = M.sum(1), C.sum(1)
    with np.errstate(divide="ignore", invalid="ignore"):
        todo = (tot_c >= DEFEITO_MIN) & (tot_m / tot_c >= DEFEITO_TAXA)
    desde[todo] = 8
    for j in range(1, 9):  # começou às 9h, 10h ... 16h
        ma, ca = M[:, j:].sum(1), C[:, j:].sum(1)
        mb, cb = M[:, :j].sum(1), C[:, :j].sum(1)
        with np.errstate(divide="ignore", invalid="ignore"):
            ok = (ca >= DEFEITO_MIN) & (ma / ca >= DEFEITO_TAXA) & (cb >= 10) & (mb / cb <= DEFEITO_ANTES)
        desde = np.where(np.isnan(desde) & ok, 8 + j, desde)
    defeito = ~np.isnan(desde) & tem

    flags = np.zeros(len(df), dtype=np.int64)
    for i, nome in enumerate(niveis):
        p = LIB[nome]
        apos = tem & (m17 >= p["min17"])
        with np.errstate(invalid="ignore"):
            salto = (tem & ~defeito & (m17 >= SALTO_MIN) & (tx17 - np.nan_to_num(txd) >= p["salto"])
                     & (tx17 >= 2 * np.nan_to_num(txd))
                     & ~(np.nan_to_num(tx_pre) > np.nan_to_num(tx_cedo) + SALTO_ANTES_FOLGA))
        flags |= apos.astype(np.int64) << i
        flags |= salto.astype(np.int64) << (3 + i)
    flags |= defeito.astype(np.int64) << BIT_DEFEITO
    df["man17"] = np.where(tem, m17, np.nan)
    df["cad17"] = np.where(tem, c17, np.nan)
    df["man_dia"] = np.where(tem, md, np.nan)
    df["cad_dia"] = np.where(tem, cd, np.nan)
    df["defeito_desde"] = np.where(defeito, desde, np.nan)
    df["flags_lib"] = flags
    df["horas_man"] = [" ".join(str(int(x)) for x in r) for r in M]
    df["horas_cad"] = [" ".join(str(int(x)) for x in r) for r in C]
    return df


def resumo_liberacoes(df: pd.DataFrame, niveis) -> dict:
    if "flags_lib" not in df:
        return {}
    f = df["flags_lib"].fillna(0).astype("int64")
    out = {"limites": LIB, "salto_min": SALTO_MIN, "defeito_taxa": DEFEITO_TAXA,
           "man17": int(df["man17"].fillna(0).sum()), "cad17": int(df["cad17"].fillna(0).sum()),
           "man_dia": int(df["man_dia"].fillna(0).sum()), "cad_dia": int(df["cad_dia"].fillna(0).sum()),
           "defeito": int(bit(f, BIT_DEFEITO).sum()),
           "defeito_dia_todo": int((df["defeito_desde"] == 8).sum())}
    for i, nome in enumerate(niveis):
        a, s = bit(f, i) > 0, bit(f, 3 + i) > 0
        out[nome] = {"apos17": int(a.sum()), "apos17_lib": int(df.loc[a, "man17"].sum()),
                     "salto": int(s.sum()), "salto_lib": int(df.loc[s, "man17"].sum())}
    return out


# ================================================================ casos extremamente atípicos
def atipicos(df: pd.DataFrame) -> pd.DataFrame:
    """Tags de casos extremamente atípicos (não mudam os 3 critérios). Grava em df:
      fora_log               comparecimento oficial − votos no log (só seções com log)
      ult_outras             último voto (Brasília) entre as OUTRAS seções do mesmo local
      v17_outras, aptos_outras   média de votos após 17h e de aptos das outras seções do local
      local_com_log          seções do local com log
      zona_19, zona_log      seções da zona com último voto depois das 19h; seções da zona com log
      flags_atip             bit 0 votos fora do log; bit 1 urna começou tarde; bit 2 terminou sozinha"""
    if "votos_log" not in df or "ultimo_voto" not in df:
        return df
    P = ATIP
    tem = df["tem_log"].astype(bool) & (df["votos_log"].fillna(0) >= 0)
    df["fora_log"] = (df["comparecimento"] - df["votos_log"]).where(tem)
    fora = tem & (df["fora_log"] >= P["fora_min"])
    tarde = tem & (df["abertura"] >= P["tarde_hora"])

    # outras seções do mesmo local (só as que têm log e algum voto)
    com = tem & (df["votos_log"] > 0) & df["local"].notna()
    d = df.loc[com, ["uf", "cd_municipio", "zona", "local", "ultimo_voto", "votos_apos_17", "aptos"]].copy()
    d["votos_apos_17"] = d["votos_apos_17"].fillna(0)
    g = d.groupby(["uf", "cd_municipio", "zona", "local"], observed=True, sort=False)
    nloc = g["ultimo_voto"].transform("size")
    mx = g["ultimo_voto"].transform("max")
    # o 2º maior último voto do local (para a seção que é a última, "as outras" terminam nele)
    seg = d["ultimo_voto"].where(d["ultimo_voto"] < mx).groupby([d[c] for c in ["uf", "cd_municipio", "zona", "local"]],
                                                              observed=True, sort=False).transform("max")
    empate = (d["ultimo_voto"] == mx).groupby([d[c] for c in ["uf", "cd_municipio", "zona", "local"]],
                                              observed=True, sort=False).transform("sum") > 1
    ult_outras = mx.where((d["ultimo_voto"] < mx) | empate, seg)
    outras = (nloc - 1).where(nloc > 1)
    v17_outras = (g["votos_apos_17"].transform("sum") - d["votos_apos_17"]) / outras
    aptos_outras = (g["aptos"].transform("sum") - d["aptos"]) / outras
    for nome, v in [("ult_outras", ult_outras), ("v17_outras", v17_outras), ("aptos_outras", aptos_outras),
                    ("local_com_log", nloc)]:
        df[nome] = v.reindex(df.index)
    agreg = df["n_agregadas"].fillna(0) > 0 if "n_agregadas" in df else pd.Series(False, index=df.index)
    sozinha = (com & (df["local_com_log"] >= P["soz_secoes"])
               & ((df["ultimo_voto"] - df["ult_outras"]) * 60 >= P["soz_min"])
               & (df["v17_outras"] <= P["soz_outras17"]) & (df["votos_apos_17"] >= P["soz_votos17"])
               & ~agreg & (df["aptos"] < P["soz_aptos"] * df["aptos_outras"]))

    # contexto: a zona inteira votou até tarde?
    z = df.loc[tem & (df["votos_log"] > 0), ["cd_municipio", "zona", "ultimo_voto"]]
    gz = (z["ultimo_voto"] >= P["zona_hora"]).groupby([z["cd_municipio"], z["zona"]], observed=True)
    ctx = pd.DataFrame({"zona_19": gz.sum(), "zona_log": gz.size()}).reset_index()
    df = df.drop(columns=[c for c in ["zona_19", "zona_log"] if c in df]).merge(ctx, on=["cd_municipio", "zona"], how="left")
    df["flags_atip"] = (fora.fillna(False).to_numpy().astype(np.int64) << BIT_FORA
                        | tarde.fillna(False).to_numpy().astype(np.int64) << BIT_TARDE
                        | sozinha.fillna(False).to_numpy().astype(np.int64) << BIT_SOZINHA)
    return df


def n_atipicos(df: pd.DataFrame, i_nivel: int) -> pd.Series:
    """Quantos padrões extremamente atípicos a seção reúne (os de flags_atip + 'salto às 17h' do nível).
    'Votos fora do log' e 'urna começou tarde' juntos contam como UM: nos dados reais de 2026 toda urna que
    começou tarde também tem votos fora do log (é a mesma troca de urna)."""
    f = df["flags_atip"].fillna(0).astype("int64")
    q = np.maximum(bit(f, BIT_FORA), bit(f, BIT_TARDE)) + bit(f, BIT_SOZINHA)
    if "flags_lib" in df:
        q = q + bit(df["flags_lib"].fillna(0).astype("int64"), 3 + i_nivel)
    return q


def resumo_atipicos(df: pd.DataFrame, niveis) -> dict:
    if "flags_atip" not in df:
        return {}
    f = df["flags_atip"].fillna(0).astype("int64")
    fora, tarde, soz = bit(f, BIT_FORA) > 0, bit(f, BIT_TARDE) > 0, bit(f, BIT_SOZINHA) > 0
    out = {"limites": ATIP,
           "fora": int(fora.sum()), "fora_votos": int(df.loc[fora, "fora_log"].sum()),
           "fora_metade": int((fora & (df["votos_log"] < df["comparecimento"] / 2)).sum()),
           "fora_vazio": int((fora & (df["votos_log"] == 0)).sum()),
           "tarde": int(tarde.sum()), "tarde_17": int((tarde & (df["abertura"] >= 17)).sum()),
           "sozinha": int(soz.sum()), "sozinha_v17": int(df.loc[soz, "votos_apos_17"].sum())}
    for i, nome in enumerate(niveis):
        q = n_atipicos(df, i)
        out[nome] = {"secoes": int((q > 0).sum()), "mult": int((q >= 2).sum())}
    # referência nacional do contexto de zona: em quantas zonas isso acontece
    z = df[df["zona_log"] > 0].drop_duplicates(["cd_municipio", "zona"])
    out["zonas"] = int(len(z))
    out["zonas_sem_19"] = int((z["zona_19"] == 0).sum())
    out["zonas_tarde"] = int((z["zona_19"] / z["zona_log"] >= ATIP["zona_alta"]).sum())
    return out


# ================================================================ Parte 2: identificação do eleitor e tempo de cabine
def parte2(df: pd.DataFrame, dados: Path, ano: int, turno: int) -> tuple[pd.DataFrame, dict]:
    """Junta as medidas por seção de medidas_eleitores.py (se o arquivo existir). Grava em df:
      sd_foto               eleitores sem digital cadastrada que têm foto no cadastro
      sd_cadastro, sd_excesso   eleitores sem biometria no cadastro de julho e quantos votaram "sem digital" a mais que isso
                            (só onde o perfil bate com os aptos)
      man_leitor_ok         liberações pelo mesário com o leitor reconhecendo a maioria dos eleitores em volta
      cab6, cab6_med, cab6_lt20, cab6_lt25, cab6_seq25, cab6_seq25_ini   tempo de cabine dos eleitores de 6 cargos
      flags_p2              bit 0: tag "sem digital, com foto"; bit 1: sinal "cabine muito rápida"
    e troca o sinal "rapidos" (intervalo entre votos, que se confunde com voto em trânsito) por "cabine"."""
    arq = dados / f"medidas_eleitores_{ano}_t{turno}.parquet"
    if not arq.exists():
        return df, {}
    m = pd.read_parquet(arq, columns=CHAVE + COLS_P2)
    df = _juntar(df, m, COLS_P2)
    tem = df["tem_log"].astype(bool) & df["cab6"].notna()
    fuso = df["fuso"].fillna(0) if "fuso" in df else 0
    df["cab6_seq25_ini"] = (df["cab6_seq25_ini"] / 3600 - fuso).where(df["cab6_seq25"] > 0)
    sd = df["votos_sem_cadastro"]
    foto = tem & (df["sd_foto"] >= P2["foto_min"]) & (df["sd_foto"] >= P2["foto_frac"] * sd)
    cabine = tem & ((df["cab6_seq25"] >= P2["cab_seq"]) | (df["cab6_lt25"] >= P2["cab_dia"]))
    if "el_biometria" in df and "eleitores_perfil" in df:
        bate = (df["eleitores_perfil"] > 0) & ((df["eleitores_perfil"] - df["aptos"]).abs() <= P2["perfil_tol"] * df["aptos"])
        df["sd_cadastro"] = (df["eleitores_perfil"] - df["el_biometria"]).where(bate & tem)
        df["sd_excesso"] = (sd - df["sd_cadastro"]).where(bate & tem)
    df["flags_p2"] = (foto.fillna(False).to_numpy().astype(np.int64) << BIT_FOTO
                      | cabine.fillna(False).to_numpy().astype(np.int64) << BIT_CABINE)
    # o sinal antigo de votos rápidos sai; entra o de cabine
    s = df["sinais_cod"].str.replace(r"(^|,)rapidos(?=,|$)", "", regex=True).str.lstrip(",")
    df["sinais_cod"] = s.where(~cabine.fillna(False), s + np.where(s == "", "", ",") + "cabine")
    T = df.loc[tem]
    rel = {"limites": P2, "sd": int(sd[tem].sum()), "sd_foto": int(T["sd_foto"].sum()),
           "foto_secoes": int(foto.sum()), "foto_municipios": int(df.loc[foto, "cd_municipio"].nunique()),
           "foto_eleitores": int(df.loc[foto, "sd_foto"].sum()),
           "man": int(df.loc[tem, "votos_manual"].sum()), "man_leitor_ok": int(T["man_leitor_ok"].sum()),
           "cab6": int(T["cab6"].sum()), "cab6_lt25": int(T["cab6_lt25"].sum()), "cab6_lt20": int(T["cab6_lt20"].sum()),
           "cab6_med": float(T["cab6_med"].median()), "cabine_secoes": int(cabine.sum()),
           "cabine_seq": int((tem & (df["cab6_seq25"] >= P2["cab_seq"])).sum())}
    if "sd_excesso" in df:
        rel["excesso_secoes"] = int((df["sd_excesso"] >= P2["foto_min"]).sum())
        rel["excesso_e_foto"] = int(((df["sd_excesso"] >= P2["foto_min"]) & foto).sum())
        rel["perfil_bate"] = int(df["sd_cadastro"].notna().sum())
    return df, rel
