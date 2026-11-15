using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.Filters;

namespace Book_Finder.Controllers;

// The consent POST of a session that ended while the consent page was open (member-center B2): the cookie was rejected because
// the account was deleted or its password was reset, so the request arrives anonymous. The global antiforgery filter would refuse it
// with 400, because the form token was issued to the signed-in identity. This filter runs first (Order below the antiforgery filter's
// 1000) and sends the browser back to login with the same authorize request, which is what the action itself does for an ended
// session. Skipping antiforgery here is safe: the only outcome is a redirect, and nothing is read or written for the anonymous request.
// With Mcp:Enabled false the action answers 404, so the filter stays out of the way.
[AttributeUsage(AttributeTargets.Method)]
internal sealed class ConsentSessionEndedRedirectAttribute : Attribute, IAuthorizationFilter, IOrderedFilter
{
    public int Order => -1000;

    public void OnAuthorization(AuthorizationFilterContext context)
    {
        var http = context.HttpContext;
        if (http.User.Identity?.IsAuthenticated == true || !http.Request.HasFormContentType)
            return;
        if (!http.RequestServices.GetRequiredService<IConfiguration>().GetValue<bool>("Mcp:Enabled"))
            return;

        context.Result = new LocalRedirectResult(OAuthController.LoginRedirect(OAuthController.FormAuthorizeUrl(http.Request)));
    }
}
