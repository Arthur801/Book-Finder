using Microsoft.AspNetCore.Antiforgery;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

namespace WebIntegration;

// Test-only endpoints for the auth pipeline. The production app never references this assembly; tests opt in
// with AddApplicationPart(typeof(TestOnlyAuthController).Assembly).
public sealed class TestOnlyAuthController : Controller
{
    [Authorize]
    [HttpGet("/test-only/protected")]
    public IActionResult Protected() => Content("ok");

    [Authorize]
    [HttpGet("/api/test-only/protected")]
    public IActionResult ApiProtected() => Ok(new { ok = true });

    [HttpPost("/test-only/echo")]
    public IActionResult Echo() => Content("ok");

    [HttpPost("/api/test-only/echo")]
    public IActionResult ApiEcho() => Ok(new { ok = true });

    // Returns a request token and stores the matching antiforgery cookie on the response.
    [HttpGet("/test-only/antiforgery-token")]
    public IActionResult AntiforgeryToken([FromServices] IAntiforgery antiforgery) =>
        Content(antiforgery.GetAndStoreTokens(HttpContext).RequestToken ?? "");
}
