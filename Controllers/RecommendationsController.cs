using Book_Finder.Application.Recommendation;
using Book_Finder.Infrastructure.Identity;
using Book_Finder.Models;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.Infrastructure;

namespace Book_Finder.Controllers;

// AI recommendation JSON endpoint (api-spec.md §3; recommendation.md §3). The input rules and the search
// itself live in Application; this controller only maps the request and the outcome.
public class RecommendationsController(RecommendationService recommendations, ProblemDetailsFactory problemDetails) : Controller
{
    [Authorize]
    [HttpPost("/api/recommendations")]
    public async Task<IActionResult> Create([FromBody] RecommendationRequest? request)
    {
        // A missing or malformed body reaches here as a null request, and is reported like a blank text.
        var input = RecommendationInputRules.ValidateRequirementText(request?.RequirementText);
        if (!input.IsValid)
            return ValidationFailed(input.Error!);

        var userId = User.CurrentUserId();
        var attempt = await recommendations.RecommendAsync(userId, input.Text!, HttpContext.RequestAborted);
        switch (attempt)
        {
            case RecommendationAttempt.Succeeded succeeded:
                return Ok(RecommendationResponse.From(succeeded.Outcome));

            case RecommendationAttempt.DailyLimitReached:
                return ApiProblemResults.DailyLimitExceeded(problemDetails, HttpContext);

            default:
                throw new InvalidOperationException($"Unexpected recommendation attempt {attempt.GetType().Name}.");
        }
    }

    private IActionResult ValidationFailed(string message) =>
        ApiProblemResults.Validation(problemDetails, HttpContext, new Dictionary<string, string> { ["requirementText"] = message });
}
