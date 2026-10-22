using Book_Finder.Application.Recommendation;
using Book_Finder.Infrastructure.Identity;
using Book_Finder.Models;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.Infrastructure;
using Microsoft.AspNetCore.Mvc.ModelBinding;

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
        var outcome = await recommendations.RecommendAsync(userId, input.Text!, HttpContext.RequestAborted);
        return Ok(RecommendationResponse.From(outcome));
    }

    // Built from a fresh ModelState so only requirementText is reported, whatever the binder said about the body.
    private IActionResult ValidationFailed(string message)
    {
        var modelState = new ModelStateDictionary();
        modelState.AddModelError("requirementText", message);
        var problem = problemDetails.CreateValidationProblemDetails(
            HttpContext,
            modelState,
            statusCode: StatusCodes.Status400BadRequest,
            title: "輸入資料有誤",
            type: "/errors/validation");
        return new ObjectResult(problem)
        {
            StatusCode = StatusCodes.Status400BadRequest,
            ContentTypes = { "application/problem+json" },
        };
    }
}
