namespace Book_Finder.Application.Identity;

// Account deletion use case (member-center plan D-E, D1). The confirmation checkbox and the current password are checked first;
// only then does the store delete anything. The store repeats the lookup under a row lock, so a deletion that races another request
// still reports the outcome instead of failing.
public sealed class AccountDeletionService(IUserStore users, IPasswordHashing passwords, IAccountDeletionStore store)
{
    public const string ConfirmationRequiredMessage = "請勾選「我了解刪除後無法復原」";
    public const string PasswordRequiredMessage = "請輸入目前的密碼";
    public const string WrongPasswordMessage = "密碼錯誤";

    public async Task<AccountDeletionResult> DeleteAsync(Guid userId, string? password, bool confirmed, CancellationToken cancellationToken)
    {
        var errors = new Dictionary<string, string>();
        if (!confirmed)
            errors["confirmed"] = ConfirmationRequiredMessage;
        if (string.IsNullOrWhiteSpace(password))
            errors["password"] = PasswordRequiredMessage;
        if (errors.Count > 0)
            return new AccountDeletionResult.InvalidInput(errors);

        var user = await users.FindByIdAsync(userId, cancellationToken);
        if (user is null)
            return new AccountDeletionResult.UserNotFound();

        if (passwords.Verify(user.PasswordHash, password!) == PasswordCheck.Failed)
            return new AccountDeletionResult.InvalidInput(new Dictionary<string, string> { ["password"] = WrongPasswordMessage });

        var outcome = await store.DeleteAsync(userId, cancellationToken);
        return outcome == AccountDeletionOutcome.Deleted
            ? new AccountDeletionResult.Deleted()
            : new AccountDeletionResult.UserNotFound();
    }
}

// Each case is a separate type so the controller pattern-matches on the outcome.
public abstract record AccountDeletionResult
{
    public sealed record Deleted : AccountDeletionResult;

    public sealed record InvalidInput(IReadOnlyDictionary<string, string> Errors) : AccountDeletionResult;

    public sealed record UserNotFound : AccountDeletionResult;
}
