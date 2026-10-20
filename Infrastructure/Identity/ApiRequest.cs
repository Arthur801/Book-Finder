using Microsoft.AspNetCore.Http;

namespace Book_Finder.Infrastructure.Identity;

// Decides which error contract a request gets: /api/* returns ProblemDetails JSON, everything else returns pages.
// Every error path that splits on this uses the same rule, so the two paths cannot drift apart.
public static class ApiRequest
{
    public static bool IsApi(HttpRequest request) => request.Path.StartsWithSegments("/api");
}
