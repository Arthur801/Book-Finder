namespace Book_Finder.Models;

// The "check your mail" page after registration. SendFailed keeps the account and offers the resend page (plan C3).
public sealed record VerificationSentViewModel(string Email, bool SendFailed);
