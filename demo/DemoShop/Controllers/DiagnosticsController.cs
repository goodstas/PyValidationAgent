using System.Diagnostics;
using DemoShop.Services;
using Microsoft.AspNetCore.Mvc;

namespace DemoShop.Controllers;

[ApiController]
[Route("diagnostics")]
public sealed class DiagnosticsController : ControllerBase
{
    private readonly IJobLauncher _launcher;

    public DiagnosticsController(IJobLauncher launcher)
    {
        _launcher = launcher;
    }

    [HttpPost("tool")]
    public IActionResult RunTool()
    {
        string tool = Request.Query["tool"].ToString();
        var startInfo = new ProcessStartInfo { FileName = tool, UseShellExecute = false };
        return Accepted(_launcher.Enqueue(startInfo));
    }

    [HttpPost("runtime-info")]
    public IActionResult RuntimeInfo()
    {
        var startInfo = new ProcessStartInfo { FileName = "dotnet", Arguments = "--info", UseShellExecute = false };
        return Accepted(_launcher.Enqueue(startInfo));
    }
}
