import json
import pathlib
import shutil
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "waren6.ps1"


class PowerShellDevToolsProbeTests(unittest.TestCase):
    def setUp(self):
        self.powershell = shutil.which("powershell.exe") or shutil.which("pwsh")
        if not self.powershell:
            self.skipTest("PowerShell is not available on this test host")

    def test_stalled_local_endpoint_honors_short_timeout(self):
        escaped_script = str(SCRIPT).replace("'", "''")
        command = rf"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile('{escaped_script}', [ref]$tokens, [ref]$parseErrors)
$fn = $ast.FindAll({{ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Invoke-WAren6DevToolsProbe' }}, $true) | Select-Object -First 1
. ([ScriptBlock]::Create($fn.Extent.Text))
$listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
$listener.Start()
try {{
    $port = ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
    $accept = $listener.AcceptTcpClientAsync()
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    $probe = Invoke-WAren6DevToolsProbe -Port $port -TimeoutMilliseconds 250
    $watch.Stop()
    if ($accept.Wait(1000)) {{ $accept.Result.Dispose() }}
    [PSCustomObject]@{{ status = $probe.status; elapsedMilliseconds = [int][Math]::Round($watch.Elapsed.TotalMilliseconds) }} | ConvertTo-Json -Compress
}}
finally {{
    $listener.Stop()
}}
"""
        result = subprocess.run(
            [self.powershell, "-NoProfile", "-NonInteractive", "-Command", command],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(payload["status"], "endpoint_timeout")
        self.assertLess(payload["elapsedMilliseconds"], 1500)

    def test_readiness_wait_does_not_overrun_its_total_budget(self):
        escaped_script = str(SCRIPT).replace("'", "''")
        command = rf"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile('{escaped_script}', [ref]$tokens, [ref]$parseErrors)
foreach ($name in @('Invoke-WAren6DevToolsProbe', 'Wait-WAren6DevToolsPage')) {{
    $fn = $ast.FindAll({{ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }}, $true) | Select-Object -First 1
    . ([ScriptBlock]::Create($fn.Extent.Text))
}}
$listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
$listener.Start()
try {{
    $port = ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
    $accept = $listener.AcceptTcpClientAsync()
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    $readiness = Wait-WAren6DevToolsPage -Port $port -ReadinessBudgetSeconds 1 -ProbeTimeoutMilliseconds 500 -PollMilliseconds 250
    $watch.Stop()
    if ($accept.Wait(1000)) {{ $accept.Result.Dispose() }}
    [PSCustomObject]@{{ status = $readiness.status; elapsedMilliseconds = [int][Math]::Round($watch.Elapsed.TotalMilliseconds) }} | ConvertTo-Json -Compress
}}
finally {{
    $listener.Stop()
}}
"""
        result = subprocess.run(
            [self.powershell, "-NoProfile", "-NonInteractive", "-Command", command],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(payload["status"], "endpoint_timeout")
        self.assertLess(payload["elapsedMilliseconds"], 1800)


if __name__ == "__main__":
    unittest.main()
