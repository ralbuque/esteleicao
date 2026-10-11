"""
Painel de abstenção e horário de votação por seção eleitoral.
    streamlit run painel.py
"""
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from analise import (juntar_horario, limites_funil, perfil_horario, pontuar_secoes, resumo,
                     resumo_coluna, votos_por_hora)

st.set_page_config(page_title="Abstenção por seção", page_icon="🗳️", layout="wide")
PASTA = Path(__file__).parent / "dados"
COR_ALTA, COR_BAIXA, COR_NORMAL = "#d6453d", "#2f6fb5", "#9aa4b1"
TODOS = "— Todos —"


def arquivos_logs(caminho_secoes: Path) -> list[Path]:
    sufixo = caminho_secoes.stem.replace("secoes_", "")  # ex.: 2026_t1
    return sorted(PASTA.glob(f"logs_{sufixo}_*.parquet"))


def arquivo_votos(caminho_secoes: Path) -> Path | None:
    """dados/votos_<ano>_t<turno>.parquet (gerado por baixar_votos.py), se existir."""
    p = PASTA / caminho_secoes.name.replace("secoes_", "votos_")
    return p if p.exists() else None


def desvio_da_cidade(df: pd.DataFrame) -> pd.DataFrame:
    """Para cada seção, % do candidato menos a média das OUTRAS seções do mesmo município
    (dif_<cand>_mun, em p.p.) e esse desvio em desvios padrão do município (z_<cand>_mun).
    Compara a seção com a própria cidade, eliminando diferenças de perfil entre cidades."""
    g = [df["uf"].astype(str), df["cd_municipio"]]
    for c in ["pct_lula", "pct_bolsonaro", "pct_outros"]:
        x = df[c]
        n = x.groupby(g, observed=True).transform("count")
        soma = x.groupby(g, observed=True).transform("sum")
        media_outras = ((soma - x.fillna(0)) / (n - 1)).where(n > 1)
        df[f"dif_{c[4:]}_mun"] = (x - media_outras).astype("float32")
        dp = x.groupby(g, observed=True).transform("std").where(n >= 5)
        df[f"z_{c[4:]}_mun"] = ((x - media_outras) / dp.where(dp > 0.01)).astype("float32")
    return df


@st.cache_data(show_spinner="Carregando e calculando estatísticas…")
def carregar(caminho: str, _assinatura: tuple) -> pd.DataFrame:
    df = pontuar_secoes(pd.read_parquet(caminho))
    arqs = arquivos_logs(Path(caminho))
    logs = pd.concat([pd.read_parquet(a) for a in arqs], ignore_index=True) if arqs else None
    df = juntar_horario(df, logs)
    votos = arquivo_votos(Path(caminho))
    if votos is not None:
        v = pd.read_parquet(votos)
        v["uf"] = v["uf"].astype(str)
        df["_uf"] = df["uf"].astype(str)
        df = df.merge(v.rename(columns={"uf": "_uf"}), on=["_uf", "cd_municipio", "zona", "secao"],
                      how="left").drop(columns="_uf")
        df = desvio_da_cidade(df)
    for c in ["uf", "municipio"]:
        df[c] = df[c].astype("category")
    return df


def pct(x, casas=1):
    return "—" if pd.isna(x) else f"{x * 100:.{casas}f}%"


def hora(x):
    if pd.isna(x):
        return "—"
    m = int(round(x * 60))
    return f"{m // 60}h{m % 60:02d}"


# indicadores que podem ser cruzados: nome -> (coluna z com sinal "suspeito = positivo", coluna bruta, rótulo bruto)
CRITERIOS = {
    "Abstenção baixa": ("z_abst_baixa", "taxa_abstencao", "taxa de abstenção"),
    "Votação tardia": ("z_horario", "pct_apos_17", "% dos votos após 17h"),
    "Muitos sem digital": ("z_sem_digital", "pct_sem_digital", "% dos eleitores liberados sem digital"),
    "Liberação manual alta": ("z_manual", "pct_manual_cadastrados",
                              "% liberados pelo mesário (entre quem tem digital)"),
}
COLS_VOTOS = {
    "pct_lula": st.column_config.NumberColumn("% Lula", format="percent"),
    "pct_bolsonaro": st.column_config.NumberColumn("% F. Bolsonaro", format="percent"),
    "pct_outros": st.column_config.NumberColumn("% outros/nulos", format="percent"),
    "dif_lula_mun": st.column_config.NumberColumn("Lula vs. cidade", format="%+.1f p.p.",
                                                  help="% Lula na seção − média das outras seções do município"),
    "dif_bolsonaro_mun": st.column_config.NumberColumn("F. Bolsonaro vs. cidade", format="%+.1f p.p.",
                                                       help="% F. Bolsonaro na seção − média das outras seções do município"),
}
EIXO_Z = {
    "Abstenção baixa": "← abstenção mais ALTA · z da abstenção (invertido) · mais BAIXA →",
    "Votação tardia": "← votos mais cedo · z da hora média · mais tarde →",
    "Muitos sem digital": "← menos · z de eleitores sem digital · mais →",
    "Liberação manual alta": "← menos · z de liberação manual · mais →",
}


def linha_df(s: pd.Series) -> pd.DataFrame:
    """Uma seção (Series) como DataFrame com tipos numéricos corretos."""
    return pd.DataFrame([s]).infer_objects()


# ---------------------------------------------------------------- dados
arquivos = sorted(PASTA.glob("secoes_*.parquet"), reverse=True)
if not arquivos:
    st.error("Nenhum dado encontrado. Rode primeiro:  `python baixar_dados.py`")
    st.stop()

with st.sidebar:
    st.header("🗳️ Abstenção por seção")
    arquivo = st.selectbox("Eleição / turno", arquivos, format_func=lambda p: p.stem.replace("secoes_", ""))
    assinatura = tuple((a.name, a.stat().st_mtime)
                       for a in [arquivo, *arquivos_logs(arquivo), *filter(None, [arquivo_votos(arquivo)])])
    base = carregar(str(arquivo), assinatura)
    tem_logs = bool(base["tem_log"].any())

    st.subheader("Navegação")
    incluir_zz = st.checkbox("Incluir exterior (ZZ)", value=False)
    if not incluir_zz:
        base = base[base["uf"] != "ZZ"]

    ufs = sorted(base["uf"].unique().tolist())
    uf = st.selectbox("Estado", [TODOS] + ufs)
    df = base if uf == TODOS else base[base["uf"] == uf]

    mun = zona = secao = TODOS
    if uf != TODOS:
        muns = df[["cd_municipio", "municipio"]].drop_duplicates().sort_values("municipio")
        opc = dict(zip(muns["cd_municipio"], muns["municipio"]))
        mun = st.selectbox("Município", [TODOS] + list(opc), format_func=lambda c: opc.get(c, c))
        if mun != TODOS:
            df = df[df["cd_municipio"] == mun]
            zona = st.selectbox("Zona", [TODOS] + sorted(df["zona"].dropna().unique().tolist()))
            if zona != TODOS:
                df = df[df["zona"] == zona]
                secao = st.selectbox("Seção", [TODOS] + sorted(df["secao"].dropna().unique().tolist()))

    st.subheader("Sinalização")
    st.caption("Uma seção é sinalizada por cada critério abaixo que ela cumprir.")
    st.markdown("**🔻 Abstenção baixa**")
    medida = st.radio("Medida", ["z_ajustado", "z_binomial", "z_simples"],
                      format_func={"z_ajustado": "z ajustado (recomendado)",
                                   "z_binomial": "z binomial",
                                   "z_simples": "z simples (média/desvio)"}.get,
                      help="Ver README: o z ajustado leva em conta o tamanho da seção "
                           "e a variação natural entre seções.")
    limite = st.slider("Abstenção abaixo do esperado em ≥ (desvios)", 2.0, 6.0, 3.0, 0.5,
                       help="Também usado para a liberação manual (z ≥ este valor).")
    min_aptos = st.number_input("Ignorar seções com menos aptos que", 0, 500, 50, 10)
    if tem_logs:
        st.markdown("**⏰ Voto após 17h**")
        lim_17 = st.slider("% dos votos depois das 17h ≥", 5, 50, 15, 5,
                           help="Mínimo de 10 votos após as 17h.") / 100
        so_destoa = st.checkbox("Só se a seção destoar da própria escola", value=True,
                                help="Exige hora média 30+ min mais tarde que as outras seções do mesmo "
                                     "local. Quando a escola inteira vota tarde, quase sempre é fila.")
        st.markdown("**🖐️ Liberação manual pelo mesário**")
        st.caption("Eleitores COM digital cadastrada liberados pelo mesário: z ≥ limite acima e "
                   "pelo menos 5 casos.")
        min_crit = st.radio("Mostrar seções que cumprem", [1, 2, 3], horizontal=True,
                            format_func=lambda n: {1: "≥ 1 critério", 2: "≥ 2", 3: "os 3"}[n])
    else:
        lim_17, so_destoa, min_crit = 0.15, True, 1

    st.subheader("Cruzamento de indicadores")
    tem_digital = "z_sem_digital" in base
    disponiveis = [c for c in CRITERIOS if c in ("Abstenção baixa", "Votação tardia") or tem_digital]
    if tem_logs:
        criterios = st.multiselect(
            "Critérios que precisam valer AO MESMO TEMPO", disponiveis,
            default=["Abstenção baixa", "Votação tardia"],
            help="Cada critério é um z comparando a seção com o próprio município. O score cruzado "
                 "é o MENOR deles: só é alto se a seção for extrema em todos os critérios escolhidos.")
        criterios = criterios or ["Abstenção baixa"]
        limite_cruz = st.slider("Destacar quando todos os critérios ≥", 1.0, 6.0, 2.0, 0.5,
                                help="Com 2, a seção precisa estar 2 desvios além do esperado em cada critério.")
        n_ufs_log = base.loc[base["tem_log"], "uf"].nunique()
        st.caption(f"Logs carregados para {n_ufs_log} UF(s): "
                   f"{int(base['tem_log'].sum()):,} seções.".replace(",", "."))
        if not tem_digital:
            st.caption("⚠️ Logs processados por uma versão antiga, sem dados de digital. "
                       "Rode `python baixar_logs.py --refazer`.")
    else:
        criterios, limite_cruz = ["Abstenção baixa", "Votação tardia"], 2.0
        st.caption("Sem logs de urna. Rode `python baixar_logs.py --ufs AC` (por exemplo).")


def calcular_score(d: pd.DataFrame) -> pd.Series:
    zs = [d[CRITERIOS[c][0]] for c in criterios if CRITERIOS[c][0] in d]
    return pd.concat(zs, axis=1).min(axis=1, skipna=False) if zs else pd.Series(np.nan, index=d.index)


base = base.assign(z_abst_baixa=-base["z_ajustado"])
base = base.assign(score_cruzado=calcular_score(base))
df = df.assign(z_abst_baixa=-df["z_ajustado"])
df = df.assign(score_cruzado=calcular_score(df))
NOME_CRUZ = " + ".join(c.lower() for c in criterios)

def sinalizar(d: pd.DataFrame) -> pd.DataFrame:
    """Marca os três critérios de interesse e conta quantos cada seção cumpre."""
    f_abst = (d[medida] <= -limite) & (d["aptos"] >= min_aptos)
    if "votos_apos_17" in d:
        f_17 = (d["pct_apos_17"] >= lim_17) & (d["votos_apos_17"] >= 10)
        if so_destoa and "dif_local_min" in d:
            f_17 &= (d["dif_local_min"] >= 30) | d["dif_local_min"].isna()
        f_17 = f_17.fillna(False).astype(bool)
    else:
        f_17 = pd.Series(False, index=d.index)
    if "z_manual" in d:
        f_man = ((d["z_manual"] >= limite) & (d["votos_manual"] >= 5)).fillna(False).astype(bool)
    else:
        f_man = pd.Series(False, index=d.index)
    n = f_abst.astype(int) + f_17.astype(int) + f_man.astype(int)
    rot = (np.where(f_abst, "abstenção baixa · ", "") + np.where(f_17, "voto após 17h · ", "")
           + np.where(f_man, "liberação manual · ", ""))
    return d.assign(f_abst=f_abst, f_17=f_17, f_man=f_man, n_criterios=n,
                    criterios_cumpridos=pd.Series(rot, index=d.index).str.rstrip(" · "),
                    alerta=np.where(n >= min_crit, "sinalizada", "normal"))


df = sinalizar(df)

# ---------------------------------------------------------------- cabeçalho
nivel = ("Brasil" if uf == TODOS else uf if mun == TODOS else
         f"{df['municipio'].iloc[0]} / {uf}" + (f" · Zona {zona}" if zona != TODOS else ""))
st.title(nivel)

r = resumo(df).iloc[0]
c = st.columns(7)
c[0].metric("Seções", f"{int(r.secoes):,}".replace(",", "."))
c[1].metric("Aptos", f"{r.aptos / 1e6:,.2f} mi".replace(".", ",") if r.aptos >= 1e6 else f"{int(r.aptos):,}".replace(",", "."))
c[2].metric("Abstenção agregada", pct(r.taxa_agregada, 2),
            help="Total de abstenções ÷ total de aptos (número oficial)")
c[3].metric("Média das seções", pct(r.media),
            help="Média simples da taxa de abstenção de cada seção")
c[4].metric("Desvio padrão", pct(r.desvio_padrao),
            help="Desvio padrão da taxa de abstenção entre as seções")
c[5].metric("🔻 Abstenção baixa", int(df["f_abst"].sum()),
            help=f"Seções com {medida} ≤ −{limite} e ≥ {min_aptos} aptos")
c[6].metric("🚩 Sinalizadas", int((df["alerta"] == "sinalizada").sum()),
            help=f"Seções que cumprem pelo menos {min_crit} dos critérios: abstenção baixa, "
                 "voto após 17h, liberação manual")

dl = df[df["tem_log"]]
if len(dl):
    c = st.columns(7)
    c[0].metric("Seções com log", f"{len(dl):,}".replace(",", "."))
    c[1].metric("Hora média", hora((dl["hora_media"] * dl["votos_log"]).sum() / dl["votos_log"].sum()),
                help="Média ponderada pelo número de votos, em horário de Brasília (8h–17h)")
    c[2].metric("Desvio (seções)", f"{dl['hora_media'].std() * 60:.0f} min",
                help="Desvio padrão da hora média de cada seção")
    c[3].metric("Votos após 17h", pct(dl["votos_apos_17"].sum() / dl["votos_log"].sum(), 2))
    c[4].metric("Seções c/ voto 17h+", pct((dl["votos_apos_17"] > 0).mean()))
    c[5].metric("Corr. abst. × hora", f"{dl['taxa_abstencao'].rank().corr(dl['hora_media'].rank()):+.2f}",
                help="Spearman entre taxa de abstenção e hora média. Negativo = onde se falta menos, "
                     "vota-se mais tarde (esperado: mais eleitores → mais fila).")
    c[6].metric("⚠️ Cruzamento", int((dl["score_cruzado"] >= limite_cruz).sum()),
                help=f"Seções com {NOME_CRUZ} (todos ≥ {limite_cruz} desvios)")
    if "votos_digital" in dl:
        tot = dl["votos_log"].sum()
        c = st.columns(7)
        c[0].metric("Sem digital", pct(1 - dl["votos_digital"].sum() / tot),
                    help="% dos eleitores liberados sem reconhecimento da digital (sem cadastro + manual)")
        c[1].metric("↳ sem cadastro", pct(dl["votos_sem_cadastro"].sum() / tot),
                    help="Eleitor não tem digital cadastrada na Justiça Eleitoral")
        c[2].metric("↳ liberação manual", pct(dl["votos_manual"].sum() / tot),
                    help="Eleitor TEM digital cadastrada, ela não foi reconhecida em 4 tentativas e o "
                         "mesário liberou o voto com a digital dele")
        c[3].metric("Desvio (seções)", f"{dl['pct_sem_digital'].std() * 100:.1f} p.p.",
                    help="Desvio padrão do % sem digital entre as seções")
        c[4].metric("Corr. abst. × sem digital",
                    f"{dl['taxa_abstencao'].rank().corr(dl['pct_sem_digital'].rank()):+.2f}",
                    help="Spearman entre abstenção e % sem digital, seção a seção")
        c[5].metric("🖐️ z ≥ 3 sem digital", int((dl["z_sem_digital"] >= 3).sum()))
        c[6].metric("🖐️ z ≥ 3 manual", int((dl["z_manual"] >= 3).sum()))


# ---------------------------------------------------------------- detalhe de seção
def detalhe_secao(s: pd.Series):
    st.subheader(f"Seção {s['secao']} · Zona {s['zona']} · {s['municipio']}/{s['uf']}")
    if "nome_local" in s and pd.notna(s.get("nome_local")):
        st.caption(f"Local de votação: {s['nome_local']}"
                   + (f" — {s['endereco_local']}" if pd.notna(s.get('endereco_local')) else ""))
    k = st.columns(5)
    k[0].metric("Abstenção da seção", pct(s["taxa_abstencao"]),
                f"{(s['taxa_abstencao'] - s['taxa_esperada']) * 100:+.1f} p.p. vs esperado",
                delta_color="inverse")
    k[1].metric("Aptos / faltaram", f"{s['aptos']} / {s['abstencoes']}",
                f"esperado ≈ {s['abst_esperadas']:.0f}", delta_color="off")
    k[2].metric("z ajustado", f"{s['z_ajustado']:+.2f}")
    k[3].metric("Percentil no município", pct(s["pct_municipio"], 0))
    k[4].metric("Percentil no Brasil", pct(s["pct_brasil"], 0))

    zona_df = base[(base["cd_municipio"] == s["cd_municipio"]) & (base["zona"] == s["zona"])]
    mun_df = base[base["cd_municipio"] == s["cd_municipio"]]
    uf_df = base[base["uf"] == s["uf"]]
    comp = pd.DataFrame({
        "nível": ["Esta seção", f"Zona {s['zona']}", "Município", s["uf"], "Brasil"],
        "media": [s["taxa_abstencao"]] + [d["taxa_abstencao"].mean() for d in (zona_df, mun_df, uf_df, base)],
        "dp": [0] + [d["taxa_abstencao"].std() for d in (zona_df, mun_df, uf_df, base)],
    })
    a, b = st.columns(2)
    fig = go.Figure(go.Bar(x=comp["nível"], y=comp["media"],
                           error_y=dict(type="data", array=comp["dp"], visible=True),
                           marker_color=[COR_ALTA if s["z_ajustado"] > 0 else COR_BAIXA] + [COR_NORMAL] * 4,
                           text=[pct(v) for v in comp["media"]], textposition="outside"))
    fig.update_layout(title="Comparação (barra = média, traço = ± 1 desvio padrão)",
                      yaxis_tickformat=".0%", height=360, margin=dict(t=50, b=10))
    a.plotly_chart(fig, width="stretch")

    fig = px.histogram(mun_df, x="taxa_abstencao", nbins=40, color_discrete_sequence=[COR_NORMAL],
                       title="Onde a seção cai entre as seções do município")
    fig.add_vline(x=s["taxa_abstencao"], line_color=COR_ALTA, line_width=3,
                  annotation_text="esta seção")
    fig.update_layout(xaxis_tickformat=".0%", height=360, margin=dict(t=50, b=10),
                      xaxis_title="taxa de abstenção", yaxis_title="seções")
    b.plotly_chart(fig, width="stretch")

    vizinhas = None
    if "local" in s and pd.notna(s.get("local")):
        vizinhas = mun_df[(mun_df["zona"] == s["zona"]) & (mun_df["local"] == s["local"])]

    if s.get("tem_log", False):
        st.markdown("#### ⏰ Horário dos votos (log da urna)")
        k = st.columns(6)
        k[0].metric("Hora média", hora(s["hora_media"]),
                    f"{(s['hora_media'] - mun_df['hora_media'].median()) * 60:+.0f} min vs município",
                    delta_color="inverse")
        k[1].metric("Votos após 17h", f"{int(s['votos_apos_17'])}  ({pct(s['pct_apos_17'])})")
        k[2].metric("Último voto", hora(s["ultimo_voto"]))
        k[3].metric("Sem biometria após 17h", pct(s["pct_sem_bio_apos_17"], 0),
                    f"{pct(s['pct_sem_bio'], 0)} no dia todo", delta_color="off")
        k[4].metric("z horário", f"{s['z_horario']:+.2f}" if pd.notna(s["z_horario"]) else "—")
        k[5].metric("Score cruzado", f"{s['score_cruzado']:+.2f}" if pd.notna(s.get("score_cruzado")) else "—",
                    help=f"Critérios: {NOME_CRUZ}")
        if s.get("sinais"):
            st.warning("**Sinais no log:** " + s["sinais"])

        perfis = {"Esta seção": perfil_horario(linha_df(s))}
        if vizinhas is not None:
            outras = vizinhas[vizinhas["secao"] != s["secao"]]
            if outras["tem_log"].any():
                perfis["Outras seções da escola"] = perfil_horario(outras)
        perfis["Município"] = perfil_horario(mun_df)
        fig = go.Figure()
        for (nome, p), cor in zip(perfis.items(), [COR_ALTA, "#33415c", COR_NORMAL]):
            p = p[(p.index >= 6) & (p.index <= 23)]
            fig.add_trace(go.Bar(x=[f"{h}h" for h in p.index], y=p.values, name=nome, marker_color=cor))
        fig.add_vline(x=10.5, line_dash="dash", line_color="black", annotation_text="17h encerramento")
        fig.update_layout(barmode="group", yaxis_tickformat=".0%", height=380, margin=dict(t=40, b=10),
                          title="% dos votos em cada hora (horário de Brasília)", legend=dict(orientation="h"))
        st.plotly_chart(fig, width="stretch")
        st.caption(f"Abertura da urna: {hora(s['abertura'])} · primeiro voto {hora(s['primeiro_voto'])} · "
                   f"maior intervalo sem votos entre 16h e 17h: {s['ociosa_antes_17_min']:.0f} min · "
                   f"votos no log: {int(s['votos_log'])} (comparecimento oficial: {int(s['comparecimento'])}) · "
                   f"urnas usadas: {int(s['n_urnas'])}")

    if s.get("tem_log", False) and pd.notna(s.get("votos_digital")):
        st.markdown("#### 🖐️ Identificação do eleitor")
        n = int(s["votos_log"])
        k = st.columns(5)
        k[0].metric("Sem digital", pct(s["pct_sem_digital"]),
                    f"{(s['pct_sem_digital'] - s['sem_digital_esperado']) * 100:+.1f} p.p. vs esperado",
                    delta_color="inverse")
        k[1].metric("Sem cadastro de digital", f"{int(s['votos_sem_cadastro'])} ({pct(s['pct_sem_cadastro'])})")
        k[2].metric("Liberação manual", f"{int(s['votos_manual'])} ({pct(s['pct_manual_cadastrados'])})",
                    f"esperado ≈ {pct(s['manual_esperado'])} de quem tem digital", delta_color="off")
        k[3].metric("Maior sequência manual", int(s["maior_seq_manual"]),
                    help="Maior número de eleitores seguidos liberados manualmente pelo mesário")
        k[4].metric("z sem digital / z manual", f"{s['z_sem_digital']:+.1f} / {s['z_manual']:+.1f}"
                    if pd.notna(s["z_sem_digital"]) else "—")
        um = linha_df(s)
        tot, sd, man = (votos_por_hora(um, p) for p in "hsm")
        faixa = [h for h in range(6, 24) if tot[h] > 0]
        if faixa:
            horas_ = list(range(min(faixa), max(faixa) + 1))
            fig = go.Figure()
            for nome, serie, cor in [("digital", tot - sd, "#9aa4b1"), ("sem cadastro", sd - man, "#e0a33a"),
                                     ("liberação manual", man, COR_ALTA)]:
                fig.add_trace(go.Bar(x=[f"{h}h" for h in horas_], y=[serie[h] for h in horas_], name=nome,
                                     marker_color=cor))
            fig.update_layout(barmode="stack", height=340, margin=dict(t=40, b=10), legend=dict(orientation="h"),
                              title=f"Como cada eleitor foi liberado, hora a hora ({n} votos)",
                              yaxis_title="votos")
            st.plotly_chart(fig, width="stretch")

    if vizinhas is not None:
        st.markdown("**Outras seções do mesmo local de votação** (mesma escola, mesmo público — "
                    "se só esta destoa, é um sinal mais forte)")
        cols_v = ["secao", "aptos", "abstencoes", "taxa_abstencao", "z_ajustado"]
        if vizinhas["tem_log"].any():
            cols_v += ["hora_media", "pct_apos_17", "ultimo_voto", "z_horario"]
            if "pct_sem_digital" in vizinhas:
                cols_v += ["pct_sem_digital", "pct_sem_cadastro", "pct_manual_cadastrados", "z_manual"]
        st.dataframe(vizinhas[cols_v].sort_values("secao"), hide_index=True, width="stretch",
                     column_config={**{c: st.column_config.NumberColumn(format="percent")
                                       for c in ["taxa_abstencao", "pct_apos_17", "pct_sem_bio_apos_17",
                                                 "pct_sem_digital", "pct_sem_cadastro", "pct_manual_cadastrados"]},
                                    **{c: st.column_config.NumberColumn(format="%.2f")
                                       for c in ["z_ajustado", "z_horario", "hora_media", "ultimo_voto",
                                                 "z_manual"]}})


if secao != TODOS:
    detalhe_secao(df[df["secao"] == secao].iloc[0])
    st.stop()

# ---------------------------------------------------------------- abas
aba_votos, aba_comp, aba_dist, aba_funil, aba_alertas, aba_hora, aba_dig, aba_cruz = st.tabs(
    ["🗳️ Votos × abstenção", "📊 Comparar", "📈 Distribuição", "🔻 Funil", "🚩 Sinalizadas",
     "⏰ Horário dos votos", "🖐️ Sem digital", "🔀 Cruzamento"])

if uf == TODOS:
    filho, rotulo = ["uf"], "uf"
elif mun == TODOS:
    filho, rotulo = ["cd_municipio", "municipio"], "municipio"
elif zona == TODOS:
    filho, rotulo = ["zona"], "zona"
else:
    filho, rotulo = (["local"], "local") if "local" in df else (["secao"], "secao")

with aba_comp:
    tab = resumo(df, filho)
    alertas = df[df["alerta"] == "sinalizada"].groupby(filho, observed=True).size().rename("sinalizadas")
    tab = tab.merge(alertas, left_on=filho, right_index=True, how="left").fillna({"sinalizadas": 0})
    tab[rotulo] = tab[rotulo].astype(str)

    if len(tab) <= 40:
        t = tab.sort_values("media")
        fig = go.Figure(go.Scatter(
            x=t["media"], y=t[rotulo], mode="markers",
            error_x=dict(type="data", array=t["desvio_padrao"].fillna(0), color="#b8c0cc"),
            marker=dict(size=9, color="#33415c"),
            customdata=np.stack([t["secoes"], t["taxa_agregada"]], axis=1),
            hovertemplate="%{y}<br>média %{x:.1%}<br>seções %{customdata[0]}<br>"
                          "agregada %{customdata[1]:.1%}<extra></extra>"))
        fig.add_vline(x=r.media, line_dash="dash", annotation_text="média do nível acima")
        fig.update_layout(title="Média ± 1 desvio padrão da abstenção das seções",
                          xaxis_tickformat=".0%", height=max(350, 22 * len(t) + 80),
                          margin=dict(l=10, r=10, t=50, b=10))
    else:
        fig = px.scatter(tab, x="media", y="desvio_padrao", size="aptos", color="sinalizadas",
                         hover_name=rotulo, color_continuous_scale="OrRd", size_max=40,
                         hover_data={"secoes": True, "taxa_agregada": ":.1%", "aptos": ":,"},
                         title="Cada ponto é uma unidade: média × desvio padrão "
                               "(longe do grupo = comportamento diferente)")
        fig.update_layout(xaxis_tickformat=".0%", yaxis_tickformat=".0%", height=560)
    st.plotly_chart(fig, width="stretch")

    st.dataframe(tab.drop(columns=[c for c in ["cd_municipio"] if c in tab and rotulo != "cd_municipio"])
                 .sort_values("media", ascending=False), hide_index=True, width="stretch",
                 column_config={c: st.column_config.NumberColumn(format="percent")
                                for c in ["taxa_agregada", "media", "desvio_padrao", "mediana",
                                          "mad", "p05", "p95", "minimo", "maximo"]})

with aba_dist:
    fig = px.histogram(df, x="taxa_abstencao", nbins=80, color_discrete_sequence=["#33415c"])
    for k, estilo in [(0, "solid"), (1, "dash"), (-1, "dash"), (2, "dot"), (-2, "dot")]:
        x = r.media + k * r.desvio_padrao
        fig.add_vline(x=x, line_dash=estilo, line_color=COR_ALTA if k else "black",
                      annotation_text="média" if k == 0 else f"{k:+d} dp")
    fig.update_layout(title="Distribuição da abstenção por seção", xaxis_tickformat=".0%",
                      xaxis_title="taxa de abstenção", yaxis_title="seções", height=480)
    st.plotly_chart(fig, width="stretch")
    st.caption("A distribuição real tem caudas mais largas que uma normal; por isso, contar "
               "seções além de ±2 dp num nível grande (Brasil, UF) sempre dá milhares de casos. "
               "O z ajustado, comparando cada seção com o próprio município, é mais útil para achar pontos.")

with aba_funil:
    pontos = df.assign(_grupo=np.where(df["f_abst"], "abstenção baixa", "demais"))
    normais = pontos[pontos["_grupo"] == "demais"]
    if len(normais) > 60_000:  # mantém o gráfico leve em nível Brasil
        pontos = pd.concat([normais.sample(60_000, random_state=1), pontos[pontos["_grupo"] != "demais"]])
    fig = go.Figure()
    for nome, cor in [("demais", COR_NORMAL), ("abstenção baixa", COR_BAIXA)]:
        d = pontos[pontos["_grupo"] == nome]
        fig.add_trace(go.Scattergl(
            x=d["aptos"], y=d["taxa_abstencao"], mode="markers", name=nome,
            marker=dict(size=4 if nome == "demais" else 7, color=cor,
                        opacity=0.35 if nome == "demais" else 0.9),
            text=d["municipio"].astype(str) + " · Z" + d["zona"].astype(str) + " · S" + d["secao"].astype(str),
            hovertemplate="%{text}<br>aptos %{x}<br>abstenção %{y:.1%}<extra></extra>"))
    tau2 = float(df["tau2"].median())
    for k, estilo in [(2, "dash"), (3, "solid")]:
        lim = limites_funil(r.taxa_agregada, tau2, int(df["aptos"].max()), k)
        for lado in ["inf", "sup"]:
            fig.add_trace(go.Scatter(x=lim["aptos"], y=lim[lado], mode="lines", showlegend=False,
                                     line=dict(color="black", dash=estilo, width=1), hoverinfo="skip"))
    fig.update_layout(title="Funil: seções pequenas variam mais por acaso — "
                            "linhas = ±2 e ±3 desvios esperados para cada tamanho",
                      xaxis_title="eleitores aptos na seção", yaxis_title="abstenção",
                      yaxis_tickformat=".0%", height=600)
    st.plotly_chart(fig, width="stretch")
    st.caption("O funil usa a abstenção agregada deste nível como centro. A cor (abstenção baixa) "
               "usa a comparação com o próprio município, por isso alguns pontos coloridos "
               "ficam dentro das linhas e vice-versa.")

with aba_alertas:
    sel = df[df["alerta"] == "sinalizada"].copy()
    # gravidade: soma do quanto a seção passa de cada critério
    grav = (-sel[medida]).clip(lower=0)
    if "z_manual" in sel:
        grav = grav + sel["z_manual"].clip(lower=0).fillna(0)
    if "pct_apos_17" in sel:
        grav = grav + (sel["pct_apos_17"].fillna(0) / max(lim_17, 1e-9)) * limite
    sel = sel.assign(gravidade=grav).sort_values(["n_criterios", "gravidade"], ascending=False)
    for c in ["dif_lula_mun", "dif_bolsonaro_mun"]:
        if c in sel:
            sel[c] = sel[c] * 100
    k = st.columns(4)
    k[0].metric("🔻 Abstenção baixa", int(df["f_abst"].sum()))
    k[1].metric("⏰ Voto após 17h", int(df["f_17"].sum()) if tem_logs else "—")
    k[2].metric("🖐️ Liberação manual", int(df["f_man"].sum()) if tem_logs else "—")
    k[3].metric("Cumprem 2 ou 3 critérios", int((df["n_criterios"] >= 2).sum()))
    sem_log = int((~df.loc[df["alerta"] == "sinalizada", "tem_log"]).sum()) if "tem_log" in df else 0
    st.write(f"**{len(sel):,}** seções cumprem pelo menos {min_crit} critério(s) (de {len(df):,}). "
             "Ordenadas pelo número de critérios e, depois, pela gravidade. Selecione uma linha para "
             "ver o detalhe." + (f" {sem_log:,} delas são de UFs sem logs baixados, onde só a abstenção "
                                 "pôde ser avaliada." if sem_log else ""))
    cols = [c for c in ["uf", "municipio", "zona", "secao", "n_criterios", "criterios_cumpridos",
                        "taxa_abstencao", "taxa_esperada", "z_ajustado",
                        "pct_lula", "pct_bolsonaro", "pct_outros", "dif_lula_mun", "dif_bolsonaro_mun",
                        "votos_apos_17", "pct_apos_17",
                        "dif_local_min", "votos_manual", "pct_manual_cadastrados", "manual_esperado",
                        "z_manual", "maior_seq_manual", "sinais", "aptos", "nome_local"] if c in sel]
    if medida != "z_ajustado":
        cols.insert(cols.index("z_ajustado") + 1, medida)
    evento = st.dataframe(
        sel[cols], hide_index=True, width="stretch", height=460,
        on_select="rerun", selection_mode="single-row",
        column_config={**{c: st.column_config.NumberColumn(format="percent")
                          for c in ["taxa_abstencao", "taxa_esperada", "pct_apos_17",
                                    "pct_manual_cadastrados", "manual_esperado"]},
                       **{c: st.column_config.NumberColumn(format="%.2f")
                          for c in ["z_ajustado", "z_binomial", "z_simples", "z_manual"]},
                       **COLS_VOTOS,
                       "dif_local_min": st.column_config.NumberColumn(format="%+.0f min"),
                       "n_criterios": st.column_config.NumberColumn("critérios", format="%d")})
    if "pct_lula" not in sel:
        st.caption("Para ver % de votos por candidato (Lula, Flávio Bolsonaro, outros/nulos), rode "
                   "`python baixar_votos.py` e recarregue.")
    st.download_button("⬇️ Baixar lista (CSV)", sel[cols].to_csv(index=False, sep=";", decimal=",")
                       .encode("utf-8-sig"), "secoes_sinalizadas.csv", "text/csv")
    linhas = evento.selection.rows if evento and evento.selection else []
    if linhas:
        st.divider()
        detalhe_secao(sel.iloc[linhas[0]])

# ---------------------------------------------------------------- votos × abstenção
VOTOS = [("pct_lula", "Lula"), ("pct_bolsonaro", "F. Bolsonaro"), ("pct_outros", "Outros/nulos")]
VOTOS_MUN = [("dif_lula_mun", "Lula vs. cidade"), ("dif_bolsonaro_mun", "F. Bolsonaro vs. cidade"),
             ("dif_outros_mun", "Outros/nulos vs. cidade")]
GEO_UFS = Path(__file__).parent / "geo" / "brasil_ufs.geojson"


@st.cache_data
def carregar_geo() -> dict:
    import json
    return json.loads(GEO_UFS.read_text(encoding="utf-8"))


def grupo_menor_abstencao(d: pd.DataFrame, modo: str, pct_menor: float, por: list | None = None) -> pd.Series:
    """Máscara das seções 'com menos abstenção'. No modo percentil, o corte é calculado
    dentro de cada grupo `por` (ex.: cada UF), para comparar cada unidade consigo mesma."""
    if modo == "sinalizadas":
        return d["f_abst"]
    ok = d["aptos"] >= min_aptos
    taxa = d["taxa_abstencao"].where(ok)
    if por:
        corte = taxa.groupby([d[c] for c in por], observed=True).transform("quantile", pct_menor)
    else:
        corte = taxa.quantile(pct_menor)
    return (taxa <= corte).fillna(False) & ok


def comparar_votos(d: pd.DataFrame, grupo: pd.Series, por: list, votos: list = VOTOS) -> pd.DataFrame:
    """Por unidade: média simples das % de votos de todas as seções vs. das seções do grupo."""
    d = d[d["pct_lula"].notna()]
    grupo = grupo.reindex(d.index).fillna(False)
    cols = [c for c, _ in votos]
    geral = d.groupby(por, observed=True).agg(secoes=("secao", "size"), abst_geral=("taxa_abstencao", "mean"),
                                              **{f"{c}_geral": (c, "mean") for c in cols})
    baixa = d[grupo].groupby(por, observed=True).agg(secoes_baixa=("secao", "size"),
                                                     abst_baixa=("taxa_abstencao", "mean"),
                                                     **{f"{c}_baixa": (c, "mean") for c in cols})
    tab = geral.join(baixa, how="left").reset_index()
    tab["secoes_baixa"] = tab["secoes_baixa"].fillna(0).astype(int)
    for c in cols:
        tab[f"{c}_dif"] = tab[f"{c}_baixa"] - tab[f"{c}_geral"]
    return tab


def barras_geral_vs_baixa(dv: pd.DataFrame, g: pd.DataFrame, titulo: str, votos: list = VOTOS) -> go.Figure:
    fig = go.Figure()
    fmt = "+.1%" if votos is VOTOS_MUN else ".1%"
    for nome, d_, cor in [("todas as seções", dv, COR_NORMAL), ("menor abstenção", g, COR_BAIXA)]:
        fig.add_trace(go.Bar(name=nome, x=[n for _, n in votos], y=[d_[c].mean() for c, _ in votos],
                             marker_color=cor, text=[f"{d_[c].mean():{fmt}}" for c, _ in votos],
                             textposition="outside"))
    fig.update_layout(barmode="group", yaxis_tickformat=fmt, height=360, title=titulo,
                      margin=dict(l=10, r=10, t=50, b=10), legend=dict(orientation="h", y=-0.15))
    return fig


def config_tabela_votos(votos: list = VOTOS) -> dict:
    cfg = {"secoes": st.column_config.NumberColumn("seções", format="%d"),
           "secoes_baixa": st.column_config.NumberColumn("seções menor abst.", format="%d"),
           "abst_geral": st.column_config.NumberColumn("abst. geral", format="percent"),
           "abst_baixa": st.column_config.NumberColumn("abst. do grupo", format="percent")}
    pref = "" if votos is VOTOS_MUN else "% "
    for c, nome in votos:
        cfg[f"{c}_geral"] = st.column_config.NumberColumn(f"{pref}{nome} geral", format="percent")
        cfg[f"{c}_baixa"] = st.column_config.NumberColumn(f"{pref}{nome} menor abst.", format="percent")
        cfg[f"{c}_dif"] = st.column_config.NumberColumn(f"dif. {nome}", format="percent")
    return cfg


def bloco_votos(dv: pd.DataFrame, modo: str, pct_menor: float, titulo: str, filho: list, rotulo: str, key: str,
                votos: list = VOTOS):
    """Métricas + barras + tabela por subunidade para um recorte `dv`."""
    cidade = votos is VOTOS_MUN
    grupo = grupo_menor_abstencao(dv, modo, pct_menor)
    g, n_g = dv[grupo], int(grupo.sum())
    if n_g == 0:
        st.warning(f"{titulo}: nenhuma seção no grupo com os filtros atuais.")
        return
    st.markdown(f"**{titulo}**: " + ("média do desvio de cada seção em relação à média da própria cidade "
                                     "(p.p.; 0 = igual à cidade). " if cidade else
                                     "média simples das % de votos de cada seção. ")
                + f"Grupo de menor abstenção = **{n_g:,}** seções (de {len(dv):,}), "
                f"abstenção média {pct(g['taxa_abstencao'].mean())} "
                f"vs. {pct(dv['taxa_abstencao'].mean())} no geral.".replace(",", "."))
    k = st.columns(3)
    for i, (c, nome) in enumerate(votos):
        mg, mb = dv[c].mean(), g[c].mean()
        if cidade:
            k[i].metric(f"{nome} · menor abstenção", f"{mb * 100:+.1f} p.p.",
                        delta=f"{(mb - mg) * 100:+.1f} p.p. vs. todas as seções ({mg * 100:+.1f})",
                        help="Média, nas seções do grupo, de (% na seção − média das outras seções da mesma "
                             "cidade). Positivo = nessas seções o candidato vai melhor que na própria cidade.")
        else:
            k[i].metric(f"% {nome} · menor abstenção", pct(mb),
                        delta=f"{(mb - mg) * 100:+.1f} p.p. vs. média geral ({pct(mg)})",
                        help="Diferença em pontos percentuais entre a média das seções do grupo "
                             "e a média de todas as seções deste nível.")
    st.plotly_chart(barras_geral_vs_baixa(dv, g, f"{titulo}: todas as seções × menor abstenção", votos),
                    width="stretch", key=f"barras_{key}")

    st.markdown(f"**Por {rotulo}**" + (" (no modo percentil, o corte de X% é calculado dentro "
                                         "de cada unidade)" if modo == "percentil" else ""))
    tab = comparar_votos(dv, grupo_menor_abstencao(dv, modo, pct_menor, por=filho), filho, votos)
    tab[rotulo] = tab[rotulo].astype(str)
    ordem = [rotulo, "secoes", "secoes_baixa", "abst_geral", "abst_baixa"]
    for c, _ in votos:
        ordem += [f"{c}_geral", f"{c}_baixa", f"{c}_dif"]
    st.dataframe(tab[ordem].sort_values(f"{votos[0][0]}_dif", ascending=False), hide_index=True,
                 width="stretch", column_config=config_tabela_votos(votos), key=f"tab_{key}")
    st.download_button("⬇️ Baixar tabela (CSV)", tab[ordem].to_csv(index=False, sep=";", decimal=",")
                       .encode("utf-8-sig"), f"votos_x_abstencao_{key}.csv", "text/csv", key=f"dl_{key}")


with aba_votos:
    if "pct_lula" not in df:
        st.info("Sem votos por candidato. Rode `python baixar_votos.py` e recarregue o painel.")
    else:
        modo, pct_menor = "sinalizadas", 0.05  # grupo = seções sinalizadas por abstenção baixa (barra lateral)
        st.caption("Seções com menos abstenção = as sinalizadas por abstenção baixa (critério da barra lateral).")
        comp = st.radio("Comparar cada seção com", ["cidade", "nivel"], horizontal=True,
                        format_func={"cidade": "a média da própria cidade (seção vs. cidade)",
                                     "nivel": "a média geral do nível (seção vs. estado/Brasil)"}.get,
                        help="'Própria cidade': % da seção menos a média das outras seções do mesmo município. "
                             "Elimina diferenças de perfil entre cidades (capital × interior, cidade grande × "
                             "pequena). 'Nível': compara as % brutas com a média de todas as seções do nível.")
        votos_ativo = VOTOS_MUN if comp == "cidade" else VOTOS
        dv = df[df["pct_lula"].notna()]

        if uf == TODOS:
            # ---------- mapa + gráfico por estado
            st.subheader("Por estado")
            cand_col, cand_nome = st.selectbox("Candidato", votos_ativo, format_func=lambda v: v[1], key="cand_mapa")
            tab_uf = comparar_votos(dv, grupo_menor_abstencao(dv, modo, pct_menor, por=["uf"]), ["uf"], votos_ativo)
            tab_uf["uf"] = tab_uf["uf"].astype(str)
            tab_uf = tab_uf[tab_uf["uf"] != "ZZ"]
            lim = float(tab_uf[f"{cand_col}_dif"].abs().max() or 0.01)
            mapa = px.choropleth(
                tab_uf, geojson=carregar_geo(), locations="uf", featureidkey="id",
                color=f"{cand_col}_dif", color_continuous_scale="RdBu" if "lula" in cand_col else "RdBu_r",
                range_color=(-lim, lim), hover_name="uf",
                hover_data={f"{cand_col}_geral": ":+.1%" if comp == "cidade" else ":.1%",
                            f"{cand_col}_baixa": ":+.1%" if comp == "cidade" else ":.1%",
                            f"{cand_col}_dif": ":+.1%", "secoes_baixa": ":,", "uf": False},
                labels={f"{cand_col}_geral": f"{cand_nome} geral", f"{cand_col}_baixa": f"{cand_nome} menor abst.",
                        f"{cand_col}_dif": "diferença", "secoes_baixa": "seções no grupo"})
            mapa.update_geos(fitbounds="locations", visible=False, projection_type="mercator")
            mapa.update_traces(marker_line_color="white", marker_line_width=0.8)
            mapa.update_layout(height=520, margin=dict(l=0, r=0, t=40, b=0),
                               title=f"Clique num estado · cor = dif. {cand_nome} (menor abst. − geral)",
                               coloraxis_colorbar=dict(title="dif.", tickformat="+.0%"), dragmode=False)
            col_mapa, col_bar = st.columns([1, 1])
            with col_mapa:
                ev = st.plotly_chart(mapa, width="stretch", on_select="rerun", selection_mode="points",
                                     key="mapa_ufs")
            with col_bar:
                tb = tab_uf.sort_values(f"{cand_col}_dif", ascending=False)
                fig = go.Figure()
                fig.add_trace(go.Bar(name="todas as seções", x=tb["uf"], y=tb[f"{cand_col}_geral"],
                                     marker_color=COR_NORMAL))
                fig.add_trace(go.Bar(name="menor abstenção", x=tb["uf"], y=tb[f"{cand_col}_baixa"],
                                     marker_color=COR_BAIXA))
                fig.update_layout(barmode="group", yaxis_tickformat="+.0%" if comp == "cidade" else ".0%", height=520,
                                  title=f"{cand_nome} por UF (ordenado pela diferença)",
                                  margin=dict(l=10, r=10, t=40, b=10), legend=dict(orientation="h", y=-0.12))
                st.plotly_chart(fig, width="stretch", key="barras_ufs")

            pontos = ev.selection.points if ev and getattr(ev, "selection", None) else []
            uf_sel = None
            for p_ in pontos:
                uf_sel = p_.get("location") or (p_.get("customdata") or [None])[0] or p_.get("hovertext")
                if uf_sel:
                    break
            if uf_sel and uf_sel in set(dv["uf"].astype(str)):
                st.divider()
                bloco_votos(dv[dv["uf"].astype(str) == uf_sel], modo, pct_menor, f"🗺️ {uf_sel}",
                            ["cd_municipio", "municipio"], "municipio", key=f"uf_{uf_sel}", votos=votos_ativo)
            else:
                st.caption("Clique num estado do mapa para ver o detalhe dele (métricas, gráfico e tabela por município).")
            st.divider()

        bloco_votos(dv, modo, pct_menor, nivel, filho, rotulo, key="nivel", votos=votos_ativo)
        st.caption("Leitura: 'dif.' é a média do grupo de menor abstenção menos a média de todas as seções, em "
                   "pontos percentuais. Diferenças são esperadas (perfil do eleitorado muda com a "
                   "abstenção); o interesse está em unidades que destoam muito das demais.")

        # ---------- seções que mais destoam da própria cidade
        st.divider()
        st.subheader("🔎 Seções de menor abstenção que mais destoam da própria cidade")
        cc1, cc2, cc3 = st.columns([2, 1, 1])
        cand_r, nome_r = cc1.selectbox("Candidato", VOTOS[:2], format_func=lambda v: v[1], key="cand_rank")
        min_sec_mun = cc2.number_input("Cidade com pelo menos N seções", 5, 200, 10, 5, key="min_sec_rank")
        n_top = cc3.number_input("Mostrar", 10, 500, 50, 10, key="n_rank")
        zc, dc = f"z_{cand_r[4:]}_mun", f"dif_{cand_r[4:]}_mun"
        g_all = dv[grupo_menor_abstencao(dv, modo, pct_menor)]
        n_sec_mun = dv.groupby([dv["uf"].astype(str), dv["cd_municipio"]], observed=True)["secao"].transform("size")
        g_all = g_all[n_sec_mun.reindex(g_all.index) >= min_sec_mun].copy()
        g_all["_media_cidade"] = g_all[cand_r] - g_all[dc]
        rank = g_all.sort_values(zc, ascending=False).head(int(n_top)).copy()
        rank[dc] = rank[dc] * 100
        cols_r = ["uf", "municipio", "zona", "secao", "aptos", "taxa_abstencao", "z_ajustado",
                  cand_r, "_media_cidade", dc, zc, "nome_local"]
        st.dataframe(rank[cols_r], hide_index=True, width="stretch", height=420, key="tab_rank",
                     column_config={"taxa_abstencao": st.column_config.NumberColumn("abstenção", format="percent"),
                                    "z_ajustado": st.column_config.NumberColumn("z abst.", format="%.2f"),
                                    cand_r: st.column_config.NumberColumn(f"% {nome_r} na seção", format="percent"),
                                    "_media_cidade": st.column_config.NumberColumn("média da cidade", format="percent"),
                                    dc: st.column_config.NumberColumn("dif. (p.p.)", format="%+.1f p.p."),
                                    zc: st.column_config.NumberColumn("z vs. cidade", format="%.2f",
                                                                      help="Desvios padrão da cidade; ≥ 2 já destoa")})
        st.download_button("⬇️ Baixar ranking (CSV)", rank[cols_r].to_csv(index=False, sep=";", decimal=",")
                           .encode("utf-8-sig"), "secoes_vs_cidade.csv", "text/csv", key="dl_rank")
        st.caption("Só seções do grupo de menor abstenção, em cidades com pelo menos N seções. 'z vs. cidade' = "
                   "quantos desvios padrão a seção está acima da média das outras seções do município. "
                   "Use o filtro de Estado/Município na barra lateral para aprofundar.")

# ---------------------------------------------------------------- horário dos votos
SEM_LOGS = ("Ainda não há logs de urna para este nível. Baixe e processe os logs do(s) estado(s):\n\n"
            "```\npython baixar_logs.py --ufs AC\n```\n"
            "Depois recarregue o painel. Comece por um estado pequeno: os arquivos do TSE são grandes.")

with aba_hora:
    dh = df[df["tem_log"]]
    if dh.empty:
        st.info(SEM_LOGS)
    else:
        perfil = perfil_horario(dh)
        perfil_br = perfil_horario(base)
        perfil, perfil_br = [p[(p.index >= 7) & (p.index <= 23)] for p in (perfil, perfil_br)]
        fig = go.Figure()
        fig.add_trace(go.Bar(x=perfil.index, y=perfil.values, name=nivel,
                             marker_color=["#33415c" if h < 17 else COR_ALTA for h in perfil.index]))
        if uf != TODOS:
            fig.add_trace(go.Scatter(x=perfil_br.index, y=perfil_br.values, name="Brasil (seções com log)",
                                     mode="lines+markers", line=dict(color=COR_NORMAL, dash="dot")))
        fig.add_vline(x=16.5, line_dash="dash", annotation_text="17h")
        fig.update_layout(title="Distribuição dos votos ao longo do dia (horário de Brasília)",
                          xaxis=dict(tickmode="array", tickvals=list(perfil.index),
                                     ticktext=[f"{h}h" for h in perfil.index]),
                          yaxis_tickformat=".0%", height=420, legend=dict(orientation="h"))
        st.plotly_chart(fig, width="stretch")

        # média ± desvio por subunidade
        th = resumo_coluna(dh, "hora_media", filho)
        tard = dh.groupby(filho, observed=True)[["votos_apos_17", "votos_log"]].sum()
        tard["pct_apos_17"] = tard["votos_apos_17"] / tard["votos_log"]
        th = th.merge(tard["pct_apos_17"], left_on=filho, right_index=True, how="left")
        th[rotulo] = th[rotulo].astype(str)
        if len(th) <= 40:
            t = th.sort_values("media")
            fig = go.Figure(go.Scatter(
                x=t["media"], y=t[rotulo], mode="markers",
                error_x=dict(type="data", array=t["desvio_padrao"].fillna(0), color="#b8c0cc"),
                marker=dict(size=9, color="#33415c"),
                customdata=np.stack([t["secoes"], t["pct_apos_17"]], axis=1),
                hovertemplate="%{y}<br>hora média %{x:.2f}h<br>seções %{customdata[0]}<br>"
                              "votos após 17h %{customdata[1]:.2%}<extra></extra>"))
            fig.add_vline(x=dh["hora_media"].mean(), line_dash="dash", annotation_text="média do nível acima")
            fig.update_layout(title="Hora média do voto: média ± 1 desvio padrão entre as seções",
                              xaxis_title="hora (decimal, Brasília)", height=max(350, 22 * len(t) + 80),
                              margin=dict(l=10, r=10, t=50, b=10))
        else:
            fig = px.scatter(th, x="media", y="pct_apos_17", size="secoes", hover_name=rotulo,
                             color="desvio_padrao", color_continuous_scale="OrRd", size_max=35,
                             labels={"media": "hora média (decimal)", "pct_apos_17": "% dos votos após 17h",
                                     "desvio_padrao": "desvio (h)"},
                             title="Cada ponto é uma unidade: hora média × % dos votos após 17h")
            fig.update_layout(yaxis_tickformat=".1%", height=560)
        st.plotly_chart(fig, width="stretch")

        a, b = st.columns(2)
        m, sd = dh["hora_media"].mean(), dh["hora_media"].std()
        fig = px.histogram(dh, x="hora_media", nbins=80, color_discrete_sequence=["#33415c"])
        for k, estilo in [(0, "solid"), (2, "dot"), (3, "dash")]:
            fig.add_vline(x=m + k * sd, line_dash=estilo, line_color=COR_ALTA if k else "black",
                          annotation_text="média" if k == 0 else f"+{k} dp")
        fig.update_layout(title="Hora média do voto, por seção", xaxis_title="hora (decimal)",
                          yaxis_title="seções", height=380)
        a.plotly_chart(fig, width="stretch")
        fig = px.histogram(dh[dh["votos_apos_17"] > 0], x="pct_apos_17", nbins=60,
                           color_discrete_sequence=[COR_ALTA], log_y=True)
        fig.update_layout(title="Seções com votos após 17h: % dos votos depois das 17h (escala log)",
                          xaxis_tickformat=".0%", xaxis_title="% dos votos após 17h", yaxis_title="seções",
                          height=380)
        b.plotly_chart(fig, width="stretch")

        st.markdown("**Seções com mais votos após 17h**")
        cols = [c for c in ["uf", "municipio", "zona", "secao", "votos_apos_17", "pct_apos_17", "sinais",
                            "ultimo_voto", "hora_media", "z_horario", "dif_local_min", "pct_sem_bio_apos_17",
                            "ociosa_antes_17_min", "taxa_abstencao", "votos_log", "nome_local"] if c in dh]
        top = dh.sort_values(["pct_apos_17", "votos_apos_17"], ascending=False).head(500)
        ev_h = st.dataframe(
            top[cols], hide_index=True, width="stretch", height=380, on_select="rerun",
            selection_mode="single-row", key="tab_hora",
            column_config={**{c: st.column_config.NumberColumn(format="percent")
                              for c in ["pct_apos_17", "pct_sem_bio_apos_17", "taxa_abstencao"]},
                           **{c: st.column_config.NumberColumn(format="%.2f")
                              for c in ["hora_media", "ultimo_voto", "z_horario"]},
                           **{c: st.column_config.NumberColumn(format="%.0f")
                              for c in ["dif_local_min", "ociosa_antes_17_min"]}})
        st.caption("Votar depois das 17h é permitido: quem está na fila às 17h vota. Em 2022 foram cerca "
                   "de 4 milhões de votos após as 17h no 1º turno. Por isso, olhe junto os sinais: "
                   "fila de verdade costuma afetar a escola inteira e vem precedida de uma última hora cheia.")
        if ev_h and ev_h.selection and ev_h.selection.rows:
            st.divider()
            detalhe_secao(top.iloc[ev_h.selection.rows[0]])

# ---------------------------------------------------------------- sem digital
with aba_dig:
    dd = df[df["tem_log"]] if "pct_sem_digital" in df else df.iloc[0:0]
    if dd.empty:
        st.info(SEM_LOGS if not tem_logs else
                "Os logs foram processados por uma versão antiga. Rode `python baixar_logs.py --refazer`.")
    else:
        ind = st.radio("Indicador", ["Sem digital (total)", "Liberação manual (só quem tem digital)"],
                       horizontal=True,
                       help="Sem digital = eleitor sem digital cadastrada + eleitor liberado pelo mesário. "
                            "Liberação manual = eleitor TEM digital cadastrada, ela não foi reconhecida e o "
                            "mesário liberou com a digital dele.")
        total_ind = ind.startswith("Sem")
        col_p, col_z, col_esp = (("pct_sem_digital", "z_sem_digital", "sem_digital_esperado") if total_ind
                                 else ("pct_manual_cadastrados", "z_manual", "manual_esperado"))

        # perfil hora a hora
        tot, sd, man = (votos_por_hora(dd, p) for p in "hsm")
        horas_ = [h for h in range(6, 24) if tot[h] >= max(30, 0.001 * tot.sum())]
        fig = go.Figure()
        fig.add_trace(go.Bar(x=[f"{h}h" for h in horas_], y=[(sd[h] - man[h]) / tot[h] for h in horas_],
                             name="sem cadastro de digital", marker_color="#e0a33a",
                             customdata=[int(tot[h]) for h in horas_],
                             hovertemplate="%{x}: %{y:.1%} de %{customdata} votos<extra></extra>"))
        fig.add_trace(go.Bar(x=[f"{h}h" for h in horas_], y=[man[h] / tot[h] for h in horas_],
                             name="liberação manual pelo mesário", marker_color=COR_ALTA))
        fig.update_layout(barmode="stack", yaxis_tickformat=".0%", height=380, legend=dict(orientation="h"),
                          title="% dos eleitores de cada hora liberados SEM digital (horário de Brasília; "
                                "horas com menos de 30 votos omitidas)")
        st.plotly_chart(fig, width="stretch")

        # por subunidade
        agg = dd.groupby(filho, observed=True)[["votos_log", "votos_digital", "votos_sem_cadastro",
                                                "votos_manual"]].sum()
        agg["sem_digital_agregado"] = 1 - agg["votos_digital"] / agg["votos_log"]
        agg["manual_agregado"] = agg["votos_manual"] / (agg["votos_log"] - agg["votos_sem_cadastro"])
        td = resumo_coluna(dd, col_p, filho).merge(agg, left_on=filho, right_index=True, how="left")
        z3 = dd[dd[col_z] >= 3].groupby(filho, observed=True).size().rename("secoes_z3")
        td = td.merge(z3, left_on=filho, right_index=True, how="left").fillna({"secoes_z3": 0})
        td[rotulo] = td[rotulo].astype(str)
        if len(td) <= 40:
            t = td.sort_values("media")
            fig = go.Figure(go.Scatter(
                x=t["media"], y=t[rotulo], mode="markers",
                error_x=dict(type="data", array=t["desvio_padrao"].fillna(0), color="#b8c0cc"),
                marker=dict(size=9, color="#33415c"),
                customdata=np.stack([t["secoes"], t["secoes_z3"]], axis=1),
                hovertemplate="%{y}<br>média %{x:.1%}<br>seções %{customdata[0]}<br>"
                              "seções com z ≥ 3: %{customdata[1]}<extra></extra>"))
            fig.add_vline(x=dd[col_p].mean(), line_dash="dash", annotation_text="média do nível acima")
            fig.update_layout(title=f"{ind}: média ± 1 desvio padrão entre as seções",
                              xaxis_tickformat=".0%", height=max(350, 22 * len(t) + 80),
                              margin=dict(l=10, r=10, t=50, b=10))
        else:
            fig = px.scatter(td, x="sem_digital_agregado", y="manual_agregado", size="votos_log",
                             color="secoes_z3", hover_name=rotulo, color_continuous_scale="OrRd", size_max=35,
                             labels={"sem_digital_agregado": "% sem digital (total)",
                                     "manual_agregado": "% liberação manual (de quem tem digital)",
                                     "secoes_z3": "seções z≥3"},
                             title="Cada ponto é uma unidade: sem digital × liberação manual")
            fig.update_layout(xaxis_tickformat=".0%", yaxis_tickformat=".0%", height=560)
        st.plotly_chart(fig, width="stretch")

        # funil: proporção × número de votos
        pts = dd[dd[col_z].notna()]
        den = pts["votos_log"] if total_ind else pts["votos_log"] - pts["votos_sem_cadastro"]
        flag = pts[col_z] >= limite
        if (~flag).sum() > 60_000:
            keep = pts[~flag].sample(60_000, random_state=1).index.union(pts[flag].index)
            pts, den, flag = pts.loc[keep], den.loc[keep], flag.loc[keep]
        fig = go.Figure()
        for nome, m, cor, tam, op in [("demais", ~flag, COR_NORMAL, 4, .35),
                                      (f"z ≥ {limite} (acima do esperado no município)", flag, COR_ALTA, 8, .95)]:
            d = pts[m]
            fig.add_trace(go.Scattergl(
                x=den[m], y=d[col_p], mode="markers", name=nome, marker=dict(size=tam, color=cor, opacity=op),
                text=(d["municipio"].astype(str) + " · Z" + d["zona"].astype(str) + " · S" + d["secao"].astype(str)
                      + "<br>esperado " + (d[col_esp] * 100).round(1).astype(str) + "% · z "
                      + d[col_z].round(1).astype(str)),
                hovertemplate="%{text}<br>%{y:.1%} de %{x} eleitores<extra></extra>"))
        fig.update_layout(title=f"{ind} × tamanho da seção (seções pequenas variam mais por acaso)",
                          xaxis_title="eleitores (votos no log)" if total_ind else "eleitores com digital cadastrada",
                          yaxis_title=ind, yaxis_tickformat=".0%", height=520, legend=dict(orientation="h"))
        st.plotly_chart(fig, width="stretch")

        sel = dd[flag.reindex(dd.index, fill_value=False) | (dd[col_z] >= limite)].sort_values(col_z, ascending=False)
        st.write(f"**{len(sel):,}** seções com {ind.lower()} {limite}+ desvios acima do esperado para o município. "
                 "Selecione uma linha para ver o detalhe.")
        cols = [c for c in ["uf", "municipio", "zona", "secao", col_z, col_p, col_esp, "pct_sem_cadastro",
                            "votos_manual", "maior_seq_manual", "dif_local_sem_digital_pp", "z_sem_digital",
                            "z_manual", "taxa_abstencao", "z_ajustado", "pct_apos_17", "sinais", "votos_log",
                            "nome_local"] if c in sel]
        cols = list(dict.fromkeys(cols))
        ev_d = st.dataframe(
            sel[cols], hide_index=True, width="stretch", height=400, on_select="rerun",
            selection_mode="single-row", key="tab_dig",
            column_config={**{c: st.column_config.NumberColumn(format="percent")
                              for c in ["pct_sem_digital", "pct_manual_cadastrados", "sem_digital_esperado",
                                        "manual_esperado", "pct_sem_cadastro", "taxa_abstencao", "pct_apos_17"]},
                           **{c: st.column_config.NumberColumn(format="%.2f")
                              for c in ["z_sem_digital", "z_manual", "z_ajustado"]},
                           "dif_local_sem_digital_pp": st.column_config.NumberColumn(format="%+.0f p.p.")})
        st.download_button("⬇️ Baixar lista (CSV)", sel[cols].to_csv(index=False, sep=";", decimal=",")
                           .encode("utf-8-sig"), "secoes_sem_digital.csv", "text/csv", key="dl_dig")
        st.caption("Liberar sem digital é previsto em lei e comum (~1 em cada 5 eleitores em 2022): "
                   "eleitor sem cadastro biométrico, idosos e trabalhadores braçais com digitais gastas, "
                   "leitor com defeito ou sujo. Por isso o z compara cada seção com o próprio município. "
                   "Sinais mais fortes: muitas LIBERAÇÕES MANUAIS (eleitor tinha digital), em SEQUÊNCIA, "
                   "numa seção que destoa das outras da mesma escola.")
        if ev_d and ev_d.selection and ev_d.selection.rows:
            st.divider()
            detalhe_secao(sel.iloc[ev_d.selection.rows[0]])

# ---------------------------------------------------------------- cruzamento
with aba_cruz:
    dc = df[df["tem_log"] & df["score_cruzado"].notna()] if tem_logs else df.iloc[0:0]
    if dc.empty:
        st.info(SEM_LOGS)
    else:
        st.markdown(f"**Critérios (barra lateral):** {NOME_CRUZ} — todos ≥ {limite_cruz} desvios.")
        cx = criterios[0]
        cy = criterios[1] if len(criterios) > 1 else ("Votação tardia" if cx != "Votação tardia" else "Abstenção baixa")
        eixos = st.radio("Eixos", ["Padronizados (z, comparando com o próprio município)", "Valores brutos"],
                         horizontal=True)
        padr = eixos.startswith("Padr")
        xcol = CRITERIOS[cx][0] if padr else CRITERIOS[cx][1]
        ycol = CRITERIOS[cy][0] if padr else CRITERIOS[cy][1]
        if xcol not in dc or ycol not in dc:
            st.warning("Indicador indisponível nestes dados. Rode `python baixar_logs.py --refazer`.")
            st.stop()
        destaque = dc["score_cruzado"] >= limite_cruz
        pontos = dc
        if (~destaque).sum() > 60_000:
            pontos = pd.concat([dc[~destaque].sample(60_000, random_state=1), dc[destaque]])
        hover = (pontos["municipio"].astype(str) + " · Z" + pontos["zona"].astype(str) + " · S"
                 + pontos["secao"].astype(str) + "<br>abstenção " + (pontos["taxa_abstencao"] * 100).round(1).astype(str)
                 + "% · hora média " + pontos["hora_media"].map(hora) + " · após 17h "
                 + (pontos["pct_apos_17"] * 100).round(1).astype(str) + "%")
        if "pct_sem_digital" in pontos:
            hover = hover + " · sem digital " + (pontos["pct_sem_digital"] * 100).round(1).astype(str) + "%"
        hover = hover + "<br>" + pontos["sinais"].fillna("")
        fig = go.Figure()
        for nome, mask, cor, tam, op in [("demais seções", pontos["score_cruzado"] < limite_cruz, COR_NORMAL, 4, .35),
                                         (NOME_CRUZ, pontos["score_cruzado"] >= limite_cruz, COR_ALTA, 9, .95)]:
            d = pontos[mask]
            fig.add_trace(go.Scattergl(
                x=d[xcol].clip(-12, 15) if padr else d[xcol], y=d[ycol].clip(-12, 15) if padr else d[ycol],
                mode="markers", name=nome, marker=dict(size=tam, color=cor, opacity=op),
                text=hover[mask], hovertemplate="%{text}<extra></extra>"))
        if padr:
            fig.add_shape(type="rect", x0=limite_cruz, x1=15, y0=limite_cruz, y1=15,
                          fillcolor=COR_ALTA, opacity=0.07, line_width=0)
            for v in (-limite_cruz, limite_cruz):
                fig.add_vline(x=v, line_dash="dot", line_color="#888")
                fig.add_hline(y=v, line_dash="dot", line_color="#888")
            fig.update_layout(xaxis_title=EIXO_Z[cx], yaxis_title=EIXO_Z[cy])
        else:
            fig.update_layout(xaxis_title=CRITERIOS[cx][2], yaxis_title=CRITERIOS[cy][2],
                              xaxis_tickformat=".0%", yaxis_tickformat=".0%")
        extra = f" (os demais critérios — {', '.join(criterios[2:]).lower()} — entram no destaque)" \
            if len(criterios) > 2 else ""
        fig.update_layout(title=f"Cada ponto é uma seção: {cx.lower()} × {cy.lower()}{extra}", height=620,
                          legend=dict(orientation="h"))
        st.plotly_chart(fig, width="stretch")

        sel = dc[destaque].sort_values(["score_cruzado", "n_sinais"], ascending=False)
        st.write(f"**{len(sel):,}** seções com {NOME_CRUZ} (todos ≥ {limite_cruz}), de {len(dc):,} com log. "
                 "Ordenadas pelo score; a coluna *sinais* resume o que o log mostra.")
        cols = [c for c in ["uf", "municipio", "zona", "secao", "score_cruzado", "n_sinais", "sinais",
                            "taxa_abstencao", "z_ajustado", "hora_media", "z_horario", "pct_apos_17",
                            "pct_sem_digital", "z_sem_digital", "pct_manual_cadastrados", "z_manual",
                            "maior_seq_manual", "ociosa_antes_17_min", "dif_local_min", "aptos", "nome_local"]
                if c in sel]
        ev_c = st.dataframe(
            sel[cols], hide_index=True, width="stretch", height=420, on_select="rerun",
            selection_mode="single-row", key="tab_cruz",
            column_config={**{c: st.column_config.NumberColumn(format="percent")
                              for c in ["taxa_abstencao", "pct_apos_17", "pct_sem_digital", "pct_manual_cadastrados"]},
                           **{c: st.column_config.NumberColumn(format="%.2f")
                              for c in ["z_ajustado", "hora_media", "z_horario", "score_cruzado", "z_sem_digital",
                                        "z_manual"]},
                           **{c: st.column_config.NumberColumn(format="%.0f")
                              for c in ["dif_local_min", "ociosa_antes_17_min"]}})
        st.download_button("⬇️ Baixar lista (CSV)", sel[cols].to_csv(index=False, sep=";", decimal=",")
                           .encode("utf-8-sig"), "cruzamento.csv", "text/csv", key="dl_cruz")
        st.caption("Indicadores andam juntos por motivos comuns: mais eleitores → mais fila → votação tardia; "
                   "região sem cadastro biométrico → mais eleitores sem digital. O que diferencia é o contexto: "
                   "compare com as outras seções da mesma escola (detalhe da seção) e veja os sinais do log.")
        if ev_c and ev_c.selection and ev_c.selection.rows:
            st.divider()
            detalhe_secao(sel.iloc[ev_c.selection.rows[0]])
