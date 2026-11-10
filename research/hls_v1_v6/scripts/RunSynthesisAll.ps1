param(
    [string]$VitisCompiler = $env:QSIM8_VITIS_COMPILER,
    [ValidateSet('v1','v2','v3','v4','v5','v6','all')]
    [string]$Version = 'all'
)

$ErrorActionPreference = 'Stop'
$suiteRoot = Split-Path -Parent $PSScriptRoot

if (-not $VitisCompiler -and $env:XILINX_VITIS) {
    $VitisCompiler = Join-Path $env:XILINX_VITIS 'bin\v++.bat'
}

if (-not $VitisCompiler -or -not (Test-Path -LiteralPath $VitisCompiler)) {
    throw 'Không tìm thấy Vitis compiler. Đặt XILINX_VITIS hoặc truyền -VitisCompiler.'
}

$versions = if ($Version -eq 'all') {
    @('v1','v2','v3','v4','v5','v6')
} else {
    @($Version)
}

foreach ($item in $versions) {
    $sourceDir = Join-Path $suiteRoot $item
    $config = Join-Path $sourceDir 'hls_config.cfg'
    $workDir = Join-Path $suiteRoot "build\$item"
    if (Test-Path -LiteralPath $workDir) {
        throw "work_dir đã tồn tại: $workDir. Chọn phiên mới hoặc dọn kết quả cũ sau khi lưu bằng chứng."
    }

    Write-Host "=== C Synthesis $($item.ToUpperInvariant()) ===" -ForegroundColor Cyan
    Push-Location -LiteralPath $sourceDir
    try {
        # v++ 2026.1 on this Windows installation can corrupt an absolute
        # --config path containing "Desktop". We are already inside sourceDir,
        # so pass the config basename and keep only work_dir absolute.
        & $VitisCompiler -c --mode hls --config 'hls_config.cfg' --work_dir $workDir
        if ($LASTEXITCODE -ne 0) {
            throw "HLS compile thất bại ở $item, exit code $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }
}

Write-Host 'Đã tổng hợp xong. Chạy scripts\collect_reports.py bằng Python 3.10+.' -ForegroundColor Green
