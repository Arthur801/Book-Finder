using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.Filters;
using Microsoft.AspNetCore.Mvc.Infrastructure;

namespace Book_Finder.Infrastructure.Identity;

// Turns an unhandled exception in an /api/* action into the 500 ProblemDetails of api-spec.md §2. Pages keep the
// framework's error path. The exception message and stack trace are logged, never returned.
// 502 and 504 (AI unavailable and timeout) are mapped in #15, not here.
public sealed class ApiExceptionProblemDetailsFilter(
    ProblemDetailsFactory problemDetails,
    ILogger<ApiExceptionProblemDetailsFilter> logger) : IExceptionFilter
{
    public void OnException(ExceptionContext context)
    {
        var http = context.HttpContext;
        if (!ApiRequest.IsApi(http.Request))
            return;

        // The client went away, so nobody is waiting for an answer and this is not a server error.
        if (http.RequestAborted.IsCancellationRequested)
            return;

        // Only the method and path are logged: the request body holds the user's requirement text.
        logger.LogError(context.Exception, "Unhandled exception in {Method} {Path}", http.Request.Method, http.Request.Path);

        var problem = problemDetails.CreateProblemDetails(
            http,
            statusCode: StatusCodes.Status500InternalServerError,
            title: "伺服器發生錯誤",
            type: "/errors/internal");
        context.Result = new ObjectResult(problem)
        {
            StatusCode = StatusCodes.Status500InternalServerError,
            ContentTypes = { "application/problem+json" },
        };
        context.ExceptionHandled = true;
    }
}
