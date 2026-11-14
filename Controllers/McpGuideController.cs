using Microsoft.AspNetCore.Mvc;

namespace Book_Finder.Controllers;

// The public MCP guide (/mcp-guide): how to connect ChatGPT, Claude and VS Code to /mcp. A static page with no data and no sign-in.
// It is not under /mcp, so the MCP authorization gate never sees it, and it renders the same whether or not Mcp:Enabled is on.
public sealed class McpGuideController : Controller
{
    [HttpGet("/mcp-guide")]
    public IActionResult Index() => View();
}
