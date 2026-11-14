namespace Book_Finder.Application.Recommendation;

// Each case is a separate type, the same way RecommendationAttempt works, so the caller pattern-matches on it.
public abstract record IdempotencyKeyCheck
{
    // No Idempotency-Key header (or an empty one): the submit is not idempotent.
    public sealed record Absent : IdempotencyKeyCheck;

    // The key exactly as sent. It is never trimmed, because a trimmed key could match a different client's key.
    public sealed record Valid(string Key) : IdempotencyKeyCheck;

    public sealed record Invalid : IdempotencyKeyCheck;
}

// Pure rules for the Idempotency-Key header (plan async-recommendation-jobs section 3.7): 1 to 128 characters, only ASCII
// letters, digits, underscore and hyphen. The database CHECK enforces the same pattern as a second layer.
public static class IdempotencyKeyRules
{
    public const int MaxLength = 128;

    public static IdempotencyKeyCheck Validate(string? raw)
    {
        if (string.IsNullOrEmpty(raw))
            return new IdempotencyKeyCheck.Absent();

        if (raw.Length > MaxLength)
            return new IdempotencyKeyCheck.Invalid();

        foreach (var ch in raw)
        {
            var allowed = ch is (>= 'A' and <= 'Z') or (>= 'a' and <= 'z') or (>= '0' and <= '9') or '_' or '-';
            if (!allowed)
                return new IdempotencyKeyCheck.Invalid();
        }

        return new IdempotencyKeyCheck.Valid(raw);
    }
}
