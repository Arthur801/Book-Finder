using Book_Finder.Application.Identity;
using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;

namespace Book_Finder.Infrastructure.Persistence;

// Account action token storage (plan member-center-email-verification section C2). Issue is one explicit transaction on the scoped
// AppDbContext, so it cannot be nested inside another transaction on the same context. Consume and discard are single statements
// that open no transaction, so a caller can run them inside its own transaction (password reset does).
// Every time comes from the service; the database clock (now()) is never used, so a test can control every instant.
internal sealed class EfAccountActionTokenStore(AppDbContext db) : IAccountActionTokenStore
{
    public async Task<TokenIssueStatus> TryIssueAsync(
        Guid userId,
        AccountActionTokenPurpose purpose,
        string tokenHash,
        DateTime nowUtc,
        DateTime throttleSinceUtc,
        DateTime expiresAtUtc,
        CancellationToken cancellationToken)
    {
        await using var transaction = await db.Database.BeginTransactionAsync(cancellationToken);

        // WHY the lock comes first: two issues for one user and purpose must not both pass the throttle check. The second issue
        // waits here, and under READ COMMITTED its throttle query runs after the first one committed, so it sees that row.
        var locked = await db.Database.SqlQuery<Guid>($"SELECT id FROM users WHERE id = {userId} FOR UPDATE").ToListAsync(cancellationToken);
        if (locked.Count == 0)
        {
            await transaction.RollbackAsync(cancellationToken);
            return TokenIssueStatus.UserNotFound;
        }

        // Any row counts, consumed or not: the throttle is about how often a link was sent, not whether it was used.
        // A discarded row is gone, so a failed send does not count. The boundary is strict: created exactly at throttleSinceUtc is allowed.
        var throttled = await db.AccountActionTokens.AsNoTracking()
            .AnyAsync(token => token.UserId == userId && token.Purpose == purpose && token.CreatedAt > throttleSinceUtc, cancellationToken);
        if (throttled)
        {
            await transaction.RollbackAsync(cancellationToken);
            return TokenIssueStatus.Throttled;
        }

        // The previous open link of this purpose stops working as soon as a new one is issued.
        await db.AccountActionTokens
            .Where(token => token.UserId == userId && token.Purpose == purpose && token.ConsumedAt == null)
            .ExecuteUpdateAsync(setters => setters.SetProperty(token => token.ConsumedAt, (DateTime?)nowUtc), cancellationToken);

        db.AccountActionTokens.Add(new AccountActionToken
        {
            Id = Guid.CreateVersion7(),
            UserId = userId,
            Purpose = purpose,
            TokenHash = tokenHash,
            CreatedAt = nowUtc,
            ExpiresAt = expiresAtUtc,
        });
        await db.SaveChangesAsync(cancellationToken);
        await transaction.CommitAsync(cancellationToken);
        return TokenIssueStatus.Issued;
    }

    public Task DiscardAsync(string tokenHash, CancellationToken cancellationToken) =>
        db.AccountActionTokens
            .Where(token => token.TokenHash == tokenHash)
            .ExecuteDeleteAsync(cancellationToken);

    public Task<bool> IsUsableAsync(string tokenHash, AccountActionTokenPurpose purpose, DateTime nowUtc, CancellationToken cancellationToken) =>
        db.AccountActionTokens.AsNoTracking()
            .AnyAsync(token => token.TokenHash == tokenHash && token.Purpose == purpose && token.ConsumedAt == null && token.ExpiresAt > nowUtc, cancellationToken);

    // WHY one conditional statement: PostgreSQL re-checks the WHERE clause after a concurrent UPDATE commits, so of two concurrent
    // consumes only one matches the row. The purpose is passed as its stored value, so the SQL carries no copy of the vocabulary.
    public async Task<Guid?> ConsumeAsync(string tokenHash, AccountActionTokenPurpose purpose, DateTime nowUtc, CancellationToken cancellationToken)
    {
        var stored = StoredEnum.ToStored(purpose);
        var userIds = await db.Database.SqlQuery<Guid>($"""
            UPDATE account_action_tokens
            SET consumed_at = {nowUtc}
            WHERE token_hash = {tokenHash} AND purpose = {stored} AND consumed_at IS NULL AND expires_at > {nowUtc}
            RETURNING user_id
            """).ToListAsync(cancellationToken);

        return userIds.Count == 1 ? userIds[0] : null;
    }
}
