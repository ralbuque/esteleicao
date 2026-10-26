"""Baixa os logs de urna pelos PACOTES POR UF dos dados abertos do TSE
(dataset "Arquivos transmitidos para totalização"), muito mais rápido que o site
de resultados e sem limite de requisições: é um .zip por estado.

Cada pacote traz, de todas as seções da UF: bu.dat, imgbu, log.jez, rdv.dat e vota.vsc.
Este script extrai os .jez (log), salva numa pasta e gera o mesmo zeresimas.csv.

Uso:  python -I baixar_logs_pacote.py [pasta_destino] [turno 1t|2t] [ufs separadas por vírgula]
      ex.: python -I baixar_logs_pacote.py D:/Eleições/logs-urnas 2t
           python -I baixar_logs_pacote.py D:/Eleições/logs-urnas-1t 1t se,al

Pode ser interrompido e rodado de novo: pula os estados já concluídos.
Precisa de ~0,25 GB de disco por estado pequeno e até ~19 GB para SP.
"""
import csv
import os
import re
import sys
import time
import urllib.request
import zipfile

CDN = 'https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2026/arqurnatot'
PACOTE = 'bu_imgbu_logjez_rdv_vscmr_2026_{turno}_{UF}.zip'
DIA = {'1t': '04/10/2026', '2t': '25/10/2026'}
UFS = 'AC AL AM AP BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS SC SE SP TO ZZ'.split()
NOME = re.compile(r'o(\d{5})([a-z]{2})(\d{5})(\d{4})(\d{4})-log\.jez', re.I)

CAMPOS = ['uf', 'municipio', 'zona', 'secao', 'arquivo', 'modelo_urna', 'versao_app',
          'urna_ligada', 'zeresima_gerada', 'zeresima_impressa', 'qtd_zeresimas_no_dia',
          'primeiro_voto', 'ultimo_voto', 'votos_computados', 'bu_gerado', 'alertas']


def ler_log(dados_jez, dia):
    """Extrai do logd.dat (dentro do .jez) os eventos do dia da eleição."""
    with zipfile.ZipFile(dados_jez) as z:
        texto = z.read('logd.dat').decode('latin-1')
    r = {'modelo_urna': '', 'versao_app': '', 'urna_ligada': '', 'zeresima_gerada': '', 'zeresima_impressa': '',
         'qtd_zeresimas_no_dia': 0, 'primeiro_voto': '', 'ultimo_voto': '', 'votos_computados': 0,
         'bu_gerado': '', 'alertas': 0}
    for linha in texto.splitlines():
        if not linha.startswith(dia):
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


def baixar(url, destino):
    """Baixa com retomada e barra simples; devolve False se o arquivo ainda não existe (404)."""
    parcial = destino + '.part'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'baixar-logs-pacote/1.0'})
        with urllib.request.urlopen(req, timeout=120) as r, open(parcial, 'wb') as f:
            total = int(r.headers.get('Content-Length', 0))
            baixado = t0 = 0
            t0 = time.time()
            while True:
                bloco = r.read(1 << 20)
                if not bloco:
                    break
                f.write(bloco)
                baixado += len(bloco)
                if total:
                    vel = baixado / (time.time() - t0 + 1e-9) / 1048576
                    print(f'\r    {baixado / 1073741824:5.2f}/{total / 1073741824:.2f} GB  {vel:5.1f} MB/s', end='', flush=True)
        print()
        os.replace(parcial, destino)
        return True
    except urllib.error.HTTPError as e:
        if os.path.exists(parcial):
            os.remove(parcial)
        if e.code == 404:
            return False
        raise


def processar_uf(uf, turno, destino, out, salvar_jez):
    url = f'{CDN}/{PACOTE.format(turno=turno, UF=uf)}'
    zip_path = os.path.join(destino, f'_pacote_{turno}_{uf}.zip')
    print(f'[{time.strftime("%H:%M:%S")}] {uf}: baixando pacote…', flush=True)
    if not (os.path.exists(zip_path) and os.path.getsize(zip_path) > 0):
        if not baixar(url, zip_path):
            print(f'  {uf}: pacote do {turno} ainda não publicado pelo TSE (404).', flush=True)
            return 0
    n = 0
    dia = DIA[turno]
    with zipfile.ZipFile(zip_path) as z:
        logs = [i for i in z.infolist() if i.filename.lower().endswith('-log.jez')]
        print(f'  {uf}: {len(logs)} urnas no pacote, extraindo logs…', flush=True)
        for info in logs:
            m = NOME.search(info.filename)
            if not m:
                continue
            _, ufa, mun, zona, secao = m.groups()
            import io
            dados = z.read(info)
            rel = ''
            if salvar_jez:
                pasta = os.path.join(destino, uf.lower(), mun)
                os.makedirs(pasta, exist_ok=True)
                arq = os.path.join(pasta, os.path.basename(info.filename))
                with open(arq, 'wb') as f:
                    f.write(dados)
                rel = os.path.relpath(arq, destino)
            try:
                ev = ler_log(io.BytesIO(dados), dia)
            except Exception as e:
                ev = {'alertas': f'ERRO: {e!r}'}
            out.writerow({'uf': uf.lower(), 'municipio': mun, 'zona': zona, 'secao': secao, 'arquivo': rel, **ev})
            n += 1
    os.remove(zip_path)   # libera o espaço do .zip; os .jez extraídos ficam
    print(f'  {uf}: {n} urnas processadas', flush=True)
    return n


def main():
    destino = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), '..', 'logs-urnas')
    turno = sys.argv[2] if len(sys.argv) > 2 else '2t'
    ufs = [u.upper() for u in sys.argv[3].split(',')] if len(sys.argv) > 3 else UFS
    salvar_jez = '--sem-salvar' not in sys.argv
    os.makedirs(destino, exist_ok=True)
    csv_path = os.path.join(destino, f'zeresimas_{turno}.csv')

    feitas = set()
    if os.path.exists(csv_path):
        with open(csv_path, encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f, delimiter=';'):
                feitas.add(row['uf'].upper())
    novo = not os.path.exists(csv_path)
    f = open(csv_path, 'a', encoding='utf-8-sig' if novo else 'utf-8', newline='')
    out = csv.DictWriter(f, fieldnames=CAMPOS, delimiter=';', extrasaction='ignore')
    if novo:
        out.writeheader()

    for uf in ufs:
        if uf in feitas:
            print(f'{uf}: já concluído, pulando', flush=True)
            continue
        processar_uf(uf, turno, destino, out, salvar_jez)
        f.flush()
    print(f'[{time.strftime("%H:%M:%S")}] concluído -> {csv_path}', flush=True)


if __name__ == '__main__':
    main()
