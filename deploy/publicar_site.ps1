<#
.SYNOPSIS
    Publica (ou atualiza) o site estatico do esteleicao no servidor Windows.

.DESCRIPTION
    1. Extrai o pacote_servidor.zip em C:\git (atualiza C:\git\esteleicao\web)
    2. Na primeira vez, para e remove o servico antigo do painel Streamlit ("esteleicao")
       no NSSM: o site novo nao precisa de Python rodando.
    3. Valida o Caddyfile principal e recarrega o Caddy (sem derrubar os outros sites)

    Rode no PowerShell COMO ADMINISTRADOR:
        cd C:\git
        Expand-Archive C:\git\pacote_servidor.zip -DestinationPath C:\git -Force
        .\esteleicao\deploy\publicar_site.ps1

.PARAMETER Pacote
    Caminho do zip (padrao C:\git\pacote_servidor.zip). Use -SemExtrair se ja extraiu.
.PARAMETER CaddyfilePrincipal
    Caddyfile que importa o deploy\Caddyfile.est.
#>
param(
    [string]$Pacote = "C:\git\pacote_servidor.zip",
    [string]$Destino = "C:\git",
    [string]$CaddyfilePrincipal = "C:\Git\veracibot\deploy\windows\Caddyfile",
    [string]$ServicoAntigo = "esteleicao",
    [switch]$SemExtrair
)
$ErrorActionPreference = "Stop"
function Passo($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Ok($t) { Write-Host "  ok  $t" -ForegroundColor Green }
function Aviso($t) { Write-Host "  !   $t" -ForegroundColor Yellow }

if (-not $SemExtrair) {
    Passo "Extraindo $Pacote"
    if (-not (Test-Path $Pacote)) { throw "Nao achei $Pacote" }
    # apaga os dados antigos para nao sobrar arquivo de uma geracao anterior
    $dados = Join-Path $Destino "esteleicao\web\dados"
    if (Test-Path $dados) { Remove-Item $dados -Recurse -Force }
    Expand-Archive $Pacote -DestinationPath $Destino -Force
    Ok "site extraido em $Destino\esteleicao\web"
}

Passo "Servico antigo do painel Streamlit"
$nssm = Get-Command nssm -ErrorAction SilentlyContinue
if ($nssm -and (Get-Service $ServicoAntigo -ErrorAction SilentlyContinue)) {
    & nssm stop $ServicoAntigo | Out-Null
    & nssm remove $ServicoAntigo confirm | Out-Null
    Ok "servico '$ServicoAntigo' parado e removido (o site agora e estatico)"
} else { Ok "nenhum servico antigo encontrado" }

Passo "Validando e recarregando o Caddy"
$caddy = (Get-Command caddy -ErrorAction SilentlyContinue).Source
if (-not $caddy) {
    $svc = Get-CimInstance Win32_Service | Where-Object { $_.PathName -match 'nssm' } |
        Where-Object { (& nssm get $_.Name Application 2>$null) -match 'caddy' } | Select-Object -First 1
    if ($svc) { $caddy = (& nssm get $svc.Name Application) }
}
if (-not $caddy) { throw "Nao encontrei o caddy.exe. Informe o caminho no PATH ou rode deploy\diagnosticar_caddy.ps1" }
& $caddy validate --config $CaddyfilePrincipal --adapter caddyfile
if ($LASTEXITCODE -ne 0) { throw "Configuracao do Caddy invalida; nada foi recarregado." }
& $caddy reload --config $CaddyfilePrincipal --adapter caddyfile
if ($LASTEXITCODE -eq 0) { Ok "Caddy recarregado" }
else { Aviso "reload falhou (a API admin do Caddy pode estar desligada). Reinicie o servico do Caddy no NSSM." }

Passo "Teste"
try {
    $r = Invoke-WebRequest "https://esteleicao.com/dados/brasil.json" -UseBasicParsing -TimeoutSec 15
    Ok "https://esteleicao.com respondeu ($($r.StatusCode))"
} catch { Aviso "https://esteleicao.com nao respondeu: rode .\esteleicao\deploy\diagnosticar_caddy.ps1" }
