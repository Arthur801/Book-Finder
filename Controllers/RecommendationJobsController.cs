using Book_Finder.Application.Recommendation;
using Book_Finder.Infrastructure.Identity;
using Book_Finder.Models;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.Infrastructure;
using Microsoft.Extensions.Options;

namespace Book_Finder.Controllers;

// Recommendation Job JSON endpoints (plan async-recommendation-jobs section 3.7). A submit only writes the job; the worker runs it later.
// While RecommendationJobs:Enabled is false every endpoint here answers the API 404, because no worker would run the job.
// The requirement text is only read from the body and never written to a URL, a Location header or a log.
public class RecommendationJobsController(
    RecommendationJobService jobs,
    IOptions<RecommendationJobOptions> options,
    ProblemDetailsFactory problemDetails) : Controller
{
    private const string IdempotencyKeyHeader = "Idempotency-Key";

    [Authorize]
    [HttpPost("/api/recommendations/jobs")]
    public async Task<IActionResult> Submit([FromBody] RecommendationRequest? request, CancellationToken cancellationToken)
    {
        if (!options.Value.Enabled)
            return NotFoundProblem();

        // Same input rules as the synchronous endpoint, so a bad text is refused before any job row is written.
        var input = RecommendationInputRules.ValidateRequirementText(request?.RequirementText);
        if (!input.IsValid)
            return ValidationFailed("requirementText", input.Error!);

        var userId = User.CurrentUserId();
        var idempotencyKey = Request.Headers[IdempotencyKeyHeader].FirstOrDefault();
        var submission = await jobs.SubmitAsync(userId, input.Text!, idempotencyKey, HttpContext.RequestAborted);
        switch (submission)
        {
            // The job is committed before this point, so the 202 never names a job that does not exist. A replay gets the same answer.
            case RecommendationJobSubmission.Accepted accepted:
                var response = RecommendationJobAcceptedResponse.From(accepted.Job);
                return Accepted(response.StatusUrl, response);

            case RecommendationJobSubmission.InvalidIdempotencyKey:
                return ValidationFailed(IdempotencyKeyHeader, "Idempotency-Key 格式不正確");

            case RecommendationJobSubmission.IdempotencyConflict:
                return ApiProblemResults.IdempotencyConflict(problemDetails, HttpContext);

            case RecommendationJobSubmission.DailyLimitReached:
                return ApiProblemResults.DailyLimitExceeded(problemDetails, HttpContext);

            default:
                throw new InvalidOperationException($"Unexpected job submission {submission.GetType().Name}.");
        }
    }

    // Newest first, 20 per page. A page that is not a number, or below 1, is the first page (PageNumber.Parse).
    [Authorize]
    [HttpGet("/api/recommendations/jobs")]
    public async Task<IActionResult> List([FromQuery] string? page, CancellationToken cancellationToken)
    {
        if (!options.Value.Enabled)
            return NotFoundProblem();

        var requestedPage = PageNumber.Parse(page);
        var list = await jobs.ListAsync(User.CurrentUserId(), requestedPage, cancellationToken);
        return Ok(RecommendationJobListResponse.From(list, requestedPage));
    }

    // Not a GUID, unknown and another user's job all get the same 404, so the response never shows whether a job exists.
    [Authorize]
    [HttpGet("/api/recommendations/jobs/{jobId}")]
    public async Task<IActionResult> Get(string jobId, CancellationToken cancellationToken)
    {
        if (!options.Value.Enabled || !Guid.TryParse(jobId, out var id))
            return NotFoundProblem();

        var job = await jobs.GetAsync(User.CurrentUserId(), id, cancellationToken);
        if (job is null)
            return NotFoundProblem();

        return Ok(RecommendationJobResponse.From(job));
    }

    private IActionResult NotFoundProblem() => ApiProblemResults.NotFound(problemDetails, HttpContext);

    private IActionResult ValidationFailed(string field, string message) =>
        ApiProblemResults.Validation(problemDetails, HttpContext, new Dictionary<string, string> { [field] = message });
}
