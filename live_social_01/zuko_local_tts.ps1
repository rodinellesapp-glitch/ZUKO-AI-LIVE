param([ValidateSet('list','synthesize','worker')][string]$Action='list',
      [ValidateSet('winrt','sapi')][string]$Backend='winrt',
      [string]$TextPath,[string]$OutputPath,[string]$VoiceName='Microsoft Maria',[int]$Rate=2)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.Encoding]::UTF8
[Console]::InputEncoding=[Text.Encoding]::UTF8
function Export-WinRTSpeech($Synthesizer,[string]$Text,[string]$Path) {
    $op=$Synthesizer.SynthesizeTextToStreamAsync($Text)
    $method=[System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'} | Select-Object -First 1
    $task=$method.MakeGenericMethod([Windows.Media.SpeechSynthesis.SpeechSynthesisStream]).Invoke($null,@($op))
    if(-not $task.Wait(10000)){throw 'LOCAL_SYNTHESIS_TIMEOUT'}
    $audio=$task.Result
    $reader=[System.IO.WindowsRuntimeStreamExtensions]::AsStreamForRead($audio)
    $file=[IO.File]::Create($Path)
    try{$reader.CopyTo($file)}finally{$file.Dispose();$reader.Dispose();$audio.Dispose()}
}
$speaker=$null
try {
    if($Backend -eq 'winrt') {
        Add-Type -AssemblyName System.Runtime.WindowsRuntime
        [Windows.Media.SpeechSynthesis.SpeechSynthesizer,Windows.Media.SpeechSynthesis,ContentType=WindowsRuntime] > $null
        [Windows.Media.SpeechSynthesis.SpeechSynthesisStream,Windows.Media.SpeechSynthesis,ContentType=WindowsRuntime] > $null
        $voices=@([Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices | Where-Object {$_.Language -eq 'pt-BR'})
        if($Action -eq 'worker') {
            $speaker=[Windows.Media.SpeechSynthesis.SpeechSynthesizer]::new()
            $available=@($voices | ForEach-Object {@{name=$_.DisplayName;language=$_.Language;backend='winrt'}})
            [Console]::WriteLine((@{ready=$true;voices=$available}|ConvertTo-Json -Compress -Depth 3))
            [Console]::Out.Flush()
            while($null -ne ($line=[Console]::ReadLine())) {
                try {
                    $request=$line|ConvertFrom-Json
                    if($request.op -eq 'close'){break}
                    if($request.op -ne 'synthesize'){throw 'INVALID_LOCAL_TTS_REQUEST'}
                    $voice=$voices | Where-Object {$_.DisplayName -eq $request.voice} | Select-Object -First 1
                    if(-not $voice){throw 'LOCAL_PTBR_VOICE_UNAVAILABLE'}
                    $speaker.Voice=$voice
                    $speaker.Options.SpeakingRate=[Math]::Max(0.5,[Math]::Min(2.0,1.0+[int]$request.rate*0.08))
                    Export-WinRTSpeech $speaker ([string]$request.text) ([string]$request.output)
                    $response=@{ok=$true;name=$voice.DisplayName;language=$voice.Language;backend='winrt'}
                } catch {$response=@{ok=$false;error=$_.Exception.Message}}
                [Console]::WriteLine(($response|ConvertTo-Json -Compress));[Console]::Out.Flush()
            }
            exit 0
        }
        if($Action -eq 'list') {
            ConvertTo-Json -InputObject @($voices | ForEach-Object {@{name=$_.DisplayName;language=$_.Language;backend='winrt'}}) -Compress
            exit 0
        }
        $voice=$voices | Where-Object {$_.DisplayName -eq $VoiceName} | Select-Object -First 1
        if(-not $voice){throw 'LOCAL_PTBR_VOICE_UNAVAILABLE'}
        $speaker=[Windows.Media.SpeechSynthesis.SpeechSynthesizer]::new()
        $speaker.Voice=$voice
        $speaker.Options.SpeakingRate=[Math]::Max(0.5,[Math]::Min(2.0,1.0+$Rate*0.08))
        $text=[IO.File]::ReadAllText($TextPath,[Text.Encoding]::UTF8)
        Export-WinRTSpeech $speaker $text $OutputPath
    } else {
        Add-Type -AssemblyName System.Speech
        $speaker=New-Object System.Speech.Synthesis.SpeechSynthesizer
        $voices=@($speaker.GetInstalledVoices() | Where-Object {$_.Enabled -and $_.VoiceInfo.Culture.Name -eq 'pt-BR'})
        if($Action -eq 'list') {
            ConvertTo-Json -InputObject @($voices | ForEach-Object {@{name=$_.VoiceInfo.Name;language='pt-BR';backend='sapi'}}) -Compress
            exit 0
        }
        $speaker.SelectVoice($VoiceName)
        $speaker.Rate=[Math]::Max(-10,[Math]::Min(10,$Rate))
        $speaker.SetOutputToWaveFile($OutputPath)
        $speaker.Speak([IO.File]::ReadAllText($TextPath,[Text.Encoding]::UTF8))
        $speaker.SetOutputToNull()
    }
    @{name=$VoiceName;language='pt-BR';backend=$Backend}|ConvertTo-Json -Compress
} catch {
    [Console]::Error.WriteLine('LOCAL_TTS_FAILURE: '+$_.Exception.Message)
    exit 1
} finally {if($speaker){$speaker.Dispose()}}
