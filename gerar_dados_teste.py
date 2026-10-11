"""
Gera dados FALSOS no mesmo formato dos arquivos do TSE, para testar o sistema
sem baixar nada:

  dados/teste_detalhe_votacao_secao.zip     (abstenção por seção)
  dados/teste_arqurna_1999_1t_<UF>.zip      (logs de urna .logjez por seção)

Inclui seções anômalas plantadas de propósito:
  - abstenção muito alta ou muito baixa;
  - "cruzadas": abstenção baixa + rajada de votos sem biometria após as 17h
    sem fila antes (o padrão que o painel procura);
  - filas legítimas: escolas inteiras votando até tarde (não devem ser destaque);
  - liberação manual alta: seções isoladas onde muitos eleitores COM digital
    cadastrada foram liberados pelo mesário, incluindo 12 seguidos;
  - escolas inteiras com muitos eleitores sem digital cadastrada (legítimo);
  - sinais extras do log: sequência de votos muito rápidos, votos antes das 8h,
    liberações manuais concentradas no fim do dia.

Também gera as fontes de "Mais análises" (veja gerar_fontes_extras):
votação por seção (voto concentrado, eleição apertada), perfil do eleitorado
(idade explica parte da abstenção), população do IBGE (cadastro inflado),
eleição anterior (1995) e 2º turno, transferência temporária, seções agregadas
e gastos de campanha. O gabarito dos casos plantados fica em
dados/teste_gabarito.csv e dados/teste_gabarito_extras.csv.

    python gerar_dados_teste.py
    python baixar_dados.py --ano 1999 --zip dados/teste_detalhe_votacao_secao.zip
    for f in dados/teste_arqurna_*.zip; do python baixar_logs.py --zip $f; done
    python baixar_locais.py --ano 1999 --zip dados/teste_eleitorado_local_votacao.zip
    python gerar_site.py
(os comandos completos, com as fontes extras, estão no README: "Testar sem baixar nada")
"""
import io
import json
import zipfile
from concurrent.futures import ProcessPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import py7zr

rng = np.random.default_rng(42)
PASTA = Path(__file__).parent / "dados"
UFS = {"SP": 0.225, "CE": 0.153, "MG": 0.226, "MS": 0.238, "RJ": 0.233}
FUSO = {"MS": -1}  # urnas do MS marcam 1h a menos (abrem às 7h locais)
CARGOS = [(1, "Presidente"), (3, "Governador"), (6, "Deputado Federal")]
DIA = date(1999, 10, 3)
PERFIL_CHEGADA = np.array([.13, .14, .13, .11, .09, .10, .11, .10, .09])  # 8h..16h

# ------------------------------------------------------------ simulação dos horários
def sortear_hab(n, p_sem_cad, p_manual):
    """0 = digital, 1 = sem cadastro de digital, 2 = liberação manual (tinha digital)."""
    u = rng.random(n)
    hab = np.zeros(n, dtype=int)
    hab[u < p_sem_cad] = 1
    cad = u >= p_sem_cad
    hab[cad & (rng.random(n) < p_manual)] = 2
    return hab


def simular(n_eleitores, tipo, aptos, p_sem_cad, p_manual):
    """Devolve (segundos dos votos, habilitação) em horário de Brasília."""
    perfil = PERFIL_CHEGADA.copy()
    if tipo in ("fila_local", "manual_tarde"):
        perfil = perfil * np.linspace(0.6, 1.9, 9)
    perfil /= perfil.sum()
    n_falsos = int(aptos * 0.25) if tipo == "cruzada" else 0
    n_reais = max(n_eleitores - n_falsos, 1)
    hora = rng.choice(9, n_reais, p=perfil)
    chegada = np.sort((8 + hora + rng.random(n_reais)) * 3600)
    atend = rng.gamma(4, 22 if tipo != "fila_local" else 30, n_reais)  # ~90 s por eleitor
    fim, votos = 8 * 3600, []
    for c, a in zip(chegada, atend):
        fim = max(fim, c) + a
        votos.append(fim)
    if tipo == "escola_sem_cadastro":
        p_sem_cad = 0.40
    if tipo == "manual_alto":
        p_manual = 0.45
    hab = sortear_hab(n_reais, p_sem_cad, p_manual)
    if tipo == "manual_alto":  # rajada de liberações manuais no meio da tarde
        meio = len(hab) // 2
        hab[meio: meio + 12] = 2
    votos = np.array(votos)
    if tipo == "manual_tarde":  # liberações manuais quase todas a partir das 16h
        tarde = votos >= 16 * 3600
        hab = np.where(tarde & (hab != 1), np.where(rng.random(len(hab)) < 0.8, 2, 0), np.where(hab == 2, 0, hab))
    if tipo == "rapida":  # 25 votos seguidos com 12 a 25 s entre eles, às 14h
        bloco = 14 * 3600 + np.cumsum(rng.integers(12, 26, 25))
        votos = np.sort(np.concatenate([votos[(votos < 14 * 3600) | (votos > bloco[-1] + 60)][: len(votos) - 25], bloco]))
        hab = hab[: len(votos)]
    if tipo == "antes_8h":  # 8 votos entre 7h30 e 7h59 (antes da abertura)
        cedo = 7.5 * 3600 + np.sort(rng.integers(0, 1700, 8))
        votos = np.concatenate([cedo, votos[8:]])
    if n_falsos:
        votos = votos[votos < 16.4 * 3600][: n_reais]  # sem fila na última meia hora
        hab = hab[: len(votos)]
        inicio = 17 * 3600 + rng.integers(60, 600)
        falsos = inicio + np.cumsum(rng.integers(25, 50, n_falsos))
        votos = np.concatenate([votos, falsos])
        hab = np.concatenate([hab, np.where(rng.random(n_falsos) < 0.9, 2, 0)])
    return votos.astype(int), hab


def hms(t):
    t = int(t)
    return f"{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}"


def montar_log(mun, zona, secao, votos, hab, fuso, id_urna, extras_teste=True):
    L = []
    d0 = (DIA - timedelta(days=12)).strftime("%d/%m/%Y")
    d = DIA.strftime("%d/%m/%Y")
    ap = lambda dia, t, app, msg: L.append(f"{dia} {hms(t)}\tINFO\t{id_urna}\t{app}\t{msg}\tA162B520DE6255E2")
    for k, v in [("Município", mun), ("Zona Eleitoral", zona), ("Seção Eleitoral", secao)]:
        ap(d0, 9 * 3600, "GAP", f"{k}: {v}")
    if extras_teste:  # votação simulada em dia anterior (deve ser ignorada)
        for t in range(3):
            ap(d0, (10 * 3600) + t * 120, "VOTA", "Aguardando digitação do título")
            ap(d0, (10 * 3600) + t * 120 + 60, "VOTA", "O voto do eleitor foi computado")
    s = fuso * 3600
    ap(d, 7 * 3600 + 1800 + s, "VOTA", "Iniciando aplicação - Oficial - 1º turno")
    ap(d, 7 * 3600 + 2200 + s, "VOTA", "Gerando relatório [ZERÉSIMA] [INÍCIO]")
    ap(d, 8 * 3600 + 2 + s, "VOTA", "Aguardando digitação do título")
    for t, h in zip(votos, hab):
        t = t + s
        ap(d, t - 50, "VOTA", "Título digitado pelo mesário")
        if h == 0:
            ap(d, t - 45, "VOTA", "Solicita digital. Tentativa [1] de [4]")
            ap(d, t - 40, "VOTA", "Tipo de habilitação do eleitor [biométrica]")
        elif h == 1:
            ap(d, t - 45, "VOTA", "O eleitor não possui biometria")
        else:
            for k in range(1, 5):
                ap(d, t - 48, "VOTA", f"Solicita digital. Tentativa [{k}] de [4]")
                ap(d, t - 47, "VOTA", "Digital capturada não corresponde a digital do eleitor: Polegar Direito [score 3]")
            ap(d, t - 45, "VOTA", "Solicitação de dado pessoal do eleitor para habilitação manual")
            ap(d, t - 42, "VOTA", "Solicita digital do mesário")
            ap(d, t - 41, "VOTA", "Capturada a digital do mesário")
        ap(d, t - 39, "VOTA", "Eleitor foi habilitado")
        ap(d, t - 10, "VOTA", "Voto confirmado para [Presidente]")
        ap(d, t, "VOTA", "O voto do eleitor foi computado")
        ap(d, t + 1, "VOTA", "Aguardando digitação do título")
    return "\n".join(L).encode("latin-1")


def logjez(texto: bytes) -> bytes:
    b = io.BytesIO()
    with py7zr.SevenZipFile(b, "w") as z:
        z.writestr(texto, "logd.dat")
    return b.getvalue()



def municipios_reais(uf: str, n: int) -> list[tuple[int, str, float, float]]:
    """Sorteia municípios REAIS da UF (código do TSE, nome, lat, lon) para o mapa funcionar no teste."""
    ref = pd.read_csv(Path(__file__).parent / "referencia" / "municipios.csv").dropna(subset=["cd_tse"])
    ref = ref[ref["uf"] == uf]
    esc = ref.sample(min(n, len(ref)), random_state=int(rng.integers(1 << 30)))
    return [(int(r.cd_tse), r.nome.upper(), r.lat, r.lon) for r in esc.itertuples()]


ENDERECOS = ["RUA DAS FLORES", "AVENIDA BRASIL", "RUA SÃO JOÃO", "PRAÇA DA MATRIZ", "RUA SETE DE SETEMBRO",
             "AVENIDA GETÚLIO VARGAS", "RUA TIRADENTES", "RUA DOM PEDRO II", "AVENIDA CENTRAL"]
BAIRROS = ["CENTRO", "JARDIM AMÉRICA", "VILA NOVA", "SÃO JOSÉ", "BOA VISTA", "SANTA LUZIA", "ZONA RURAL"]
TIPOS_LOCAL = ["ESCOLA ESTADUAL", "ESCOLA MUNICIPAL", "COLÉGIO", "CENTRO COMUNITÁRIO", "UNIVERSIDADE"]


def main():
    # ------------------------------------------------------------ seções e abstenção
    linhas = []
    coords = {}
    for uf, base in UFS.items():
        for cd, nm, lat, lon in municipios_reais(uf, int(rng.integers(8, 20))):
            coords[cd] = (lat, lon)
            p_mun = np.clip(base + rng.normal(0, 0.03), 0.05, 0.6)
            p_sem_cad_mun = float(rng.uniform(0.04, 0.18))  # cobertura biométrica varia por município
            for zona in range(1, rng.integers(2, 5)):
                for s in range(1, rng.integers(15, 70)):
                    aptos = int(rng.integers(30, 420))
                    # perfil de idade da seção: quem tem 70+ ou 16-17 anos falta mais
                    s70 = float(np.clip(rng.normal(0.12, 0.03), 0.01, 0.5))
                    s16 = float(np.clip(rng.normal(0.025, 0.012), 0, 0.1))
                    p = np.clip(p_mun + 0.6 * (s70 - 0.12) + 0.6 * (s16 - 0.025) + rng.normal(0, 0.02), 0.01, 0.95)
                    abst = int(rng.binomial(aptos, p))
                    linhas.append([uf, cd, nm, zona, s, aptos, abst, (zona * 1000 + s // 8), p_sem_cad_mun, s70, s16])

    df = pd.DataFrame(linhas, columns=["SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO", "NR_ZONA",
                                       "NR_SECAO", "QT_APTOS", "QT_ABSTENCOES", "NR_LOCAL_VOTACAO",
                                       "p_sem_cad", "s70", "s16"])
    df["tipo"] = "normal"

    # abstenção anômala (alta / baixa)
    idx = rng.choice(df.index[df["QT_APTOS"] >= 150], 12, replace=False)
    for i, j in enumerate(idx):
        df.loc[j, "QT_ABSTENCOES"] = int(df.loc[j, "QT_APTOS"] * (0.02 if i % 2 else 0.65))
        df.loc[j, "tipo"] = "abstencao_baixa" if i % 2 else "abstencao_alta"

    # cruzadas: abstenção baixa + votos tardios sem biometria (seções grandes)
    grandes = df.index[(df["QT_APTOS"] > 250) & (df["tipo"] == "normal")]
    cruz = rng.choice(grandes, 8, replace=False)
    df.loc[cruz, "tipo"] = "cruzada"

    # filas legítimas: alguns locais de votação inteiros com eleitores chegando no fim do dia
    locais = df.loc[df["tipo"] == "normal", ["CD_MUNICIPIO", "NR_ZONA", "NR_LOCAL_VOTACAO"]].drop_duplicates()
    fila = locais.sample(6, random_state=1)
    marca = df.merge(fila.assign(_f=1), how="left", on=list(fila.columns))["_f"].eq(1).to_numpy()
    df.loc[marca & (df["tipo"] == "normal"), "tipo"] = "fila_local"

    # liberação manual alta (tinha digital, mesário liberou) em seções isoladas
    normais = df.index[(df["tipo"] == "normal") & (df["QT_APTOS"] > 150)]
    df.loc[rng.choice(normais, 8, replace=False), "tipo"] = "manual_alto"

    # escolas inteiras com muita gente sem digital cadastrada (legítimo: ex. eleitores novos)
    locais = df.loc[df["tipo"] == "normal", ["CD_MUNICIPIO", "NR_ZONA", "NR_LOCAL_VOTACAO"]].drop_duplicates()
    esc = locais.sample(4, random_state=7)
    marca = df.merge(esc.assign(_f=1), how="left", on=list(esc.columns))["_f"].eq(1).to_numpy()
    df.loc[marca & (df["tipo"] == "normal"), "tipo"] = "escola_sem_cadastro"

    # sinais extras do log, em seções isoladas
    for tipo, qtd in [("rapida", 6), ("antes_8h", 4), ("manual_tarde", 6)]:
        normais = df.index[(df["tipo"] == "normal") & (df["QT_APTOS"] > 200)]
        df.loc[rng.choice(normais, qtd, replace=False), "tipo"] = tipo

    # perfil explica: abstenção baixa porque quase não há idosos (o perfil explica o destaque)
    normais = df.index[(df["tipo"] == "normal") & (df["QT_APTOS"] > 250)]
    for j in rng.choice(normais, 4, replace=False):
        df.loc[j, ["s70", "s16"]] = [0.0, 0.0]
        df.loc[j, "QT_ABSTENCOES"] = int(df.loc[j, "QT_APTOS"] * max(UFS[df.loc[j, "SG_UF"]] - 0.11, 0.03))
        df.loc[j, "tipo"] = "perfil_jovem"
    # muitos idosos: mais liberação manual, explicada pela idade
    normais = df.index[(df["tipo"] == "normal") & (df["QT_APTOS"] > 250)]
    for j in rng.choice(normais, 4, replace=False):
        df.loc[j, "s70"] = 0.55
        df.loc[j, "tipo"] = "idosos"

    # locais de votação (formato do arquivo do TSE "Eleitorado por local de votação"),
    # com endereço e coordenadas inventados perto do centro do município
    loc = df[["SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO", "NR_ZONA", "NR_SECAO", "NR_LOCAL_VOTACAO", "QT_APTOS"]].copy()
    unicos = loc[["CD_MUNICIPIO", "NR_ZONA", "NR_LOCAL_VOTACAO"]].drop_duplicates()
    info = {}
    for r in unicos.itertuples(index=False):
        lat, lon = coords[r.CD_MUNICIPIO]
        k = int(rng.integers(1000))
        info[tuple(r)] = (f"{TIPOS_LOCAL[k % 5]} {['ANITA GARIBALDI', 'RUI BARBOSA', 'MONTEIRO LOBATO', 'CECÍLIA MEIRELES', 'PAULO FREIRE'][k % 5]} {r.NR_LOCAL_VOTACAO % 100}",
                          f"{ENDERECOS[k % 9]}, {int(rng.integers(10, 2000))}", BAIRROS[k % 7],
                          f"{int(rng.integers(10000, 99999))}{int(rng.integers(100, 999))}",
                          round(lat + rng.normal(0, 0.02), 6) if k % 13 else -1,
                          round(lon + rng.normal(0, 0.02), 6) if k % 13 else -1)
    vals = [info[(a, b, c)] for a, b, c in zip(loc["CD_MUNICIPIO"], loc["NR_ZONA"], loc["NR_LOCAL_VOTACAO"])]
    for i, col in enumerate(["NM_LOCAL_VOTACAO", "DS_ENDERECO", "NM_BAIRRO", "NR_CEP", "NR_LATITUDE", "NR_LONGITUDE"]):
        loc[col] = [v[i] for v in vals]
    loc["DS_TIPO_LOCAL"] = [TIPOS_LOCAL[0] if "ESCOLA" in v[0] else "OUTROS" for v in vals]
    loc = loc.rename(columns={"QT_APTOS": "QT_ELEITOR_SECAO"})
    loc, agregadas = secoes_agregadas(loc)
    loc.insert(0, "NR_TURNO", 1)
    loc.insert(0, "AA_ELEICAO", 1999)
    buf = io.StringIO()
    loc.to_csv(buf, sep=";", index=False, decimal=",")
    PASTA.mkdir(exist_ok=True)
    with zipfile.ZipFile(PASTA / "teste_eleitorado_local_votacao.zip", "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("eleitorado_local_votacao_1999.csv", buf.getvalue().encode("latin-1"))
    nomes_local = {k: v[0] for k, v in info.items()}

    PASTA.mkdir(exist_ok=True)
    for f in PASTA.glob("teste_arqurna_*.zip"):
        f.unlink()
    zips = {uf: zipfile.ZipFile(PASTA / f"teste_arqurna_1999_1t_{uf}.zip", "w", zipfile.ZIP_STORED) for uf in UFS}
    interno = io.BytesIO()
    zip_interno = zipfile.ZipFile(interno, "w")  # CE: logs dentro de um zip interno (testa os dois formatos)
    pendentes = []
    for i, r in enumerate(df.itertuples()):
        comparec = r.QT_APTOS - r.QT_ABSTENCOES
        if r.tipo == "cruzada":
            comparec = r.QT_APTOS - int(r.QT_APTOS * 0.03)
            df.at[r.Index, "QT_ABSTENCOES"] = r.QT_APTOS - comparec
        if r.tipo == "fila_local":
            comparec = r.QT_APTOS - int(r.QT_APTOS * 0.12)
            df.at[r.Index, "QT_ABSTENCOES"] = r.QT_APTOS - comparec
        p_manual = float(np.clip(rng.normal(0.08, 0.025) + 0.4 * (r.s70 - 0.12), 0.01, 0.4))
        votos, hab = simular(comparec, r.tipo, r.QT_APTOS, r.p_sem_cad, p_manual)
        nome = f"o00999-{r.CD_MUNICIPIO:05d}{r.NR_ZONA:04d}{r.NR_SECAO:04d}"
        texto = montar_log(r.CD_MUNICIPIO, r.NR_ZONA, r.NR_SECAO, votos, hab, FUSO.get(r.SG_UF, 0), 2000000 + i)
        pendentes.append((r.SG_UF, nome, texto))
    print(f"Compactando {len(pendentes):,} logs…")
    with ProcessPoolExecutor() as ex:
        comprimidos = list(ex.map(logjez, [p[2] for p in pendentes], chunksize=64))
    for (uf, nome, _), conteudo in zip(pendentes, comprimidos):
        destino = zip_interno if uf == "CE" else zips[uf]
        destino.writestr(f"{nome}.logjez", conteudo)
        destino.writestr(f"{nome}.bu", b"bu-falso")
    zip_interno.close()
    zips["CE"].writestr("logs_ce.zip", interno.getvalue())
    for z in zips.values():
        z.close()

    print("Seções plantadas:")
    print(df[df["tipo"] != "normal"].groupby("tipo").size().to_string())
    print(df[df["tipo"] == "cruzada"][["SG_UF", "NM_MUNICIPIO", "NR_ZONA", "NR_SECAO"]].to_string())

    # ------------------------------------------------------------ zip de abstenção
    df["QT_COMPARECIMENTO"] = df["QT_APTOS"] - df["QT_ABSTENCOES"]
    df["NM_LOCAL_VOTACAO"] = [nomes_local[(a, b, c)] for a, b, c in
                              zip(df["CD_MUNICIPIO"], df["NR_ZONA"], df["NR_LOCAL_VOTACAO"])]
    df["NR_TURNO"] = 1
    df["ANO_ELEICAO"] = 1999
    t2 = segundo_turno(df)
    gravar_detalhe(PASTA / "teste_detalhe_votacao_secao.zip", 1999, [(df, 1, CARGOS), (t2, 2, CARGOS[:2])])
    df[["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "tipo"]].to_csv(PASTA / "teste_gabarito.csv", index=False)
    print(f"\n{len(df):,} seções sintéticas -> dados/teste_detalhe_votacao_secao.zip (1º e 2º turno) "
          "e dados/teste_arqurna_*.zip")
    gerar_fontes_extras(df, coords, agregadas)


def gravar_detalhe(saida: Path, ano: int, conjuntos):
    """Zip no formato "Detalhe da apuração por seção": (seções, turno, cargos) para cada turno."""
    partes = []
    for base, turno, cargos in conjuntos:
        for cd, ds in cargos:
            d = base.drop(columns=["tipo", "p_sem_cad", "s70", "s16"], errors="ignore").copy()
            d["NR_TURNO"], d["ANO_ELEICAO"], d["CD_CARGO"], d["DS_CARGO"] = turno, ano, cd, ds
            partes.append(d)
    tudo = pd.concat(partes)
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as z:
        for uf, g in tudo.groupby("SG_UF"):
            buf = io.StringIO()
            g.to_csv(buf, sep=";", index=False)
            z.writestr(f"detalhe_votacao_secao_{ano}_{uf}.csv", buf.getvalue().encode("latin-1"))


def segundo_turno(df: pd.DataFrame) -> pd.DataFrame:
    """2º turno: abstenção um pouco maior; 5 seções plantadas com comparecimento que dispara."""
    t2 = df.copy()
    p = t2["QT_ABSTENCOES"] / t2["QT_APTOS"] + 0.02
    t2["QT_ABSTENCOES"] = rng.binomial(t2["QT_APTOS"], p.clip(0.01, 0.95))
    salto = rng.choice(t2.index[(t2["tipo"] == "normal") & (t2["QT_APTOS"] > 200)], 5, replace=False)
    t2.loc[salto, "QT_ABSTENCOES"] = (t2.loc[salto, "QT_APTOS"] * 0.02).astype(int)
    t2["QT_COMPARECIMENTO"] = t2["QT_APTOS"] - t2["QT_ABSTENCOES"]
    EXTRAS.extend(("salto_2turno", *k) for k in t2.loc[salto, ["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO"]]
                  .itertuples(index=False))
    return t2


EXTRAS: list[tuple] = []  # gabarito dos casos plantados nas fontes extras


def secoes_agregadas(loc: pd.DataFrame) -> tuple[pd.DataFrame, list]:
    """Cinco seções recebem seções agregadas (linhas a mais no arquivo de locais, com
    NR_SECAO_PRINCIPAL apontando para a seção que de fato funcionou)."""
    loc = loc.copy()
    loc["DS_TIPO_SECAO_AGREGADA"] = "NÃO AGREGADA"
    loc["NR_SECAO_PRINCIPAL"] = loc["NR_SECAO"]
    principais = loc.sample(5, random_state=3)
    novas = []
    for r in principais.itertuples():
        loc.loc[r.Index, "DS_TIPO_SECAO_AGREGADA"] = "PRINCIPAL"
        for k in range(2):
            a = loc.loc[r.Index].copy()
            a["NR_SECAO"] = 900 + len(novas)
            a["DS_TIPO_SECAO_AGREGADA"] = "AGREGADA"
            a["NR_SECAO_PRINCIPAL"] = r.NR_SECAO
            novas.append(a)
        EXTRAS.append(("agregada", r.SG_UF, r.CD_MUNICIPIO, r.NR_ZONA, r.NR_SECAO))
    return pd.concat([loc, pd.DataFrame(novas)], ignore_index=True), principais


# ------------------------------------------------------------ fontes de "Mais análises"
CANDIDATOS = {  # cargo: (código, descrição, nº de candidatos, votos por eleitor)
    "pres": (1, "PRESIDENTE", 4, 1), "gov": (3, "GOVERNADOR", 3, 1), "sen": (5, "SENADOR", 4, 2),
    "fed": (6, "DEPUTADO FEDERAL", 14, 1), "est": (7, "DEPUTADO ESTADUAL", 18, 1),
}
NOMES = ["ANA", "BRUNO", "CARLA", "DANIEL", "ELISA", "FÁBIO", "GABRIELA", "HUGO", "IRENE", "JOÃO", "LÚCIA",
         "MÁRCIO", "NÁDIA", "OTÁVIO", "PAULA", "RAUL", "SÍLVIA", "TIAGO", "ÚRSULA", "VÍTOR"]
SOBRENOMES = ["SILVA", "SOUZA", "OLIVEIRA", "PEREIRA", "LIMA", "COSTA", "RIBEIRO", "ALMEIDA", "CARVALHO"]


def gerar_fontes_extras(df: pd.DataFrame, coords: dict, agregadas):
    df = df.copy()
    df["QT_COMPARECIMENTO"] = df["QT_APTOS"] - df["QT_ABSTENCOES"]
    votacao(df)
    perfil(df)
    populacao(df)
    eleicao_anterior(df)
    transferencia(df)
    gastos(df)
    g = pd.DataFrame(EXTRAS, columns=["caso", "SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO"])
    g.to_csv(PASTA / "teste_gabarito_extras.csv", index=False)
    print("\nFontes extras plantadas:")
    print(g.groupby("caso").size().to_string())


def votacao(df: pd.DataFrame):
    """votacao_secao_1999_<UF>.zip: votos por candidato em cada seção.
    Planta: voto muito concentrado num deputado federal (10 seções, 4 delas com abstenção baixa
    e quase sem brancos e nulos = padrão de 'curral'); governador do MS numa disputa apertada."""
    linhas = []
    baixa = df.index[df["tipo"] == "abstencao_baixa"][:4]
    normais = df.index[(df["tipo"] == "normal") & (df["QT_APTOS"] > 180)]
    conc = list(baixa) + list(rng.choice(normais, 10 - len(baixa), replace=False))
    for i in conc:
        r = df.loc[i]
        EXTRAS.append(("concentrado_curral" if r["tipo"] == "abstencao_baixa" else "concentrado",
                       r["SG_UF"], r["CD_MUNICIPIO"], r["NR_ZONA"], r["NR_SECAO"]))
    conc = set(conc)
    for uf, g_uf in df.groupby("SG_UF"):
        cands = {}
        for k, (cd, ds, nc, _) in CANDIDATOS.items():
            dig = 2 if cd in (1, 3) else (3 if cd == 5 else (4 if cd == 6 else 5))
            nums = sorted(int(x) for x in rng.choice(np.arange(10 ** (dig - 1) + 10 ** (dig - 2), 10 ** dig - 1), nc, replace=False))
            if cd in (1, 3):
                nums = [10 + 3 * j for j in range(nc)]
            nomes = [f"{NOMES[int(rng.integers(len(NOMES)))]} {SOBRENOMES[int(rng.integers(len(SOBRENOMES)))]}" for _ in nums]
            base = rng.dirichlet(np.ones(nc) * 3)
            if k == "gov" and uf == "MS":
                base = np.array([0.39, 0.385, 0.225])
            cands[k] = (cd, ds, nums, nomes, base)
        for cd_mun, g in g_uf.groupby("CD_MUNICIPIO"):
            local = {k: rng.dirichlet(v[4] * 60) for k, v in cands.items()}  # preferência do município
            for r in g.itertuples():
                comp = r.QT_APTOS - r.QT_ABSTENCOES
                for k, (cd, ds, nums, nomes, _) in cands.items():
                    pref = local[k]
                    p_bn = 0.07 if cd in (1, 3, 5) else 0.12
                    curral = r.Index in conc and k == "fed"
                    if curral:
                        pref = np.full(len(nums), 0.3 / (len(nums) - 1))
                        pref[0] = 0.7
                        p_bn = 0.005 if r.tipo == "abstencao_baixa" else 0.06
                    for _ in range(CANDIDATOS[k][3]):
                        bn = rng.binomial(comp, p_bn)
                        branco = rng.binomial(bn, 0.45)
                        v = rng.multinomial(comp - bn, pref / pref.sum())
                        for nr, nm, q in zip(nums, nomes, v):
                            if q:
                                linhas.append((uf, cd_mun, r.NM_MUNICIPIO, r.NR_ZONA, r.NR_SECAO, cd, ds, nr, nm, q))
                        linhas.append((uf, cd_mun, r.NM_MUNICIPIO, r.NR_ZONA, r.NR_SECAO, cd, ds, 95, "VOTO BRANCO", branco))
                        linhas.append((uf, cd_mun, r.NM_MUNICIPIO, r.NR_ZONA, r.NR_SECAO, cd, ds, 96, "VOTO NULO", bn - branco))
    v = pd.DataFrame(linhas, columns=["SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO", "NR_ZONA", "NR_SECAO", "CD_CARGO",
                                      "DS_CARGO", "NR_VOTAVEL", "NM_VOTAVEL", "QT_VOTOS"])
    v = v.groupby(list(v.columns[:-1]), as_index=False)["QT_VOTOS"].sum()  # senador: 2 votos somados
    v = v[v["QT_VOTOS"] > 0]
    v.insert(0, "NR_TURNO", 1)
    v.insert(0, "ANO_ELEICAO", 1999)
    for uf, g in v.groupby("SG_UF"):
        with zipfile.ZipFile(PASTA / f"teste_votacao_secao_1999_{uf}.zip", "w", zipfile.ZIP_DEFLATED) as z:
            buf = io.StringIO()
            g.to_csv(buf, sep=";", index=False)
            z.writestr(f"votacao_secao_1999_{uf}.csv", buf.getvalue().encode("latin-1"))


def perfil(df: pd.DataFrame):
    """perfil_eleitor_secao_1999_<UF>.zip: eleitores por faixa etária e biometria."""
    faixas = ["16 anos", "17 anos", "18 a 20 anos", "21 a 24 anos", "25 a 34 anos", "35 a 44 anos",
              "45 a 59 anos", "60 a 69 anos", "70 a 79 anos", "80 anos ou mais"]
    linhas = []
    for r in df.itertuples():
        resto = max(1 - r.s70 - r.s16, 0)
        meio = np.array([0.08, 0.09, 0.2, 0.2, 0.25, 0.18]) * resto / 1.0
        pr = np.array([r.s16 / 2, r.s16 / 2, *meio, r.s70 * 0.75, r.s70 * 0.25])
        q = rng.multinomial(r.QT_APTOS, pr / pr.sum())
        for fx, qq in zip(faixas, q):
            if qq:
                bio = rng.binomial(qq, 1 - r.p_sem_cad)
                linhas.append((r.SG_UF, r.CD_MUNICIPIO, r.NM_MUNICIPIO, r.NR_ZONA, r.NR_SECAO, fx, "MASCULINO", qq, bio))
        if r.tipo in ("perfil_jovem", "idosos"):
            EXTRAS.append((r.tipo, r.SG_UF, r.CD_MUNICIPIO, r.NR_ZONA, r.NR_SECAO))
    p = pd.DataFrame(linhas, columns=["SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO", "NR_ZONA", "NR_SECAO",
                                      "DS_FAIXA_ETARIA", "DS_GENERO", "QT_ELEITORES_PERFIL", "QT_ELEITORES_BIOMETRIA"])
    p.insert(0, "ANO_ELEICAO", 1999)
    for uf, g in p.groupby("SG_UF"):
        with zipfile.ZipFile(PASTA / f"teste_perfil_eleitor_secao_1999_{uf}.zip", "w", zipfile.ZIP_DEFLATED) as z:
            buf = io.StringIO()
            g.to_csv(buf, sep=";", index=False)
            z.writestr(f"perfil_eleitor_secao_1999_{uf}.csv", buf.getvalue().encode("latin-1"))


def populacao(df: pd.DataFrame):
    """teste_populacao_ibge.zip no formato da API do SIDRA. Planta 2 municípios com mais eleitores
    do que moradores com 16 anos ou mais."""
    ref = pd.read_csv(Path(__file__).parent / "referencia" / "municipios.csv", dtype={"cd_ibge": str}).dropna(subset=["cd_tse"])
    ibge = ref.set_index(ref["cd_tse"].astype(int))["cd_ibge"]
    aptos = df.groupby(["SG_UF", "CD_MUNICIPIO"])["QT_APTOS"].sum()
    inflados = set(rng.choice(len(aptos), 2, replace=False))
    cab = {"NC": "Nível Territorial (Código)", "NN": "Nível Territorial", "MC": "Unidade de Medida (Código)",
           "MN": "Unidade de Medida", "V": "Valor", "D1C": "Município (Código)", "D1N": "Município",
           "D2C": "Variável (Código)", "D2N": "Variável", "D3C": "Ano (Código)", "D3N": "Ano",
           "D4C": "Idade (Código)", "D4N": "Idade"}
    linhas = [cab]
    for i, ((uf, cd), a) in enumerate(aptos.items()):
        razao = 1.3 if i in inflados else rng.uniform(0.75, 0.95)
        pop16 = int(a / razao)
        menores = rng.multinomial(int(pop16 * 0.28), np.ones(16) / 16)
        total = pop16 + int(menores.sum())
        if i in inflados:
            EXTRAS.append(("cadastro_inflado", uf, cd, None, None))
        for cod, v in [("total", total)] + [(str(k), int(m)) for k, m in enumerate(menores)]:
            linhas.append({"NC": "6", "NN": "Município", "MC": "45", "MN": "Pessoas", "V": str(v),
                           "D1C": ibge[cd], "D1N": f"Município {cd}", "D2C": "93", "D2N": "População residente",
                           "D3C": "2022", "D3N": "2022", "D4C": cod, "D4N": cod})
    with zipfile.ZipFile(PASTA / "teste_populacao_ibge.zip", "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("metadados.json", json.dumps({"menores": [str(k) for k in range(16)], "total": "total"}))
        z.writestr("populacao.json", json.dumps(linhas, ensure_ascii=False))


def eleicao_anterior(df: pd.DataFrame):
    """teste_detalhe_votacao_secao_1995.zip: a eleição anterior (como 2022 para 2026).
    Metade das seções de abstenção baixa já era baixa em 1995 (causa estrutural); 2 municípios
    tiveram o eleitorado crescendo 40% de uma eleição para a outra."""
    ant = df.copy()
    cresc = set(rng.choice(ant["CD_MUNICIPIO"].unique(), 2, replace=False))
    fator = np.where(ant["CD_MUNICIPIO"].isin(cresc), 1 / 1.4, rng.uniform(0.9, 1.0, len(ant)))
    ant["QT_APTOS"] = np.maximum((ant["QT_APTOS"] * fator).astype(int), 20)
    p = (df["QT_ABSTENCOES"] / df["QT_APTOS"]).where(df["tipo"] == "normal", np.nan)
    p = p.fillna(p.mean())
    baixa = df.index[df["tipo"] == "abstencao_baixa"]
    repete = baixa[: len(baixa) // 2]
    p.loc[repete] = 0.02
    ant["QT_ABSTENCOES"] = rng.binomial(ant["QT_APTOS"], p.clip(0.01, 0.95))
    ant["QT_COMPARECIMENTO"] = ant["QT_APTOS"] - ant["QT_ABSTENCOES"]
    for i in baixa:
        r = df.loc[i]
        EXTRAS.append(("repetiu_1995" if i in repete else "novidade_1999", r["SG_UF"], r["CD_MUNICIPIO"],
                       r["NR_ZONA"], r["NR_SECAO"]))
    for cd in cresc:
        EXTRAS.append(("crescimento_40pct", df.loc[df["CD_MUNICIPIO"] == cd, "SG_UF"].iloc[0], cd, None, None))
    gravar_detalhe(PASTA / "teste_detalhe_votacao_secao_1995.zip", 1995, [(ant, 1, CARGOS[:1])])


def transferencia(df: pd.DataFrame):
    """transf_temporaria_secao_1999.zip: uma linha por grupo transferido (origem -> destino).
    Planta 3 seções que recebem 150 eleitores em trânsito."""
    linhas = []
    destinos = df.sample(120, random_state=5)
    grandes = rng.choice(len(destinos), 3, replace=False)
    for i, r in enumerate(destinos.itertuples()):
        o = df.loc[int(rng.integers(len(df)))]
        q = 150 if i in grandes else int(rng.integers(1, 12))
        linhas.append((r.SG_UF, o["CD_MUNICIPIO"], o["NR_ZONA"], o["NR_SECAO"], r.CD_MUNICIPIO, r.NR_ZONA, r.NR_SECAO,
                       "VOTO EM TRÂNSITO" if i % 3 else "MESÁRIO", q))
        if i in grandes:
            EXTRAS.append(("transferencia_grande", r.SG_UF, r.CD_MUNICIPIO, r.NR_ZONA, r.NR_SECAO))
    t = pd.DataFrame(linhas, columns=["SG_UF", "CD_MUNICIPIO_ORIGEM", "NR_ZONA_ORIGEM", "NR_SECAO_ORIGEM",
                                      "CD_MUNICIPIO_DESTINO", "NR_ZONA_DESTINO", "NR_SECAO_DESTINO",
                                      "DS_TIPO_TRANSFERENCIA", "QT_ELEITORES"])
    t.insert(0, "NR_TURNO", 1)
    buf = io.StringIO()
    t.to_csv(buf, sep=";", index=False)
    with zipfile.ZipFile(PASTA / "teste_transf_temporaria_secao_1999.zip", "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("transf_temporaria_secao_1999_BRASIL.csv", buf.getvalue().encode("latin-1"))


def gastos(df: pd.DataFrame):
    """prestacao_de_contas_eleitorais_candidatos_1999.zip com despesas_contratadas_..._BRASIL.csv.
    Planta 2 municípios com gasto de transporte e combustível ~20 vezes maior por eleitor
    (um deles é o município de uma seção 'cruzada')."""
    tipos = ["Combustíveis e lubrificantes", "Cessão ou locação de veículos", "Despesas com transporte ou deslocamento",
             "Despesas com pessoal", "Atividades de militância e mobilização de rua",
             "Publicidade por materiais impressos", "Serviços prestados por terceiros"]
    mun = df.groupby(["SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO"])["QT_APTOS"].sum().reset_index()
    cruz = df.loc[df["tipo"] == "cruzada", "CD_MUNICIPIO"].iloc[0]
    caros = {cruz, int(rng.choice(mun["CD_MUNICIPIO"][mun["CD_MUNICIPIO"] != cruz]))}
    linhas = []
    for r in mun.itertuples():
        fator = 20 if r.CD_MUNICIPIO in caros else 1
        for tp in tipos:
            n = int(rng.integers(3, 12))
            por_eleitor = rng.uniform(0.2, 0.6) * (fator if tp in tipos[:4] else 1)
            vals = rng.dirichlet(np.ones(n)) * r.QT_APTOS * por_eleitor
            for v in vals:
                linhas.append((r.SG_UF, "DEPUTADO FEDERAL", tp, f"{v:.2f}".replace(".", ","), r.CD_MUNICIPIO,
                               r.NM_MUNICIPIO, r.SG_UF, "PESSOA FÍSICA"))
        if fator > 1:
            EXTRAS.append(("gasto_alto", r.SG_UF, r.CD_MUNICIPIO, None, None))
    g = pd.DataFrame(linhas, columns=["SG_UF", "DS_CARGO", "DS_ORIGEM_DESPESA", "VR_DESPESA_CONTRATADA",
                                      "CD_MUNICIPIO_FORNECEDOR", "NM_MUNICIPIO_FORNECEDOR", "SG_UF_FORNECEDOR",
                                      "DS_TIPO_FORNECEDOR"])
    buf = io.StringIO()
    g.to_csv(buf, sep=";", index=False)
    with zipfile.ZipFile(PASTA / "teste_prestacao_de_contas_eleitorais_candidatos_1999.zip", "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("despesas_contratadas_candidatos_1999_BRASIL.csv", buf.getvalue().encode("latin-1"))
        z.writestr("receitas_candidatos_1999_BRASIL.csv", "SG_UF;VR_RECEITA\nSP;1\n".encode("latin-1"))

if __name__ == "__main__":
    main()
