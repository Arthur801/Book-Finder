namespace Book_Finder.Application.Recommendation;

// Thrown when a fenced commit finds no valid lease: the token is wrong, the lease expired, or the job already left RUNNING.
public sealed class RecommendationJobLeaseLostException : Exception
{
    public RecommendationJobLeaseLostException(Guid jobId)
        : base($"Recommendation job {jobId} no longer has a valid lease for this worker.")
    {
    }
}
