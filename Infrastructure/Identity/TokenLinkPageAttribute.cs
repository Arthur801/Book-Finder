using Microsoft.AspNetCore.Mvc.Filters;

namespace Book_Finder.Infrastructure.Identity;

// Marks an action whose URL or form carries a one-time account token (plan member-center C3, and reused by C4). The page must not be
// cached, and the token must not leak in the Referer header to any third-party resource the page loads.
[AttributeUsage(AttributeTargets.Method | AttributeTargets.Class)]
public sealed class TokenLinkPageAttribute : ActionFilterAttribute
{
    public override void OnResultExecuting(ResultExecutingContext context)
    {
        var headers = context.HttpContext.Response.Headers;
        headers["Cache-Control"] = "no-store";
        headers["Referrer-Policy"] = "no-referrer";
        base.OnResultExecuting(context);
    }
}
