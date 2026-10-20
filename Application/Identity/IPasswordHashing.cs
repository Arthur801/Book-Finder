namespace Book_Finder.Application.Identity;

// Password hashing port (identity-auth.md §2 invariant 1). Only hashes are stored; plain text is never kept or logged.
public interface IPasswordHashing
{
    string Hash(string password);

    PasswordCheck Verify(string hash, string password);
}

public enum PasswordCheck
{
    Failed,
    Success,
    SuccessRehashNeeded,
}
