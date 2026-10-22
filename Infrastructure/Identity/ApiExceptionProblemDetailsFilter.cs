using Book_Finder.Application.Recommendation;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.Filters;
using Microsoft.AspNetCore.Mvc.Infrastructure;

namespace Book_Finder.Infrastructure.Identity;

// Turns an unhandled exception in an /api/* action into the ProblemDetails of api-spec.md §2: AiUnavailableException becomes
// 502 /errors/ai-unavailable, AiTimeoutException becomes 504 /errors/ai-timeout, anything else 500. Pages keep the framework's
// error path. The exception message and stack trace are logged, never returned.
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
        // The AiUnavailableException's inner exception (the SDK error) is logged with it.
        if (context.Exception is AiUnavailableException)
        {
            logger.LogError(context.Exception, "AI call failed in {Method} {Path}", http.Request.Method, http.Request.Path);
            context.Result = ApiProblemResults.AiUnavailable(problemDetails, http);
            context.ExceptionHandled = true;
            return;
        }

        if (context.Exception is AiTimeoutException)
        {
            logger.LogError(context.Exception, "AI call timed out in {Method} {Path}", http.Request.Method, http.Request.Path);
            context.Result = ApiProblemResults.AiTimeout(problemDetails, http);
            context.ExceptionHandled = true;
            return;
        }

        logger.LogError(context.Exception, "Unhandled exception in {Method} {Path}", http.Request.Method, http.Request.Path);

        var problem = problemDetails.CreateProblemDetails(
            http,
            statusCode: StatusCodes.Status500InternalServerError,
            title: "伺服器發生錯誤",
            type: "/errors/internal");
        context.Result = ApiProblemResults.From(problem);
        context.ExceptionHandled = true;
    }
}
