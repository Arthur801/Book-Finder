using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.Filters;
using Microsoft.AspNetCore.Mvc.Infrastructure;

namespace Book_Finder.Infrastructure.Identity;

// Turns the framework's antiforgery failure into the API error contract (api-spec.md §2) for /api/* only.
// Page requests keep the framework's plain 400. AlwaysRun so it also sees the failure that the auth filter short-circuits.
public sealed class AntiforgeryProblemDetailsFilter(ProblemDetailsFactory problemDetails) : IAlwaysRunResultFilter
{
    // The framework's failure result implements an internal marker interface that is not public in .NET 10,
    // so it is recognized by name. A test asserts this behavior, so a framework change breaks the build's tests, not silently.
    private const string FailedResultMarker = "IAntiforgeryValidationFailedResult";

    public void OnResultExecuting(ResultExecutingContext context)
    {
        if (!context.HttpContext.Request.Path.StartsWithSegments("/api") || !IsAntiforgeryFailure(context.Result))
            return;

        var problem = problemDetails.CreateProblemDetails(
            context.HttpContext,
            statusCode: StatusCodes.Status400BadRequest,
            title: "請重新整理頁面後再試",
            type: "/errors/antiforgery");
        context.Result = new ObjectResult(problem)
        {
            StatusCode = StatusCodes.Status400BadRequest,
            ContentTypes = { "application/problem+json" },
        };
    }

    public void OnResultExecuted(ResultExecutedContext context)
    {
    }

    private static bool IsAntiforgeryFailure(IActionResult? result) =>
        result is not null
        && result.GetType().GetInterfaces().Any(type => type.Name == FailedResultMarker);
}
