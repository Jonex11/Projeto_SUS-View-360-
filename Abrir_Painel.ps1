# Abrir_Painel.ps1
# Inicia um servidor local simples (sem instalar nada) e abre o Painel Leitos
# SUS no navegador padrao. Isso faz o carregamento do CSV funcionar de forma
# totalmente automatica, pois os navegadores bloqueiam a leitura direta de
# arquivos locais (file://) por seguranca, mas permitem normalmente via
# http://localhost.
#
# Basta manter este arquivo, o Abrir_Painel.bat, o PainelLeitosSus.html e o
# LEITOS_SUS_2026.csv na mesma pasta (ex: C:\ETL_CNES_LEITOS\saida\) e clicar
# duas vezes em Abrir_Painel.bat sempre que quiser abrir o painel.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$htmlFile = "PainelLeitosSus.html"
$portsParaTentar = 8743..8752

$mimeTypes = @{
    ".html" = "text/html; charset=utf-8"
    ".htm"  = "text/html; charset=utf-8"
    ".csv"  = "text/csv; charset=utf-8"
    ".js"   = "application/javascript; charset=utf-8"
    ".css"  = "text/css; charset=utf-8"
    ".json" = "application/json; charset=utf-8"
}

function Iniciar-Servidor {
    param([int]$Port)
    $listener = New-Object System.Net.HttpListener
    $listener.Prefixes.Add("http://localhost:$Port/")
    $listener.Start()
    return $listener
}

$listener = $null
$portEscolhida = $null
foreach ($p in $portsParaTentar) {
    try {
        $listener = Iniciar-Servidor -Port $p
        $portEscolhida = $p
        break
    } catch {
        continue
    }
}

if (-not $listener) {
    Write-Host "Nao foi possivel iniciar o servidor local (portas 8743-8752 ocupadas)." -ForegroundColor Red
    Write-Host "Feche outros programas usando essas portas e tente novamente."
    Read-Host "Pressione ENTER para sair"
    exit 1
}

if (-not (Test-Path -LiteralPath (Join-Path $root $htmlFile) -PathType Leaf)) {
    Write-Host "Aviso: nao encontrei '$htmlFile' na pasta $root." -ForegroundColor Yellow
    Write-Host "Confirme se este script esta na mesma pasta do painel."
}

Write-Host "Servindo a pasta: $root"
Write-Host "Endereco:         http://localhost:$portEscolhida/$htmlFile"
Write-Host ""
Write-Host "Deixe esta janela aberta enquanto usa o painel."
Write-Host "Para encerrar o servidor, feche esta janela ou pressione Ctrl+C."
Write-Host ""

Start-Process "http://localhost:$portEscolhida/$htmlFile"

try {
    while ($listener.IsListening) {
        $context = $listener.GetContext()
        $request = $context.Request
        $response = $context.Response
        try {
            $localPath = [System.Uri]::UnescapeDataString($request.Url.AbsolutePath.TrimStart('/'))
            if ([string]::IsNullOrWhiteSpace($localPath)) { $localPath = $htmlFile }
            $filePath = Join-Path $root $localPath
            $fullRoot = (Resolve-Path $root).Path
            $fullFile = [System.IO.Path]::GetFullPath($filePath)

            if ($fullFile.StartsWith($fullRoot) -and (Test-Path -LiteralPath $filePath -PathType Leaf)) {
                $ext = [System.IO.Path]::GetExtension($filePath).ToLowerInvariant()
                $contentType = $mimeTypes[$ext]
                if (-not $contentType) { $contentType = "application/octet-stream" }
                $bytes = [System.IO.File]::ReadAllBytes($filePath)
                $response.ContentType = $contentType
                $response.ContentLength64 = $bytes.Length
                $response.Headers.Add("Cache-Control", "no-store")
                $response.OutputStream.Write($bytes, 0, $bytes.Length)
            } else {
                $response.StatusCode = 404
                $msg = [System.Text.Encoding]::UTF8.GetBytes("Arquivo nao encontrado: $localPath")
                $response.OutputStream.Write($msg, 0, $msg.Length)
            }
        } catch {
            try {
                $response.StatusCode = 500
                $msg = [System.Text.Encoding]::UTF8.GetBytes("Erro no servidor: $($_.Exception.Message)")
                $response.OutputStream.Write($msg, 0, $msg.Length)
            } catch { }
        } finally {
            $response.OutputStream.Close()
        }
    }
} finally {
    $listener.Stop()
    $listener.Close()
}
