using Microsoft.AspNetCore.Mvc;

namespace Book_Finder.Infrastructure.Identity;

// Lives in Infrastructure rather than Application because it depends on MVC's IUrlHelper.
// Only local paths are allowed through, which prevents open redirects (identity-auth.md §6).
public static class SafeReturnUrl
{
    public const string Fallback = "/";

    public static string Resolve(string? returnUrl, IUrlHelper url) =>
        string.IsNullOrWhiteSpace(returnUrl) || !url.IsLocalUrl(returnUrl)
            ? Fallback
            : returnUrl;
}
