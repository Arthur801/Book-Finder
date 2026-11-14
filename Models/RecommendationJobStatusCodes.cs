using Book_Finder.Domain.Entities;

namespace Book_Finder.Models;

// The status values the job API and the job page show. They are the same words the database stores, but Models keeps its own
// map instead of calling the persistence helper, so the web layer does not depend on Infrastructure. A DatabaseIntegration test
// (StoredEnumTests) fails if the two ever differ.
public static class RecommendationJobStatusCodes
{
    public static string Of(RecommendationJobStatus status) => status switch
    {
        RecommendationJobStatus.Queued => "QUEUED",
        RecommendationJobStatus.Running => "RUNNING",
        RecommendationJobStatus.Succeeded => "SUCCEEDED",
        RecommendationJobStatus.Failed => "FAILED",
        _ => throw new ArgumentOutOfRangeException(nameof(status), status, null),
    };
}
