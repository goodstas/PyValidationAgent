using Microsoft.AspNetCore.Mvc;

namespace DemoShop.Controllers;

[ApiController]
[Route("documents")]
public sealed class DocumentsController : ControllerBase
{
    private static readonly IReadOnlyDictionary<string, string> PublishedDocuments = new Dictionary<string, string>
    {
        ["terms"] = "content/terms.txt",
        ["privacy"] = "content/privacy.txt",
    };

    [HttpGet("export")]
    public IActionResult Export()
    {
        string fileName = Request.Query["file"].ToString();
        string path = Path.Combine("exports", fileName);
        return Content(System.IO.File.ReadAllText(path));
    }

    [HttpGet("published")]
    public IActionResult Published()
    {
        string key = Request.Query["name"].ToString();
        if (!PublishedDocuments.TryGetValue(key, out var path))
        {
            return NotFound();
        }

        return Content(System.IO.File.ReadAllText(path));
    }
}
