using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.Core.Infrastructure;
using Microsoft.AspNetCore.Mvc.Filters;
using Microsoft.AspNetCore.Mvc.Infrastructure;

namespace Book_Finder.Infrastructure.Identity;

// Turns the framework's antiforgery failure (IAntiforgeryValidationFailedResult) into the API error contract
// (api-spec.md §2) for /api/* only. Page requests keep the framework's plain 400. AlwaysRun so it also sees
// the failure that the auth filter short-circuits.
public sealed class AntiforgeryProblemDetailsFilter(ProblemDetailsFactory problemDetails) : IAlwaysRunResultFilter
{
    public void OnResultExecuting(ResultExecutingContext context)
    {
        if (context.Result is not IAntiforgeryValidationFailedResult
            || !ApiRequest.IsApi(context.HttpContext.Request))
        {
            return;
        }

        var problem = problemDetails.CreateProblemDetails(
            context.HttpContext,
            statusCode: StatusCodes.Status400BadRequest,
            title: "請重新整理頁面後再試",
            type: "/errors/antiforgery");
        context.Result = ApiProblemResults.From(problem);
    }

    public void OnResultExecuted(ResultExecutedContext context)
    {
    }
}
