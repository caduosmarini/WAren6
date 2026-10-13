import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "waren6.ps1"


class PowerShellRuntimeCaptureTests(unittest.TestCase):
    def _source(self):
        return SCRIPT.read_text(encoding="utf-8", errors="replace")

    def test_runtime_only_passes_writable_diagnostics_reference(self):
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if not shell:
            self.skipTest("PowerShell is required for the parameter binding regression")
        source = self._source()
        branch_start = source.rindex("elseif ($RuntimeOnly) {")
        branch_end = source.index("elseif ($PSBoundParameters.ContainsKey('GetID'))", branch_start)
        branch = source[branch_start:branch_end]
        call = re.search(r"^\s*\$runtimePath = Invoke-WAren6RuntimeStore8Capture[^\r\n]+", branch, re.M).group(0)
        initialize = re.search(r"^\s*\$runtimeCaptureDiagnostics = \$null", branch, re.M)
        self.assertIsNotNone(initialize)
        # Execute the real RuntimeOnly call with a harmless mock using the
        # capture function's [ref] contract. No app launch or process changes.
        probe = r"""
$ErrorActionPreference = 'Stop'
function Invoke-WAren6RuntimeStore8Capture {
    param([string]$OutputDirectory, [switch]$Silent, [switch]$BlockClose,
          [switch]$DeepRuntime, [ref]$Diagnostics = $null)
    if ($null -eq $Diagnostics) { throw 'diagnostics reference missing' }
    $Diagnostics.Value = @{ status = 'mock_capture_reached' }
    return 'mock-runtime.jsonl'
}
$CasePath = 'mock-output'
$runtimeHidden = $true
$ForegroundRuntime = $false
$DeepRuntime = $false
""" + initialize.group(0) + "\n" + call + r"""
if ($runtimePath -ne 'mock-runtime.jsonl') { throw 'capture result lost' }
if ($runtimeCaptureDiagnostics.status -ne 'mock_capture_reached') { throw 'diagnostics output lost' }
Write-Output 'runtime-only-binding-ok'
"""
        result = subprocess.run(
            [shell, "-NoProfile", "-NonInteractive", "-Command", probe],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("runtime-only-binding-ok", result.stdout)

    def test_registry_denial_falls_back_and_cleans_up_after_capture_failure(self):
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if not shell:
            self.skipTest("PowerShell is required for runtime cleanup regression")
        source = self._source()
        start = source.index("function Invoke-WAren6RuntimeStore8Capture {")
        end = source.index("function Test-WAren6RuntimeJsonl", start)
        capture = source[start:end]
        probe = r"""
$ErrorActionPreference = 'Stop'
$script:events = @()
$script:running = $false
[Environment]::SetEnvironmentVariable('WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS', 'previous-value', 'Process')
function Test-Path { param($Path) return $false }
function New-Item {
    param($Path, $ItemType, [switch]$Force, $ErrorAction)
    if ($Path -like 'HKCU:*') { throw 'mock registry permission denied' }
}
function Get-Process {
    param($Name, $ErrorAction)
    if ($script:running) { [PSCustomObject]@{ Id = 123 } }
}
function Stop-Process {
    param([Parameter(ValueFromPipeline=$true)]$InputObject, [switch]$Force)
    process { $script:running = $false; $script:events += 'stopped' }
}
function Invoke-WAren6WhatsAppRuntimeLaunch {
    param([switch]$Silent, [switch]$ProcessArguments)
    if ($ProcessArguments) {
        if ($env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS -notmatch '--remote-debugging-port=9222') { throw 'fallback arguments missing' }
        $script:running = $true
        $script:events += 'fallback'
    }
    else {
        if ($env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS -ne 'previous-value') { throw 'process environment not restored' }
        $script:events += 'normal'
    }
}
function Wait-WAren6DevToolsPage {
    param($Port, $ReadinessBudgetSeconds, $ProbeTimeoutMilliseconds, $PollMilliseconds, $MaintenanceAction)
    return [PSCustomObject]@{ status = 'endpoint_timeout'; page = $null }
}
""" + capture + r"""
$diagnostics = $null
$failedAsExpected = $false
try { Invoke-WAren6RuntimeStore8Capture -OutputDirectory 'mock-output' -Silent -Diagnostics ([ref]$diagnostics) }
catch { $failedAsExpected = $_.Exception.Message -match 'endpoint_timeout'; if (-not $failedAsExpected) { throw } }
if (-not $failedAsExpected) { throw 'expected capture failure was lost' }
if (($script:events -join ',') -ne 'fallback,stopped,normal') { throw 'debug process cleanup and normal relaunch failed' }
if ($diagnostics.status -ne 'endpoint_timeout') { throw 'readiness diagnostics lost' }
if ($env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS -ne 'previous-value') { throw 'environment restoration failed' }
Write-Output 'fallback-cleanup-ok'
"""
        # Only the capture function is loaded; every process/registry operation
        # is mocked, and readiness fails before any WebSocket can be opened.
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [shell, "-NoProfile", "-NonInteractive", "-Command", probe],
                cwd=directory, capture_output=True, text=True, timeout=30,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("fallback-cleanup-ok", result.stdout)

    def _runtime_expression(self):
        source = self._source()
        function_start = source.index("function Get-WAren6RuntimeExpression")
        heredoc_start = source.index("return @'", function_start)
        expression_start = source.index("\n", heredoc_start) + 1
        expression_end = source.index("\n'@", expression_start)
        return source[expression_start:expression_end]

    def test_hybrid_runtime_capture_is_preserved_after_acquisition_copy(self):
        source = self._source()

        self.assertIn("function Copy-WAren6RuntimeSupplement", source)
        self.assertRegex(
            source,
            r"Invoke-WAren6RuntimeStore8Capture\s+`?\s+-OutputDirectory\s+\$runtimeCaptureRoot",
        )
        self.assertNotRegex(
            source,
            r"Invoke-WAren6RuntimeStore8Capture\s+-OutputDirectory\s+\$targetOutput",
        )

        acquisition = source.index("Copy-Directory -Source $WhatsAppPath")
        preserve = source.index("Copy-WAren6RuntimeSupplement `")
        self.assertLess(acquisition, preserve)

    def test_runtime_expression_does_not_shadow_message_key_helper(self):
        expression = self._runtime_expression()

        self.assertIn("function normalizeMsgKey(", expression)
        self.assertNotIn("function msgKey(", expression)
        self.assertIn("const latestEditMsgKey = normalizeMsgKey(", expression)
        self.assertIn("const protocolMessageKey = normalizeMsgKey(", expression)

    def test_runtime_capture_reports_javascript_evaluation_errors(self):
        source = self._source()

        self.assertIn("$result.exceptionDetails", source)
        self.assertIn("$lastRuntimeException", source)
        self.assertIn("Runtime JS evaluation failed", source)
        # The runtime capture retry loop must still sleep between attempts
        # (exponential backoff, capped at $maxBackoffMs). We assert on the
        # variable name so the loop can be re-tuned without churning tests,
        # but the sleep-per-attempt contract is preserved.
        self.assertIn("Start-Sleep -Milliseconds $backoffMs", source)
        self.assertIn("$maxBackoffMs", source)

    def test_runtime_capture_uses_bulk_jsonl_handoff(self):
        source = self._source()
        expression = self._runtime_expression()

        self.assertIn('messages_jsonl: messages.join("\\n")', expression)
        self.assertIn("$payload.messages_jsonl", source)
        self.assertIn("$writer.Write($payload.messages_jsonl)", source)

    def test_silent_runtime_launch_does_not_block_for_full_window_hide_period(self):
        source = self._source()
        function_start = source.index("function Invoke-WAren6WhatsAppRuntimeLaunch")
        function_end = source.index("function Get-WAren6RuntimeExpression", function_start)
        launch_source = source[function_start:function_end]

        self.assertIn("Hide-WAren6WhatsAppWindows", launch_source)
        self.assertIn("Start-Sleep -Milliseconds", launch_source)
        self.assertNotIn("Hide-WAren6WhatsAppWindowsForPeriod -Seconds 8", launch_source)

    def test_runtime_readiness_uses_fast_default_and_deep_opt_in(self):
        source = self._source()

        self.assertIn("[switch]$DeepRuntime", source)
        self.assertIn('"deep-runtime" = "DeepRuntime"', source)
        self.assertIn("function Get-WAren6RuntimeReadinessBudgetSeconds", source)
        self.assertIn("return 20", source)
        self.assertIn("return 90", source)

        runtime_start = source.index("function Invoke-WAren6RuntimeStore8Capture")
        runtime_end = source.index("function Test-WAren6RuntimeJsonl", runtime_start)
        runtime_source = source[runtime_start:runtime_end]
        self.assertIn("[int]$ReadinessBudgetSeconds", runtime_source)
        self.assertIn("[switch]$DeepRuntime", runtime_source)
        self.assertIn("[ref]$Diagnostics", runtime_source)
        self.assertNotIn('Invoke-RestMethod -Uri "http://127.0.0.1:$Port/json/list"', runtime_source)
        self.assertIn("-DeepRuntime:$DeepRuntime", source)

    def test_runtime_readiness_probe_is_bounded_and_diagnosable(self):
        source = self._source()

        self.assertIn("function Invoke-WAren6DevToolsProbe", source)
        self.assertIn("[System.Net.HttpWebRequest]", source)
        self.assertIn("$request.Timeout = $TimeoutMilliseconds", source)
        self.assertIn("$request.ReadWriteTimeout = $TimeoutMilliseconds", source)
        self.assertIn("$effectiveProbeTimeoutMilliseconds", source)
        for status in (
            "endpoint_unreachable",
            "endpoint_timeout",
            "endpoint_http_error",
            "invalid_target_payload",
            "no_web_whatsapp_target",
            "whatsapp_exit_timeout",
        ):
            self.assertIn(status, source)

        self.assertIn("$runtimeCaptureDiagnostics", source)
        self.assertIn("readiness = $runtimeCaptureDiagnostics", source)


if __name__ == "__main__":
    unittest.main()
