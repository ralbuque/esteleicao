"""
Cálculos estatísticos de abstenção por seção.

Três medidas de "quão fora do normal" uma seção está, todas em relação ao
próprio município (ou à UF, quando o município tem poucas seções):

1. z_simples    = (taxa da seção - média das seções) / desvio padrão das seções
                  É o que se pede intuitivamente, mas penaliza seções pequenas:
                  uma seção com 40 eleitores varia muito mais por puro acaso.

2. z_binomial   = (abstenções observadas - esperadas) / sqrt(aptos * p * (1-p))
                  Leva em conta o tamanho da seção (cada eleitor como "moeda").

3. z_ajustado   = (taxa - esperada) / sqrt(p(1-p)/aptos + tau²)   <- RECOMENDADO
                  tau² é a variação "real" entre seções que existe mesmo sem
                  nada de errado (perfil de idade, renda, cadastro desatualizado,
                  zona rural...). Sem ele, quase tudo vira "anomalia". tau² é
                  estimado por UF de forma robusta (mediana/MAD, que não se deixa
                  levar pelos próprios outliers) — modelo de efeitos aleatórios
                  aditivo usado em funnel plots (Spiegelhalter, 2005).
                  Com isso, |z_ajustado| > 3 fica raro de verdade.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_SECOES_MUNICIPIO = 5  # abaixo disso, a referência é a UF


def resumo(df: pd.DataFrame, por: list[str] | None = None) -> pd.DataFrame:
    """Média, desvio padrão etc. da taxa de abstenção das seções, por grupo."""
    df = df[list(dict.fromkeys((por or []) + ["taxa_abstencao", "aptos", "abstencoes"]))]  # só o necessário

    def _agg(g):
        t = g["taxa_abstencao"]
        mediana = t.median()
        return pd.Series({
            "secoes": len(g),
            "aptos": int(g["aptos"].sum()),
            "abstencoes": int(g["abstencoes"].sum()),
            "taxa_agregada": g["abstencoes"].sum() / g["aptos"].sum(),
            "media": t.mean(),
            "desvio_padrao": t.std(ddof=1) if len(g) > 1 else np.nan,
            "mediana": mediana,
            "mad": 1.4826 * (t - mediana).abs().median(),
            "p05": t.quantile(0.05),
            "p95": t.quantile(0.95),
            "minimo": t.min(),
            "maximo": t.max(),
        })
    if not por:
        return _agg(df).to_frame().T
    return df.groupby(por, observed=True).apply(_agg, include_groups=False).reset_index()


def _tau2(g: pd.DataFrame) -> float:
    """Variância entre seções além do acaso binomial, estimada de forma robusta."""
    r = (g["taxa_abstencao"] - g["taxa_esperada"]).dropna()
    if len(r) < 20:
        return 0.0
    var_robusta = (1.4826 * (r - r.median()).abs().median()) ** 2
    var_acaso = float((g["taxa_esperada"] * (1 - g["taxa_esperada"]) / g["aptos"]).median())
    return max(var_robusta - var_acaso, 0.0)


def pontuar_secoes(df: pd.DataFrame) -> pd.DataFrame:
    """Adiciona z-scores e referência a cada seção."""
    df = df.copy()
    chave_mun = ["uf", "cd_municipio"]

    mun = df.groupby(chave_mun, observed=True).agg(
        mun_secoes=("aptos", "size"), mun_aptos=("aptos", "sum"),
        mun_abst=("abstencoes", "sum"), mun_media=("taxa_abstencao", "mean"),
        mun_dp=("taxa_abstencao", "std")).reset_index()
    uf = df.groupby("uf", observed=True).agg(
        uf_aptos=("aptos", "sum"), uf_abst=("abstencoes", "sum"),
        uf_media=("taxa_abstencao", "mean"), uf_dp=("taxa_abstencao", "std")).reset_index()
    df = df.merge(mun, on=chave_mun, how="left").merge(uf, on="uf", how="left")

    usa_mun = df["mun_secoes"] >= MIN_SECOES_MUNICIPIO
    df["referencia"] = np.where(usa_mun, "município", "UF")

    # "leave-one-out": a própria seção não entra na média com que é comparada
    p_mun = (df["mun_abst"] - df["abstencoes"]) / (df["mun_aptos"] - df["aptos"]).replace(0, np.nan)
    p_uf = (df["uf_abst"] - df["abstencoes"]) / (df["uf_aptos"] - df["aptos"])
    df["taxa_esperada"] = np.where(usa_mun, p_mun, p_uf)
    df["taxa_esperada"] = df["taxa_esperada"].fillna(df["uf_abst"] / df["uf_aptos"])

    media_ref = np.where(usa_mun, df["mun_media"], df["uf_media"])
    dp_ref = np.where(usa_mun, df["mun_dp"], df["uf_dp"])
    df["z_simples"] = (df["taxa_abstencao"] - media_ref) / np.where(dp_ref > 0, dp_ref, np.nan)

    p = df["taxa_esperada"].clip(1e-4, 1 - 1e-4)
    df["abst_esperadas"] = df["aptos"] * p
    df["z_binomial"] = (df["abstencoes"] - df["abst_esperadas"]) / np.sqrt(df["aptos"] * p * (1 - p))

    tau2 = df.groupby("uf", observed=True)[["taxa_abstencao", "taxa_esperada", "aptos"]] \
        .apply(_tau2).rename("tau2")
    df = df.merge(tau2, left_on="uf", right_index=True, how="left")
    df["z_ajustado"] = (df["taxa_abstencao"] - p) / np.sqrt(p * (1 - p) / df["aptos"] + df["tau2"])

    # percentil da seção dentro do município e do Brasil
    df["pct_municipio"] = df.groupby(chave_mun, observed=True)["taxa_abstencao"].rank(pct=True)
    df["pct_brasil"] = df["taxa_abstencao"].rank(pct=True)

    descartar = ["mun_aptos", "mun_abst", "uf_aptos", "uf_abst"]
    return df.drop(columns=descartar)


def limites_funil(p: float, tau2: float, n_max: int, k: float) -> pd.DataFrame:
    """Curvas de controle (funnel plot) para média p, variação extra tau² e k desvios."""
    n = np.unique(np.geomspace(10, max(n_max, 20), 200).astype(int))
    sd = np.sqrt(p * (1 - p) / n + tau2)
    return pd.DataFrame({"aptos": n, "inf": np.clip(p - k * sd, 0, 1), "sup": np.clip(p + k * sd, 0, 1)})


# ====================================================================== horário dos votos
HORAS = [f"h{h:02d}" for h in range(24)]
MIN_VOTOS_HORARIO = 30      # seções com menos votos no log ficam fora do z de horário
PISO_ESCALA_HORARIO = 0.15  # horas (9 min): evita z enorme em municípios muito homogêneos


def resumo_coluna(df: pd.DataFrame, col: str, por: list[str] | None = None) -> pd.DataFrame:
    """Média, desvio padrão, mediana e percentis de uma métrica qualquer, por grupo."""
    df = df[list(dict.fromkeys((por or []) + [col]))]

    def _agg(g):
        x = g[col].dropna()
        return pd.Series({"secoes": len(x), "media": x.mean(), "desvio_padrao": x.std(ddof=1),
                          "mediana": x.median(), "p05": x.quantile(0.05), "p95": x.quantile(0.95),
                          "maximo": x.max()})
    if not por:
        return _agg(df).to_frame().T
    return df.groupby(por, observed=True).apply(_agg, include_groups=False).reset_index()


def _z_robusto(x: pd.Series, grupos: list[pd.Series], piso: float) -> pd.Series:
    """(x - mediana do grupo) / (1,4826 × MAD do grupo), com piso na escala."""
    med = x.groupby(grupos, observed=True).transform("median")
    mad = (x - med).abs().groupby(grupos, observed=True).transform("median") * 1.4826
    return (x - med) / np.maximum(mad, piso), med, np.maximum(mad, piso)


def corrigir_fuso(logs: pd.DataFrame) -> pd.DataFrame:
    """
    Reaplica a regra de fuso atual (logs_urna.fuso_por_abertura) a logs já processados,
    sem precisar baixar de novo. As contagens por hora local (h/s/m00..23) permitem
    recalcular exatamente os votos após 17h; horários médios são deslocados em horas inteiras.
    """
    from logs_urna import ABERTURA, ENCERRAMENTO, fuso_por_abertura
    if logs is None or logs.empty or "h00" not in logs:
        return logs
    logs = logs.copy()
    ref_local = logs["abertura"].fillna(logs["primeiro_voto"]) + logs["fuso"]
    novo = pd.Series([fuso_por_abertura(r, u) for r, u in zip(ref_local, logs["uf"].astype(str))],
                     index=logs.index)
    # harmoniza pelo fuso mais comum do município (como no processamento)
    novo = novo.groupby([logs["uf"], logs["cd_municipio"]]).transform(lambda s: s.mode().iloc[0])
    delta = novo - logs["fuso"]
    m = delta != 0
    if not m.any():
        return logs
    for c in ["hora_media", "hora_mediana", "hora_p90", "primeiro_voto", "ultimo_voto", "abertura"]:
        if c in logs:
            logs.loc[m, c] = logs.loc[m, c] - delta[m]
    if "abertura_atrasada_min" in logs:
        logs.loc[m, "abertura_atrasada_min"] = ((logs.loc[m, "abertura"] - ABERTURA) * 60).clip(lower=0)
    H = logs.loc[m, [f"h{h:02d}" for h in range(24)]].to_numpy()
    S = logs.loc[m, [f"s{h:02d}" for h in range(24)]].to_numpy() if "s00" in logs else None
    M = logs.loc[m, [f"m{h:02d}" for h in range(24)]].to_numpy() if "m00" in logs else None
    hora_local = np.arange(24)[None, :]
    f = novo[m].to_numpy()[:, None]
    apos = hora_local >= ENCERRAMENTO + f
    n = logs.loc[m, "votos_log"].to_numpy()
    va = (H * apos).sum(1)
    logs.loc[m, "votos_apos_17"] = va
    logs.loc[m, "pct_apos_17"] = va / np.maximum(n, 1)
    logs.loc[m, "pct_ultima_hora"] = (H * (hora_local == ENCERRAMENTO - 1 + f)).sum(1) / np.maximum(n, 1)
    logs.loc[m, "pct_manha"] = (H * (hora_local < 12 + f)).sum(1) / np.maximum(n, 1)
    if S is not None:
        logs.loc[m, "pct_sem_bio_apos_17"] = np.where(va > 0, (S * apos).sum(1) / np.maximum(va, 1), np.nan)
    if M is not None and "votos_manual_apos_17" in logs:
        logs.loc[m, "votos_manual_apos_17"] = (M * apos).sum(1)
    for c in ["ociosa_antes_17_min", "intervalo_med_apos_17_s"]:  # não dá para recalcular sem o log bruto
        if c in logs:
            logs.loc[m, c] = np.nan
    logs.loc[m, "fuso"] = novo[m]
    return logs


def juntar_horario(secoes: pd.DataFrame, logs: pd.DataFrame | None) -> pd.DataFrame:
    """
    Junta as métricas dos logs às seções e calcula:
      z_horario        hora média dos votos vs. demais seções do município (robusto).
                       Positivo = votação mais concentrada no fim do dia.
      dif_local_min    minutos de diferença da hora média para a mediana das OUTRAS
                       seções do mesmo local de votação (mesma escola = mesmas filas,
                       mesmo público). Fila legítima costuma atingir a escola inteira.
      score_cruzado    min(−z_ajustado, z_horario): só é alto se a seção tiver,
                       AO MESMO TEMPO, abstenção baixa e votação tardia.
      sinais           lista de padrões objetivos encontrados no log.
    """
    if logs is None or logs.empty:
        return secoes.assign(tem_log=False)
    chave = ["uf", "cd_municipio", "zona", "secao"]
    logs = corrigir_fuso(logs)
    for c in ["cd_municipio", "zona", "secao"]:
        logs[c] = logs[c].astype("Int32")
    logs["uf"] = logs["uf"].astype(str)
    sec = secoes.copy()
    sec["_uf"] = sec["uf"].astype(str)
    df = sec.merge(logs.rename(columns={"uf": "_uf"}), on=["_uf", "cd_municipio", "zona", "secao"],
                   how="left").drop(columns="_uf")
    df["tem_log"] = df["votos_log"].notna()

    ok = df["tem_log"] & (df["votos_log"] >= MIN_VOTOS_HORARIO)
    hm = df["hora_media"].where(ok)
    z_mun, _, _ = _z_robusto(hm, [df["uf"], df["cd_municipio"]], PISO_ESCALA_HORARIO)
    z_uf, _, _ = _z_robusto(hm, [df["uf"]], PISO_ESCALA_HORARIO)
    n_mun = hm.groupby([df["uf"], df["cd_municipio"]], observed=True).transform("count")
    df["z_horario"] = np.where(n_mun >= MIN_SECOES_MUNICIPIO, z_mun, z_uf)

    if "local" in df:
        g = [df["uf"], df["cd_municipio"], df["zona"], df["local"]]
        soma = hm.groupby(g, observed=True).transform("sum")
        cont = hm.groupby(g, observed=True).transform("count")
        media_outras = (soma - hm.fillna(0)) / (cont - hm.notna()).replace(0, np.nan)
        df["dif_local_min"] = (hm - media_outras) * 60
        df["secoes_no_local"] = cont

    df["score_cruzado"] = np.minimum(-df["z_ajustado"], df["z_horario"])
    # % dos votos após 17h comparado com o município (mesmo método das demais proporções)
    df["z_apos_17"], df["apos_17_esperado"] = z_proporcao(df, df["votos_apos_17"], df["votos_log"])

    # ---- habilitação sem digital
    if "votos_digital" in df:
        sem_dig = df["votos_log"] - df["votos_digital"]
        cadastrados = df["votos_log"] - df["votos_sem_cadastro"]
        df["pct_sem_digital"] = sem_dig / df["votos_log"]
        df["z_sem_digital"], df["sem_digital_esperado"] = z_proporcao(df, sem_dig, df["votos_log"])
        df["z_manual"], df["manual_esperado"] = z_proporcao(df, df["votos_manual"], cadastrados)
        if "local" in df:
            g = [df["uf"], df["cd_municipio"], df["zona"], df["local"]]
            s_n = sem_dig.groupby(g, observed=True).transform("sum")
            s_d = df["votos_log"].groupby(g, observed=True).transform("sum")
            outras = (s_n - sem_dig) / (s_d - df["votos_log"]).replace(0, np.nan)
            df["dif_local_sem_digital_pp"] = (df["pct_sem_digital"] - outras) * 100
        if "s00" in df:
            df = salto_fim_do_dia(df)
    df["dif_log_comparecimento"] = df["votos_log"] - df["comparecimento"]

    s = pd.Series("", index=df.index)
    tarde = df["votos_apos_17"].fillna(0) >= 5

    def add(mask, texto):
        nonlocal s
        s = s.where(~mask.fillna(False), s + np.where(s == "", "", " · ") + texto)
    add(df["pct_apos_17"] >= 0.10, "≥10% dos votos após 17h")
    add(tarde & (df["ociosa_antes_17_min"] >= 20), "urna ociosa ≥20 min antes das 17h, mas votos depois")
    add(tarde & (df["pct_sem_bio_apos_17"] >= 0.5), "maioria sem biometria após 17h")
    add(tarde & (df["intervalo_med_apos_17_s"] <= 45), "votos após 17h em ritmo muito rápido")
    if "dif_local_min" in df:
        add(df["dif_local_min"] >= 60, "1h+ mais tarde que as outras seções da escola")
    if "z_sem_digital" in df:
        add(df["z_sem_digital"] >= 3, "sem digital muito acima do município")
        add(df["z_manual"] >= 3, "liberação manual (tinha digital) muito acima do município")
        add(df["maior_seq_manual"] >= 8, "8+ liberações manuais seguidas")
        if "dif_local_sem_digital_pp" in df:
            add(df["dif_local_sem_digital_pp"] >= 25, "sem digital 25+ p.p. acima das outras seções da escola")
    if "z_sem_digital_fim" in df:
        add(criterio_fim(df), "salto de liberações sem digital a partir das 16h")
    add(df["dif_log_comparecimento"].abs() >= 1, "votos no log ≠ comparecimento oficial")
    add(df["n_urnas"] > 1, "urna substituída")
    add(df["abertura_atrasada_min"] >= 30, "abertura atrasada ≥30 min")
    df["sinais"] = s.where(df["tem_log"], "")
    df["n_sinais"] = df["sinais"].str.count("·").add(1).where(df["sinais"] != "", 0)
    return df


def z_proporcao(df: pd.DataFrame, num: pd.Series, den: pd.Series, min_den: int = 30) -> tuple[pd.Series, pd.Series]:
    """
    Mesmo método do z ajustado da abstenção, para qualquer proporção num/den por seção:
    compara com a proporção do próprio município (sem contar a seção; UF se o município
    tiver menos de 5 seções), somando ao acaso binomial a variação natural entre seções
    (tau², estimada por UF de forma robusta). Devolve (z, proporção esperada).
    """
    ok = den >= min_den
    num, den = num.where(ok), den.where(ok)
    taxa = num / den
    g_mun = [df["uf"], df["cd_municipio"]]
    n_mun = taxa.groupby(g_mun, observed=True).transform("count")
    s_mun = num.groupby(g_mun, observed=True).transform("sum")
    d_mun = den.groupby(g_mun, observed=True).transform("sum")
    s_uf = num.groupby(df["uf"], observed=True).transform("sum")
    d_uf = den.groupby(df["uf"], observed=True).transform("sum")
    p_mun = (s_mun - num) / (d_mun - den).replace(0, np.nan)
    p_uf = (s_uf - num) / (d_uf - den).replace(0, np.nan)
    esperada = pd.Series(np.where(n_mun >= MIN_SECOES_MUNICIPIO, p_mun, p_uf), index=df.index)
    esperada = esperada.fillna(p_uf)
    p = esperada.clip(1e-3, 1 - 1e-3)
    var_acaso = p * (1 - p) / den
    resid = taxa - p

    def _tau2_uf(idx):
        r = resid.loc[idx].dropna()
        if len(r) < 20:
            return 0.0
        v = (1.4826 * (r - r.median()).abs().median()) ** 2
        return max(v - float(var_acaso.loc[r.index].median()), 0.0)
    tau2 = resid.groupby(df["uf"], observed=True).transform(lambda s: _tau2_uf(s.index))
    z = resid / np.sqrt(var_acaso + tau2)
    return z, esperada


# ====================================================================== salto sem digital no fim do dia
HORA_FIM = 16          # "fim do dia": votos a partir das 16h (Brasília)
Z_FIM = 3.0            # padrão do critério (o painel deixa ajustar)
EXCESSO_MIN_FIM = 8    # votos sem digital a mais que o esperado, no mínimo
LEITOR_MIN_FIM = 0.25  # entre quem tem digital, pelo menos 25% reconhecidos no fim do dia


def salto_fim_do_dia(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compara a seção com ela mesma: a proporção de eleitores liberados sem digital
    (sem cadastro + manual) a partir das 16h contra a da própria seção antes das 16h.

    Quem vota no lugar de um ausente não passa na digital dele, então esse voto sai
    como "sem cadastro" ou como liberação manual. Fila às 17h não muda a composição
    (é o mesmo público do dia), idosos votam cedo e leitor com defeito falha para
    quase todos (por isso o leitor_ok_fim). Não depende da média do município.

      excesso_sem_digital_fim  votos sem digital a partir das 16h acima do esperado
                               pela taxa da própria seção antes das 16h
      z_sem_digital_fim        z binomial desse excesso, padronizado por UF (mediana/MAD),
                               porque o fim do dia tem perfil próprio
      deficit_abstencao        abstenções esperadas − observadas (as que "faltaram")
      votos_em_jogo            menor valor entre o déficit de abstenção e o excesso
    """
    tem = df["tem_log"].to_numpy(bool)
    fuso = df["fuso"].fillna(0).to_numpy(int)[:, None]
    tarde = (np.arange(24)[None, :] - fuso) >= HORA_FIM  # hora local -> Brasília

    def somas(prefixo):
        m = df[[f"{prefixo}{h:02d}" for h in range(24)]].fillna(0).to_numpy(np.float32)
        return (m * ~tarde).sum(1), (m * tarde).sum(1)

    n_d, n_t = somas("h")
    s_d, s_t = somas("s")
    m_t = somas("m")[1]
    p = np.clip((s_d + 0.5) / (n_d + 1), 1e-3, 1 - 1e-3)
    excesso = s_t - n_t * p
    zb = pd.Series(np.where(tem & (n_t >= 10), excesso / np.sqrt(np.maximum(n_t * p * (1 - p), 1e-9)), np.nan),
                   index=df.index)
    med = zb.groupby(df["uf"], observed=True).transform("median")
    mad = (zb - med).abs().groupby(df["uf"], observed=True).transform("median") * 1.4826
    df["pct_sem_digital_antes_16"] = np.where(tem, s_d / np.maximum(n_d, 1), np.nan)
    df["pct_sem_digital_fim"] = np.where(tem & (n_t > 0), s_t / np.maximum(n_t, 1), np.nan)
    df["excesso_sem_digital_fim"] = np.where(tem, excesso, np.nan)
    df["z_sem_digital_fim"] = (zb - med) / mad.clip(lower=0.5)
    df["leitor_ok_fim"] = tem & ((n_t - s_t) / np.maximum(n_t - (s_t - m_t), 1) >= LEITOR_MIN_FIM)
    df["deficit_abstencao"] = df["abst_esperadas"] - df["abstencoes"]
    df["votos_em_jogo"] = np.minimum(df["deficit_abstencao"], df["excesso_sem_digital_fim"]).clip(lower=0)
    return df


def criterio_fim(df: pd.DataFrame, z_lim: float = Z_FIM) -> pd.Series:
    """Seções com salto sem digital a partir das 16h (z ≥ z_lim, excesso mínimo e leitor funcionando)."""
    return ((df["z_sem_digital_fim"] >= z_lim) & (df["excesso_sem_digital_fim"] >= EXCESSO_MIN_FIM)
            & df["leitor_ok_fim"]).fillna(False).astype(bool)


def votos_por_hora(df: pd.DataFrame, prefixo: str = "h") -> pd.Series:
    """Votos por hora em horário equivalente (Brasília), somando as seções de df.
    prefixo: "h" = todos os votos, "s" = sem digital, "m" = liberação manual."""
    tot = np.zeros(30)
    cols = [f"{prefixo}{h:02d}" for h in range(24)]
    if cols[0] not in df:
        return pd.Series(tot[3:27], index=range(24))
    d = df.loc[df["tem_log"].astype(bool), ["fuso"] + cols]
    if d.empty:
        return pd.Series(tot[3:27], index=range(24))
    for fuso, g in d.groupby("fuso"):
        idx = np.arange(24) - int(fuso) + 3   # hora local h -> hora equivalente h - fuso
        tot[idx] += g[cols].sum().to_numpy(dtype=float)
    return pd.Series(tot[3:27], index=range(24))


def perfil_horario(df: pd.DataFrame) -> pd.Series:
    """Distribuição % dos votos por hora (horário equivalente), somando as seções de df."""
    v = votos_por_hora(df, "h")
    return v / max(v.sum(), 1)
