using Book_Finder.Application.Common;
using Microsoft.Extensions.Options;

namespace Book_Finder.Application.Recommendation;

// Reports today's Recommendation quota for the account page (recommendation.md §11). It uses the same Taipei-day count as
// RecommendationService, and only reads: it never refuses a request or changes the counting rules.
public sealed class RecommendationQuotaReader(
    IRecommendationUsage usage,
    IOptions<RecommendationOptions> options,
    TimeProvider time)
{
    public async Task<RecommendationQuota> ReadAsync(Guid userId, CancellationToken cancellationToken)
    {
        var limit = options.Value.DailyLimit;
        var used = await usage.CountSinceAsync(userId, TaipeiTimeZone.StartOfDayUtc(time.GetUtcNow()), cancellationToken);

        return new RecommendationQuota(used, limit, Math.Max(0, limit - used));
    }
}
