param(
    [string]$OutputPath = "app/static/audio/brb-8bit-loop.wav"
)

# Original 12-second chiptune loop. Mono PCM keeps the asset small and OBS-friendly.
$sampleRate = 11025
$durationSeconds = 12
$sampleCount = $sampleRate * $durationSeconds
$outputDirectory = Split-Path -Parent $OutputPath
New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null

$melody = @(76, 79, 83, 79, 76, 74, 72, 74, 76, 79, 84, 83, 79, 76, 74, 72, 74, 76, 79, 83, 86, 83, 79, 76)
$bass = @(40, 40, 43, 43, 45, 45, 43, 43, 40, 40, 36, 36)

function Get-Frequency([int]$midi) {
    return 440.0 * [Math]::Pow(2.0, ($midi - 69) / 12.0)
}

$stream = [System.IO.File]::Open($OutputPath, [System.IO.FileMode]::Create)
$writer = [System.IO.BinaryWriter]::new($stream)
try {
    $dataBytes = $sampleCount * 2
    $writer.Write([System.Text.Encoding]::ASCII.GetBytes("RIFF"))
    $writer.Write([int](36 + $dataBytes))
    $writer.Write([System.Text.Encoding]::ASCII.GetBytes("WAVEfmt "))
    $writer.Write([int]16)
    $writer.Write([int16]1)
    $writer.Write([int16]1)
    $writer.Write([int]$sampleRate)
    $writer.Write([int]($sampleRate * 2))
    $writer.Write([int16]2)
    $writer.Write([int16]16)
    $writer.Write([System.Text.Encoding]::ASCII.GetBytes("data"))
    $writer.Write([int]$dataBytes)

    for ($i = 0; $i -lt $sampleCount; $i++) {
        $time = $i / [double]$sampleRate
        $melodyStep = [Math]::Floor($time / 0.5) % $melody.Count
        $bassStep = [Math]::Floor($time) % $bass.Count
        $noteTime = $time - [Math]::Floor($time / 0.5) * 0.5
        $beatTime = $time - [Math]::Floor($time) 
        $melodyEnvelope = [Math]::Exp(-$noteTime * 3.2)
        $melodyWave = if ([Math]::Sin(2 * [Math]::PI * (Get-Frequency $melody[$melodyStep]) * $time) -ge 0) { 1.0 } else { -1.0 }
        $bassWave = if ([Math]::Sin(2 * [Math]::PI * (Get-Frequency $bass[$bassStep]) * $time) -ge 0) { 1.0 } else { -1.0 }
        $drumEnvelope = [Math]::Exp(-$beatTime * 18)
        $drumWave = [Math]::Sin(2 * [Math]::PI * (92 - $beatTime * 45) * $time)
        $sample = (0.44 * $melodyWave * $melodyEnvelope) + (0.22 * $bassWave) + (0.18 * $drumWave * $drumEnvelope)
        $sample = [Math]::Max(-1.0, [Math]::Min(1.0, $sample))
        $writer.Write([int16]($sample * 32767))
    }
}
finally {
    $writer.Dispose()
}

Write-Host "Created $OutputPath"
