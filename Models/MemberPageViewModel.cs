using Book_Finder.Application.Recommendation;

namespace Book_Finder.Models;

// The member center at /account (member-center plan A3). Three sections in fixed order: the Library (#library), the AI quota and
// the Recommendation Job list (#ai-history), and account security (#account-security: the delete and reset links).
// JobList is null while RecommendationJobs:Enabled is false; the page then says the list is not open yet.
// PasswordResetEnabled is EmailVerification:Enabled (plan D-A): the reset link in the security section is shown only then.
public sealed record MemberPageViewModel(
    LibraryPageViewModel Library,
    RecommendationQuota Quota,
    bool JobsEnabled,
    AiJobListViewModel? JobList,
    bool PasswordResetEnabled);
