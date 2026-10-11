<#
.SYNOPSIS
    Diagnostica (e tenta corrigir) o HTTPS de esteleicao.com no Caddy rodando via NSSM.

    Rode no PowerShell COMO ADMINISTRADOR:
        cd C:\git\esteleicao
        Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
        .\deploy\diagnosticar_caddy.ps1

    O que faz:
      1. acha o servico do Caddy no NSSM, o caddy.exe e o Caddyfile principal
      2. confere se o Caddyfile principal importa deploy\Caddyfile.est
      3. valida a configuracao do Caddy
      4. confere se os arquivos do site (web\) estao no lugar
      5. reinicia o Caddy (forca nova tentativa de emitir o certificado)
      6. mostra o que o log do Caddy diz sobre o dominio
      7. testa o HTTPS localmente
#>
param(
    [string]$Dominio = "esteleicao.com",
    [string]$PastaSite = "C:\git\esteleicao\web",
    [string]$ServicoCaddy = "",
    [switch]$SemReiniciar
)
$ErrorActionPreference = "Continue"
function Passo($t) { Write-Host "`n==> $t" -ForegroundColor Cyan }
function Ok($t)    { Write-Host "  OK   $t" -ForegroundColor Green }
function Ruim($t)  { Write-Host "  ERRO $t" -ForegroundColor Red }
function Info($t)  { Write-Host "       $t" }
# o nssm escreve em UTF-16; remove os caracteres nulos
function NssmGet($svc, $campo) { ((& nssm get $svc $campo 2>$null) -join "").Replace("`0", "").Trim() }

if (-not (Get-Command nssm -ErrorAction SilentlyContinue)) { Ruim "nssm nao encontrado no PATH"; exit 1 }

# ------------------------------------------------------------ 1. servico do Caddy
Passo "Servico do Caddy no NSSM"
$svc = $null; $caddyExe = $null
$candidatos = if ($ServicoCaddy) { @(Get-Service -Name $ServicoCaddy -ErrorAction SilentlyContinue) } else { @(Get-Service) }
foreach ($s in $candidatos) {
    $app = NssmGet $s.Name Application
    if ($app -match 'caddy') { $svc = $s; $caddyExe = $app; break }
}
if (-not $svc) { Ruim "nenhum servico do NSSM roda o caddy.exe. Informe: -ServicoCaddy NOME"; exit 1 }
$params = NssmGet $svc.Name AppParameters
$dir    = NssmGet $svc.Name AppDirectory
$logs   = @((NssmGet $svc.Name AppStderr), (NssmGet $svc.Name AppStdout)) | Where-Object { $_ } | Select-Object -Unique
Ok "servico '$($svc.Name)' ($($svc.Status))"
Info "executavel: $caddyExe"
Info "parametros: $params"

$cfg = $null
if ($params -match '--config\s+"([^"]+)"') { $cfg = $Matches[1] }
elseif ($params -match '--config\s+(\S+)') { $cfg = $Matches[1] }
if (-not $cfg) { $cfg = Join-Path $dir "Caddyfile" }
if (-not [IO.Path]::IsPathRooted($cfg)) { $cfg = Join-Path $dir $cfg }
if (Test-Path $cfg) { Ok "Caddyfile principal: $cfg" } else { Ruim "Caddyfile principal nao encontrado: $cfg"; exit 1 }

# ------------------------------------------------------------ 2. import
Passo "Import do Caddyfile.est"
$imp = Select-String -Path $cfg -Pattern '^\s*import\s+.*Caddyfile\.est' -ErrorAction SilentlyContinue
if ($imp) {
    Ok "linha encontrada: $($imp.Line.Trim())"
    $alvo = ($imp.Line.Trim() -replace '^\s*import\s+', '').Trim('"', ' ')
    if (Test-Path $alvo) { Ok "arquivo importado existe: $alvo" } else { Ruim "o arquivo importado NAO existe: $alvo" }
} else {
    Ruim "o Caddyfile principal NAO importa o Caddyfile.est. Acrescente, fora de qualquer bloco { }:"
    Info "import C:/git/esteleicao/deploy/Caddyfile.est"
}

# ------------------------------------------------------------ 3. validacao
Passo "Validando a configuracao do Caddy"
$val = & $caddyExe validate --config $cfg --adapter caddyfile 2>&1 | ForEach-Object { "$_" }
if ($LASTEXITCODE -eq 0) { Ok "configuracao valida" } else { Ruim "configuracao invalida:"; $val | Select-Object -Last 8 | ForEach-Object { Info $_ } }

# ------------------------------------------------------------ 4. arquivos do site
Passo "Arquivos do site em $PastaSite"
if (Test-Path (Join-Path $PastaSite "index.html")) { Ok "index.html encontrado" } else { Ruim "nao achei $PastaSite\index.html (extraia o pacote_servidor.zip em C:\git)" }
if (Test-Path (Join-Path $PastaSite "dados\brasil.json")) { Ok "dados gerados encontrados (dados\brasil.json)" } else { Ruim "faltam os dados: rode gerar_site.py no Mac e extraia o pacote de novo" }

# ------------------------------------------------------------ 5. reinicia o Caddy
if (-not $SemReiniciar) {
    Passo "Reiniciando o Caddy para emitir o certificado de $Dominio (aguarde ~60 s)"
    & nssm restart $svc.Name | Out-Null
    Start-Sleep -Seconds 60
}

# ------------------------------------------------------------ 6. log
Passo "O que o log do Caddy diz sobre $Dominio"
$achou = $false
foreach ($log in $logs) {
    if (Test-Path $log) {
        $linhas = Get-Content $log -Tail 400 | Select-String -SimpleMatch $Dominio | Select-Object -Last 12
        foreach ($l in $linhas) {
            $achou = $true
            $t = $l.Line
            if ($t -match 'certificate obtained successfully|certificate is valid|already exists|obtained') { Ok $t.Substring(0, [Math]::Min(220, $t.Length)) }
            elseif ($t -match '"level":"error"|error|failed|NXDOMAIN|unauthorized|rateLimited|timeout') { Ruim $t.Substring(0, [Math]::Min(300, $t.Length)) }
            else { Info $t.Substring(0, [Math]::Min(220, $t.Length)) }
        }
    } else { Info "(log nao encontrado: $log)" }
}
if (-not $achou) { Info "nenhuma linha sobre $Dominio no log (o Caddy pode nao ter carregado o Caddyfile.est)" }

# ------------------------------------------------------------ 7. teste HTTPS local
Passo "Testando HTTPS de $Dominio direto neste servidor"
$cod = & curl.exe -s -o NUL -w "%{http_code}" --max-time 15 --resolve "${Dominio}:443:127.0.0.1" "https://$Dominio/dados/brasil.json" 2>$null
if ($cod -eq "200") { Ok "https://$Dominio responde com certificado valido" }
else {
    Ruim "https://$Dominio ainda nao responde (codigo '$cod')"
    Info "Se o log mostrar erro de validacao, confirme que as portas 80 e 443 estao abertas para a internet"
    Info "(as mesmas do duad.live) e rode este script de novo em alguns minutos."
}
