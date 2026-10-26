"""Baixa o log de todas as urnas do 2º turno de 2026 (Presidente) do site de resultados do TSE
e extrai os horários da zerésima e da votação para um CSV.

Uso:  python -I baixar_logs_urnas.py [pasta_destino] [ufs separadas por vírgula]
      ex.: python -I baixar_logs_urnas.py D:/Eleições/logs-urnas se,al

Pode ser interrompido e rodado de novo: pula as seções que já estão no CSV.
"""
import csv
import http.client
import io
import json
import os
import sys
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor

import base64 as _b64

HOST = 'resultados.tse.jus.br'
BASE = 'https://resultados.tse.jus.br/oficial/ele2026/arquivo-urna/3221'

# --proxy: roteia TUDO por um serviço de proxy (POST {"url": ...} com Basic Auth).
# --hibrido: usa a rota direta e só desvia para o proxy enquanto o TSE estiver bloqueando o IP.
PROXY = '--proxy' in sys.argv
HIBRIDO = '--hibrido' in sys.argv
USA_PROXY = PROXY or HIBRIDO
PROXY_HOST = ''          # preenchidos a partir de PROXY_URL (.env) quando --proxy/--hibrido
PROXY_PATH = '/proxy/fetch'


def carregar_env(caminho):
    """Lê um .env simples (CHAVE=valor) sem depender de biblioteca externa."""
    try:
        for linha in open(caminho, encoding='utf-8'):
            linha = linha.strip()
            if linha and not linha.startswith('#') and '=' in linha:
                k, v = linha.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass


_ENV = os.path.join(os.path.dirname(__file__), '..', '.env')
carregar_env(_ENV)
# endereço e credencial do proxy vêm do .env (nunca ficam no código nem em log)
_PROXY_AUTH = ''
if USA_PROXY:
    import urllib.parse as _up
    _pu = _up.urlparse(os.environ.get('PROXY_URL', ''))
    PROXY_HOST = _pu.hostname or ''
    PROXY_PATH = _pu.path or '/proxy/fetch'
    if not PROXY_HOST:
        sys.exit('Defina PROXY_URL no .env para usar --proxy/--hibrido (ex.: https://seu-host/proxy/fetch)')
    u, p = os.environ.get('N8N_BASIC_AUTH_USER', ''), os.environ.get('N8N_BASIC_AUTH_PASSWORD', '')
    _PROXY_AUTH = 'Basic ' + _b64.b64encode(f'{u}:{p}'.encode()).decode()
PLEITO = '003221'
DIA = '25/10/2026'
# --rapido: muitas threads e sem freio inicial (começa no máximo). Mais rápido, mas pode
# ser bloqueado pelo TSE; se tomar 429, ainda desacelera sozinho para não martelar à toa.
RAPIDO = '--rapido' in sys.argv
# híbrido/proxy precisam de mais threads por causa da latência do proxy nas janelas de bloqueio
WORKERS = 48 if USA_PROXY else (64 if RAPIDO else 24)
UFS = 'ac al am ap ba ce df es go ma mg ms mt pa pb pe pi pr rj rn ro rr rs sc se sp to zz'.split()

CAMPOS = ['uf', 'municipio', 'zona', 'secao', 'situacao', 'qtd_logs', 'arquivo', 'modelo_urna', 'versao_app',
          'urna_ligada', 'zeresima_gerada', 'zeresima_impressa', 'qtd_zeresimas_no_dia',
          'primeiro_voto', 'ultimo_voto', 'votos_computados', 'bu_gerado', 'alertas']

lock = threading.Lock()
local = threading.local()


class Ritmo:
    """Limita as requisições por segundo de todas as threads juntas e se adapta ao servidor:
    sobe devagar enquanto tudo vai bem; ao receber 429 (Too Many Requests), todas as threads
    pausam e a taxa cai pela metade."""

    def __init__(self, inicial=10.0, minimo=1.0, maximo=60.0):
        self.taxa, self.minimo, self.maximo = inicial, minimo, maximo
        self.proximo = time.monotonic()
        self.pausa_ate = 0.0
        self.ok_seguidos = 0
        self.lk = threading.Lock()

    def esperar(self):
        with self.lk:
            agora = time.monotonic()
            inicio = max(agora, self.proximo, self.pausa_ate)
            self.proximo = inicio + 1.0 / self.taxa
        time.sleep(max(0.0, inicio - time.monotonic()))

    def sucesso(self):
        with self.lk:
            self.ok_seguidos += 1
            if self.ok_seguidos >= 200:
                self.ok_seguidos = 0
                self.taxa = min(self.maximo, self.taxa * 1.1)

    def bloqueado(self, segundos):
        with self.lk:
            self.ok_seguidos = 0
            if time.monotonic() >= self.pausa_ate:   # conta só um bloqueio por pausa
                self.taxa = max(self.minimo, self.taxa / 2)
                self.pausa_ate = time.monotonic() + segundos
                print(f'  [{time.strftime("%H:%M:%S")}] servidor pediu para desacelerar (429): pausa de {segundos:.0f}s, '
                      f'nova taxa {self.taxa:.1f} req/s', flush=True)


# híbrido: direta em ritmo moderado; nas janelas de bloqueio o próprio proxy (lento) segura o fluxo.
# moderado: ritmo baixo e constante para tentar passar sob o bloqueio. Rápido: começa no teto.
if HIBRIDO:
    ritmo = Ritmo(inicial=12.0, minimo=2.0, maximo=15.0)
elif '--moderado' in sys.argv:
    ritmo = Ritmo(inicial=9.0, minimo=2.0, maximo=10.0)
elif PROXY:
    ritmo = Ritmo(inicial=18.0, minimo=3.0, maximo=25.0)
elif RAPIDO:
    ritmo = Ritmo(inicial=60.0, maximo=120.0)
else:
    ritmo = Ritmo()


def _conexao(host, timeout, renovar=False):
    """Uma conexão HTTPS persistente por thread e por host (TSE e/ou proxy)."""
    attr = 'conn_' + host
    c = getattr(local, attr, None)
    if renovar and c:
        try:
            c.close()
        except Exception:
            pass
        c = None
    if not c:
        c = http.client.HTTPSConnection(host, timeout=timeout)
        setattr(local, attr, c)
    return c


# --- janela de bloqueio da rota direta (modo híbrido), compartilhada entre as threads ---
_bloqlk = threading.Lock()
_bloq_ate = 0.0       # até quando a rota direta é considerada bloqueada (monotonic)
_prox_sonda = 0.0     # próxima vez que uma requisição pode sondar a direta durante o bloqueio


def direta_bloqueada():
    """Em bloqueio, manda usar o proxy; mas a cada 30s libera uma requisição para sondar a direta."""
    global _prox_sonda
    with _bloqlk:
        agora = time.monotonic()
        if agora >= _bloq_ate:
            return False
        if agora >= _prox_sonda:
            _prox_sonda = agora + 30
            return False
        return True


def marca_bloqueio(segundos):
    global _bloq_ate
    with _bloqlk:
        if time.monotonic() >= _bloq_ate:
            _bloq_ate = time.monotonic() + segundos
            print(f'  [{time.strftime("%H:%M:%S")}] rota direta bloqueada (429): desviando para o proxy '
                  f'por ~{segundos:.0f}s (sondando a direta a cada 30s)', flush=True)


def limpa_bloqueio():
    global _bloq_ate
    with _bloqlk:
        if _bloq_ate:
            _bloq_ate = 0.0
            print(f'  [{time.strftime("%H:%M:%S")}] rota direta voltou: usando o TSE diretamente', flush=True)


def _get_direto(url, renovar):
    c = _conexao(HOST, 60, renovar)
    c.request('GET', url.split(HOST, 1)[1],
              headers={'User-Agent': 'baixar-logs-urnas/1.4', 'Connection': 'keep-alive'})
    r = c.getresponse()
    return r.status, r.read(), r.getheader('Retry-After')


def _get_proxy(url, renovar):
    c = _conexao(PROXY_HOST, 12, renovar)   # proxy lento é proxy morto: tempo curto
    corpo = json.dumps({'url': url}).encode()
    c.request('POST', PROXY_PATH, body=corpo,
              headers={'Content-Type': 'application/json', 'Authorization': _PROXY_AUTH,
                       'Connection': 'keep-alive', 'User-Agent': 'baixar-logs-urnas/1.4'})
    r = c.getresponse()
    return r.status, r.read(), r.getheader('Retry-After')


def get(url, tentativas=14):
    erro = None
    for i in range(tentativas):
        # proxy puro sempre; híbrido só enquanto a direta estiver bloqueada; senão, direta
        via_proxy = PROXY or (HIBRIDO and direta_bloqueada())
        ritmo.esperar()
        renovar = erro is not None and not isinstance(erro, Bloqueio)
        try:
            if via_proxy:
                status, dados, _ = _get_proxy(url, renovar)
                if status == 200:
                    ritmo.sucesso()
                    return dados
                if status == 502 and i >= 2:   # proxy esgotou tentativas (origem 404): arquivo ausente
                    ritmo.sucesso()
                    return None
                if status in (429, 503):        # o próprio proxy limitou: desacelera todas as threads
                    ritmo.bloqueado(30)
                    erro = Bloqueio(f'proxy {status}')
                    continue
                erro = Exception(f'proxy HTTP {status}')
            else:
                status, dados, ra = _get_direto(url, renovar)
                if status == 200:
                    if HIBRIDO:
                        limpa_bloqueio()
                    ritmo.sucesso()
                    return dados
                if status == 404:
                    ritmo.sucesso()
                    return None
                if status in (429, 503):
                    seg = float(ra) if ra and ra.isdigit() else 90
                    if HIBRIDO:
                        marca_bloqueio(seg)      # próxima volta já tenta pelo proxy
                        erro = Bloqueio(f'HTTP {status}')
                        continue
                    ritmo.bloqueado(seg)
                    erro = Bloqueio(f'HTTP {status}')
                    continue
                erro = Exception(f'HTTP {status}')
        except Exception as e:  # conexão derrubada/instável: reconecta e tenta de novo
            erro = e
            if HIBRIDO and not via_proxy:
                marca_bloqueio(60)   # erro na direta costuma ser o bloqueio chegando; desvia
        # proxy ou bloqueio: nova tentativa quase imediata; erro comum na direta: recuo exponencial
        time.sleep(0.4 if (via_proxy or isinstance(erro, Bloqueio)) else min(2 ** i, 30))
    raise erro


class Bloqueio(Exception):
    pass


def jws_payload(raw):
    import base64
    p = raw.decode().strip().split('.')[1]
    return json.loads(base64.urlsafe_b64decode(p + '=' * (-len(p) % 4)))


def secoes(uf):
    cfg = jws_payload(get(f'{BASE}/config/{uf}/{uf}-p{PLEITO}-cs.jws'))
    for a in cfg['abr']:
        for m in a['mu']:
            for z in m['zon']:
                for s in z['sec']:
                    yield uf, m['cd'], z['cd'], s['ns']


def ler_log(dados_jez):
    """Extrai do logd.dat os eventos do dia da eleição."""
    with zipfile.ZipFile(io.BytesIO(dados_jez)) as z:
        texto = z.read('logd.dat').decode('latin-1')
    r = {'modelo_urna': '', 'versao_app': '', 'urna_ligada': '', 'zeresima_gerada': '', 'zeresima_impressa': '',
         'qtd_zeresimas_no_dia': 0, 'primeiro_voto': '', 'ultimo_voto': '', 'votos_computados': 0,
         'bu_gerado': '', 'alertas': 0}
    for linha in texto.splitlines():
        if not linha.startswith(DIA):
            continue
        partes = linha.split('\t')
        if len(partes) < 5:
            continue
        hora, nivel, msg = partes[0][11:], partes[1], partes[4]
        if nivel == 'ALERTA':
            r['alertas'] += 1
        if msg.startswith('Identificação do Modelo de Urna:'):
            r['modelo_urna'] = msg.split(':', 1)[1].strip()
        elif msg.startswith('Versão da aplicação:'):
            r['versao_app'] = msg.split(':', 1)[1].strip()
        elif msg.startswith('Urna ligada em') and not r['urna_ligada']:
            r['urna_ligada'] = hora
        elif msg == 'Gerando relatório [ZERÉSIMA] [INÍCIO]':
            r['qtd_zeresimas_no_dia'] += 1
            if not r['zeresima_gerada']:
                r['zeresima_gerada'] = hora
        elif msg.startswith('Imprimindo relatório [ZERÉSIMA]') and not r['zeresima_impressa']:
            r['zeresima_impressa'] = hora
        elif msg == 'O voto do eleitor foi computado':
            r['votos_computados'] += 1
            r['primeiro_voto'] = r['primeiro_voto'] or hora
            r['ultimo_voto'] = hora
        elif msg == 'Gerando relatório [BU] [INÍCIO]' and not r['bu_gerado']:
            r['bu_gerado'] = hora
    return r


def processar(sec, destino, out, err):
    uf, mun, zona, secao = sec
    pasta = f'{BASE}/dados/{uf}/{mun}/{zona}/{secao}'
    try:
        raw = get(f'{pasta}/p{PLEITO}-{uf}-m{mun}-z{zona}-s{secao}-aux.json')
        aux = json.loads(raw) if raw else {'st': 'sem índice', 'hashes': []}
        logs = [(h['hash'], a['nm']) for h in aux.get('hashes', []) for a in h.get('arq', []) if a.get('tp') == 'log']
        base = {'uf': uf, 'municipio': mun, 'zona': zona, 'secao': secao, 'situacao': aux.get('st', ''),
                'qtd_logs': len(logs)}
        linhas = []
        for i, (h, nm) in enumerate(logs):
            dir_local = os.path.join(destino, uf, mun)
            os.makedirs(dir_local, exist_ok=True)
            nome = nm if i == 0 else f'{nm[:-4]}-{i + 1}.jez'   # urna substituída: mais de um log na seção
            arq = os.path.join(dir_local, nome)
            if os.path.exists(arq) and os.path.getsize(arq) > 0:
                dados = open(arq, 'rb').read()
            else:
                dados = get(f'{pasta}/{h}/{nm}')
                if dados is None:
                    continue
                with open(arq + '.part', 'wb') as f:
                    f.write(dados)
                os.replace(arq + '.part', arq)
            linhas.append({**base, 'arquivo': os.path.relpath(arq, destino), **ler_log(dados)})
        if not linhas:
            linhas.append({**base, 'arquivo': ''})
        with lock:
            for l in linhas:
                out.writerow(l)
        return len(linhas)
    except Exception as e:
        with lock:
            err.writerow([uf, mun, zona, secao, repr(e)])
        return 0


def main():
    pos = [a for a in sys.argv[1:] if not a.startswith('--')]   # ignora flags como --rapido
    destino = pos[0] if pos else os.path.join(os.path.dirname(__file__), '..', 'logs-urnas')
    destino = os.path.abspath(destino)
    ufs = pos[1].split(',') if len(pos) > 1 else UFS
    os.makedirs(destino, exist_ok=True)
    csv_path = os.path.join(destino, 'zeresimas.csv')

    feitas = set()
    if os.path.exists(csv_path):
        # se a execução anterior foi interrompida no meio de uma linha, fecha a linha cortada
        with open(csv_path, 'rb+') as f:
            f.seek(0, 2)
            if f.tell() and (f.seek(-1, 2) or f.read(1) != b'\n'):
                f.write(b'\r\n')
        with open(csv_path, encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f, delimiter=';'):
                if row.get('alertas') is not None:   # linha completa
                    feitas.add((row['uf'], row['municipio'], row['zona'], row['secao']))
    novo = not os.path.exists(csv_path)
    fcsv = open(csv_path, 'a', encoding='utf-8-sig' if novo else 'utf-8', newline='')
    out = csv.DictWriter(fcsv, fieldnames=CAMPOS, delimiter=';', extrasaction='ignore')
    if novo:
        out.writeheader()
    ferr = open(os.path.join(destino, 'erros.csv'), 'a', encoding='utf-8', newline='')
    err = csv.writer(ferr, delimiter=';')

    for uf in ufs:
        lista = [s for s in secoes(uf) if s not in feitas]
        print(f'[{time.strftime("%H:%M:%S")}] {uf.upper()}: {len(lista)} seções a processar', flush=True)
        t0, n = time.time(), 0
        with ThreadPoolExecutor(WORKERS) as ex:
            for _ in ex.map(lambda s: processar(s, destino, out, err), lista):
                n += 1
                if n % 1000 == 0:
                    with lock:
                        fcsv.flush(); ferr.flush()
                    taxa = n / (time.time() - t0)
                    print(f'  {uf.upper()} {n}/{len(lista)}  {taxa:.1f} seções/s  (limite atual {ritmo.taxa:.1f} req/s)  '
                          f'faltam ~{(len(lista) - n) / taxa / 60:.0f} min', flush=True)
        fcsv.flush(); ferr.flush()
    print(f'[{time.strftime("%H:%M:%S")}] concluído', flush=True)


if __name__ == '__main__':
    main()
