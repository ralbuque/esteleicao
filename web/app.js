// esteleição — site estático. Todos os números vêm de arquivos JSON pré-calculados
// por gerar_site.py; nada é processado no servidor durante a visita.

// =============================================================== utilidades
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const NF = new Intl.NumberFormat("pt-BR");
const n = (x) => (x == null || Number.isNaN(x) ? "—" : NF.format(Math.round(x)));
const p = (x, casas = 1) => (x == null || !Number.isFinite(x) ? "—" :
  (x * 100).toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas }) + "%");
const hora = (h) => {
  if (h == null) return "—";
  const m = Math.round(h * 60);
  return `${Math.floor(m / 60)}h${String(m % 60).padStart(2, "0")}`;
};
const div = (a, b) => (b ? a / b : null);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const plural = (q, um, varios) => `${n(q)} ${q === 1 ? um : varios}`;

const NOMES_UF = {
  AC: "Acre", AL: "Alagoas", AM: "Amazonas", AP: "Amapá", BA: "Bahia", CE: "Ceará", DF: "Distrito Federal",
  ES: "Espírito Santo", GO: "Goiás", MA: "Maranhão", MG: "Minas Gerais", MS: "Mato Grosso do Sul",
  MT: "Mato Grosso", PA: "Pará", PB: "Paraíba", PE: "Pernambuco", PI: "Piauí", PR: "Paraná",
  RJ: "Rio de Janeiro", RN: "Rio Grande do Norte", RO: "Rondônia", RR: "Roraima", RS: "Rio Grande do Sul",
  SC: "Santa Catarina", SE: "Sergipe", SP: "São Paulo", TO: "Tocantins",
};
const IBGE_UF = { 11: "RO", 12: "AC", 13: "AM", 14: "RR", 15: "PA", 16: "AP", 17: "TO", 21: "MA", 22: "PI", 23: "CE",
  24: "RN", 25: "PB", 26: "PE", 27: "AL", 28: "SE", 29: "BA", 31: "MG", 32: "ES", 33: "RJ", 35: "SP", 41: "PR",
  42: "SC", 43: "RS", 50: "MS", 51: "MT", 52: "GO", 53: "DF" };
const NIVEIS = ["rigoroso", "padrao", "amplo"];
const CRIT = {
  abst: { bit: 1, nome: "Abstenção muito baixa", curto: "Abstenção baixa", classe: "cor-abst" },
  "17h": { bit: 2, nome: "Muitos votos depois das 17h", curto: "Após 17h", classe: "cor-17h" },
  man: { bit: 4, nome: "Muitas liberações pelo mesário", curto: "Liberação manual", classe: "cor-man" },
};
// 4º critério, opcional: voto muito concentrado num candidato (aba "Seções em atenção")
const CONC = { bit: 8, nome: "Voto muito concentrado num candidato", curto: "Voto concentrado", classe: "cor-conc" };
const ROT_FAIXA = (h) => (h === 18 ? "18h+" : `${h}h`);
const reais = (x) => (x == null || !Number.isFinite(x) ? "—" : x.toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: Math.abs(x) >= 100 ? 0 : 2 }));
const vezes = (x) => (x == null || !Number.isFinite(x) ? "—" : `${x.toLocaleString("pt-BR", { maximumFractionDigits: x >= 10 ? 0 : 1 })}×`);
const dec = (x, casas = 2) => (x == null || !Number.isFinite(x) ? "—" : x.toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas }));

// tabela compacta {cols, rows} -> lista de objetos
const objetos = (t) => (t && t.rows ? t.rows.map((r) => Object.fromEntries(t.cols.map((c, i) => [c, r[i]]))) : []);

// =============================================================== dados
const cache = new Map();
let versao = "";
async function json(caminho) {
  if (!cache.has(caminho)) {
    cache.set(caminho, fetch(`dados/${caminho}${versao ? `?v=${versao}` : ""}`).then((r) => {
      if (!r.ok) throw new Error(`${caminho}: ${r.status}`);
      return r.json();
    }).catch((e) => { cache.delete(caminho); throw e; }));
  }
  return cache.get(caminho);
}
const D = {
  brasil: null, municipios: null, munPorCd: new Map(),
  async iniciar() {
    const r = await fetch(`dados/brasil.json?t=${Date.now() / 60000 | 0}`);
    if (!r.ok) throw new Error("brasil.json");
    this.brasil = await r.json();
    versao = encodeURIComponent(this.brasil.meta.gerado_em);
    this.municipios = objetos(await json("municipios.json"));
    for (const m of this.municipios) this.munPorCd.set(m.cd_municipio, m);
  },
  uf: (uf) => json(`uf/${uf}.json`),
  mun: (cd) => json(`mun/${cd}.json`),
  zona: (cd, z) => json(`zona/${cd}-${z}.json`),
  apos17: () => json("apos17.json"),
  plano: () => json("plano.json"),
  // extras.json só existe se o site foi gerado com a versão que tem "Mais análises"
  extras: () => json("extras.json").catch(() => ({})),
  extrasUf: (uf) => json(`extras/${uf}.json`).catch(() => ({})),
};

// seções de um arquivo -> objetos com local de votação e município preenchidos
function secoesDe(arq, campo = "secoes", extra = {}) {
  return objetos(arq[campo]).map((s) => {
    const cd = s.cd_municipio ?? arq.cd;
    const mun = D.munPorCd.get(cd) || {};
    const loc = arq.locais?.[`${cd}-${s.zona}-${s.local}`] || [];
    return {
      ...s, ...extra, cd_municipio: cd, uf: s.uf ?? mun.uf ?? arq.uf, mun_nome: mun.mun_nome,
      escola: loc[0], endereco: loc[1], bairro: loc[2], cep: loc[3], lat: loc[4], lon: loc[5], tipo_local: loc[6],
      horasArr: s.horas ? s.horas.split(" ").map(Number) : null,
    };
  });
}

// =============================================================== estado (fica na URL)
const E = { tela: "panorama", uf: null, mun: null, zona: null, nivel: "padrao" };
function lerHash() {
  const [cam, qs] = location.hash.replace(/^#\/?/, "").split("?");
  const q = new URLSearchParams(qs || "");
  E.tela = cam || "panorama";
  E.uf = q.get("uf") || null;
  E.mun = q.get("mun") ? +q.get("mun") : null;
  E.zona = q.get("zona") ? +q.get("zona") : null;
  E.nivel = NIVEIS.includes(q.get("nivel")) ? q.get("nivel") : (localStorageGet("nivel") || "padrao");
}
function link(mud = {}) {
  const e = { ...E, ...mud };
  const q = new URLSearchParams();
  if (e.uf) q.set("uf", e.uf);
  if (e.uf && e.mun) q.set("mun", e.mun);
  if (e.uf && e.mun && e.zona) q.set("zona", e.zona);
  if (e.nivel !== "padrao") q.set("nivel", e.nivel);
  const s = q.toString();
  return `#/${e.tela}${s ? "?" + s : ""}`;
}
const ir = (mud) => { location.hash = link(mud); };
function localStorageGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function localStorageSet(k, v) { try { localStorage.setItem(k, v); } catch { /* sem armazenamento */ } }

const iNivel = () => NIVEIS.indexOf(E.nivel);
const crit = (flags) => (flags >> (3 * iNivel())) & 7;
const ncrit = (c) => (c & 1 ? 1 : 0) + (c & 2 ? 1 : 0) + (c & 4 ? 1 : 0) + (c & 8 ? 1 : 0);
// voto concentrado no nível atual (bit i de flags_conc); "comConc" inclui o 4º critério em crit()
const temConc = (s) => !!((s.flags_conc ?? 0) >> iNivel() & 1);
const critX = (s, comConc) => crit(s.flags) | (comConc && temConc(s) ? 8 : 0);
const explicaIdade = (s, bit) => !!((s.perfil_explica ?? 0) >> ((bit === 4 ? 3 : 0) + iNivel()) & 1);
const pref = () => E.nivel; // prefixo das colunas agregadas do nível

// recorte atual: nome, agregados e filhos
function nomeRecorte() {
  if (E.mun) {
    const m = D.munPorCd.get(E.mun);
    return `${m?.mun_nome ?? E.mun} (${m?.uf ?? E.uf})${E.zona ? `, zona ${E.zona}` : ""}`;
  }
  if (E.uf) return NOMES_UF[E.uf] ?? E.uf;
  return "Brasil";
}
// "no Brasil", "na Bahia", "em São Paulo", "em Campinas (SP)"
const PREP_UF = { BA: "na", PB: "na", AL: "em", GO: "em", MG: "em", PE: "em", RO: "em", RR: "em", SC: "em", SE: "em", SP: "em" };
function emRecorte() {
  if (E.mun) return `em ${nomeRecorte()}`;
  if (E.uf) return `${PREP_UF[E.uf] ?? "no"} ${NOMES_UF[E.uf] ?? E.uf}`;
  return "no Brasil";
}
const Cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
async function agregadoRecorte() {
  if (E.mun && E.zona) {
    const m = await D.mun(E.mun);
    return objetos(m.zonas).find((z) => z.zona === E.zona) || {};
  }
  if (E.mun) return D.munPorCd.get(E.mun) || {};
  if (E.uf) return objetos(D.brasil.ufs).find((u) => u.uf === E.uf) || {};
  return D.brasil.total;
}
const dentro = (s) => (!E.uf || s.uf === E.uf) && (!E.mun || s.cd_municipio === E.mun) && (!E.zona || s.zona === E.zona);

// =============================================================== componentes
function numeros(itens) {
  return `<dl class="numeros">${itens.map((i) => `<div class="numero${i.destaque ? " destaque" : ""}"><dt>${i.rotulo}</dt><dd>${i.valor}${i.sub ? `<small>${i.sub}</small>` : ""}</dd></div>`).join("")}</dl>`;
}
function selos(c) {
  return `<span class="selos">${[...Object.values(CRIT), CONC].filter((k) => c & k.bit).map((k) => `<span class="selo ${k.classe}">${k.curto}</span>`).join("")}</span>`;
}
const PRIO = { 3: "Alta", 2: "Média", 1: "Baixa" };
const mapsUrl = (s) => s.lat != null && s.lon != null
  ? `https://www.google.com/maps/search/?api=1&query=${s.lat},${s.lon}`
  : `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent([s.escola, s.endereco, s.bairro, s.mun_nome, s.uf].filter(Boolean).join(", "))}`;

// Tabela com ordenação, "mostrar mais" e exportação CSV.
// colunas: [{ k, rot, num, html(o), csv(o), ord(o) }]
function tabela(el, { colunas, linhas, ordem, limite = 50, aoClicar, arquivo, vazio = "Nada para mostrar neste recorte." }) {
  let ord = ordem || null;
  let mostrar = limite;
  const valOrd = (c, o) => (c.ord ? c.ord(o) : o[c.k]);
  function desenhar() {
    let ls = linhas;
    if (ord) {
      const c = colunas.find((x) => x.k === ord.k);
      ls = [...linhas].sort((a, b) => {
        const va = valOrd(c, a), vb = valOrd(c, b);
        if (va == null && vb == null) return 0;
        if (va == null) return 1;
        if (vb == null) return -1;
        return (va < vb ? -1 : va > vb ? 1 : 0) * (ord.desc ? -1 : 1);
      });
    }
    if (!ls.length) { el.innerHTML = `<div class="vazio">${vazio}</div>`; return; }
    const vis = ls.slice(0, mostrar);
    const visiveis = colunas.filter((c) => !c.oculto);
    el.innerHTML = `<div class="tabela-envolta"><table><thead><tr>${visiveis.map((c) =>
      `<th class="${c.num ? "num" : ""}" ${ord && ord.k === c.k ? `aria-sort="${ord.desc ? "descending" : "ascending"}"` : ""}>${c.semOrdem ? c.rot : `<button data-k="${c.k}">${c.rot}</button>`}</th>`).join("")}</tr></thead>
      <tbody>${vis.map((o, i) => `<tr data-i="${i}" class="${aoClicar ? "clicavel" : ""}" ${aoClicar ? 'tabindex="0"' : ""}>${visiveis.map((c) =>
        `<td class="${c.num ? "num" : ""} ${c.classe || ""}">${c.html ? c.html(o) : esc(o[c.k] ?? "—")}</td>`).join("")}</tr>`).join("")}</tbody></table>
      <div class="tabela-rodape"><span>Mostrando ${n(vis.length)} de ${n(ls.length)}</span><span>
      ${ls.length > mostrar ? `<button data-mais>Mostrar mais ${n(Math.min(200, ls.length - mostrar))}</button>` : ""}
      ${arquivo ? `<button data-csv>Baixar planilha (CSV)</button>` : ""}</span></div></div>`;
    $$("th button", el).forEach((b) => b.addEventListener("click", () => {
      const k = b.dataset.k;
      ord = ord && ord.k === k ? { k, desc: !ord.desc } : { k, desc: !!colunas.find((c) => c.k === k).num };
      desenhar();
    }));
    $("[data-mais]", el)?.addEventListener("click", () => { mostrar += 200; desenhar(); });
    $("[data-csv]", el)?.addEventListener("click", () => baixarCsv(arquivo, colunas, ls));
    if (aoClicar) $$("tbody tr", el).forEach((tr) => {
      const f = () => aoClicar(vis[+tr.dataset.i]);
      tr.addEventListener("click", (ev) => { if (!ev.target.closest("a")) f(); });
      tr.addEventListener("keydown", (ev) => { if (ev.key === "Enter") f(); });
    });
  }
  desenhar();
}
function baixarCsv(nome, colunas, linhas) {
  const cs = colunas.filter((c) => c.csv !== false);
  const cel = (v) => {
    if (v == null) return "";
    if (typeof v === "number") return String(v).replace(".", ",");
    const s = String(v);
    return /[;"\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const txt = [cs.map((c) => c.rotCsv || c.rot.replace(/<[^>]+>/g, "")).join(";"),
    ...linhas.map((o) => cs.map((c) => cel(c.csv ? c.csv(o) : o[c.k])).join(";"))].join("\r\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob(["﻿" + txt], { type: "text/csv;charset=utf-8" }));
  a.download = nome;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

// Gráfico de barras dos votos por hora (horário de Brasília). comparacao: outra série (em %) desenhada como linha.
function graficoHoras(valores, { comparacao, rotComparacao, rotSerie = "Votos" } = {}) {
  const faixas = D.brasil.meta.faixas;
  const tot = valores.reduce((a, b) => a + b, 0) || 1;
  const pct = valores.map((v) => v / tot);
  const pc = comparacao ? (() => { const t = comparacao.reduce((a, b) => a + b, 0) || 1; return comparacao.map((v) => v / t); })() : null;
  const max = Math.max(...pct, ...(pc || [0])) || 1;
  const W = 640, H = 230, m = { t: 26, r: 8, b: 26, l: 8 };
  const bw = (W - m.l - m.r) / faixas.length;
  const y = (v) => m.t + (H - m.t - m.b) * (1 - v / max);
  const barras = faixas.map((h, i) => {
    const x = m.l + i * bw + 3, yy = y(pct[i]);
    const tarde = h >= 17;
    return `<rect class="barra${tarde ? " tarde" : ""}" x="${x}" y="${yy}" width="${bw - 6}" height="${H - m.b - yy}" rx="2"><title>${ROT_FAIXA(h)}: ${n(valores[i])} votos (${p(pct[i])})</title></rect>
      <text class="valor${tarde ? " tarde" : ""}" x="${x + (bw - 6) / 2}" y="${yy - 6}" text-anchor="middle">${tarde || valores.length < 12 ? n(valores[i]) : ""}</text>
      <text x="${x + (bw - 6) / 2}" y="${H - 8}" text-anchor="middle">${ROT_FAIXA(h)}</text>`;
  }).join("");
  const linha = pc ? `<polyline class="comparacao" points="${faixas.map((h, i) => `${m.l + i * bw + bw / 2},${y(pc[i])}`).join(" ")}"/>` : "";
  return `<div class="grafico"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Votos por hora">
    <line class="eixo" x1="${m.l}" x2="${W - m.r}" y1="${H - m.b}" y2="${H - m.b}"/>${barras}${linha}</svg>
    <div class="legenda"><span><i style="background:var(--tinta-3)"></i>${rotSerie} até 17h</span><span><i style="background:var(--c-17h)"></i>Depois das 17h</span>${pc ? `<span><i style="background:none;border-top:2px dashed var(--tinta);height:0;border-radius:0"></i>${rotComparacao}</span>` : ""}</div></div>`;
}

// =============================================================== barra de recorte (UF > município > zona)
async function desenharEscopo() {
  const el = $("#escopo");
  const ufs = objetos(D.brasil.ufs).map((u) => u.uf);
  let html = `<div class="escopo-dentro"><span class="rotulo">Recorte</span>
    <select id="sel-uf" aria-label="Estado"><option value="">Brasil inteiro</option>${ufs.map((u) => `<option value="${u}" ${u === E.uf ? "selected" : ""}>${NOMES_UF[u] ?? u}</option>`).join("")}</select>`;
  if (E.uf) {
    const muns = D.municipios.filter((m) => m.uf === E.uf);
    html += `<span class="seta" aria-hidden="true">›</span><select id="sel-mun" aria-label="Município"><option value="">Todos os municípios (${n(muns.length)})</option>${muns.map((m) => `<option value="${m.cd_municipio}" ${m.cd_municipio === E.mun ? "selected" : ""}>${esc(m.mun_nome)}</option>`).join("")}</select>`;
  }
  if (E.mun) {
    const zonas = objetos((await D.mun(E.mun)).zonas);
    html += `<span class="seta" aria-hidden="true">›</span><select id="sel-zona" aria-label="Zona eleitoral"><option value="">Todas as zonas (${zonas.length})</option>${zonas.map((z) => `<option value="${z.zona}" ${z.zona === E.zona ? "selected" : ""}>Zona ${z.zona}</option>`).join("")}</select>`;
  }
  if (E.uf) html += `<button class="limpar" id="limpar">Voltar ao Brasil</button>`;
  el.innerHTML = html + "</div>";
  $("#sel-uf").addEventListener("change", (e) => ir({ uf: e.target.value || null, mun: null, zona: null }));
  $("#sel-mun")?.addEventListener("change", (e) => ir({ mun: e.target.value ? +e.target.value : null, zona: null }));
  $("#sel-zona")?.addEventListener("change", (e) => ir({ zona: e.target.value ? +e.target.value : null }));
  $("#limpar")?.addEventListener("click", () => ir({ uf: null, mun: null, zona: null }));
}

// =============================================================== telas
const TELAS = {};

// ---------------------------------------------------------------- Panorama
TELAS.panorama = async (el) => {
  const a = await agregadoRecorte();
  const P = pref();
  const tem17 = a.votos_log > 0;
  const sec = a[`${P}_sec`] ?? 0;
  el.innerHTML = `
    <section class="manchete">
      <h1>${tem17
        ? `${esc(Cap(emRecorte()))}, <b>${n(a.votos_apos_17)} pessoas votaram depois das 17h</b>, ${p(div(a.votos_apos_17, a.votos_log), 2)} de todos os votos. <b>${plural(sec, "seção eleitoral chama", "seções eleitorais chamam")} atenção</b> em pelo menos um critério.`
        : `${esc(Cap(emRecorte()))}, <b>${plural(sec, "seção eleitoral chama", "seções eleitorais chamam")} atenção</b> pela abstenção. Os logs das urnas deste recorte ainda não foram processados.`}</h1>
      <p>Comparamos cada seção com as outras do mesmo município. Destacar uma seção não significa fraude: significa que vale olhar de perto, de preferência com um fiscal no próximo turno.</p>
    </section>
    ${numeros([
      { rotulo: "Seções eleitorais", valor: n(a.secoes), sub: `${n(a.aptos)} eleitores aptos` },
      { rotulo: "Compareceram", valor: n(a.comparecimento), sub: `${p(div(a.comparecimento, a.aptos))} dos aptos; faltaram ${n(a.abstencoes)}` },
      { rotulo: "Votaram depois das 17h", valor: tem17 ? n(a.votos_apos_17) : "—", sub: tem17 ? `${p(div(a.votos_apos_17, a.votos_log), 2)} dos votos, em ${plural(a.com_17h, "seção", "seções")}` : "sem logs neste recorte", destaque: tem17 },
      { rotulo: "Liberados pelo mesário", valor: tem17 ? n(a.votos_manual) : "—", sub: tem17 ? `${p(div(a.votos_manual, a.votos_log - a.votos_sem_cadastro))} de quem tem digital cadastrada` : "" },
      { rotulo: "Seções em atenção", valor: n(sec), sub: `${n(a[`${P}_mult`])} com 2 critérios ou mais`, destaque: true },
    ])}
    <section class="bloco">
      <header><h2>Os três critérios</h2><p>Uma seção entra na lista quando cumpre pelo menos um deles. Com o rigor <strong>${{ rigoroso: "rigoroso", padrao: "padrão", amplo: "amplo" }[E.nivel]}</strong> (mude no alto da página).</p></header>
      <div class="criterios">
        ${cartaoCriterio("abst", a[`${P}_abst`], "Compareceu muito mais gente do que o normal para o município. Pode ser seção nova, cadastro recém-revisado ou comunidade pequena, mas também é o que se veria com votos de quem não foi votar.")}
        ${cartaoCriterio("17h", a[`${P}_17h`], `Uma parte grande dos votos foi depois do encerramento, e a seção terminou bem depois das outras da mesma escola. Votar após as 17h é legal para quem estava na fila; quando a escola inteira atrasa, quase sempre é fila.`)}
        ${cartaoCriterio("man", a[`${P}_man`], "Muitos eleitores que têm digital cadastrada foram liberados pelo mesário depois de a digital falhar. Acontece com idosos, digitais gastas e leitor com defeito, que deve ser registrado em ata.")}
      </div>
    </section>
    ${tem17 ? `<section class="bloco duas-colunas">
      <div><header style="margin-bottom:14px"><h2>A que horas se votou</h2></header><div id="g-horas"></div></div>
      <div><header style="margin-bottom:14px"><h2>Votos depois das 17h, por seção</h2></header><div id="t-faixas"></div><p class="nota" style="margin-top:10px">A maior parte das seções tem poucos votos depois das 17h, o que é normal. Os casos que interessam estão nas faixas de cima.</p></div>
    </section>` : ""}
    <section class="bloco"><header><h2 id="t-filhos-titulo"></h2><p id="t-filhos-nota"></p></header><div id="t-filhos"></div></section>`;

  if (tem17) {
    let perfil = D.brasil.perfil.votos;
    if (E.mun) perfil = (await D.mun(E.mun)).perfil;
    else if (E.uf) perfil = D.brasil.perfil_uf[E.uf]?.votos || perfil;
    if (E.zona) {
      const z = secoesDe(await D.zona(E.mun, E.zona));
      perfil = z.reduce((acc, s) => (s.horasArr ? acc.map((v, i) => v + s.horasArr[i]) : acc), perfil.map(() => 0));
    }
    $("#g-horas").innerHTML = graficoHoras(perfil);
    let fx = E.uf ? D.brasil.faixas_17h_uf[E.uf] : D.brasil.faixas_17h;
    if (E.mun) fx = null;
    if (fx && fx.length) {
      tabela($("#t-faixas"), {
        colunas: [
          { k: "faixa", rot: "Votos após 17h na seção", semOrdem: true, html: (o) => esc(o.faixa) },
          { k: "secoes", rot: "Seções", num: true, semOrdem: true, html: (o) => n(o.secoes) },
          { k: "votos", rot: "Votos somados", num: true, semOrdem: true, html: (o) => n(o.votos) },
        ], linhas: [...fx].reverse(),
      });
    } else $("#t-faixas").innerHTML = `<p class="nota">Veja a aba <a href="${link({ tela: "apos17" })}">Votos após 17h</a> para o detalhe deste município.</p>`;
  }
  await tabelaFilhos();
};

function cartaoCriterio(k, q, texto) {
  const c = CRIT[k];
  return `<article class="criterio ${c.classe}"><span class="qtd">${n(q)}</span><h3>${c.nome}</h3><p>${texto}</p>
    <a href="${link({ tela: "atencao" })}${link({ tela: "atencao" }).includes("?") ? "&" : "?"}crit=${k}">Ver as seções</a></article>`;
}

// tabela com os "filhos" do recorte: UFs, municípios, zonas ou seções
async function tabelaFilhos() {
  const P = pref();
  const tit = $("#t-filhos-titulo"), nota = $("#t-filhos-nota"), el = $("#t-filhos");
  const colAgg = [
    { k: "secoes", rot: "Seções", num: true, html: (o) => n(o.secoes) },
    { k: "aptos", rot: "Eleitores aptos", num: true, html: (o) => n(o.aptos) },
    { k: "abst", rot: "Abstenção", num: true, ord: (o) => div(o.abstencoes, o.aptos), html: (o) => p(div(o.abstencoes, o.aptos)), csv: (o) => div(o.abstencoes, o.aptos) },
    { k: "votos_apos_17", rot: "Votos após 17h", num: true, html: (o) => (o.votos_log ? `<span class="forte">${n(o.votos_apos_17)}</span>` : "sem log"), csv: (o) => o.votos_apos_17 },
    { k: "p17", rot: "% após 17h", num: true, ord: (o) => div(o.votos_apos_17, o.votos_log), html: (o) => p(div(o.votos_apos_17, o.votos_log), 2), csv: (o) => div(o.votos_apos_17, o.votos_log) },
    { k: "sec", rot: "Seções em atenção", num: true, ord: (o) => o[`${P}_sec`], html: (o) => `<span class="forte">${n(o[`${P}_sec`])}</span>${o[`${P}_mult`] ? `<span class="sub">${n(o[`${P}_mult`])} com 2+ critérios</span>` : ""}`, csv: (o) => o[`${P}_sec`] },
  ];
  if (!E.uf) {
    tit.textContent = "Por estado";
    nota.textContent = "Clique num estado para ver os municípios.";
    tabela(el, { colunas: [{ k: "uf", rot: "Estado", html: (o) => `<span class="forte">${esc(NOMES_UF[o.uf] ?? o.uf)}</span>`, csv: (o) => o.uf }, ...colAgg],
      linhas: objetos(D.brasil.ufs), ordem: { k: "sec", desc: true }, limite: 30, aoClicar: (o) => ir({ uf: o.uf }), arquivo: "estados.csv" });
  } else if (!E.mun) {
    tit.textContent = "Por município";
    nota.textContent = "Clique num município para ver as zonas eleitorais.";
    tabela(el, { colunas: [{ k: "mun_nome", rot: "Município", html: (o) => `<span class="forte">${esc(o.mun_nome)}</span>` }, ...colAgg],
      linhas: D.municipios.filter((m) => m.uf === E.uf), ordem: { k: "sec", desc: true }, aoClicar: (o) => ir({ mun: o.cd_municipio }), arquivo: `municipios_${E.uf}.csv` });
  } else if (!E.zona) {
    tit.textContent = "Por zona eleitoral";
    nota.textContent = "Clique numa zona para ver todas as seções.";
    tabela(el, { colunas: [{ k: "zona", rot: "Zona", html: (o) => `<span class="forte">Zona ${o.zona}</span>` }, ...colAgg],
      linhas: objetos((await D.mun(E.mun)).zonas), ordem: { k: "sec", desc: true }, aoClicar: (o) => ir({ zona: o.zona }), arquivo: `zonas_${E.mun}.csv` });
  } else {
    tit.textContent = "Todas as seções da zona";
    nota.textContent = "Clique numa seção para ver o detalhe.";
    const ss = secoesDe(await D.zona(E.mun, E.zona));
    tabela(el, { colunas: colunasSecao({ compacto: true }), linhas: ss, ordem: { k: "crit", desc: true }, limite: 100, aoClicar: abrirSecao, arquivo: `secoes_${E.mun}_zona${E.zona}.csv` });
  }
}

// colunas padrão para listas de seções
function colunasSecao({ compacto = false, comMunicipio = false, comConc = false } = {}) {
  return [
    { k: "secao", rot: "Seção", html: (o) => `<span class="forte">Seção ${o.secao}</span><span class="sub">Zona ${o.zona}</span>`, csv: (o) => o.secao, ord: (o) => o.zona * 1e5 + o.secao },
    { k: "zona", rot: "Zona", csv: (o) => o.zona, html: () => "", semOrdem: true, oculto: true },
    { k: "escola", rot: "Local de votação", html: (o) => `${esc(o.escola ?? "Local não informado")}<span class="sub">${esc([o.bairro, comMunicipio ? `${o.mun_nome} (${o.uf})` : null].filter(Boolean).join(", "))}</span>`, csv: (o) => o.escola },
    ...(comMunicipio ? [{ k: "mun_nome", rot: "Município", csv: (o) => `${o.mun_nome} (${o.uf})`, html: () => "", oculto: true }] : []),
    { k: "endereco", rot: "Endereço", csv: (o) => [o.endereco, o.bairro, o.cep].filter(Boolean).join(" - "), html: () => "", oculto: true },
    { k: "crit", rot: "Critérios", ord: (o) => ncrit(critX(o, comConc)) * 100 + gravidade(o), html: (o) => (critX(o, comConc) ? selos(critX(o, comConc)) + (explicaIdade(o, 1) || explicaIdade(o, 4) ? `<span class="sub">idade explica parte</span>` : "") : `<span class="sub">nenhum</span>`), csv: (o) => [...Object.values(CRIT), CONC].filter((k) => critX(o, comConc) & k.bit).map((k) => k.curto).join(", ") },
    { k: "aptos", rot: "Eleitores aptos", num: true, html: (o) => n(o.aptos) },
    { k: "taxa_abstencao", rot: "Abstenção", num: true, html: (o) => `${p(o.taxa_abstencao)}<span class="sub">esperado ${p(o.taxa_esperada)}</span>`, csv: (o) => o.taxa_abstencao },
    { k: "votos_apos_17", rot: "Votos após 17h", num: true, html: (o) => (o.votos_log ? `<span class="forte">${n(o.votos_apos_17)}</span><span class="sub">${p(o.pct_apos_17)} dos votos</span>` : "—") },
    { k: "votos_manual", rot: "Liberados pelo mesário", num: true, html: (o) => (o.votos_log ? `${n(o.votos_manual)}<span class="sub">${p(o.pct_manual_cadastrados)} de quem tem digital</span>` : "—") },
    ...(comConc ? [{ k: "conc_votos", rot: "Voto concentrado", num: true, html: (o) => (temConc(o) ? `<span class="forte">${n(o.conc_votos)}</span><span class="sub">${p(o.conc_fatia)} para ${esc(nomeCand(o.conc_nome))}</span>` : "—"), csv: (o) => (temConc(o) ? `${o.conc_nome}: ${o.conc_votos} votos (${p(o.conc_fatia)})` : "") }] : []),
    { k: "tipo_local", rot: "Tipo de local", oculto: true, csv: (o) => o.tipo_local ?? "" },
  ];
}
const nomeCand = (s) => (s ? s.toLowerCase().replace(/(^|\s)\S/g, (c) => c.toUpperCase()) : "candidato");
// "quanto" a seção passa dos critérios (para ordenar)
function gravidade(o) {
  const c = crit(o.flags);
  return (c & 1 ? Math.max(0, -(o.z_ajustado ?? 0)) / 3 : 0) + (c & 2 ? (o.pct_apos_17 ?? 0) / 0.15 : 0) + (c & 4 ? Math.max(0, o.z_manual ?? 0) / 3 : 0);
}

// ---------------------------------------------------------------- Seções em atenção
TELAS.atencao = async (el) => {
  const q = new URLSearchParams(location.hash.split("?")[1] || "");
  el.innerHTML = `<section class="manchete"><h1 id="at-titulo">Seções em atenção ${esc(emRecorte())}</h1>
    <p>Cada linha é uma seção que cumpre pelo menos um critério. Clique para ver os números explicados, o horário dos votos e as outras seções da mesma escola.</p></section>
    <div class="carregando">Carregando as seções…</div>`;
  const ufs = E.uf ? [E.uf] : objetos(D.brasil.ufs).map((u) => u.uf);
  const arqs = await Promise.all(ufs.map((u) => D.uf(u)));
  const todas = arqs.flatMap((a) => secoesDe(a)).filter((s) => (crit(s.flags) || temConc(s)) && dentro(s));
  const temConcDados = todas.some((s) => s.flags_conc != null) || (D.brasil.meta.fontes_extras || []).includes("concentracao");
  const comConcIni = q.get("crit") === "conc" || localStorageGet("conc") === "1";
  const filtroCrit = new Set(q.get("crit") && q.get("crit") !== "conc" ? [q.get("crit")] : ["abst", "17h", "man", "conc"]);
  const tipos = [...new Set(todas.map((s) => s.tipo_local).filter(Boolean))].sort();
  const temIdade = todas.some((s) => s.perfil_explica != null);
  const temAnt = todas.some((s) => s.flags_ant != null);
  const anoAnt = D.brasil.meta.ano - 4;
  const temTransf = todas.some((s) => s.transf_recebidos != null);
  const temAgreg = todas.some((s) => s.n_agregadas != null);
  const P = pref();
  const ag = await agregadoRecorte();
  el.innerHTML = `<section class="manchete"><h1 id="at-titulo"></h1>
    <p>Cada linha é uma seção que cumpre pelo menos um critério. Clique para ver os números explicados, o horário dos votos e as outras seções da mesma escola.</p></section>
    <div class="filtros">
      ${Object.entries(CRIT).map(([k, c]) => `<label><input type="checkbox" data-crit="${k}" ${filtroCrit.has(k) ? "checked" : ""}> <span class="selo ${c.classe}">${c.curto}</span></label>`).join("")}
      ${temConcDados ? `<label title="Critério opcional: um candidato teve na seção uma fatia de votos muito acima da que teve no resto do município"><input type="checkbox" id="f-conc" ${comConcIni ? "checked" : ""}> <span class="selo ${CONC.classe}">${CONC.curto}</span> <span class="sub">(4º critério, opcional)</span></label>` : ""}
      <label><input type="checkbox" id="f-multi"> Só com 2 critérios ou mais</label>
      <input type="search" id="f-busca" placeholder="Buscar escola, bairro ou número da seção" aria-label="Buscar">
    </div>
    ${tipos.length || temIdade || temAnt || temTransf || temAgreg ? `<div class="filtros filtros-contexto">
      ${tipos.length ? `<label>Tipo de local <select id="f-tipo"><option value="">Todos</option>${tipos.map((t) => `<option>${esc(t)}</option>`).join("")}</select></label>` : ""}
      ${temIdade ? `<label><input type="checkbox" id="f-idade"> Esconder quando a idade dos eleitores explica o destaque</label>` : ""}
      ${temAnt ? `<label>Em ${anoAnt} <select id="f-ant"><option value="">tanto faz</option><option value="ja">já destoava (mesmo critério)</option><option value="novo">não destoava (novidade)</option></select></label>` : ""}
      ${temTransf ? `<label><input type="checkbox" id="f-transf"> Só seções que receberam eleitores transferidos</label>` : ""}
      ${temAgreg ? `<label><input type="checkbox" id="f-agreg"> Só seções com outras agregadas</label>` : ""}
    </div>` : ""}
    <div id="lista"></div>`;
  const filtrar = () => {
    const comConc = !!$("#f-conc")?.checked;
    localStorageSet("conc", comConc ? "1" : "0");
    const bits = $$("[data-crit]", el).filter((i) => i.checked).reduce((a, i) => a | CRIT[i.dataset.crit].bit, 0) | (comConc ? 8 : 0);
    const multi = $("#f-multi").checked;
    const termo = $("#f-busca").value.trim().toLowerCase();
    const tipo = $("#f-tipo")?.value || "";
    const semIdade = $("#f-idade")?.checked;
    const ant = $("#f-ant")?.value || "";
    const soTransf = $("#f-transf")?.checked, soAgreg = $("#f-agreg")?.checked;
    const ls = todas.filter((s) => {
      let c = critX(s, comConc);
      if (semIdade) c &= ~((explicaIdade(s, 1) ? 1 : 0) | (explicaIdade(s, 4) ? 4 : 0));
      if (!(c & bits)) return false;
      if (multi && ncrit(c) < 2) return false;
      if (tipo && s.tipo_local !== tipo) return false;
      if (ant) {
        const ca = s.tem_ant ? (s.flags_ant >> (3 * iNivel())) & 7 : null;
        if (ca == null) return false;
        const repetiu = (ca & crit(s.flags)) > 0;
        if ((ant === "ja") !== repetiu) return false;
      }
      if (soTransf && !(s.transf_recebidos > 0)) return false;
      if (soAgreg && !(s.n_agregadas > 0)) return false;
      if (termo && !`${s.escola} ${s.bairro} ${s.mun_nome} secao ${s.secao} zona ${s.zona} ${s.conc_nome ?? ""}`.toLowerCase().includes(termo)) return false;
      return true;
    });
    const mult = ls.filter((s) => ncrit(critX(s, comConc)) >= 2).length;
    $("#at-titulo").innerHTML = `<b>${plural(ls.length, "seção chama", "seções chamam")} atenção</b> ${esc(emRecorte())}${mult ? `, ${plural(mult, "delas", "delas")} em dois critérios ou mais` : ""}.`;
    tabela($("#lista"), {
      colunas: colunasSecao({ comMunicipio: !E.mun, comConc }), linhas: ls, ordem: { k: "crit", desc: true },
      aoClicar: abrirSecao, arquivo: `secoes_em_atencao_${E.uf || "BR"}${E.mun ? "_" + E.mun : ""}_${E.nivel}.csv`,
      vazio: "Nenhuma seção com esses filtros neste recorte. Tente o rigor amplo ou marque outros critérios.",
    });
  };
  void ag; void P;
  $$("input, select", el).forEach((i) => i.addEventListener(i.type === "search" ? "input" : "change", filtrar));
  filtrar();
};

// ---------------------------------------------------------------- Votos após 17h
TELAS.apos17 = async (el) => {
  const a = await agregadoRecorte();
  if (!a.votos_log) {
    el.innerHTML = `<div class="vazio">Os logs das urnas deste recorte (${esc(nomeRecorte())}) ainda não foram processados, então não há horário dos votos. Rode <code>python baixar_logs.py --ufs ${E.uf || "UF"}</code> e gere o site de novo.</div>`;
    return;
  }
  const P = pref();
  el.innerHTML = `<section class="manchete">
      <h1>${esc(Cap(emRecorte()))}, <b>${n(a.votos_apos_17)} votos</b> foram registrados depois das 17h, <b>${p(div(a.votos_apos_17, a.votos_log), 2)}</b> do total, em ${plural(a.com_17h, "seção", "seções")}.</h1>
      <p>Quem está na fila às 17h tem direito de votar, então algum voto depois desse horário é normal. Para dimensionar o problema, olhe a quantidade: das ${n(a.votos_apos_17)} pessoas, ${n(a[`${P}_v17`])} votaram em seções que chamam atenção por algum critério.</p>
    </section>
    ${numeros([
      { rotulo: "Votos depois das 17h", valor: n(a.votos_apos_17), sub: `${p(div(a.votos_apos_17, a.votos_log), 2)} de ${n(a.votos_log)} votos`, destaque: true },
      { rotulo: "Seções com algum voto após 17h", valor: n(a.com_17h), sub: `${p(div(a.com_17h, a.com_log))} das seções com log` },
      { rotulo: "Maior quantidade numa seção", valor: n(a.max_17h), sub: "votos depois das 17h" },
      { rotulo: "Seções em atenção por este critério", valor: n(a[`${P}_17h`]), sub: "muitos votos tarde e destoando da escola" },
    ])}
    <section class="bloco duas-colunas"><div><header style="margin-bottom:14px"><h2>Votos por hora</h2></header><div id="g17"></div></div>
      <div><header style="margin-bottom:14px"><h2>Seções por quantidade</h2></header><div id="fx17"></div></div></section>
    <section class="bloco"><header><h2>${E.mun ? "Por zona eleitoral" : E.uf ? "Por município" : "Por estado"}</h2><p>Ordenado pela quantidade de votos depois das 17h.</p></header><div id="r17"></div></section>
    <section class="bloco"><header><h2>As seções com mais votos depois das 17h</h2><p>A coluna "Comparado à escola" mostra quanto a votação dessa seção terminou mais tarde que a das outras seções do mesmo local. Perto de zero: a escola inteira atrasou, o que costuma ser fila.</p></header><div id="s17"></div></section>`;

  let perfil = D.brasil.perfil.votos;
  if (E.mun) perfil = (await D.mun(E.mun)).perfil;
  else if (E.uf) perfil = D.brasil.perfil_uf[E.uf]?.votos || perfil;
  $("#g17").innerHTML = graficoHoras(perfil);
  const fx = E.mun ? null : (E.uf ? D.brasil.faixas_17h_uf[E.uf] : D.brasil.faixas_17h);
  if (fx) tabela($("#fx17"), { colunas: [
    { k: "faixa", rot: "Votos após 17h na seção", semOrdem: true },
    { k: "secoes", rot: "Seções", num: true, semOrdem: true, html: (o) => n(o.secoes) },
    { k: "votos", rot: "Votos somados", num: true, semOrdem: true, html: (o) => `<span class="forte">${n(o.votos)}</span><span class="sub">${p(div(o.votos, a.votos_apos_17))} dos votos após 17h</span>` },
  ], linhas: [...fx].reverse() });
  else $("#fx17").innerHTML = `<p class="nota">Distribuição disponível para estados e para o Brasil.</p>`;

  // ranking dos filhos
  const max17 = (ls) => Math.max(1, ...ls.map((o) => o.votos_apos_17 || 0));
  const colR = (ls) => [
    { k: "votos_apos_17", rot: "Votos após 17h", num: true, html: (o) => `<span class="barrinha" style="width:${Math.round(60 * (o.votos_apos_17 || 0) / max17(ls))}px"></span><span class="forte">${n(o.votos_apos_17)}</span>` },
    { k: "p17", rot: "% dos votos", num: true, ord: (o) => div(o.votos_apos_17, o.votos_log), html: (o) => p(div(o.votos_apos_17, o.votos_log), 2), csv: (o) => div(o.votos_apos_17, o.votos_log) },
    { k: "com_17h", rot: "Seções com voto após 17h", num: true, html: (o) => `${n(o.com_17h)}<span class="sub">de ${n(o.secoes)}</span>` },
    { k: "max_17h", rot: "Maior numa seção", num: true, html: (o) => n(o.max_17h) },
    { k: "s17", rot: "Seções em atenção (17h)", num: true, ord: (o) => o[`${P}_17h`], html: (o) => n(o[`${P}_17h`]), csv: (o) => o[`${P}_17h`] },
  ];
  if (!E.uf) {
    const ls = objetos(D.brasil.ufs);
    tabela($("#r17"), { colunas: [{ k: "uf", rot: "Estado", html: (o) => `<span class="forte">${NOMES_UF[o.uf]}</span>` }, ...colR(ls)], linhas: ls, ordem: { k: "votos_apos_17", desc: true }, limite: 30, aoClicar: (o) => ir({ uf: o.uf }), arquivo: "votos_apos_17h_estados.csv" });
  } else if (!E.mun) {
    const ls = D.municipios.filter((m) => m.uf === E.uf);
    tabela($("#r17"), { colunas: [{ k: "mun_nome", rot: "Município", html: (o) => `<span class="forte">${esc(o.mun_nome)}</span>` }, ...colR(ls)], linhas: ls, ordem: { k: "votos_apos_17", desc: true }, aoClicar: (o) => ir({ mun: o.cd_municipio }), arquivo: `votos_apos_17h_${E.uf}.csv` });
  } else {
    const ls = objetos((await D.mun(E.mun)).zonas);
    tabela($("#r17"), { colunas: [{ k: "zona", rot: "Zona", html: (o) => `<span class="forte">Zona ${o.zona}</span>` }, ...colR(ls)], linhas: ls, ordem: { k: "votos_apos_17", desc: true }, aoClicar: (o) => ir({ zona: o.zona }), arquivo: `votos_apos_17h_${E.mun}.csv` });
  }

  // seções com mais votos após 17h
  let ss;
  if (E.zona) ss = secoesDe(await D.zona(E.mun, E.zona)).filter((s) => s.votos_apos_17 > 0);
  else if (E.mun) ss = secoesDe(await D.mun(E.mun), "top17");
  else if (E.uf) ss = secoesDe(await D.uf(E.uf), "top17");
  else ss = secoesDe(await D.apos17());
  tabela($("#s17"), {
    colunas: [
      { k: "secao", rot: "Seção", html: (o) => `<span class="forte">Seção ${o.secao}</span><span class="sub">Zona ${o.zona}</span>`, ord: (o) => o.zona * 1e5 + o.secao },
      { k: "zona", rot: "Zona", oculto: true },
      { k: "escola", rot: "Local de votação", html: (o) => `${esc(o.escola ?? "Local não informado")}<span class="sub">${esc([o.bairro, `${o.mun_nome} (${o.uf})`].filter(Boolean).join(", "))}</span>`, csv: (o) => `${o.escola ?? ""} - ${o.mun_nome} (${o.uf})` },
      { k: "votos_apos_17", rot: "Votos após 17h", num: true, html: (o) => `<span class="forte">${n(o.votos_apos_17)}</span><span class="sub">${p(o.pct_apos_17)} dos ${n(o.votos_log)} votos</span>` },
      { k: "ultimo_voto", rot: "Último voto", num: true, html: (o) => hora(o.ultimo_voto), csv: (o) => hora(o.ultimo_voto) },
      { k: "dif_local_min", rot: "Comparado à escola", num: true, html: (o) => (o.dif_local_min == null ? `<span class="sub">única seção</span>` : `${o.dif_local_min > 0 ? "+" : ""}${n(o.dif_local_min)} min`) },
      { k: "crit", rot: "Critérios", ord: (o) => ncrit(crit(o.flags)), html: (o) => (crit(o.flags) ? selos(crit(o.flags)) : `<span class="sub">nenhum</span>`), csv: (o) => ncrit(crit(o.flags)) },
    ],
    linhas: ss, ordem: { k: "votos_apos_17", desc: true }, aoClicar: abrirSecao,
    arquivo: `secoes_mais_votos_apos_17h_${E.uf || "BR"}.csv`,
  });
};

// ---------------------------------------------------------------- Plano de fiscalização
TELAS.plano = async (el) => {
  el.innerHTML = `<div class="carregando">Montando a lista de escolas…</div>`;
  const esc_ = objetos(await D.plano()).filter((e) => (!E.uf || e.uf === E.uf) && (!E.mun || e.cd_municipio === E.mun) && (!E.zona || e.zona === E.zona));
  const cont = { 3: 0, 2: 0, 1: 0 };
  let secs = 0, eleit = 0, fiscais = 0;
  for (const e of esc_) { cont[e.prioridade]++; secs += e.sinalizadas; eleit += e.aptos_sinalizadas; fiscais += Math.max(1, Math.ceil(e.sinalizadas / 4)); }
  const fiscaisAlta = esc_.filter((e) => e.prioridade === 3).reduce((a, e) => a + Math.max(1, Math.ceil(e.sinalizadas / 4)), 0);
  el.innerHTML = `
    <section class="manchete"><h1>Para cobrir as seções em atenção ${esc(emRecorte())}, é preciso estar presente em <b>${plural(esc_.length, "local de votação", "locais de votação")}</b>, ${n(cont[3])} de prioridade alta.</h1>
      <p>O fiscal é credenciado por partido ou federação e atua no local de votação, então a lista é por escola, não por seção. A prioridade sai dos dados do 1º turno e usa sempre o rigor padrão.</p></section>
    ${numeros([
      { rotulo: "Locais com prioridade alta", valor: n(cont[3]), destaque: true, sub: `${n(fiscaisAlta)} fiscais sugeridos` },
      { rotulo: "Prioridade média", valor: n(cont[2]) },
      { rotulo: "Prioridade baixa", valor: n(cont[1]) },
      { rotulo: "Seções a observar", valor: n(secs), sub: `${n(eleit)} eleitores aptos nelas` },
      { rotulo: "Fiscais sugeridos (todos)", valor: n(fiscais), sub: "1 por local, mais 1 a cada 4 seções" },
    ])}
    <section class="bloco"><header><h2>Locais de votação, por prioridade</h2>
      <p><strong>Alta</strong>: alguma seção cumpre 2 critérios ou mais, ou o local tem 3+ seções em atenção, ou há um desvio muito forte. <strong>Média</strong>: 2 seções em atenção, ou uma seção com sinal concreto no log da urna (urna parada e depois rajada de votos, liberações manuais em sequência). <strong>Baixa</strong>: uma seção em atenção.</p></header>
      <div class="filtros"><span class="seg" role="group" aria-label="Prioridade">${[["todas", "Todas"], ["3", "Alta"], ["2", "Média"], ["1", "Baixa"]].map(([v, r]) => `<button data-p="${v}" aria-pressed="${v === "todas"}">${r}</button>`).join("")}</span>
      <input type="search" id="p-busca" placeholder="Buscar escola, bairro ou município" aria-label="Buscar local">
      ${esc_.some((e) => e.rota) ? `<label><input type="checkbox" id="p-rota"> Só locais em rota</label>` : ""}
      <button id="imprimir">Imprimir lista</button><button id="fichas" class="primario">Fichas para imprimir</button></div>
      <p class="nota" id="p-nota-fichas" style="margin:-4px 0 12px">As fichas trazem uma página por local da lista filtrada (até 300), com as seções a observar, os números do 1º turno, o checklist e campos para o fiscal anotar.</p>
      <div id="plano-lista"></div></section>
    <section class="bloco"><header><h2>O que o fiscal deve observar</h2></header><div class="criterios">
      <article class="criterio cor-abst"><h3>Onde a abstenção foi muito baixa</h3><ul class="checklist">
        <li>Confira se cada eleitor se identifica pessoalmente, com documento oficial com foto ou título digital.</li>
        <li>Observe chegadas em grupo, transporte de eleitores e conversas na entrada da escola.</li>
        <li>No fim, compare o comparecimento do boletim de urna com o número de eleitores que você viu passar.</li></ul></article>
      <article class="criterio cor-17h"><h3>Onde muita gente votou depois das 17h</h3><ul class="checklist">
        <li>Às 17h, anote quantas pessoas estão na fila e confira se o mesário distribuiu as senhas aos que estavam nela.</li>
        <li>Anote o horário do último voto e quantos votos houve depois das 17h; peça registro em ata se algo destoar.</li>
        <li>Atenção a eleitores que chegam depois das 17h e votam mesmo assim.</li></ul></article>
      <article class="criterio cor-man"><h3>Onde muitos foram liberados pelo mesário</h3><ul class="checklist">
        <li>Quando a digital não for reconhecida, confira que o eleitor apresentou documento com foto antes da liberação.</li>
        <li>Se o leitor biométrico falhar com todos, peça o registro na ata e a troca ou limpeza do equipamento.</li>
        <li>Anote sequências de liberações manuais seguidas e o horário em que ocorreram.</li></ul></article>
    </div>
    <p class="nota" style="margin-top:14px">Suspeita de compra de votos ou outro crime eleitoral pode ser denunciada pelo aplicativo Pardal, da Justiça Eleitoral, ou ao Ministério Público Eleitoral. O fiscal deve pedir que qualquer ocorrência seja registrada na ata da mesa receptora.</p></section>`;

  let filtroP = "todas";
  const desenhar = () => {
    const termo = $("#p-busca").value.trim().toLowerCase();
    const soRota = $("#p-rota")?.checked;
    const ls = esc_.filter((e) => (filtroP === "todas" || e.prioridade === +filtroP) && (!soRota || e.rota) &&
      (!termo || `${e.nome_local} ${e.bairro} ${e.mun_nome}`.toLowerCase().includes(termo)));
    filtradas = ls;
    tabela($("#plano-lista"), {
      colunas: [
        { k: "prioridade", rot: "Prioridade", html: (o) => `<span class="prio prio-${o.prioridade}">${PRIO[o.prioridade]}</span>`, csv: (o) => PRIO[o.prioridade], ord: (o) => o.prioridade * 1e6 + o.multi * 1e4 + o.sinalizadas * 100 + o.forte },
        { k: "nome_local", rot: "Local de votação", html: (o) => `<span class="forte">${esc(o.nome_local ?? "Local não informado")}</span><span class="sub">${esc([o.endereco, o.bairro].filter(Boolean).join(", "))}</span><a class="sub" href="${mapsUrl({ ...o, escola: o.nome_local })}" target="_blank" rel="noopener">Abrir no mapa</a>`, csv: (o) => o.nome_local },
        { k: "endereco", rot: "Endereço", oculto: true, csv: (o) => [o.endereco, o.bairro, o.cep].filter(Boolean).join(" - ") },
        { k: "mun_nome", rot: "Município", html: (o) => `${esc(o.mun_nome)} (${o.uf})<span class="sub">Zona ${o.zona}</span>`, csv: (o) => `${o.mun_nome} (${o.uf})` },
        { k: "zona", rot: "Zona", oculto: true },
        { k: "secoes", rot: "Seções a observar", html: (o) => `<span class="forte">${esc(o.secoes.split(" ").join(", "))}</span><span class="sub">${o.sinalizadas} de ${o.secoes_total} seções do local</span>`, ord: (o) => o.sinalizadas, csv: (o) => o.secoes },
        { k: "motivos", rot: "Por quê", html: (o) => motivos(o), csv: (o) => motivosTexto(o), ord: (o) => o.multi },
        { k: "aptos_sinalizadas", rot: "Eleitores nessas seções", num: true, html: (o) => n(o.aptos_sinalizadas) },
        { k: "v17", rot: "Votos após 17h nelas", num: true, html: (o) => n(o.v17) },
        ...(esc_.some((e) => e.rota) ? [{ k: "rota", rot: "Rota", ord: (o) => (o.rota ? `${o.rota.padStart(12)}-${String(o.rota_ordem).padStart(3, "0")}` : null), html: (o) => (o.rota ? `<span class="forte">${esc(o.rota)}</span><span class="sub">${o.rota_ordem}ª parada${o.rota_ordem > 1 ? `, ${dec(o.rota_km, 1)} km da anterior` : ""}</span>` : `<span class="sub">—</span>`), csv: (o) => (o.rota ? `${o.rota} parada ${o.rota_ordem}` : "") }] : []),
      ],
      linhas: ls, ordem: { k: "prioridade", desc: true }, limite: 100,
      arquivo: `plano_fiscalizacao_${E.uf || "BR"}${E.mun ? "_" + E.mun : ""}.csv`,
      vazio: "Nenhum local de votação com seções em atenção neste recorte.",
    });
  };
  $$("[data-p]", el).forEach((b) => b.addEventListener("click", () => {
    filtroP = b.dataset.p;
    $$("[data-p]", el).forEach((x) => x.setAttribute("aria-pressed", x === b));
    desenhar();
  }));
  let filtradas = esc_;
  $("#p-busca").addEventListener("input", desenhar);
  $("#p-rota")?.addEventListener("change", desenhar);
  $("#imprimir").addEventListener("click", () => window.print());
  $("#fichas").addEventListener("click", () => imprimirFichas(filtradas.slice(0, 300)));
  desenhar();
};

// Ficha da escola para imprimir: uma página por local de votação
async function imprimirFichas(escolas) {
  if (!escolas.length) return;
  const botao = $("#fichas");
  botao.disabled = true;
  botao.textContent = "Montando as fichas…";
  try {
    const ufs = [...new Set(escolas.map((e) => e.uf))];
    const porUf = Object.fromEntries(await Promise.all(ufs.map(async (u) => [u, secoesDe(await D.uf(u))])));
    const m = D.brasil.meta;
    const campos = ["Pessoas na fila às 17h", "Horário do último voto", "Liberações manuais que viu", "Troca de urna (horário)"];
    const html = escolas.map((e) => {
      const nums = e.secoes.split(" ").map(Number);
      const ss = nums.map((sec) => porUf[e.uf].find((s) => s.cd_municipio === e.cd_municipio && s.zona === e.zona && s.secao === sec) || { secao: sec, zona: e.zona });
      return `<article class="ficha">
        <header><p class="ficha-topo">esteleição · Eleições ${m.ano} · ficha do fiscal · prioridade ${PRIO[e.prioridade].toLowerCase()}${e.rota ? ` · rota ${esc(e.rota)}, ${e.rota_ordem}ª parada` : ""}</p>
        <h2>${esc(e.nome_local ?? "Local de votação")}</h2>
        <p>${esc([e.endereco, e.bairro, e.cep ? `CEP ${e.cep}` : null].filter(Boolean).join(", "))}<br>${esc(e.mun_nome)} (${e.uf}), zona ${e.zona}. ${n(e.sinalizadas)} de ${n(e.secoes_total)} seções do local em atenção.</p></header>
        <h3>Seções a observar e números do ${m.turno}º turno</h3>
        <table><thead><tr><th>Seção</th><th>Por quê</th><th class="num">Aptos</th><th class="num">Compareceram</th><th class="num">Votos após 17h</th><th class="num">Último voto</th><th class="num">Liberados pelo mesário</th></tr></thead>
        <tbody>${ss.map((s) => `<tr><td><strong>${s.secao}</strong></td><td>${Object.values(CRIT).filter((k) => crit(s.flags ?? 0) & k.bit).map((k) => k.curto).join(", ") || "—"}</td>
          <td class="num">${n(s.aptos)}</td><td class="num">${s.aptos ? `${n(s.comparecimento)} (${p(1 - s.taxa_abstencao)})` : "—"}</td>
          <td class="num">${s.votos_log ? `${n(s.votos_apos_17)} (${p(s.pct_apos_17)})` : "—"}</td><td class="num">${hora(s.ultimo_voto)}</td>
          <td class="num">${s.votos_log ? `${n(s.votos_manual)} (${p(s.pct_manual_cadastrados)})` : "—"}</td></tr>`).join("")}</tbody></table>
        <h3>O que observar</h3>
        <ul class="checklist">
          <li>Cada eleitor se identifica pessoalmente, com documento oficial com foto ou título digital.</li>
          <li>Às 17h: quantas pessoas estão na fila e se o mesário distribuiu as senhas só a elas.</li>
          <li>Quando a digital falha: o eleitor apresenta documento com foto antes da liberação; anote sequências de liberações seguidas.</li>
          <li>Chegadas em grupo, transporte de eleitores, conversas na entrada da escola.</li>
          <li>Qualquer ocorrência: peça o registro na ata da mesa receptora.</li></ul>
        <h3>Anotações do fiscal</h3>
        <table class="anotar"><thead><tr><th>Seção</th>${campos.map((c) => `<th>${c}</th>`).join("")}<th>Observações</th></tr></thead>
        <tbody>${ss.map((s) => `<tr><td><strong>${s.secao}</strong></td>${campos.map(() => "<td></td>").join("")}<td></td></tr>`).join("")}</tbody></table>
        <p class="ficha-rodape">Fiscal: ______________________ Partido/federação: ______________ Assinatura: ______________</p>
        <p class="ficha-rodape">Destaque estatístico não é prova de irregularidade: a maioria dos casos tem explicação comum (fila, idade dos eleitores, leitor de digital com defeito).</p>
      </article>`;
    }).join("");
    let caixa = $("#fichas-impressao");
    if (!caixa) { caixa = document.createElement("div"); caixa.id = "fichas-impressao"; document.body.appendChild(caixa); }
    caixa.innerHTML = html;
    document.body.classList.add("imprimindo-fichas");
    const fim = () => { document.body.classList.remove("imprimindo-fichas"); removeEventListener("afterprint", fim); };
    addEventListener("afterprint", fim);
    window.print();
    setTimeout(fim, 1500);
  } finally {
    botao.disabled = false;
    botao.textContent = "Fichas para imprimir";
  }
}
function motivos(o) {
  const ps = [];
  if (o.n_abst) ps.push(`<span class="selo cor-abst">${o.n_abst}× abstenção baixa</span>`);
  if (o.n_17h) ps.push(`<span class="selo cor-17h">${o.n_17h}× após 17h</span>`);
  if (o.n_man) ps.push(`<span class="selo cor-man">${o.n_man}× liberação manual</span>`);
  const extra = [o.multi ? `${o.multi} seção com 2+ critérios` : "", o.com_sinal ? "sinal no log" : ""].filter(Boolean).join("; ");
  return `<span class="selos">${ps.join("")}</span>${extra ? `<span class="sub">${extra}</span>` : ""}`;
}
const motivosTexto = (o) => [o.n_abst && `${o.n_abst} abstenção baixa`, o.n_17h && `${o.n_17h} após 17h`, o.n_man && `${o.n_man} liberação manual`].filter(Boolean).join(", ");

// ---------------------------------------------------------------- Mais análises
// Cada item de docs/ideias-de-relatorios.md. Os dados vêm de extras.json (Brasil), dos arquivos
// das UFs e de municipios.json; quando uma fonte não foi baixada, a seção explica como obter.
const SECOES_MAIS = [
  ["materialidade", "Os votos em atenção mudariam o resultado?"],
  ["concentrado", "Voto concentrado num candidato"],
  ["perfil", "Idade dos eleitores"],
  ["cadastro", "Cadastro inflado"],
  ["repeticao", "Repetição entre eleições e turnos"],
  ["contexto", "Contexto do local de votação"],
  ["gastos", "Gastos de campanha"],
  ["operacional", "Para o dia da eleição"],
  ["sinais", "Outros sinais no log da urna"],
];
const semDados = (txt) => `<div class="vazio">${txt}</div>`;
const filtraRecorte = (ls) => ls.filter(dentro);

TELAS.mais = async (el) => {
  el.innerHTML = `<div class="carregando">Carregando as análises…</div>`;
  const X = await D.extras();
  const P = pref();
  el.innerHTML = `<section class="manchete"><h1>Mais análises ${esc(emRecorte())}</h1>
      <p>Outras formas de olhar os mesmos dados e dados de outras fontes (votação por candidato, perfil do eleitorado, IBGE, prestação de contas). Servem para dimensionar e dar contexto aos destaques; nenhuma delas, sozinha, indica irregularidade.</p></section>
    <nav class="indice" aria-label="Análises nesta página">${SECOES_MAIS.map(([id, t], i) => `<a href="#mais-${id}" data-ancora="${id}">${String.fromCharCode(97 + i)}) ${t}</a>`).join("")}</nav>
    ${SECOES_MAIS.map(([id, t], i) => `<section class="bloco" id="mais-${id}"><header><h2>${String.fromCharCode(97 + i)}) ${t}</h2><p id="mais-${id}-nota"></p></header><div id="mais-${id}-corpo"></div></section>`).join("")}`;
  $$(".indice a", el).forEach((a) => a.addEventListener("click", (ev) => { ev.preventDefault(); $(`#mais-${a.dataset.ancora}`).scrollIntoView({ behavior: "smooth" }); }));
  const secoes = E.uf ? secoesDe(await D.uf(E.uf)).filter(dentro) : null;
  const L = E.uf ? await D.extrasUf(E.uf) : X;  // listas completas do estado ou as mais fortes do Brasil
  const partes = { materialidade: maisMaterialidade, concentrado: maisConcentrado, perfil: maisPerfil, cadastro: maisCadastro,
    repeticao: maisRepeticao, contexto: maisContexto, gastos: maisGastos, operacional: maisOperacional, sinais: maisSinais };
  for (const [id] of SECOES_MAIS) {
    try { await partes[id]($(`#mais-${id}-corpo`), $(`#mais-${id}-nota`), X, P, secoes, L); }
    catch (e) { console.error(e); $(`#mais-${id}-corpo`).innerHTML = semDados(`Não foi possível montar esta parte (${esc(e.message)}).`); }
  }
};

// lista de seções de uma análise (Brasil: extras.json; estado: extras/<UF>.json), no recorte atual
function listaSecoes(L, chave, filtro) {
  return L[chave] ? filtraRecorte(secoesDe(L[chave])).filter(filtro) : [];
}
const colSecao = { k: "secao", rot: "Seção", html: (o) => `<span class="forte">Seção ${o.secao}</span><span class="sub">Zona ${o.zona}</span>`, ord: (o) => o.zona * 1e5 + o.secao, csv: (o) => o.secao };
const colLocal = { k: "escola", rot: "Local de votação", html: (o) => `${esc(o.escola ?? "Local não informado")}<span class="sub">${esc([o.bairro, `${o.mun_nome} (${o.uf})`].filter(Boolean).join(", "))}</span>`, csv: (o) => `${o.escola ?? ""} - ${o.mun_nome} (${o.uf})` };
const colZona = { k: "zona", rot: "Zona", oculto: true };
const colCrit = { k: "crit", rot: "Critérios", ord: (o) => ncrit(critX(o, true)), html: (o) => (critX(o, true) ? selos(critX(o, true)) : `<span class="sub">nenhum</span>`), csv: (o) => ncrit(critX(o, true)) };

// a) materialidade
async function maisMaterialidade(el, nota, X, P) {
  const linhas = (X.materialidade || []).filter((r) => r.escopo === "BR" || !E.uf || r.escopo === E.uf);
  if (!linhas.length) { el.innerHTML = semDados("Falta a votação por seção. Rode <code>python baixar_votacao.py</code> e gere o site de novo."); return; }
  nota.innerHTML = `Para cada disputa, a diferença entre o 1º e o 2º colocado ao lado dos votos que estão nas seções em atenção (rigor ${{ rigoroso: "rigoroso", padrao: "padrão", amplo: "amplo" }[E.nivel]}). <strong>Comparecimento acima do esperado</strong> é quantos eleitores a mais votaram nessas seções do que o padrão do município faria esperar. Os três números podem contar a mesma pessoa (um voto depois das 17h liberado pelo mesário entra em dois), então a soma é um teto.${E.mun ? " A tabela mostra o estado inteiro." : ""}`;
  const margem = (r) => (r.vagas === 2 && r.dif_ultima_vaga != null ? r.dif_ultima_vaga : r.dif_1_2);
  const soma = (r) => r[P].v17 + r[P].manual + r[P].excesso;
  const frase = (r) => {
    const a = r[P];
    const m = margem(r);
    let t = `Nas seções em atenção houve ${plural(a.v17, "voto", "votos")} depois das 17h; a diferença para o ${r.vagas === 2 ? "3º colocado (última vaga)" : "2º colocado"} foi ${plural(m, "voto", "votos")}.`;
    if (!a.secoes) return `Nenhuma seção em atenção neste recorte; a diferença foi ${plural(m, "voto", "votos")}.`;
    t += soma(r) >= m
      ? ` <strong>Somando votos após 17h, liberações manuais e comparecimento acima do esperado (${n(soma(r))}), o total passa da diferença:</strong> numa disputa tão apertada, essas seções merecem prioridade na fiscalização.`
      : ` Mesmo somando tudo (${n(soma(r))}), seria preciso ${vezes(m / Math.max(soma(r), 1))} isso para chegar à diferença.`;
    return t;
  };
  tabela(el, {
    colunas: [
      { k: "disputa", rot: "Disputa", html: (o) => `<span class="forte">${o.rotulo}</span><span class="sub">${o.escopo === "BR" ? "Brasil" : NOMES_UF[o.escopo]}${o.vagas === 2 ? ", 2 vagas" : ""}</span>`, ord: (o) => o.cargo * 100 + (o.escopo === "BR" ? 0 : 1), csv: (o) => `${o.rotulo} ${o.escopo}` },
      { k: "cands", rot: "Mais votados", semOrdem: true, classe: "cands", html: (o) => o.candidatos.slice(0, o.vagas + 1).map((c, i) => `<span class="${i ? "sub" : "forte"}">${i + 1}º ${esc(nomeCand(c.nome))}: ${n(c.votos)} (${p(div(c.votos, o.validos))})</span>`).join(""), csv: (o) => o.candidatos.slice(0, o.vagas + 1).map((c) => `${c.nome} ${c.votos}`).join(" | ") },
      { k: "margem", rot: "Diferença", num: true, ord: margem, html: (o) => `<span class="forte">${n(margem(o))}</span><span class="sub">${p(div(margem(o), o.validos), 2)} dos válidos</span>`, csv: margem },
      { k: "atencao", rot: "Nas seções em atenção", ord: soma, html: (o) => `<span class="forte">${plural(o[P].secoes, "seção", "seções")}</span><span class="sub">${n(o[P].v17)} votos após 17h</span><span class="sub">${n(o[P].manual)} liberações manuais</span><span class="sub">${n(o[P].excesso)} acima do comparecimento esperado</span>`, csv: (o) => o[P].secoes },
      { k: "v17", rot: "Votos após 17h nelas", oculto: true, csv: (o) => o[P].v17 },
      { k: "man", rot: "Liberações manuais nelas", oculto: true, csv: (o) => o[P].manual },
      { k: "exc", rot: "Comparecimento acima do esperado", oculto: true, csv: (o) => o[P].excesso },
      { k: "frase", rot: "Em uma frase", classe: "frase", ord: (o) => margem(o) / Math.max(soma(o), 1), html: frase, csv: (o) => frase(o).replace(/<[^>]+>/g, "") },
    ],
    linhas: linhas, ordem: { k: "frase", desc: false }, limite: 60, arquivo: `materialidade_${E.uf || "BR"}_${E.nivel}.csv`,
  });
}

// b) voto concentrado
async function maisConcentrado(el, nota, X, P, secoes, L) {
  const R = X.concentracao;
  if (!R) { el.innerHTML = semDados("Falta a votação por seção. Rode <code>python baixar_votacao.py</code> e gere o site de novo."); return; }
  const lim = R.limites[E.nivel];
  nota.innerHTML = `Para cada seção e cada candidato a deputado, comparamos a fatia dos votos válidos que ele teve na seção com a fatia que teve no resto do município (a mesma conta da abstenção). Entra quando o candidato tem pelo menos ${p(lim.fatia, 0)} dos votos válidos da seção e ${n(lim.votos)} votos, muito acima do resto do município (intensidade ${dec(lim.z, 0)} ou mais). <strong>Reduto eleitoral é comum</strong>: o bairro do candidato, a comunidade onde ele trabalha. O sinal pesa quando aparece junto com <strong>abstenção muito baixa</strong> e <strong>poucos brancos e nulos</strong>, o padrão de quem leva eleitores para votar num nome só.`;
  const ls = listaSecoes(L, "lista_conc", temConc);
  const r = R[E.nivel];
  const loc = E.uf ? {
    secoes: ls.length, com_abst: ls.filter((s) => crit(s.flags) & 1).length,
    com_bn: ls.filter((s) => s.conc_z_bn <= R.z_bn_baixo).length,
    tudo: ls.filter((s) => (crit(s.flags) & 1) && s.conc_z_bn <= R.z_bn_baixo).length,
    votos: ls.reduce((a, s) => a + (s.conc_votos || 0), 0) } : r;
  el.innerHTML = numeros([
    { rotulo: "Seções com voto muito concentrado", valor: n(loc.secoes), sub: `${n(loc.votos)} votos para o candidato destacado`, destaque: true },
    { rotulo: "Também com abstenção muito baixa", valor: n(loc.com_abst) },
    { rotulo: "Também com poucos brancos e nulos", valor: n(loc.com_bn) },
    { rotulo: "As três coisas juntas", valor: n(loc.tudo), destaque: loc.tudo > 0 },
  ]) + `<p class="nota" style="margin:12px 0">Na aba <a href="${link({ tela: "atencao" })}${link({ tela: "atencao" }).includes("?") ? "&" : "?"}crit=conc">Seções em atenção</a>, marque "Voto concentrado" para somar este critério aos outros três.${E.uf ? "" : " A lista abaixo mostra as 300 seções mais fortes do país; escolha um estado para ver todas."}</p><div id="t-conc"></div>`;
  tabela($("#t-conc"), {
    colunas: [colSecao, colZona, colLocal,
      { k: "conc_nome", rot: "Candidato", html: (o) => `<span class="forte">${esc(nomeCand(o.conc_nome))}</span><span class="sub">${esc(CARGOS_CONC[o.conc_cargo] ?? "")}</span>`, csv: (o) => o.conc_nome },
      { k: "conc_votos", rot: "Votos dele na seção", num: true, html: (o) => `<span class="forte">${n(o.conc_votos)}</span><span class="sub">${p(o.conc_fatia)} de ${n(o.conc_validos)} válidos</span>` },
      { k: "conc_esperada", rot: "No resto do município", num: true, html: (o) => `${p(o.conc_esperada)}<span class="sub">seriam ~${n(o.conc_validos * o.conc_esperada)} votos</span>`, csv: (o) => o.conc_esperada },
      { k: "conc_pct_bn", rot: "Brancos e nulos", num: true, html: (o) => (o.conc_pct_bn == null ? "—" : `${p(o.conc_pct_bn)}<span class="sub">${o.conc_z_bn <= R.z_bn_baixo ? "<b>muito abaixo</b> de " : "município "}${p(o.conc_esp_bn)}</span>`), csv: (o) => o.conc_pct_bn },
      { k: "abst", rot: "Abstenção", num: true, ord: (o) => o.taxa_abstencao, html: (o) => `${p(o.taxa_abstencao)}<span class="sub">${crit(o.flags) & 1 ? "<b>muito baixa</b>; " : ""}esperado ${p(o.taxa_esperada)}</span>`, csv: (o) => o.taxa_abstencao },
      colCrit],
    linhas: ls, ordem: { k: "crit", desc: true }, aoClicar: abrirSecao, arquivo: `voto_concentrado_${E.uf || "BR"}_${E.nivel}.csv`,
    vazio: "Nenhuma seção com voto muito concentrado neste recorte e rigor.",
  });
}

// c) perfil do eleitorado
async function maisPerfil(el, nota, X, P, secoes, L) {
  const R = X.perfil;
  if (!R) { el.innerHTML = semDados("Falta o perfil do eleitorado por seção. Rode <code>python baixar_perfil.py</code> e gere o site de novo."); return; }
  const a = await agregadoRecorte();
  const ca = R.coef_abst || {}, cm = R.coef_manual || {};
  nota.innerHTML = `Quem tem 70 anos ou mais e quem tem 16 ou 17 não é obrigado a votar, e falta mais. Idosos também têm mais falha de digital. Usamos a idade dos eleitores de cada seção para recalcular o esperado e separar o que a idade explica do que continua estranho.`;
  const expl = (k) => `${n(R[`${E.nivel}_${k}_explica`])} de ${n(R[`${E.nivel}_${k}`])}`;
  const ls = listaSecoes(L, "lista_perfil", (s) => explicaIdade(s, 1) || explicaIdade(s, 4));
  el.innerHTML = numeros([
    { rotulo: "Eleitores com 70 anos ou mais", valor: n(a.el_70_mais ?? R.el_70_mais), sub: `${p(div(a.el_70_mais ?? R.el_70_mais, a.eleitores_perfil ?? R.eleitores))} do eleitorado` },
    { rotulo: "Eleitores com 16 ou 17 anos", valor: n(a.el_16_17 ?? R.el_16_17), sub: `${p(div(a.el_16_17 ?? R.el_16_17, a.eleitores_perfil ?? R.eleitores))} do eleitorado` },
    ...(R.el_biometria != null ? [{ rotulo: "Com biometria cadastrada", valor: n(a.el_biometria ?? R.el_biometria), sub: p(div(a.el_biometria ?? R.el_biometria, a.eleitores_perfil ?? R.eleitores)) }] : []),
    { rotulo: "Abstenção baixa explicada pela idade", valor: expl("abst"), sub: "seções do Brasil, no rigor atual", destaque: true },
    ...(R[`${E.nivel}_man`] != null && cm.pct_70 != null ? [{ rotulo: "Liberação manual explicada pela idade", valor: expl("man"), sub: "seções do Brasil, no rigor atual" }] : []),
  ]) + `<p class="nota" style="margin:12px 0">Nos dados, cada 10 pontos percentuais a mais de eleitores com 70+ (em relação ao município) aumentam a abstenção esperada em ${dec((ca.pct_70 ?? 0) * 10, 1)} pontos${ca.pct_16_17 != null ? `; cada 10 pontos a mais de eleitores de 16–17 anos, em ${dec(ca.pct_16_17 * 10, 1)} pontos` : ""}.${cm.pct_70 != null ? ` Na liberação manual, cada 10 pontos a mais de idosos somam ${dec(cm.pct_70 * 10, 1)} pontos ao esperado.` : ""} Abaixo, as seções em atenção cujo destaque a idade explica. Na aba Seções em atenção dá para escondê-las.</p><div id="t-perfil"></div>`;
  tabela($("#t-perfil"), {
    colunas: [colSecao, colZona, colLocal,
      { k: "pct_70", rot: "Eleitores 70+", num: true, html: (o) => `${p(o.pct_70)}<span class="sub">${n(o.aptos * o.pct_70)} pessoas</span>` },
      { k: "taxa_abstencao", rot: "Abstenção", num: true, html: (o) => `${p(o.taxa_abstencao)}<span class="sub">esperado ${p(o.taxa_esperada)}</span>` },
      { k: "explica", rot: "A idade explica", ord: (o) => (explicaIdade(o, 1) ? 2 : 0) + (explicaIdade(o, 4) ? 1 : 0), html: (o) => [explicaIdade(o, 1) && "abstenção baixa", explicaIdade(o, 4) && "liberação manual"].filter(Boolean).join(" e "), csv: (o) => [explicaIdade(o, 1) && "abstenção", explicaIdade(o, 4) && "manual"].filter(Boolean).join(" e ") },
      colCrit],
    linhas: ls, ordem: { k: "pct_70", desc: false }, aoClicar: abrirSecao, arquivo: `idade_explica_${E.uf || "BR"}_${E.nivel}.csv`,
    vazio: "Nenhuma seção em atenção explicada pela idade neste recorte.",
  });
}

// d) cadastro inflado
async function maisCadastro(el, nota, X, P) {
  const R = X.cadastro || {};
  const ms = D.municipios.filter((m) => (!E.uf || m.uf === E.uf) && (!E.mun || m.cd_municipio === E.mun));
  const temPop = ms.some((m) => m.razao_pop != null), temCresc = ms.some((m) => m.cresc_eleitorado != null);
  if (!temPop && !temCresc) { el.innerHTML = semDados("Falta a população do IBGE (<code>python baixar_ibge.py</code>) e o eleitorado da eleição anterior (<code>python baixar_dados.py --ano 2022</code>)."); return; }
  const anoAnt = R.crescimento?.ano_ant ?? D.brasil.meta.ano - 4;
  nota.innerHTML = `${temPop ? "Eleitores aptos divididos pela população com 16 anos ou mais (Censo 2022 do IBGE). Acima de 1, o município tem mais eleitores do que moradores em idade de votar: em geral é gente que se mudou sem transferir o título ou que morreu e ainda não saiu do cadastro, mas também é o que se veria com transferências de título em massa. " : ""}${temCresc ? `O crescimento compara os eleitores aptos com os de ${anoAnt}.` : ""} Os dois aparecem no Mapa.`;
  const acima = ms.filter((m) => m.razao_pop > 1);
  el.innerHTML = numeros([
    ...(temPop ? [{ rotulo: "Municípios com mais eleitores que população 16+", valor: n(acima.length), sub: `${n(acima.reduce((a, m) => a + m.aptos - m.pop_16_mais, 0))} eleitores além da população`, destaque: true },
      { rotulo: "Eleitores ÷ população 16+ (recorte)", valor: dec(div(ms.reduce((a, m) => a + m.aptos, 0), ms.reduce((a, m) => a + (m.pop_16_mais || 0), 0))) }] : []),
    ...(temCresc ? [{ rotulo: `Crescimento do eleitorado desde ${anoAnt}`, valor: p(div(ms.reduce((a, m) => a + m.aptos, 0), ms.reduce((a, m) => a + (m.aptos_mun_ant || 0), 0)) - 1), sub: `${n(ms.reduce((a, m) => a + m.aptos - (m.aptos_mun_ant || m.aptos), 0))} eleitores a mais` },
      { rotulo: "Municípios que cresceram mais de 20%", valor: n(ms.filter((m) => m.cresc_eleitorado > 0.2).length) }] : []),
  ]) + `<div id="t-cad" style="margin-top:14px"></div>`;
  tabela($("#t-cad"), {
    colunas: [
      { k: "mun_nome", rot: "Município", html: (o) => `<span class="forte">${esc(o.mun_nome)}</span><span class="sub">${o.uf}</span>`, csv: (o) => `${o.mun_nome} (${o.uf})` },
      { k: "aptos", rot: "Eleitores aptos", num: true, html: (o) => n(o.aptos) },
      ...(temPop ? [{ k: "pop_16_mais", rot: "População 16+", num: true, html: (o) => n(o.pop_16_mais) },
        { k: "razao_pop", rot: "Eleitores ÷ população", num: true, html: (o) => `<span class="${o.razao_pop > 1 ? "forte" : ""}">${dec(o.razao_pop)}</span><span class="sub">${o.razao_pop > 1 ? `${n(o.aptos - o.pop_16_mais)} a mais` : ""}</span>` }] : []),
      ...(temCresc ? [{ k: "cresc_eleitorado", rot: `Desde ${anoAnt}`, num: true, html: (o) => (o.cresc_eleitorado == null ? "—" : `${o.cresc_eleitorado > 0 ? "+" : ""}${p(o.cresc_eleitorado)}<span class="sub">${o.aptos - o.aptos_mun_ant >= 0 ? "+" : ""}${n(o.aptos - o.aptos_mun_ant)} eleitores</span>`) }] : []),
      { k: "sec", rot: "Seções em atenção", num: true, ord: (o) => o[`${P}_sec`], html: (o) => n(o[`${P}_sec`]), csv: (o) => o[`${P}_sec`] },
    ],
    linhas: ms, ordem: { k: temPop ? "razao_pop" : "cresc_eleitorado", desc: true }, limite: 30,
    aoClicar: (o) => ir({ tela: "panorama", uf: o.uf, mun: o.cd_municipio, zona: null }), arquivo: `cadastro_${E.uf || "BR"}.csv`,
  });
}

// e) repetição entre eleições e turnos
async function maisRepeticao(el, nota, X, P, secoes, L) {
  const A = X.anterior, T = X.turnos, R = X.repeticao;
  if (!A && !T) { el.innerHTML = semDados(`Falta a eleição anterior (<code>python baixar_dados.py --ano ${D.brasil.meta.ano - 4}</code>, e se der os logs com <code>python baixar_logs.py --ano ${D.brasil.meta.ano - 4}</code>). Depois de 25/10, o 2º turno: <code>python baixar_dados.py --turno 2</code>.`); return; }
  let html = "";
  if (A && R) {
    nota.innerHTML = `Uma seção que já destoava em ${A.ano} quase sempre tem causa estrutural (perfil do local). Se é novidade, a prioridade sobe. A comparação é pela mesma seção (mesmo município, zona e número): ${n(A.secoes_casadas)} de ${n(A.secoes)} seções casaram.${A.com_logs ? "" : ` Sem os logs de ${A.ano}, só a abstenção pode se repetir.`}`;
    let linhas;
    if (secoes) {
      linhas = [["abst", 1], ["17h", 2], ["man", 4], ["sec", 7]].map(([k, b]) => {
        const em = secoes.filter((s) => crit(s.flags) & b);
        const cas = em.filter((s) => s.tem_ant);
        const ja = cas.filter((s) => ((s.flags_ant >> (3 * iNivel())) & 7) & b);
        return { k, v: [em.length, cas.length, ja.length] };
      });
    } else linhas = ["abst", "17h", "man", "sec"].map((k) => ({ k, v: R[`${E.nivel}_${k}`] }));
    const rot = { abst: "Abstenção baixa", "17h": "Após 17h", man: "Liberação manual", sec: "Qualquer critério" };
    html += `<div id="t-rep"></div>`;
    el.innerHTML = html;
    tabela($("#t-rep"), {
      colunas: [
        { k: "k", rot: "Critério", semOrdem: true, html: (o) => `<span class="forte">${rot[o.k]}</span>` },
        { k: "em", rot: "Seções em atenção", num: true, semOrdem: true, html: (o) => n(o.v[0]) },
        { k: "cas", rot: `Existiam em ${A.ano}`, num: true, semOrdem: true, html: (o) => n(o.v[1]) },
        { k: "ja", rot: `Já destoavam em ${A.ano}`, num: true, semOrdem: true, html: (o) => `<span class="forte">${n(o.v[2])}</span><span class="sub">${p(div(o.v[2], o.v[1]))} das que existiam</span>` },
        { k: "novo", rot: "Novidade", num: true, semOrdem: true, html: (o) => `${n(o.v[1] - o.v[2])}<span class="sub">não destoavam</span>` },
      ], linhas,
    });
    el.insertAdjacentHTML("beforeend", `<p class="nota" style="margin-top:10px">Para listar só as novidades, use o filtro "Em ${A.ano}" na aba <a href="${link({ tela: "atencao" })}">Seções em atenção</a>.</p>`);
  } else el.innerHTML = "";
  if (T) {
    const ls = listaSecoes(L, "lista_turnos", (s) => (s.z_comp_turnos ?? 0) >= 3);
    el.insertAdjacentHTML("beforeend", `<h3 style="margin:24px 0 8px">1º e 2º turno</h3><p class="nota">Compareceram ${n(T.comp_t1)} eleitores no 1º turno e ${n(T.comp_t2)} no 2º. ${plural(T.secoes_sobe, "seção teve", "seções tiveram")} o comparecimento subindo pelo menos ${p(T.dif, 0)} e muito mais que o resto do município${T.apos17_so_t2 != null ? `; ${plural(T.apos17_so_t2, "seção teve", "seções tiveram")} 10 ou mais votos depois das 17h só no 2º turno` : ""}. Útil também para medir o efeito da presença de fiscais.</p><div id="t-turnos" style="margin-top:12px"></div>`);
    tabela($("#t-turnos"), {
      colunas: [colSecao, colZona, colLocal,
        { k: "taxa_comp_t1", rot: "Comparecimento 1º turno", num: true, html: (o) => p(o.taxa_comp_t1) },
        { k: "taxa_comp_t2", rot: "2º turno", num: true, html: (o) => p(o.taxa_comp_t2) },
        { k: "dif_comp_turnos", rot: "Mudança", num: true, html: (o) => `<span class="forte">${o.dif_comp_turnos >= 0 ? "+" : ""}${dec(o.dif_comp_turnos * 100, 1)} pontos</span><span class="sub">${n(o.aptos * o.dif_comp_turnos)} eleitores</span>` },
        colCrit],
      linhas: ls, ordem: { k: "dif_comp_turnos", desc: true }, aoClicar: abrirSecao, arquivo: `turnos_${E.uf || "BR"}.csv`,
      vazio: "Nenhuma seção com mudança forte de comparecimento neste recorte.",
    });
  }
}

// f) contexto do local
async function maisContexto(el, nota, X, P, secoes, L) {
  const C = X.contexto || {};
  const tl = objetos(X.tipos_local);
  if (!tl.length && !C.transferencia && !C.agregadas) { el.innerHTML = semDados("Falta o cadastro de locais (<code>python baixar_locais.py</code>) e a transferência temporária (<code>python baixar_transferencia.py</code>)."); return; }
  nota.innerHTML = "Zona rural, aldeia, unidade prisional e seções que receberam outras (agregadas) ou eleitores em trânsito têm comparecimento e horário diferentes das vizinhas. Isso explica parte dos destaques. Na aba Seções em atenção dá para filtrar por tipo de local.";
  el.innerHTML = numeros([
    ...(C.agregadas ? [{ rotulo: "Seções que receberam agregadas", valor: n(C.agregadas.secoes_principais), sub: `${n(C.agregadas.secoes_agregadas)} seções agregadas nelas` }] : []),
    ...(C.transferencia ? [{ rotulo: "Seções com eleitores transferidos", valor: n(C.transferencia.secoes), sub: `${n(C.transferencia.recebidos)} eleitores recebidos` }] : []),
  ]) + `<div id="t-tipos" style="margin-top:14px"></div><div id="t-transf" style="margin-top:20px"></div>`;
  if (tl.length && !E.uf) tabela($("#t-tipos"), {
    colunas: [{ k: "tipo", rot: "Tipo de local", html: (o) => `<span class="forte">${esc(o.tipo)}</span>` },
      { k: "secoes", rot: "Seções", num: true, html: (o) => n(o.secoes) },
      { k: "aptos", rot: "Eleitores aptos", num: true, html: (o) => n(o.aptos) },
      { k: "sec", rot: "Em atenção", num: true, ord: (o) => o[`${P}_sec`], html: (o) => `<span class="forte">${n(o[`${P}_sec`])}</span><span class="sub">${p(div(o[`${P}_sec`], o.secoes))} das seções</span>` }],
    linhas: tl, ordem: { k: "secoes", desc: true }, limite: 20,
  });
  else if (tl.length) $("#t-tipos").innerHTML = `<p class="nota">A contagem por tipo de local está na visão do Brasil.</p>`;
  if (C.transferencia) {
    const ls = listaSecoes(L, "lista_transf", (s) => (s.transf_recebidos ?? 0) >= 20);
    $("#t-transf").innerHTML = `<h3 style="margin-bottom:8px">Seções que mais receberam eleitores transferidos</h3><div id="t-transf-l"></div>`;
    tabela($("#t-transf-l"), {
      colunas: [colSecao, colZona, colLocal,
        { k: "transf_recebidos", rot: "Transferidos", num: true, html: (o) => `<span class="forte">${n(o.transf_recebidos)}</span><span class="sub">${p(div(o.transf_recebidos, o.aptos))} dos aptos</span>` },
        { k: "taxa_abstencao", rot: "Abstenção", num: true, html: (o) => `${p(o.taxa_abstencao)}<span class="sub">esperado ${p(o.taxa_esperada)}</span>` },
        colCrit],
      linhas: ls, ordem: { k: "transf_recebidos", desc: true }, aoClicar: abrirSecao, limite: 30, arquivo: `transferencia_${E.uf || "BR"}.csv`,
      vazio: "Nenhuma seção com 20+ eleitores transferidos neste recorte.",
    });
  }
}

// g) gastos de campanha
async function maisGastos(el, nota, X, P) {
  const R = X.gastos || {};
  const ms = D.municipios.filter((m) => (!E.uf || m.uf === E.uf) && (!E.mun || m.cd_municipio === E.mun) && m.gasto_total != null);
  if (!ms.length) { el.innerHTML = semDados("Falta a prestação de contas. Rode <code>python baixar_gastos.py</code> e gere o site de novo."); return; }
  nota.innerHTML = `Despesas contratadas pelos candidatos com transporte, combustível, locação de veículos e pessoal (inclui cabos eleitorais e mobilização de rua), pelo município do fornecedor, divididas pelos eleitores aptos. Campanha gasta em todo lugar; o que chama atenção é gasto por eleitor muitas vezes acima do resto do estado <strong>num município que também tem seções em atenção</strong>.${R.sem_municipio ? ` ${reais(R.sem_municipio)} em despesas sem município identificado ficaram de fora.` : ""}`;
  const tot = ms.reduce((a, m) => a + m.gasto_total, 0);
  const alto = ms.filter((m) => m.gasto_vs_uf >= 3 && m[`${P}_sec`] > 0);
  el.innerHTML = numeros([
    { rotulo: "Gasto nas 4 categorias", valor: reais(tot), sub: `${reais(div(tot, ms.reduce((a, m) => a + m.aptos, 0)))} por eleitor` },
    ...Object.entries({ transporte: "Transporte", combustivel: "Combustível", veiculos: "Locação de veículos", pessoal: "Pessoal" }).map(([k, r]) => ({ rotulo: r, valor: reais(ms.reduce((a, m) => a + (m[`gasto_${k}`] || 0), 0)) })),
    { rotulo: "Gasto 3× acima da UF e com seções em atenção", valor: n(alto.length), sub: "municípios", destaque: alto.length > 0 },
  ]) + `<div id="t-gastos" style="margin-top:14px"></div>`;
  tabela($("#t-gastos"), {
    colunas: [
      { k: "mun_nome", rot: "Município", html: (o) => `<span class="forte">${esc(o.mun_nome)}</span><span class="sub">${o.uf}</span>`, csv: (o) => `${o.mun_nome} (${o.uf})` },
      { k: "gasto_total", rot: "Gasto", num: true, html: (o) => reais(o.gasto_total) },
      { k: "gasto_eleitor", rot: "Por eleitor", num: true, html: (o) => `<span class="forte">${reais(o.gasto_eleitor)}</span><span class="sub">${n(o.aptos)} eleitores</span>` },
      { k: "gasto_vs_uf", rot: "Comparado à UF", num: true, html: (o) => `${vezes(o.gasto_vs_uf)}<span class="sub">a mediana dos municípios</span>` },
      { k: "gasto_transporte", rot: "Transporte e combustível", num: true, ord: (o) => (o.gasto_transporte || 0) + (o.gasto_combustivel || 0) + (o.gasto_veiculos || 0), html: (o) => reais((o.gasto_transporte || 0) + (o.gasto_combustivel || 0) + (o.gasto_veiculos || 0)) },
      { k: "gasto_pessoal", rot: "Pessoal", num: true, html: (o) => reais(o.gasto_pessoal) },
      { k: "sec", rot: "Seções em atenção", num: true, ord: (o) => o[`${P}_sec`], html: (o) => `<span class="${o[`${P}_sec`] ? "forte" : ""}">${n(o[`${P}_sec`])}</span>`, csv: (o) => o[`${P}_sec`] },
    ],
    linhas: ms, ordem: { k: "gasto_vs_uf", desc: true }, limite: 30,
    aoClicar: (o) => ir({ tela: "panorama", uf: o.uf, mun: o.cd_municipio, zona: null }), arquivo: `gastos_${E.uf || "BR"}.csv`,
  });
}

// h) operacional
async function maisOperacional(el, nota, X) {
  const R = X.rotas || {};
  const es = objetos(await D.plano()).filter((e) => (!E.uf || e.uf === E.uf) && (!E.mun || e.cd_municipio === E.mun));
  const rotas = new Set(es.filter((e) => e.rota).map((e) => e.rota));
  nota.innerHTML = "Ferramentas para organizar os fiscais no próximo turno. Ficam na aba Plano de fiscalização.";
  el.innerHTML = numeros([
    { rotulo: "Locais de prioridade alta", valor: n(es.filter((e) => e.prioridade === 3).length) },
    { rotulo: "Rotas com locais próximos", valor: n(rotas.size), sub: `${n(es.filter((e) => e.rota).length)} locais a até ${dec(R.raio_km ?? 2, 0)} km um do outro` },
  ]) + `<ul class="checklist" style="margin-top:14px">
    <li><strong>Rotas</strong>: locais de prioridade alta a até ${dec(R.raio_km ?? 2, 0)} km uns dos outros, no mesmo município, em ordem de visita (do local com mais seções em atenção para o mais próximo). Um fiscal pode cobrir a rota se o horário permitir.</li>
    <li><strong>Ficha da escola para imprimir</strong>: uma página por local, com as seções a observar, os números do 1º turno, o checklist e campos em branco para anotar fila às 17h, horário do último voto, liberações manuais e troca de urna.</li></ul>
    <p style="margin-top:12px"><a class="botao primario" href="${link({ tela: "plano" })}">Abrir o plano de fiscalização</a></p>`;
}

// i) sinais extras do log
async function maisSinais(el, nota, X, P, secoes, L) {
  const R = X.sinais || {};
  if (!R.antes_8 && !R.manual_tarde && !R.rapidos) { el.innerHTML = semDados("Faltam os logs das urnas. Rode <code>python baixar_logs.py</code> e gere o site de novo."); return; }
  nota.innerHTML = "Padrões do log que não entram nos critérios, mas ajudam a decidir onde olhar. Todos têm explicações comuns, que estão ao lado de cada um.";
  const blocos = [];
  if (R.antes_8) blocos.push(["antes", "Votos antes das 8h", `${plural(R.antes_8.votos, "voto foi registrado", "votos foram registrados")} antes das 8h (horário de Brasília) em ${plural(R.antes_8.secoes, "seção", "seções")}. A causa mais comum é o relógio da urna adiantado (como em Guaporema, Nova Olímpia e Tapira, no PR); a ata da seção registra o horário real de abertura.`, "lista_antes_8", (s) => s.votos_antes_8 > 0,
    { k: "votos_antes_8", rot: "Votos antes das 8h", num: true, html: (o) => `<span class="forte">${n(o.votos_antes_8)}</span><span class="sub">de ${n(o.votos_log)} votos</span>` }]);
  if (R.manual_tarde) blocos.push(["mtarde", "Liberações manuais no fim do dia", `Das 16h em diante, a mesa já sabe quem faltou. Marcamos a seção quando as liberações pelo mesário desse horário são pelo menos ${n(R.manual_tarde.min)}, o dobro do que o horário dos votos da própria seção faria esperar, e bem acima do acaso: ${plural(R.manual_tarde.secoes_sinal, "seção", "seções")}. No país, ${n(R.manual_tarde.manual_16h)} das ${n(R.manual_tarde.manual)} liberações manuais (${p(div(R.manual_tarde.manual_16h, R.manual_tarde.manual))}) foram das 16h em diante. Leitor de digital que começa a falhar à tarde também produz esse padrão.`, "lista_manual_tarde", (s) => (s.sinais_cod || "").includes("manual_tarde"),
    { k: "manual_16h", rot: "Liberações manuais das 16h em diante", num: true, html: (o) => `<span class="forte">${n(o.manual_16h)}</span><span class="sub">de ${n(o.votos_manual)}; esperado ~${n(o.manual_tarde_esperado)}</span>` }]);
  if (R.rapidos) blocos.push(["rapidos", "Votos muito rápidos em sequência", R.rapidos.com_metrica ? `Sequências de ${n(R.rapidos.minimo)} ou mais votos seguidos com menos de 30 segundos entre um e outro, em qualquer horário: ${plural(R.rapidos.secoes_sinal, "seção", "seções")}. Votar em todos os cargos costuma levar mais de um minuto; eleitores que já chegam com os números anotados votam mais rápido.` : "Esta medida precisa reprocessar os logs: <code>python baixar_logs.py --refazer</code> (usa os logs já baixados).", "lista_rapidos", (s) => (s.maior_seq_rapida ?? 0) >= 6,
    { k: "maior_seq_rapida", rot: "Maior sequência rápida", num: true, html: (o) => `<span class="forte">${n(o.maior_seq_rapida)} votos</span><span class="sub">${o.seq_rapida_inicio != null ? `a partir das ${hora(o.seq_rapida_inicio)}` : ""}</span>` }]);
  el.innerHTML = blocos.map(([id, t, txt]) => `<h3 style="margin:18px 0 6px">${t}</h3><p class="nota">${txt}</p><div id="t-${id}" style="margin-top:10px"></div>`).join("");
  for (const [id, , , chave, f, col] of blocos) {
    tabela($(`#t-${id}`), {
      colunas: [colSecao, colZona, colLocal, col, colCrit], linhas: listaSecoes(L, chave, f),
      ordem: { k: col.k, desc: true }, aoClicar: abrirSecao, limite: 20, arquivo: `${chave.replace("lista_", "")}_${E.uf || "BR"}.csv`,
      vazio: "Nenhuma seção com este sinal neste recorte.",
    });
  }
}

// ---------------------------------------------------------------- Mapa
let geo = null;
function carregarScript(src) {
  return new Promise((ok, erro) => {
    const s = document.createElement("script");
    s.src = src; s.onload = ok; s.onerror = erro;
    document.head.appendChild(s);
  });
}
async function carregarGeo() {
  if (geo) return geo;
  await carregarScript("vendor/d3-array.min.js");
  await Promise.all([carregarScript("vendor/d3-geo.min.js"), carregarScript("vendor/topojson-client.min.js")]);
  const topo = await (await fetch("mapa/brasil.topo.json")).json();
  const muns = topojson.feature(topo, topo.objects.municipios).features;
  // a simplificação da malha deixa alguns polígonos com os anéis na ordem inversa;
  // para o d3 isso vira "o mundo inteiro menos o município" e cobre o mapa. Desvira.
  const desvira = (aneis) => aneis.map((r) => r.slice().reverse());
  for (const f of muns) {
    if (f.geometry && d3.geoArea(f) > 2 * Math.PI) {
      const g = f.geometry;
      g.coordinates = g.type === "Polygon" ? desvira(g.coordinates) : g.coordinates.map(desvira);
    }
  }
  const estados = topojson.feature(topo, topo.objects.estados).features;
  geo = { topo, muns, estados };
  return geo;
}
const METRICAS = {
  atencao: { rot: "Seções em atenção", val: (m) => m[`${pref()}_sec`], fmt: (v) => n(v) },
  v17: { rot: "Votos depois das 17h (quantidade)", val: (m) => m.votos_apos_17, fmt: (v) => n(v) },
  p17: { rot: "Votos depois das 17h (% dos votos)", val: (m) => (m.votos_log ? m.votos_apos_17 / m.votos_log : null), fmt: (v) => p(v, 2) },
  abst: { rot: "Seções com abstenção muito baixa", val: (m) => m[`${pref()}_abst`], fmt: (v) => n(v) },
  man: { rot: "Seções com muitas liberações manuais", val: (m) => m[`${pref()}_man`], fmt: (v) => n(v) },
  // métricas das fontes opcionais (aparecem só quando o dado existe)
  conc: { rot: "Seções com voto concentrado", val: (m) => m[`${pref()}_conc`], fmt: (v) => n(v), campo: "padrao_conc" },
  razao: { rot: "Eleitores ÷ população com 16+", val: (m) => m.razao_pop, fmt: (v) => dec(v), campo: "razao_pop" },
  cresc: { rot: "Crescimento do eleitorado", val: (m) => m.cresc_eleitorado, fmt: (v) => p(v), campo: "cresc_eleitorado", zero: "não cresceu" },
  gasto: { rot: "Gasto de campanha por eleitor (transporte e pessoal)", val: (m) => m.gasto_eleitor, fmt: (v) => reais(v), campo: "gasto_eleitor" },
};
const metricasDisponiveis = () => Object.entries(METRICAS).filter(([, v]) => !v.campo || D.municipios.some((m) => m[v.campo] != null));
let metricaMapa = "atencao";
TELAS.mapa = async (el) => {
  el.innerHTML = `<section class="manchete"><h1>Onde ficam as seções em atenção</h1>
    <p>Cada município é pintado conforme o indicador escolhido. Municípios sem nenhuma seção no critério ficam em cinza. Clique num município para ver as seções e os endereços.</p></section>
    <div class="mapa-layout"><div class="mapa-caixa"><div class="mapa-controles">
      <label>Pintar por <select id="m-metrica">${metricasDisponiveis().map(([k, v]) => `<option value="${k}" ${k === metricaMapa ? "selected" : ""}>${v.rot}</option>`).join("")}</select></label>
      ${E.uf ? `<label><input type="checkbox" id="m-escolas" checked> Mostrar locais de votação em atenção</label>` : ""}
    </div><div id="m-svg"><div class="carregando">Carregando o mapa…</div></div><div class="mapa-legenda" id="m-legenda"></div></div>
    <aside class="painel-lateral" id="m-painel"></aside></div>`;
  const g = await carregarGeo();
  const plano = E.uf ? objetos(await D.plano()).filter((e) => e.uf === E.uf) : [];
  const porIbge = new Map(D.municipios.map((m) => [m.cd_ibge, m]));
  desenharPainelMapa(E.mun ? D.munPorCd.get(E.mun) : null);

  const desenhar = () => {
    if (!metricasDisponiveis().some(([k]) => k === metricaMapa)) metricaMapa = "atencao";
    const M = METRICAS[metricaMapa];
    const vals = D.municipios.filter((m) => !E.uf || m.uf === E.uf).map((m) => M.val(m)).filter((v) => v > 0).sort((a, b) => a - b);
    // 6 faixas pelos quantis dos municípios com valor > 0 (assim o mapa não fica todo da mesma cor)
    const qs = [0.35, 0.6, 0.8, 0.92, 0.98].map((q) => vals[Math.floor(q * (vals.length - 1))] ?? 0);
    const cortes = [...new Set([vals[0] ?? 1, ...qs])].filter((v) => v != null);
    const cor = (v) => {
      if (!(v > 0)) return "var(--mapa-0)";
      let i = 0;
      while (i < cortes.length - 1 && v >= cortes[i + 1]) i++;
      return `var(--mapa-${Math.min(6, i + 1)})`;
    };
    const feats = E.uf ? g.muns.filter((f) => IBGE_UF[f.id.slice(0, 2)] === E.uf) : g.muns;
    const alvo = E.uf ? { type: "FeatureCollection", features: feats } : { type: "FeatureCollection", features: g.estados };
    const W = 900, H = E.uf ? 760 : 860;
    const proj = d3.geoMercator().fitExtent([[10, 10], [W - 10, H - 10]], alvo);
    const caminho = d3.geoPath(proj);
    const semGeo = D.municipios.filter((m) => (!E.uf || m.uf === E.uf) && m.cd_ibge && !g.muns.some((f) => f.id === m.cd_ibge) && m.mun_lat != null);
    let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Mapa de ${esc(nomeRecorte())} por município">`;
    for (const f of feats) {
      const m = porIbge.get(f.id);
      const v = m ? M.val(m) : null;
      const d = caminho(f);
      if (!d) { // polígono pequeno demais depois da simplificação: vira um ponto
        if (m && m.mun_lat != null) { const [x, y] = proj([m.mun_lon, m.mun_lat]); svg += `<circle class="mun" cx="${x}" cy="${y}" r="3" fill="${cor(v)}" data-ibge="${f.id}"></circle>`; }
        continue;
      }
      svg += `<path class="mun${m && m.cd_municipio === E.mun ? " sel" : ""}" d="${d}" fill="${cor(v)}" data-ibge="${f.id}"></path>`;
    }
    for (const m of semGeo) {
      const [x, y] = proj([m.mun_lon, m.mun_lat]);
      svg += `<circle class="mun" cx="${x}" cy="${y}" r="4" fill="${cor(M.val(m))}" data-ibge="${m.cd_ibge}"></circle>`;
    }
    const estados = E.uf ? g.estados.filter((f) => IBGE_UF[f.id] === E.uf) : g.estados;
    svg += `<path class="estados" d="${estados.map((f) => caminho(f)).join("")}"></path>`;
    if (E.uf && $("#m-escolas")?.checked) {
      for (const e of plano) {
        const lat = e.lat ?? e.mun_lat, lon = e.lon ?? e.mun_lon;
        if (lat == null) continue;
        const [x, y] = proj([lon, lat]);
        svg += `<circle class="escola p${e.prioridade}" cx="${x}" cy="${y}" r="${2.5 + e.prioridade * 1.2}" data-escola="${e.cd_municipio}-${e.zona}-${e.local}"></circle>`;
      }
    }
    $("#m-svg").innerHTML = svg + "</svg>";
    // legenda
    const faixas = cortes.map((c, i) => [c, cortes[i + 1]]);
    $("#m-legenda").innerHTML = `<span class="titulo">${M.rot}</span><span class="cx"><i style="background:var(--mapa-0)"></i>${M.zero ?? (M.campo && M.campo !== "padrao_conc" ? "sem dado" : "nenhum")}</span>` +
      faixas.map(([a, b], i) => `<span class="cx"><i style="background:var(--mapa-${i + 1})"></i>${M.fmt(a)}${b != null ? "" : " ou mais"}</span>`).join("") +
      (E.uf && plano.length ? `<span class="cx" style="margin-left:16px"><i style="background:var(--corrige);border-radius:50%;width:10px"></i>local de prioridade alta</span>` : "");
    // interação
    const dica = $("#dica");
    $$("#m-svg [data-ibge]").forEach((pth) => {
      const m = porIbge.get(pth.dataset.ibge);
      pth.addEventListener("mousemove", (ev) => {
        if (!m) { dica.hidden = true; return; }
        dica.innerHTML = `<b>${esc(m.mun_nome)} (${m.uf})</b><br>${M.rot}: ${M.fmt(M.val(m)) ?? "—"}<br>${n(m.votos_apos_17)} votos após 17h; ${n(m[`${pref()}_sec`])} seções em atenção`;
        dica.hidden = false;
        dica.style.left = Math.min(ev.clientX + 14, innerWidth - 300) + "px";
        dica.style.top = ev.clientY + 14 + "px";
      });
      pth.addEventListener("mouseleave", () => { dica.hidden = true; });
      pth.addEventListener("click", () => {
        if (!m) return;
        $$("#m-svg .sel").forEach((x) => x.classList.remove("sel"));
        pth.classList.add("sel");
        if (!E.uf) { ir({ uf: m.uf, mun: null, zona: null }); return; }
        desenharPainelMapa(m);
      });
    });
    $$("#m-svg [data-escola]").forEach((c) => {
      const e = plano.find((x) => `${x.cd_municipio}-${x.zona}-${x.local}` === c.dataset.escola);
      c.addEventListener("mousemove", (ev) => {
        dica.innerHTML = `<b>${esc(e.nome_local ?? "Local de votação")}</b><br>${esc(e.mun_nome)}, zona ${e.zona}<br>Prioridade ${PRIO[e.prioridade].toLowerCase()}: ${e.sinalizadas} de ${e.secoes_total} seções em atenção`;
        dica.hidden = false;
        dica.style.left = Math.min(ev.clientX + 14, innerWidth - 300) + "px";
        dica.style.top = ev.clientY + 14 + "px";
      });
      c.addEventListener("mouseleave", () => { dica.hidden = true; });
      c.addEventListener("click", () => desenharPainelMapa(D.munPorCd.get(e.cd_municipio)));
    });
  };
  $("#m-metrica").addEventListener("change", (e) => { metricaMapa = e.target.value; desenhar(); });
  $("#m-escolas")?.addEventListener("change", desenhar);
  desenhar();
};
async function desenharPainelMapa(m) {
  const el = $("#m-painel");
  if (!el) return;
  const P = pref();
  if (!m) {
    const a = await agregadoRecorte();
    el.innerHTML = `<h3>${esc(nomeRecorte())}</h3><p class="nota">${E.uf ? "Clique num município para ver as seções em atenção e os endereços." : "Clique num estado para aproximar o mapa."}</p>
      ${numeros([{ rotulo: "Seções em atenção", valor: n(a[`${P}_sec`]), destaque: true }, { rotulo: "Votos após 17h", valor: n(a.votos_apos_17), sub: p(div(a.votos_apos_17, a.votos_log), 2) }])}`;
    return;
  }
  el.innerHTML = `<h3>${esc(m.mun_nome)} (${m.uf})</h3>
    <p class="nota">${n(m.secoes)} seções, ${n(m.aptos)} eleitores aptos</p>
    ${numeros([{ rotulo: "Seções em atenção", valor: n(m[`${P}_sec`]), destaque: true }, { rotulo: "Votos após 17h", valor: n(m.votos_apos_17), sub: p(div(m.votos_apos_17, m.votos_log), 2) }])}
    <div class="acoes" style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap"><a class="botao primario" href="${link({ tela: "panorama", uf: m.uf, mun: m.cd_municipio, zona: null })}">Abrir município</a>
    <a class="botao" href="${link({ tela: "plano", uf: m.uf, mun: m.cd_municipio, zona: null })}">Locais para fiscalizar</a></div>
    <div class="lista" id="m-lista"><div class="carregando">Carregando seções…</div></div>`;
  const ss = secoesDe(await D.uf(m.uf)).filter((s) => s.cd_municipio === m.cd_municipio && crit(s.flags))
    .sort((a, b) => ncrit(crit(b.flags)) - ncrit(crit(a.flags)) || gravidade(b) - gravidade(a));
  const lista = $("#m-lista");
  if (!ss.length) { lista.innerHTML = `<p class="nota">Nenhuma seção em atenção neste município com o rigor atual.</p>`; return; }
  lista.innerHTML = ss.slice(0, 60).map((s, i) => `<button class="item-secao" data-i="${i}"><strong>Seção ${s.secao}, zona ${s.zona}</strong>
    ${selos(crit(s.flags))}<span style="display:block;margin-top:4px">${esc(s.escola ?? "Local não informado")}${s.endereco ? `, ${esc(s.endereco)}` : ""}${s.bairro ? `, ${esc(s.bairro)}` : ""}</span></button>`).join("") +
    (ss.length > 60 ? `<p class="nota">E mais ${n(ss.length - 60)} seções. Veja todas em <a href="${link({ tela: "atencao", uf: m.uf, mun: m.cd_municipio })}">Seções em atenção</a>.</p>` : "");
  $$(".item-secao", lista).forEach((b) => b.addEventListener("click", () => abrirSecao(ss[+b.dataset.i])));
}

// ---------------------------------------------------------------- Como ler
TELAS["como-ler"] = async (el) => {
  const nv = D.brasil.meta.niveis;
  el.innerHTML = `<div class="texto">
    <section class="manchete"><h1>Como ler este site</h1><p>O que cada número significa, de onde vem e o que ele não prova.</p></section>
    <div class="aviso"><strong>Um destaque não é prova de fraude.</strong> São cerca de 470 mil seções; mesmo com regras rigorosas, dezenas a centenas aparecem só por acaso, e a maioria tem explicação comum. O objetivo é saber onde vale a pena olhar de perto e onde colocar fiscais.</div>
    <h2>De onde vêm os dados</h2>
    <ul><li><strong>Resultado por seção</strong> (TSE): eleitores aptos, quantos compareceram e quantos faltaram.</li>
      <li><strong>Log de cada urna</strong> (TSE): o registro de cada eleitor com o horário do voto e como ele foi liberado (digital reconhecida, sem digital cadastrada ou liberado pelo mesário).</li>
      <li><strong>Eleitorado por local de votação</strong> (TSE): nome, endereço e coordenadas da escola de cada seção.</li></ul>
    <p>Os horários estão todos no horário de Brasília (a votação vai das 8h às 17h em todo o país). Os números são calculados uma vez, quando os dados são atualizados, e não mudam conforme quem visita.</p>
    <h2>Os três critérios</h2>
    <h3>Abstenção muito baixa</h3>
    <p>Para cada seção calculamos quanta gente deveria ter faltado, olhando as outras seções do mesmo município (ou do estado, se o município tem menos de 5 seções). Seções pequenas variam mais por acaso, e seções diferem naturalmente entre si (idade dos eleitores, zona rural, cadastro desatualizado); a conta leva as duas coisas em consideração. A seção entra na lista quando falta muito menos gente que o esperado: ${nv.rigoroso.abst_z}, ${nv.padrao.abst_z} ou ${nv.amplo.abst_z} desvios abaixo, conforme o rigor, e tem pelo menos ${D.brasil.meta.min_aptos_abst} eleitores aptos.</p>
    <h3>Muitos votos depois das 17h</h3>
    <p>A seção entra quando pelo menos ${p(nv.padrao.p17, 0)} dos votos foram depois das 17h (${p(nv.rigoroso.p17, 0)} no rigor rigoroso, ${p(nv.amplo.p17, 0)} no amplo), com pelo menos ${D.brasil.meta.min_votos_17} votos nesse horário, <strong>e</strong> a votação terminou bem depois das outras seções da mesma escola (${nv.padrao.dest17} minutos no padrão). Quando a escola inteira atrasa, o motivo costuma ser fila, e essa seção não entra.</p>
    <p>Sempre mostramos a <strong>quantidade</strong> de votos junto com a porcentagem: 30% de uma seção com 40 votantes são 12 pessoas.</p>
    <h3>Muitas liberações pelo mesário</h3>
    <p>Quando a digital de um eleitor que tem biometria cadastrada não é reconhecida em quatro tentativas, o mesário pode liberar o voto. A seção entra quando isso acontece muito mais que no resto do município (mesma conta da abstenção) e em pelo menos ${nv.padrao.man_min} eleitores. Eleitores sem digital cadastrada não contam aqui.</p>
    <h3>Opcional: voto muito concentrado num candidato</h3>
    <p>Quando a votação por candidato está disponível, existe um quarto critério, que só conta se você marcar na aba Seções em atenção: um candidato a deputado teve na seção uma fatia dos votos válidos muito acima da que teve no resto do município. Reduto eleitoral é comum (o bairro do candidato), então ele pesa mais junto com abstenção muito baixa e poucos brancos e nulos. Veja a aba <a href="${link({ tela: "mais" })}">Mais análises</a>.</p>
    <h2>Sinais no log da urna</h2>
    <p>No detalhe de cada seção listamos fatos objetivos do log que ajudam a separar fila de algo estranho: urna parada antes das 17h e depois com votos, maioria dos votos tardios sem digital, ritmo muito rápido depois das 17h, sequências de liberações manuais, urna substituída, abertura atrasada e diferença entre o log e o comparecimento oficial.</p>
    <h2>Mais análises</h2>
    <p>A aba <a href="${link({ tela: "mais" })}">Mais análises</a> junta outras fontes para dar tamanho e contexto aos destaques: se os votos das seções em atenção mudariam o resultado de alguma disputa, a idade dos eleitores de cada seção (que explica parte da abstenção e das falhas de digital), o cadastro comparado com a população do IBGE, a repetição entre eleições e entre turnos, o tipo do local de votação, os gastos de campanha com transporte e pessoal, rotas e fichas para os fiscais e outros sinais do log (votos antes das 8h, liberações manuais concentradas no fim do dia e votos muito rápidos em sequência). Nenhuma delas muda os três critérios.</p>
    <h2>Causas comuns para cada destaque</h2>
    <ul><li><strong>Abstenção baixa</strong>: seção nova, revisão recente do cadastro, comunidade pequena e mobilizada.</li>
      <li><strong>Votos após 17h</strong>: fila, problemas de biometria que deixam cada voto mais lento, urna substituída, abertura atrasada, relógio da urna adiantado.</li>
      <li><strong>Liberação manual</strong>: idosos, trabalhadores com digitais gastas, leitor sujo ou com defeito.</li></ul>
    <h2>Como investigar uma seção</h2>
    <ul class="checklist"><li>Compare com as outras seções da mesma escola (está no detalhe). Se todas destoam, é perfil do local.</li>
      <li>Consulte o boletim de urna e o log da seção no site de resultados do TSE (resultados.tse.jus.br).</li>
      <li>Peça a ata da mesa receptora ao cartório eleitoral: ela registra filas, troca de urna e problemas com a biometria.</li>
      <li>Se a dúvida continuar, procure o Tribunal Regional Eleitoral do estado ou o Ministério Público Eleitoral.</li></ul>
  </div>`;
};

// =============================================================== detalhe da seção
async function abrirSecao(s) {
  const g = $("#gaveta"), corpo = $("#gaveta-corpo");
  g.setAttribute("aria-hidden", "false");
  document.body.style.overflow = "hidden";
  const c = crit(s.flags);
  const mun = D.munPorCd.get(s.cd_municipio) || {};
  const intensidade = (z, lado) => {
    const a = Math.abs(z ?? 0);
    const rot = a >= 5 ? "muito forte" : a >= 4 ? "forte" : a >= 3 ? "moderada" : "leve";
    return `Intensidade ${rot}: ${a.toLocaleString("pt-BR", { maximumFractionDigits: 1 })} desvios ${lado} do esperado. Se nada de anormal acontecesse, só cerca de 1 seção em cada 700 passaria de 3 por acaso.`;
  };
  const achados = [];
  if (c & 1 || (s.z_ajustado ?? 0) <= -2.5) achados.push(`<div class="achado cor-abst"><h3>Abstenção ${c & 1 ? "muito baixa" : "abaixo do esperado"}</h3>
    <p>Faltaram <strong>${n(s.aptos - s.comparecimento)} de ${n(s.aptos)} eleitores</strong> (${p(s.taxa_abstencao)}). Pelo padrão de ${esc(mun.mun_nome ?? "município")}, o esperado seria faltarem cerca de ${n(s.aptos * s.taxa_esperada)} (${p(s.taxa_esperada)}).</p>
    <p class="intensidade">${intensidade(s.z_ajustado, "abaixo")}</p></div>`);
  if (s.votos_log && (c & 2 || s.votos_apos_17 >= 10)) achados.push(`<div class="achado cor-17h"><h3>${c & 2 ? "Muitos votos" : "Votos"} depois das 17h</h3>
    <p><strong>${n(s.votos_apos_17)} de ${n(s.votos_log)} votos</strong> (${p(s.pct_apos_17)}) foram registrados depois das 17h. O último voto foi às ${hora(s.ultimo_voto)}.</p>
    ${s.dif_local_min != null ? `<p>A votação desta seção terminou, em média, ${n(Math.abs(s.dif_local_min))} minutos ${s.dif_local_min >= 0 ? "mais tarde" : "mais cedo"} que nas outras seções da mesma escola.</p>` : `<p>É a única seção do local, então não dá para comparar com a escola.</p>`}</div>`);
  if (s.votos_log && (c & 4 || (s.z_manual ?? 0) >= 2.5)) achados.push(`<div class="achado cor-man"><h3>Liberações pelo mesário ${c & 4 ? "muito acima do normal" : "acima do normal"}</h3>
    <p><strong>${n(s.votos_manual)} eleitores</strong> com digital cadastrada foram liberados pelo mesário, ${p(s.pct_manual_cadastrados)} de ${n(s.cadastrados)}. No município, o esperado seria ${p(s.manual_esperado ?? null)}.</p>
    ${s.maior_seq_manual >= 3 ? `<p>A maior sequência foi de ${n(s.maior_seq_manual)} liberações manuais seguidas.</p>` : ""}
    ${s.z_manual != null ? `<p class="intensidade">${intensidade(s.z_manual, "acima")}</p>` : ""}</div>`);
  const sinaisTxt = (s.sinais_cod || "").split(",").filter(Boolean).map((k) => ({
    ociosa: s.ociosa_antes_17_min != null ? `A urna ficou ${n(s.ociosa_antes_17_min)} minutos sem votos antes das 17h e depois voltou a receber votos.` : "A urna ficou parada antes das 17h e depois voltou a receber votos.",
    sem_bio_17h: s.pct_sem_bio_apos_17 != null ? `${p(s.pct_sem_bio_apos_17, 0)} dos votos depois das 17h foram de eleitores liberados sem digital.` : "A maioria dos votos depois das 17h foi sem digital.",
    ritmo_17h: s.intervalo_med_apos_17_s != null ? `Depois das 17h, saiu um voto a cada ${n(s.intervalo_med_apos_17_s)} segundos, ritmo bem mais rápido que o normal.` : "Depois das 17h, os votos saíram em ritmo muito rápido.",
    tarde_escola: "A seção terminou mais de 1 hora depois das outras seções da mesma escola.",
    seq_manual: `Houve ${n(s.maior_seq_manual)} liberações manuais seguidas.`,
    log_dif: s.comparecimento != null ? `O log da urna registra ${n(s.votos_log)} votos, mas o comparecimento oficial é ${n(s.comparecimento)}.` : "O número de votos no log difere do comparecimento oficial.",
    urna_trocada: "A urna foi substituída durante a votação.",
    abertura: s.abertura_atrasada_min != null ? `A urna começou a receber eleitores com ${n(s.abertura_atrasada_min)} minutos de atraso.` : "A urna abriu com atraso.",
    sem_digital_escola: "Muito mais eleitores sem digital do que nas outras seções da mesma escola.",
    antes_8h: `${plural(s.votos_antes_8, "voto foi registrado", "votos foram registrados")} antes das 8h, horário de abertura. Pode ser relógio da urna adiantado; confira a ata.`,
    manual_tarde: `${plural(s.manual_16h, "liberação manual aconteceu", "liberações manuais aconteceram")} das 16h em diante, quando o esperado pelo horário dos votos seria cerca de ${n(s.manual_tarde_esperado)}. No fim do dia a mesa já sabe quem faltou.`,
    rapidos: `Houve ${n(s.maior_seq_rapida)} votos seguidos com menos de 30 segundos entre um e outro${s.seq_rapida_inicio != null ? `, a partir das ${hora(s.seq_rapida_inicio)}` : ""}. Votar em todos os cargos costuma levar mais de um minuto.`,
  }[k])).filter(Boolean);

  corpo.innerHTML = `<div class="detalhe">
    <h2 id="gaveta-titulo">Seção ${s.secao}, zona ${s.zona}</h2>
    <p class="onde"><strong>${esc(s.escola ?? "Local de votação não informado")}</strong><br>${esc([s.endereco, s.bairro, s.cep ? `CEP ${s.cep}` : null].filter(Boolean).join(", "))}${s.endereco || s.bairro ? "<br>" : ""}${esc(mun.mun_nome ?? "")} (${esc(s.uf)})</p>
    <div class="acoes"><a class="botao" href="${mapsUrl({ ...s, mun_nome: mun.mun_nome })}" target="_blank" rel="noopener">Abrir no mapa</a>
      <a class="botao" href="${link({ tela: "panorama", uf: s.uf, mun: s.cd_municipio, zona: s.zona })}" data-fechar>Ver a zona ${s.zona}</a></div>
    <div style="margin:14px 0 16px">${c || temConc(s) ? selos(c | (temConc(s) ? 8 : 0)) : `<span class="nota">Não cumpre nenhum critério no rigor atual.</span>`}${temConc(s) ? ` <span class="sub" style="display:inline">voto concentrado é o 4º critério, opcional</span>` : ""}</div>
    ${numeros([
      { rotulo: "Eleitores aptos", valor: n(s.aptos) },
      { rotulo: "Compareceram", valor: n(s.comparecimento), sub: p(1 - s.taxa_abstencao) },
      { rotulo: "Votos após 17h", valor: s.votos_log ? n(s.votos_apos_17) : "—", sub: s.votos_log ? p(s.pct_apos_17) : "sem log", destaque: !!(c & 2) },
      { rotulo: "Liberados pelo mesário", valor: s.votos_log ? n(s.votos_manual) : "—", sub: s.votos_log ? p(s.pct_manual_cadastrados) + " de quem tem digital" : "" },
    ])}
    ${achados.join("")}
    ${sinaisTxt.length ? `<div class="achado"><h3>Sinais no log da urna</h3><ul class="sinais">${sinaisTxt.map((t) => `<li>${esc(t)}</li>`).join("")}</ul></div>` : ""}
    <div id="d-extras"></div>
    <section class="bloco" style="margin-top:28px"><header><h2>Votos por hora</h2><p>Barras: esta seção. Linha tracejada: média do município, para comparar o formato.</p></header><div id="d-horas">${s.horasArr ? "" : '<p class="nota">Sem log de urna para esta seção.</p>'}</div></section>
    <section class="bloco" style="margin-top:28px"><header><h2>Outras seções da mesma escola</h2><p>Se todas destoam juntas, o mais provável é o perfil do local ou fila. Se só esta destoa, vale olhar mais.</p></header><div id="d-escola"><div class="carregando">Carregando…</div></div></section>
    <section class="bloco" style="margin-top:28px"><header><h2>Como verificar</h2></header><ul class="checklist">
      <li>Consulte o boletim de urna e o log da seção ${s.secao} da zona ${s.zona} no site de resultados do TSE (resultados.tse.jus.br).</li>
      <li>Peça a ata da mesa receptora ao cartório eleitoral da zona ${s.zona}: ela registra fila às 17h, troca de urna e problemas com o leitor de digital.</li>
      <li>No próximo turno, coloque um fiscal neste local de votação.</li></ul></section>
  </div>`;
  $$("[data-fechar]", corpo).forEach((x) => x.addEventListener("click", fecharGaveta));
  $(".gaveta-fechar").focus();

  const [mArq, zArq] = await Promise.all([D.mun(s.cd_municipio), D.zona(s.cd_municipio, s.zona)]);
  const completa = { ...(secoesDe(zArq).find((x) => x.secao === s.secao) || {}), ...s };
  if ($("#d-extras")) $("#d-extras").innerHTML = achadosExtras(completa, mun);
  if (s.horasArr && $("#d-horas")) $("#d-horas").innerHTML = graficoHoras(s.horasArr, { comparacao: mArq.perfil, rotComparacao: `Média de ${mun.mun_nome ?? "município"}` });
  const irmas = secoesDe(zArq).filter((x) => x.local === s.local);
  if ($("#d-escola")) tabela($("#d-escola"), {
    colunas: [
      { k: "secao", rot: "Seção", html: (o) => `<span class="forte">${o.secao === s.secao ? `Seção ${o.secao} (esta)` : `Seção ${o.secao}`}</span>` },
      { k: "crit", rot: "Critérios", ord: (o) => ncrit(crit(o.flags)), html: (o) => (crit(o.flags) ? selos(crit(o.flags)) : `<span class="sub">nenhum</span>`) },
      { k: "taxa_abstencao", rot: "Abstenção", num: true, html: (o) => p(o.taxa_abstencao) },
      { k: "votos_apos_17", rot: "Votos após 17h", num: true, html: (o) => (o.votos_log ? `${n(o.votos_apos_17)}<span class="sub">${p(o.pct_apos_17)}</span>` : "—") },
      { k: "ultimo_voto", rot: "Último voto", num: true, html: (o) => hora(o.ultimo_voto) },
      { k: "votos_manual", rot: "Liberados pelo mesário", num: true, html: (o) => (o.votos_log ? `${n(o.votos_manual)}<span class="sub">${p(o.pct_manual_cadastrados)}</span>` : "—") },
    ], linhas: irmas, ordem: { k: "secao", desc: false }, limite: 60,
    aoClicar: (o) => { if (o.secao !== s.secao) abrirSecao(o); },
  });
}
// cartões com os dados das fontes opcionais (Mais análises), no detalhe da seção
function achadosExtras(s, mun) {
  const out = [];
  const nomeMun = mun.mun_nome ?? "município";
  const pm = (num, den) => div(mun[num], mun[den]);
  if (s.conc_nome != null) {
    const forte = temConc(s);
    out.push(`<div class="achado cor-conc"><h3>${forte ? "Voto muito concentrado num candidato" : "Candidato com mais votos acima do esperado"}</h3>
      <p><strong>${esc(nomeCand(s.conc_nome))}</strong> (${esc(CARGOS_CONC[s.conc_cargo] ?? "deputado")}) teve <strong>${n(s.conc_votos)} dos ${n(s.conc_validos)} votos válidos</strong> desta seção (${p(s.conc_fatia)}). No resto de ${esc(nomeMun)}, teve ${p(s.conc_esperada)} dos votos.</p>
      ${s.conc_pct_bn != null ? `<p>Brancos e nulos para o mesmo cargo: ${p(s.conc_pct_bn)} dos votos (no município, cerca de ${p(s.conc_esp_bn)}).${s.conc_z_bn <= -3 ? " <strong>Muito abaixo do normal.</strong>" : ""}</p>` : ""}
      ${s.conc_z != null ? `<p class="intensidade">${intensidadeTxt(s.conc_z, "acima")} Candidato forte no próprio bairro ou na própria comunidade é comum; o sinal pesa mais junto com abstenção muito baixa e poucos brancos e nulos.</p>` : ""}</div>`);
  }
  if (s.eleitores_perfil != null) {
    const linhas = [`<p>Eleitores com <strong>70 anos ou mais: ${n(s.el_70_mais)}</strong> (${p(s.pct_70)}; em ${esc(nomeMun)}, ${p(pm("el_70_mais", "eleitores_perfil"))}). Com <strong>16 ou 17 anos: ${n(s.el_16_17)}</strong> (${p(s.pct_16_17)}; município, ${p(pm("el_16_17", "eleitores_perfil"))}). Para os dois grupos o voto é facultativo.</p>`];
    if (s.el_biometria != null) linhas.push(`<p>Com biometria cadastrada: ${n(s.el_biometria)} eleitores (${p(s.pct_biometria)}; município, ${p(pm("el_biometria", "eleitores_perfil"))}).</p>`);
    if (s.abst_esperada_idade != null) linhas.push(`<p>Considerando a idade dos eleitores, o esperado seria faltarem cerca de ${n(s.aptos * s.abst_esperada_idade)} (${p(s.abst_esperada_idade)}), em vez de ${n(s.aptos * s.taxa_esperada)} (${p(s.taxa_esperada)}) pela média do município. Faltaram ${n(s.aptos - s.comparecimento)}.</p>`);
    if (explicaIdade(s, 1)) linhas.push(`<p><strong>A idade dos eleitores explica a abstenção baixa desta seção</strong>: com ela na conta, a seção fica dentro do normal.</p>`);
    if (s.manual_esperado_idade != null && (crit(s.flags) & 4)) linhas.push(`<p>Idosos têm mais falha de digital. Considerando a idade, o esperado de liberações pelo mesário seria ${p(s.manual_esperado_idade)} de quem tem digital (cerca de ${n(s.cadastrados * s.manual_esperado_idade)} eleitores); foram ${n(s.votos_manual)}.${explicaIdade(s, 4) ? " <strong>A idade explica o destaque.</strong>" : ""}</p>`);
    out.push(`<div class="achado"><h3>Quem vota nesta seção</h3>${linhas.join("")}</div>`);
  }
  const ctx = [];
  if (s.tipo_local) ctx.push(`Tipo de local: <strong>${esc(s.tipo_local)}</strong>.`);
  if (s.n_agregadas > 0) ctx.push(`Esta seção recebeu ${plural(s.n_agregadas, "outra seção agregada", "outras seções agregadas")} (os eleitores delas votaram aqui).`);
  if (s.tipo_secao_agregada) ctx.push(`Situação no cadastro: ${esc(s.tipo_secao_agregada.toLowerCase())}.`);
  if (s.transf_recebidos > 0) ctx.push(`Recebeu <strong>${plural(s.transf_recebidos, "eleitor transferido", "eleitores transferidos")}</strong> temporariamente (voto em trânsito, mesários, presos provisórios e outros), ${p(s.pct_transf)} dos aptos. Isso muda o comparecimento esperado.`);
  if (s.transf_enviados > 0) ctx.push(`${plural(s.transf_enviados, "eleitor desta seção votou", "eleitores desta seção votaram")} em outra seção por transferência temporária.`);
  if (ctx.length) out.push(`<div class="achado"><h3>Contexto do local</h3>${ctx.map((t) => `<p>${t}</p>`).join("")}</div>`);
  if (s.tem_ant != null) {
    const anoAnt = D.brasil.meta.ano - 4;
    if (!s.tem_ant) out.push(`<div class="achado"><h3>Eleição de ${anoAnt}</h3><p>Não há seção com o mesmo número nesta zona em ${anoAnt} (seção nova ou renumerada).</p></div>`);
    else {
      const ca = (s.flags_ant >> (3 * iNivel())) & 7;
      const repetiu = Object.values(CRIT).filter((k) => ca & k.bit);
      out.push(`<div class="achado"><h3>Eleição de ${anoAnt}</h3><p>Na mesma seção, em ${anoAnt}: ${n(s.aptos_ant)} eleitores aptos, abstenção de ${p(s.taxa_abst_ant)}${s.votos_apos_17_ant != null ? `, ${n(s.votos_apos_17_ant)} votos depois das 17h (${p(s.pct_apos_17_ant)})` : ""}${s.votos_manual_ant != null ? `, ${n(s.votos_manual_ant)} liberados pelo mesário` : ""}.</p>
        <p>${repetiu.length ? `<strong>Já chamava atenção em ${anoAnt}</strong> por: ${repetiu.map((k) => k.curto.toLowerCase()).join(", ")}. Destaque que se repete costuma ter causa estrutural (perfil do local).` : `Não cumpria nenhum critério em ${anoAnt}${crit(s.flags) ? ": o destaque é novidade nesta eleição, o que aumenta a prioridade" : ""}.`}</p></div>`);
    }
  }
  if (s.taxa_comp_t1 != null && s.taxa_comp_t2 != null) {
    const c1 = s.comparecimento_t1 ?? s.comparecimento, c2 = s.comparecimento_t2 ?? s.comparecimento;
    out.push(`<div class="achado${s.comp_sobe_turno ? " cor-17h" : ""}"><h3>1º e 2º turno</h3><p>Compareceram ${n(c1)} eleitores no 1º turno (${p(s.taxa_comp_t1)}) e ${n(c2)} no 2º (${p(s.taxa_comp_t2)}): ${s.dif_comp_turnos >= 0 ? "subiu" : "caiu"} ${dec(Math.abs((s.dif_comp_turnos ?? 0) * 100), 1)} pontos.</p>
      ${s.comp_sobe_turno ? `<p><strong>O comparecimento subiu muito mais que nas outras seções do município.</strong></p>` : ""}
      ${s.apos17_so_t2 ? `<p>Teve votos depois das 17h só no 2º turno (${n(s.votos_apos_17_t2 ?? s.votos_apos_17)}).</p>` : ""}</div>`);
  }
  return out.join("");
}
const CARGOS_CONC = { 6: "deputado federal", 7: "deputado estadual", 8: "deputado distrital" };
function intensidadeTxt(z, lado) {
  const a = Math.abs(z ?? 0);
  const rot = a >= 5 ? "muito forte" : a >= 4 ? "forte" : a >= 3 ? "moderada" : "leve";
  return `Intensidade ${rot}: ${a.toLocaleString("pt-BR", { maximumFractionDigits: 1 })} desvios ${lado} do esperado.`;
}

function fecharGaveta() {
  $("#gaveta").setAttribute("aria-hidden", "true");
  document.body.style.overflow = "";
}

// =============================================================== inicialização
async function renderizar() {
  lerHash();
  $("#nivel").value = E.nivel;
  $$(".abas a").forEach((a) => a.setAttribute("aria-current", a.dataset.tela === E.tela ? "page" : "false"));
  $$(".abas a").forEach((a) => { a.href = link({ tela: a.dataset.tela }); });
  fecharGaveta();
  const el = $("#conteudo");
  try {
    await desenharEscopo();
    const tela = TELAS[E.tela] || TELAS.panorama;
    await tela(el);
  } catch (e) {
    console.error(e);
    el.innerHTML = `<div class="vazio">Não foi possível carregar esta parte dos dados (${esc(e.message)}). Recarregue a página; se continuar, os arquivos do site podem estar sendo atualizados.</div>`;
  }
}

async function iniciar() {
  try {
    await D.iniciar();
  } catch (e) {
    $("#conteudo").innerHTML = `<div class="vazio">Os dados do site ainda não foram gerados. No computador com os dados, rode <code>python gerar_site.py</code>.</div>`;
    return;
  }
  const m = D.brasil.meta;
  $("#eleicao").textContent = `Eleições ${m.ano}, ${m.turno}º turno`;
  $("#gerado").textContent = `Dados gerados em ${new Date(m.gerado_em).toLocaleString("pt-BR", { dateStyle: "long", timeStyle: "short" })}. ${m.ufs_com_log.length} de ${objetos(D.brasil.ufs).length} estados com logs de urna processados.`;
  $("#nivel").addEventListener("change", (e) => { localStorageSet("nivel", e.target.value); ir({ nivel: e.target.value }); });
  $$("[data-fechar]").forEach((x) => x.addEventListener("click", fecharGaveta));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") fecharGaveta(); });
  addEventListener("hashchange", renderizar);
  renderizar();
}
iniciar();
