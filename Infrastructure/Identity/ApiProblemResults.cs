using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.Infrastructure;
using Microsoft.AspNetCore.Mvc.ModelBinding;

namespace Book_Finder.Infrastructure.Identity;

// Builds the application/problem+json results of api-spec.md §2, so every /api/* error uses the same shape.
// Controllers and filters share these instead of each writing its own ObjectResult.
public static class ApiProblemResults
{
    public static ObjectResult From(ProblemDetails problem) => new(problem)
    {
        StatusCode = problem.Status,
        ContentTypes = { "application/problem+json" },
    };

    public static ObjectResult NotFound(ProblemDetailsFactory problemDetails, HttpContext http)
    {
        var problem = problemDetails.CreateProblemDetails(
            http,
            statusCode: StatusCodes.Status404NotFound,
            title: "找不到資源",
            type: "/errors/not-found");
        return From(problem);
    }

    // The daily AI recommendation limit (api-spec.md §2, recommendation.md §11). Same 429 status as the rate limit, different type.
    public static ObjectResult DailyLimitExceeded(ProblemDetailsFactory problemDetails, HttpContext http)
    {
        var problem = problemDetails.CreateProblemDetails(
            http,
            statusCode: StatusCodes.Status429TooManyRequests,
            title: "今天的 AI 推薦次數已用完",
            type: "/errors/daily-limit-exceeded");
        return From(problem);
    }

    // An OpenAI call failed after the SDK's retries (api-spec.md §2, recommendation.md §8).
    // The title is fixed, so no provider detail reaches the client.
    public static ObjectResult AiUnavailable(ProblemDetailsFactory problemDetails, HttpContext http)
    {
        var problem = problemDetails.CreateProblemDetails(
            http,
            statusCode: StatusCodes.Status502BadGateway,
            title: "AI 推薦暫時無法使用",
            type: "/errors/ai-unavailable");
        return From(problem);
    }

    // Built from a fresh ModelState so only the given fields are reported, whatever the binder said about the body.
    public static ObjectResult Validation(
        ProblemDetailsFactory problemDetails,
        HttpContext http,
        IReadOnlyDictionary<string, string> errors)
    {
        var modelState = new ModelStateDictionary();
        foreach (var (field, message) in errors)
            modelState.AddModelError(field, message);
        var problem = problemDetails.CreateValidationProblemDetails(
            http,
            modelState,
            statusCode: StatusCodes.Status400BadRequest,
            title: "輸入資料有誤",
            type: "/errors/validation");
        return From(problem);
    }
}
