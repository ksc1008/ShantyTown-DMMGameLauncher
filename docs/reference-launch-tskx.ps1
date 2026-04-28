<#
.SYNOPSIS
    DMM Game Player - Twinkle Star Knights X 런처

.DESCRIPTION
    토큰 검증, 파일 무결성 확인(병렬 MD5), CDN 다운로드(진행률 표시) 후 게임을 실행합니다.
    스크립트는 게임 프로세스를 띄운 직후 종료되므로, 바로가기에서 실행 시 콘솔 창도 함께 닫힙니다.

.PARAMETER Hidden
    숨김 모드. 사용자 입력이 필요한 상황(토큰 만료/누락)이 발생하면
    콘솔창이 보이는 모드로 자기 자신을 재실행하고 현재 인스턴스는 즉시 종료합니다.
    바로가기에서 호출할 때 이 스위치를 사용하세요.
#>
[CmdletBinding()]
param(
    [switch] $Hidden
)

# ===============================
#  PowerShell 7.5+ 검증 / 부트스트랩
# ===============================
function Get-PwshExecutable {
    $candidates = @(
        "$env:ProgramFiles\PowerShell\7\pwsh.exe",
        "$env:ProgramFiles\PowerShell\7-preview\pwsh.exe"
    )
    foreach ($path in $candidates) {
        if (Test-Path $path) { return $path }
    }
    $fromPath = Get-Command pwsh.exe -ErrorAction SilentlyContinue
    if ($fromPath) { return $fromPath.Source }
    return $null
}

function Test-Pwsh7 {
    # 이미 PS7.5+에서 실행 중이면 통과
    if ($PSVersionTable.PSVersion.Major -gt 7 -or
        ($PSVersionTable.PSVersion.Major -eq 7 -and $PSVersionTable.PSVersion.Minor -ge 5)) {
        return
    }

    $PS7 = Get-PwshExecutable
    if (-not $PS7) {
        # 숨김 모드는 사용자 안내가 불가능 → 그냥 종료
        if ($Hidden) { exit 1 }

        Write-Host "PowerShell 7.5 이상이 필요합니다. 설치하시겠습니까? (y/n): " -NoNewline -ForegroundColor Yellow
        $response = Read-Host
        if ($response -eq "y") {
            Write-Host "PowerShell 7.5를 설치합니다..."
            Start-Process -FilePath "winget" `
                -ArgumentList "install", "--id", "Microsoft.Powershell", "--source", "winget" `
                -Wait -NoNewWindow
            Write-Host "설치가 완료되었습니다. 스크립트를 다시 실행해주세요." -ForegroundColor Green
            Read-Host "Enter를 눌러 종료"
        } else {
            Write-Host "PowerShell 7.5 이상이 필요합니다. 종료합니다." -ForegroundColor Red
            Read-Host "Enter를 눌러 종료"
        }
        exit 1
    }

    # PS7이 있지만 현재 세션이 5.x → PS7로 재실행 후 종료
    # ※ 인자 순서 수정: -ExecutionPolicy는 -File 앞에 와야 함
    # ※ 숨김 모드라면 -Hidden 스위치도 함께 전달
    if (-not $Hidden) {
        Write-Host "PowerShell 7로 전환하여 재실행합니다..." -ForegroundColor Cyan
    }
    $relaunchArgs = @("-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"")
    if ($Hidden) { $relaunchArgs += "-Hidden" }
    Start-Process -FilePath $PS7 -ArgumentList $relaunchArgs
    exit 0
}

# ===============================
#  공용 유틸: 재시도 래퍼
# ===============================
function Invoke-WithRetry {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [scriptblock] $ScriptBlock,
        [int] $MaxAttempts = 3,
        [int] $DelaySeconds = 2,
        [string] $OperationName = "작업"
    )
    $attempt = 0
    while ($true) {
        $attempt++
        try {
            return & $ScriptBlock
        } catch {
            if ($attempt -ge $MaxAttempts) {
                throw "[$OperationName] $MaxAttempts회 시도 후 실패: $($_.Exception.Message)"
            }
            $wait = $DelaySeconds * $attempt  # 백오프
            Write-Warning "[$OperationName] 시도 $attempt/$MaxAttempts 실패: $($_.Exception.Message) → ${wait}초 후 재시도"
            Start-Sleep -Seconds $wait
        }
    }
}

# ===============================
#  숨김 모드 → 콘솔 모드 재실행
# ===============================
# 숨김 모드에서 사용자 입력이 필요한 상황을 만나면 호출됩니다.
# 콘솔창이 보이는 새 pwsh 인스턴스를 띄워서 동일 흐름을 처음부터 다시 진행하게 하고,
# 현재(숨김) 인스턴스는 즉시 종료합니다. 콘솔 인스턴스는 -Hidden 없이 실행되므로
# Read-Host가 정상 작동하고, 토큰 발급 후 그대로 게임 실행까지 이어집니다.
function Switch-ToConsoleMode {
    param([string] $Reason)

    # 현재 pwsh 경로 (Test-Pwsh7 통과 후이므로 PS7+ 보장)
    $pwshPath = (Get-Process -Id $PID).Path
    if (-not $pwshPath -or -not (Test-Path $pwshPath)) {
        # 폴백: PATH에서 검색
        $pwshPath = (Get-Command pwsh.exe -ErrorAction SilentlyContinue).Source
    }
    if (-not $pwshPath) {
        throw "콘솔 모드 재실행을 위한 pwsh.exe를 찾을 수 없습니다."
    }

    # 콘솔창이 보이는 모드로 재실행 ( -Hidden 스위치 제외 )
    Start-Process -FilePath $pwshPath `
        -ArgumentList "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`""
    exit 0
}

# ===============================
#  토큰 관리
# ===============================
$script:CommonHeaders = @{
    "Content-Type"    = "application/json"
    "client-app"      = "DMMGamePlayer5"
    "client-version"  = "5.4.8"
    "sec-fetch-site"  = "none"
    "sec-fetch-mode"  = "no-cors"
    "sec-fetch-dest"  = "empty"
    "accept-encoding" = "gzip, deflate, br, zstd"
    "user-agent"      = "DMMGamePlayer5-Win/5.4.8 Electron/34.3.0"
}

function Get-AccessToken {
    # 숨김 모드면 사용자 입력이 불가능하므로 콘솔 모드로 재실행
    if ($Hidden) {
        Switch-ToConsoleMode -Reason "토큰 발급에 사용자 로그인이 필요합니다."
    }

    $loginGetUrl = "https://apidgp-gameplayer.games.dmm.com/v5/auth/login/url"
    $getUrlBody = @{ prompt = "choose" } | ConvertTo-Json -Compress

    $urlResponse = Invoke-WithRetry -OperationName "로그인 URL 요청" -ScriptBlock {
        Invoke-RestMethod -Uri $loginGetUrl -Method Post -Body $getUrlBody -ContentType "application/json"
    }

    Start-Process $urlResponse.data.url
    Write-Host "로그인 후 리디렉션된 URL을 붙여넣으세요: " -NoNewline -ForegroundColor Cyan
    $inputUrl = Read-Host

    if ($inputUrl -notmatch "[\?&]code=([^&]+)") {
        throw "URL에서 code 파라미터를 찾을 수 없습니다."
    }
    $code = $matches[1]

    $issueBody = @{ code = $code } | ConvertTo-Json -Compress
    $issueResponse = Invoke-WithRetry -OperationName "토큰 발급" -ScriptBlock {
        Invoke-RestMethod -Uri "https://apidgp-gameplayer.games.dmm.com/v5/auth/accesstoken/issue" `
            -Method POST -Headers $script:CommonHeaders -Body $issueBody -ContentType "application/json"
    }

    $newToken = $issueResponse.data.access_token
    if ([string]::IsNullOrEmpty($newToken)) {
        throw "Access token을 가져올 수 없습니다."
    }

    @{ access_token = $newToken } | ConvertTo-Json | Set-Content -Path $script:tokenPath -Encoding UTF8
    Write-Host "토큰을 발급하여 저장했습니다: $script:tokenPath" -ForegroundColor Green
    return $newToken
}

function Get-ValidAccessToken {
    $access_token = $null
    if (Test-Path $script:tokenPath) {
        try {
            $access_token = Get-Content $script:tokenPath -Raw | ConvertFrom-Json |
                Select-Object -ExpandProperty access_token
        } catch {
            Write-Warning "토큰 파일을 읽을 수 없습니다. 재발급합니다."
        }
    }
    if (-not $access_token) {
        return Get-AccessToken
    }

    # 유효성 확인
    $checkBody = @{ access_token = $access_token; expires_in_seconds = 1209600 } |
        ConvertTo-Json -Compress
    try {
        $checkResponse = Invoke-WithRetry -OperationName "토큰 검증" -ScriptBlock {
            Invoke-RestMethod -Uri "https://apidgp-gameplayer.games.dmm.com/v5/auth/accesstoken/check" `
                -Method POST -Headers $script:CommonHeaders -Body $checkBody -ContentType "application/json"
        }
        if (-not $checkResponse.data.result) {
            Write-Warning "토큰이 만료되었습니다. 재발급합니다."
            return Get-AccessToken
        }
    } catch {
        Write-Warning "토큰 검증 실패. 재발급을 시도합니다. ($($_.Exception.Message))"
        return Get-AccessToken
    }

    Write-Host "토큰 유효성 확인 완료." -ForegroundColor Green
    return $access_token
}

# ===============================
#  스트리밍 다운로드 + 진행률
# ===============================
function Save-FileWithProgress {
    param(
        [Parameter(Mandatory)] [string] $Url,
        [Parameter(Mandatory)] [string] $Destination,
        [string] $Cookie,
        [string] $DisplayName
    )

    if (-not $DisplayName) { $DisplayName = Split-Path $Destination -Leaf }

    $destDir = Split-Path $Destination -Parent
    if ($destDir -and -not (Test-Path $destDir)) {
        New-Item -ItemType Directory -Path $destDir -Force | Out-Null
    }

    Invoke-WithRetry -OperationName "다운로드: $DisplayName" -ScriptBlock {
        $handler = [System.Net.Http.HttpClientHandler]::new()
        $handler.AutomaticDecompression = [System.Net.DecompressionMethods]::All
        $client = [System.Net.Http.HttpClient]::new($handler)
        $client.Timeout = [TimeSpan]::FromMinutes(10)

        try {
            if ($Cookie) {
                $client.DefaultRequestHeaders.Add("Cookie", $Cookie)
            }

            $response = $client.GetAsync($Url, [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
            try {
                if (-not $response.IsSuccessStatusCode) {
                    throw "HTTP $([int]$response.StatusCode) $($response.ReasonPhrase)"
                }

                $totalBytes = $response.Content.Headers.ContentLength
                $sourceStream = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
                $fileStream = [System.IO.File]::Create($Destination)

                try {
                    $buffer = New-Object byte[] 81920
                    $totalRead = 0L
                    $lastReport = [DateTime]::MinValue

                    while (($read = $sourceStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
                        $fileStream.Write($buffer, 0, $read)
                        $totalRead += $read

                        # 250ms 마다만 진행률 갱신 (너무 잦은 갱신 방지)
                        if (([DateTime]::Now - $lastReport).TotalMilliseconds -ge 250) {
                            if ($totalBytes -and $totalBytes -gt 0) {
                                $pct = [int](($totalRead / $totalBytes) * 100)
                                Write-Progress -Activity "다운로드 중: $DisplayName" `
                                    -Status ("{0:N1} / {1:N1} MB" -f ($totalRead/1MB), ($totalBytes/1MB)) `
                                    -PercentComplete $pct
                            } else {
                                Write-Progress -Activity "다운로드 중: $DisplayName" `
                                    -Status ("{0:N1} MB 받는 중" -f ($totalRead/1MB))
                            }
                            $lastReport = [DateTime]::Now
                        }
                    }
                } finally {
                    $fileStream.Dispose()
                    $sourceStream.Dispose()
                }
                Write-Progress -Activity "다운로드 중: $DisplayName" -Completed
            } finally {
                $response.Dispose()
            }
        } finally {
            $client.Dispose()
            $handler.Dispose()
        }
    } | Out-Null
}

# ===============================
#  병렬 파일 무결성 검증
# ===============================
function Test-GameFiles {
    param(
        [array]  $FileList,
        [string] $ExeDir,
        [string] $DownloadUrlPrefix,
        [string] $CdnSign,
        [int]    $ThrottleLimit = 8
    )

    Write-Host "`n[1/2] 파일 무결성 검증 (병렬: $ThrottleLimit)" -ForegroundColor Cyan

    # 병렬로 검증만 수행 → 다운로드 필요 목록 수집
    $needsDownload = $FileList | ForEach-Object -ThrottleLimit $ThrottleLimit -Parallel {
        $file = $_
        $exeDir = $using:ExeDir
        $filePath = Join-Path $exeDir $file.local_path

        $reason = $null
        if (-not (Test-Path $filePath)) {
            $reason = "missing"
        } else {
            $actualSize = (Get-Item $filePath).Length
            if ($actualSize -ne $file.size) {
                $reason = "size mismatch (expected: $($file.size), actual: $actualSize)"
            } else {
                $md5 = [System.Security.Cryptography.MD5]::Create()
                try {
                    $stream = [System.IO.File]::OpenRead($filePath)
                    try {
                        $hashBytes = $md5.ComputeHash($stream)
                    } finally {
                        $stream.Dispose()
                    }
                    $actualHash = [System.BitConverter]::ToString($hashBytes).Replace("-", "").ToLower()
                    if ($actualHash -ne $file.hash) {
                        $reason = "hash mismatch"
                    }
                } finally {
                    $md5.Dispose()
                }
            }
        }

        if ($reason) {
            [PSCustomObject]@{
                LocalPath  = $file.local_path
                RemotePath = $file.path
                FullPath   = $filePath
                Reason     = $reason
            }
        }
    }

    $okCount = $FileList.Count - @($needsDownload).Count
    Write-Host "  검증 완료: $okCount OK, $(@($needsDownload).Count)개 다운로드 필요" -ForegroundColor Green

    if (-not $needsDownload) { return }

    Write-Host "`n[2/2] 누락/손상된 파일 다운로드" -ForegroundColor Cyan
    $idx = 0
    $total = @($needsDownload).Count
    foreach ($item in $needsDownload) {
        $idx++
        Write-Host ("  ({0}/{1}) {2} — {3}" -f $idx, $total, $item.LocalPath, $item.Reason) -ForegroundColor Yellow
        Save-FileWithProgress `
            -Url ($DownloadUrlPrefix + $item.RemotePath) `
            -Destination $item.FullPath `
            -Cookie $CdnSign `
            -DisplayName $item.LocalPath
    }
}

# ===============================
#  메인
# ===============================
function Main {
    Test-Pwsh7

    # 토큰은 스크립트와 같은 폴더에 저장 → DMM 런처와 완전히 분리
    # (DMM 런처는 %APPDATA%\dmmgameplayer5\token.txt를 사용)
    $script:tokenPath = Join-Path (Split-Path -Parent $PSCommandPath) "token.json"
    $access_token = Get-ValidAccessToken

    # MAC 주소
    $mac_address = (Get-NetAdapter |
        Where-Object { $_.Status -eq 'Up' } |
        Select-Object -First 1 -ExpandProperty MacAddress).ToLower() -replace '-', ':'

    # 게임 실행 요청
    $launchBody = @{
        product_id   = "tskx"
        game_type    = "ACL"
        game_os      = "win"
        launch_type  = "SCHEME"
        mac_address  = $mac_address
        hdd_serial   = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        motherboard  = "487578a3684a308fca6319f990c3f18db162efcfe97ba8e441864f01deb68d42"
        user_os      = "win"
    } | ConvertTo-Json -Compress

    $launchHeaders = $script:CommonHeaders.Clone()
    $launchHeaders["actauth"] = $access_token
    $launchHeaders["cookie"]  = "age_check_done=1; ckcy_remedied_check=ec_mrnhbtk"

    $launchResponse = Invoke-WithRetry -OperationName "게임 실행 요청" -ScriptBlock {
        Invoke-RestMethod -Uri "https://apidgp-gameplayer.games.dmm.com/v5/r2/launch/cl" `
            -Method POST -Headers $launchHeaders -Body $launchBody -ContentType "application/json"
    }

    $cdn_sign           = $launchResponse.data.sign
    $filelist_url       = "https://apidgp-gameplayer.games.dmm.com" + $launchResponse.data.file_list_url

    $filelistResponse = Invoke-WithRetry -OperationName "파일 리스트 요청" -ScriptBlock {
        Invoke-RestMethod -Uri $filelist_url -Method GET -Headers $launchHeaders -ContentType "application/json"
    }
    if (-not $filelistResponse) { throw "파일 리스트를 가져오지 못했습니다: $filelist_url" }

    $filelist           = $filelistResponse.data.file_list
    $download_url_prefix = $filelistResponse.data.domain + "/"

    # dmmgame.cnf에서 실행 경로 확인
    $configPath = "$env:APPDATA\dmmgameplayer5\dmmgame.cnf"
    if (-not (Test-Path $configPath)) {
        throw "dmmgame.cnf를 찾을 수 없습니다: $configPath"
    }
    $config = Get-Content $configPath -Raw | ConvertFrom-Json
    $exe_name = "twinkle_starknightsx.exe"
    $exe_dir = $config.contents |
        Where-Object { $_.productId -eq "tskx" } |
        Select-Object -ExpandProperty detail |
        Select-Object -ExpandProperty path
    $exe_path = Join-Path $exe_dir $exe_name
    if (-not (Test-Path $exe_path)) {
        throw "실행 파일이 존재하지 않습니다: $exe_path"
    }

    # 파일 검증 및 다운로드
    Test-GameFiles -FileList $filelist `
        -ExeDir $exe_dir `
        -DownloadUrlPrefix $download_url_prefix `
        -CdnSign $cdn_sign

    $exec_arg = $launchResponse.data.execute_args
    if (-not $exec_arg) { throw "실행 인자를 가져오지 못했습니다." }

    Write-Host "`n게임을 실행합니다..." -ForegroundColor Green
    Start-Process -FilePath $exe_path -ArgumentList $exec_arg
    # 게임은 별도 프로세스로 분리 → 여기서 스크립트가 즉시 종료됨
    # 바로가기로 실행했다면 콘솔창도 함께 닫힘
}

# 최상위 try/catch — 어떤 단계에서 실패하든 사용자에게 사유를 보여주고 깔끔히 종료
try {
    Main
} catch {
    if ($Hidden) {
        # 숨김 모드에서는 콘솔이 안 보이므로 Read-Host로 멈추면 좀비 프로세스가 됨
        # 에러를 이벤트 로그 대신 사용자 임시 폴더에 기록하고 조용히 종료
        $logPath = Join-Path $env:TEMP "launch-tskx-error.log"
        @(
            "[$([DateTime]::Now.ToString('s'))] $($_.Exception.Message)"
            $_.ScriptStackTrace
            ""
        ) -join "`r`n" | Add-Content -Path $logPath -Encoding UTF8
        exit 1
    }
    Write-Host "`n[오류] $($_.Exception.Message)" -ForegroundColor Red
    Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray
    Read-Host "`nEnter를 눌러 종료"
    exit 1
}
